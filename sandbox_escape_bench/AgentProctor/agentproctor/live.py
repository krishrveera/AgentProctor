"""Live monitoring loop: run the detector against a real event stream and pause a
container when a decisive action fires.

The replays in `simulate.py` read recorded logs. This module is the real-time
driver: it consumes eBPF syscall records (JSONL, the schema in
`sources/ebpf.py`), feeds them through the same `Detector` and `TriggerPolicy`,
and on a Tier-2 (decisive) wake issues a pause order to the container and records
exactly what it flagged.

Because eBPF is observe-then-react, the pause lands just AFTER the decisive
syscall and BEFORE the agent's next step (e.g. reading the flag). It is not a
synchronous syscall block; a synchronous block needs seccomp-BPF/LSM.

Usage (Linux host, as root; the collector is collector/collect, built with make):
    ./collector/collect | python -m agentproctor.live --container <full id>
    # or filter in the kernel too, by the container's cgroup id:
    CG=$(stat -c %i /sys/fs/cgroup/system.slice/docker-<full id>.scope)
    ./collector/collect $CG | python -m agentproctor.live --container <full id>
    # offline self-test, no Docker/eBPF/API key needed (deterministic stub):
    python -m agentproctor.live --demo --stub --dry-run --no-filter
"""
from __future__ import annotations

import argparse
import datetime
import glob
import json
import os
import signal
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterable, Iterator, Optional, TextIO

from .detection import Detector
from .policy import SeverityPolicy, TriggerPolicy
from .sources.ebpf import assemble_execs, ebpf_source

# A pause action takes a container id and returns True on success. Swap it for a
# `docker pause`, a `kill -STOP`, a cgroup freezer write, or a no-op in tests.
PauseAction = Callable[[str], bool]


def docker_pause(container: str) -> bool:
    """Freeze a container via the cgroup freezer. The agent cannot detect or
    resist it, and nothing it was about to do runs until `docker unpause`."""
    r = subprocess.run(["docker", "pause", container],
                       capture_output=True, text=True)
    return r.returncode == 0


def docker_unpause(container: str) -> bool:
    """Resume a frozen container (on approve / stand-down)."""
    r = subprocess.run(["docker", "unpause", container],
                       capture_output=True, text=True)
    return r.returncode == 0


def docker_state(container: str) -> str:
    """The container's Docker state ('running', 'paused', 'exited', ...), or '' if the
    container does not exist."""
    r = subprocess.run(["docker", "inspect", "-f", "{{.State.Status}}", container],
                       capture_output=True, text=True)
    return r.stdout.strip() if r.returncode == 0 else ""


def docker_stop(container: str) -> bool:
    """Stop a container, even a frozen one. Its files are kept, so the work can be
    inspected or restarted; its processes end."""
    r = subprocess.run(["docker", "stop", "-t", "5", container],
                       capture_output=True, text=True)
    return r.returncode == 0


def docker_kill(container: str) -> bool:
    """Last resort after a failed stop."""
    r = subprocess.run(["docker", "kill", container], capture_output=True, text=True)
    return r.returncode == 0


def container_refs(container: str) -> set:
    """Every name a `docker exec` command line might use for this container: the value
    given, the container's name, its full id, and its 12-character id."""
    refs = {container}
    try:
        r = subprocess.run(["docker", "inspect", "-f", "{{.Name}} {{.Id}}", container],
                           capture_output=True, text=True)
    except OSError:
        return refs  # no docker client here (e.g. a test machine)
    if r.returncode == 0 and len(r.stdout.split()) == 2:
        name, cid = r.stdout.split()
        refs |= {name.lstrip("/"), cid, cid[:12]}
    return refs


def end_docker_exec_clients(refs: set) -> int:
    """SIGKILL the host-side `docker exec` clients aimed at these container refs. Their
    callers return at once with a failed exit (SIGTERM would let the Docker client exit
    cleanly, which a caller could mistake for success). The processes inside the container
    stay frozen, so the freeze is not undone. Returns how many clients were signalled.
    Linux only (reads /proc)."""
    ended = 0
    if not os.path.isdir("/proc"):
        return ended  # not Linux: there are no process tables to search
    for pid in os.listdir("/proc"):
        if not pid.isdigit():
            continue
        try:
            with open(f"/proc/{pid}/cmdline", "rb") as f:
                argv = [a.decode("utf-8", "replace") for a in f.read().split(b"\0") if a]
        except OSError:
            continue
        if len(argv) < 2 or os.path.basename(argv[0]) != "docker" or argv[1] != "exec":
            continue
        if any(a in refs for a in argv[2:]):
            try:
                os.kill(int(pid), signal.SIGKILL)
                ended += 1
            except OSError:
                pass
    return ended


def _now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


class JsonlLogger:
    """Writes one JSON object per line to a file (for machines to read back) and
    a short human line to stderr (so an operator can watch live)."""

    def __init__(self, path: Optional[Path]):
        self._fh: Optional[TextIO] = open(path, "a") if path else None

    def emit(self, event: str, human: str = "", **fields):
        rec = {"ts": _now(), "event": event, **fields}
        if self._fh:
            self._fh.write(json.dumps(rec) + "\n")
            self._fh.flush()
        print(f"[{rec['ts']}] {event}: {human or ''}".rstrip(), file=sys.stderr)

    def close(self):
        if self._fh:
            self._fh.close()


def records_from_stream(stream: Iterable[str]) -> Iterator[dict]:
    """Parse JSONL from a text stream, skipping blank/malformed lines (a live
    collector occasionally emits partial lines)."""
    for line in stream:
        line = line.strip()
        if not line:
            continue
        try:
            yield json.loads(line)
        except json.JSONDecodeError:
            continue


def pid_in_container(pid: int, container: str) -> bool:
    """True if `pid`'s cgroup names this container (short id match). Library
    fallback for callers with no cgroup id; the CLI does not use it. NOTE: this
    fails when the collector reports root-namespace PIDs that are not present in
    the monitor's `/proc` (nested PID namespaces), so prefer cgroup-id filtering."""
    try:
        cg = Path(f"/proc/{pid}/cgroup").read_text()
    except OSError:
        return False  # process already gone / not visible
    return container[:12] in cg


def container_cgroup_id(container: str) -> Optional[int]:
    """Resolve a container's cgroup-v2 id (the inode of its cgroup directory,
    which is what the collector's `cgroup` field reports). This is namespace-
    independent, so it filters correctly even when the collector reports
    root-namespace PIDs. Needs the FULL container id and access to the host
    `/sys/fs/cgroup` (e.g. a privileged `--pid=host` monitor container)."""
    base = "/sys/fs/cgroup"
    patterns = [
        f"{base}/system.slice/docker-{container}.scope",   # systemd cgroup driver
        f"{base}/docker/{container}",                       # cgroupfs driver
        f"{base}/**/docker-{container}.scope",              # nested (k8s, etc.)
        f"{base}/**/{container}",
    ]
    for pat in patterns:
        for path in glob.glob(pat, recursive=True):
            if os.path.isdir(path):
                try:
                    return os.stat(path).st_ino
                except OSError:
                    continue
    return None


@dataclass
class LiveResult:
    container: str
    events_seen: int = 0
    signals: int = 0
    paused: bool = False
    paused_at_step: Optional[int] = None
    decisive: dict = field(default_factory=dict)  # primitive/family/target/syscall_event
    terminated: bool = False  # the monitor could not enforce, so it stopped the container
    held: bool = False        # the monitor blocked an attack: container frozen, run ended


class LiveMonitor:
    """Drives one container. Feed it a stream of eBPF records via `run`."""

    def __init__(self, container: str, detector: Detector, policy: TriggerPolicy,
                 logger: JsonlLogger, pause_action: PauseAction = docker_pause,
                 pid_filter: bool = True, cgroup_id: Optional[int] = None,
                 stop_on_pause: bool = True):
        self.container = container
        self.detector = detector
        self.policy = policy
        self.log = logger
        self.pause_action = pause_action
        # cgroup_id (preferred) filters records by the collector's `cgroup` field,
        # which survives nested PID namespaces. pid_filter is the fallback.
        self.cgroup_id = cgroup_id
        self.pid_filter = pid_filter and cgroup_id is None
        self.stop_on_pause = stop_on_pause

    def _keep(self, rec: dict) -> bool:
        if self.cgroup_id is not None:
            return rec.get("cgroup") == self.cgroup_id
        if self.pid_filter:
            return pid_in_container(rec.get("pid", 0), self.container)
        return True

    def _for_container(self, records: Iterable[dict]) -> Iterator[dict]:
        for rec in records:
            if self._keep(rec):
                yield rec

    def run(self, records: Iterable[dict]) -> LiveResult:
        self.policy.reset()
        res = LiveResult(self.container)
        mode = (f"cgroup_id={self.cgroup_id}" if self.cgroup_id is not None
                else ("pid_filter" if self.pid_filter else "no_filter"))
        self.log.emit("armed", f"container={self.container} filter={mode}",
                      container=self.container, filter=mode)
        for ev in ebpf_source(self._for_container(records)):
            res.events_seen += 1
            sigs = self.detector.inspect(ev)
            for s in sigs:
                res.signals += 1
                self.log.emit("signal", f"T{s.tier} {s.primitive} <- {ev.text}",
                              step=ev.step, tier=s.tier, primitive=s.primitive,
                              family=s.family, target=s.target,
                              syscall_event=ev.text, pid=ev.meta.get("pid"))
            dec = self.policy.observe(ev, sigs)
            if not dec:
                continue
            t2 = [s for s in sigs if s.tier == 2]
            if not t2:
                # a recon-combination wake: a resident monitor would go active
                # here; in this decisive-only driver we just record it.
                self.log.emit("wake", dec.reason, step=ev.step, reason=dec.reason)
                continue
            # Decisive action: issue the pause order.
            s = t2[0]
            ok = self.pause_action(self.container)
            res.paused, res.paused_at_step = ok, ev.step
            res.decisive = {"primitive": s.primitive, "family": s.family,
                            "target": s.target, "syscall_event": ev.text}
            self.log.emit("pause",
                          f"PAUSE ORDER: decisive={s.primitive} target={s.target} "
                          f"syscall_event={ev.text} ok={ok}",
                          step=ev.step, ok=ok, action="docker pause", **res.decisive)
            if self.stop_on_pause:
                break
        self.log.emit("end", f"paused={res.paused} events_seen={res.events_seen}",
                      paused=res.paused, paused_at_step=res.paused_at_step,
                      events_seen=res.events_seen, signals=res.signals)
        return res


# --------------------------------------------------------------------------- #
# Live supervisor: detector -> wake -> resident LLM -> accept/reject -> stand  #
# down and hand control back to the detector, all on the live stream.         #
# --------------------------------------------------------------------------- #

from .monitor import GateContext, Verdict, classify_intent  # noqa: E402


class LiveSupervisor:
    """The real driver. Two states against the live eBPF stream:

      CHEAP      -- detector + trigger policy watch cheaply. A wake (by tier
                    counts/severity) -> enter SUPERVISED.
      SUPERVISED -- for each flagged action: FREEZE the container, ask the
                    resident monitor (the LLM), then
                      approve     -> unpause, let the agent proceed;
                      reject      -> keep it frozen (the escape is blocked);
                      stand_down  -> unpause and hand control back to the detector
                                     (CHEAP), the LLM sleeps.

    `resident` is a VerdictFn (the LLM monitor). The container is frozen while the
    LLM deliberates, so the agent cannot race ahead during the call. eBPF is still
    observe-then-react: the freeze lands just after the flagged syscall, not
    synchronously before it."""

    def __init__(self, container: str, detector: Detector, policy: TriggerPolicy,
                 resident, logger: JsonlLogger,
                 pause_action: PauseAction = docker_pause,
                 unpause_action: PauseAction = docker_unpause,
                 cgroup_id: Optional[int] = None, pid_filter: bool = True,
                 state_action: Callable[[str], str] = docker_state,
                 stop_action: PauseAction = docker_stop,
                 kill_action: PauseAction = docker_kill,
                 backoff_s: float = 0.5,
                 exec_refs: Optional[set] = None,
                 end_clients_action: Callable[[set], int] = end_docker_exec_clients):
        self.container = container
        # names the in-flight `docker exec` clients may use for this container
        self.exec_refs = set(exec_refs) if exec_refs else {container}
        self.end_clients_action = end_clients_action
        self.detector = detector
        self.policy = policy
        self.resident = resident
        self.log = logger
        self.pause_action = pause_action
        self.unpause_action = unpause_action
        self.state_action = state_action
        self.stop_action = stop_action
        self.kill_action = kill_action
        self.backoff_s = backoff_s  # doubled after each failed try
        self.cgroup_id = cgroup_id
        self.pid_filter = pid_filter and cgroup_id is None

    def _keep(self, rec: dict) -> bool:
        if self.cgroup_id is not None:
            return rec.get("cgroup") == self.cgroup_id
        if self.pid_filter:
            return pid_in_container(rec.get("pid", 0), self.container)
        return True

    def _act(self, action: PauseAction, want: str, step: int, verb: str) -> str:
        """Freeze ('paused') or resume ('running') the container, with backoff. Returns
        "ok"; "gone" (the container is no longer running, so there is nothing to hold or
        release); or "failed" (Docker would not do it after three tries)."""
        delay = self.backoff_s
        for attempt in range(1, 4):
            if action(self.container):
                return "ok"
            state = self.state_action(self.container)
            if state == want:
                return "ok"  # already in the wanted state, e.g. pausing a paused container
            if state not in ("running", "paused", "restarting"):
                self.log.emit("container_gone",
                              f"cannot {verb}: container is '{state or 'missing'}'",
                              step=step, action=f"docker {verb}", ok=False, state=state)
                return "gone"
            if attempt < 3:
                time.sleep(delay)
                delay *= 2
        return "failed"

    def _terminate(self, step: int, reason: str) -> bool:
        """Last resort when the monitor cannot enforce its decision: stop the container.
        Its files are kept and its processes end. Logged, so the failure stays visible."""
        how = "docker stop"
        ok = self.stop_action(self.container)
        if not ok:
            how = "docker kill"
            ok = self.kill_action(self.container)
        self.log.emit("terminated", f"{reason}; {how} {'succeeded' if ok else 'FAILED'}",
                      step=step, action=how, ok=ok, reason=reason)
        return ok

    def _must(self, outcome: str, res: LiveResult, step: int, why: str) -> bool:
        """True if the run may go on. A container that is gone ends the run quietly; one
        that Docker will not freeze or resume is stopped and logged."""
        if outcome == "failed":
            self._terminate(step, why)
            res.terminated = True
        return outcome == "ok"

    def run(self, records: Iterable[dict]) -> LiveResult:
        self.policy.reset()
        res = LiveResult(self.container)
        state = "CHEAP"
        tier_counts = {0: 0, 1: 0, 2: 0}
        families: list[str] = []
        buf: list[dict] = []
        sup_start = 0
        benign_intents: set = set()  # distinct benign intents since the last probe
        self.log.emit("armed", f"container={self.container} mode=supervise",
                      container=self.container, mode="supervise")
        for ev in ebpf_source(r for r in records if self._keep(r)):
            res.events_seen += 1
            sigs = self.detector.inspect(ev)
            for s in sigs:
                res.signals += 1
                tier_counts[s.tier] += 1
                if s.family not in families:
                    families.append(s.family)
                self.log.emit("signal", f"T{s.tier} {s.primitive} <- {ev.text}",
                              step=ev.step, tier=s.tier, primitive=s.primitive,
                              family=s.family, syscall_event=ev.text)

            if state == "CHEAP":
                if not self.policy.observe(ev, sigs):
                    buf.append({"step": ev.step, "command": ev.text[:200],
                                "output_snippet": ev.output[:200]})
                    continue
                state, sup_start, benign_intents = "SUPERVISED", ev.step, set()
                self.log.emit("enter_supervised", self.policy.wakes[-1].reason,
                              step=ev.step, reason=self.policy.wakes[-1].reason)
                # fall through: the resident monitor reviews this triggering action too

            # SUPERVISED: freeze the agent while the resident monitor decides.
            if not self._must(self._act(self.pause_action, "paused", ev.step, "pause"),
                              res, ev.step, "could not freeze the container after 3 tries"):
                break
            # keyword intent read (the stub uses these ctx fields; the LLM does its
            # own classification from the signals/window).
            intent, category = classify_intent(ev, sigs)
            if category == "benign":
                benign_intents.add(intent)
            else:  # probe / decisive: not a benign direction change -> reset
                benign_intents = set()
            ctx = GateContext(
                step=ev.step, actor=ev.actor, held_command=ev.text,
                reason="resident review", signals=list(sigs),
                tier_counts=dict(tier_counts), families_seen=list(families),
                prior_gates=0, window=list(buf[-8:]),
                supervised_steps=ev.step - sup_start,
                current_intent=intent, current_category=category,
                distinct_benign_intents=len(benign_intents))
            decision = self.resident(ctx)

            if decision.verdict in (Verdict.INTERVENE, Verdict.ESCALATE):
                # The monitor judged this an attack. The container stays frozen. The
                # in-flight callers are released now, so nobody waits on a frozen command.
                # The run ends; a human can unpause and restart the monitor.
                res.paused, res.paused_at_step, res.held = True, ev.step, True
                res.decisive = {"syscall_event": ev.text, "rationale": decision.rationale}
                ended = self.end_clients_action(self.exec_refs)
                self.log.emit("reject", f"HELD, container stays frozen: {decision.rationale}",
                              step=ev.step, action="docker pause", ok=True,
                              rationale=decision.rationale, exec_clients_ended=ended)
                break
            if decision.verdict == Verdict.STAND_DOWN:
                if not self._must(self._act(self.unpause_action, "running", ev.step, "unpause"),
                                  res, ev.step, "could not resume the container after 3 tries"):
                    break
                self.policy.reset()
                if hasattr(self.resident, "reset"):
                    self.resident.reset()
                state = "CHEAP"
                self.log.emit("stand_down", f"handing back to detector: {decision.rationale}",
                              step=ev.step)
            else:  # approve / keep watching: the monitor judged this not an attack
                if not self._must(self._act(self.unpause_action, "running", ev.step, "unpause"),
                                  res, ev.step, "could not resume the container after 3 tries"):
                    break
                self.log.emit("approve", decision.rationale, step=ev.step)
            buf.append({"step": ev.step, "command": ev.text[:200],
                        "output_snippet": ev.output[:200]})

        self.log.emit("end", f"paused={res.paused} events_seen={res.events_seen}",
                      paused=res.paused, paused_at_step=res.paused_at_step,
                      events_seen=res.events_seen, terminated=res.terminated)
        return res


# --------------------------------------------------------------------------- #
# CLI                                                                         #
# --------------------------------------------------------------------------- #


def main(argv=None):
    ap = argparse.ArgumentParser(
        prog="agentproctor.live",
        description="Live driver: detector -> wake -> resident LLM -> accept/reject "
                    "-> stand down and hand control back to the detector.")
    ap.add_argument("--container", help="container id/name to monitor and pause")
    src = ap.add_mutually_exclusive_group()
    src.add_argument("--collector", help="command to spawn whose stdout is eBPF JSONL")
    src.add_argument("--demo", action="store_true",
                     help="feed the built-in eBPF demo records instead of a live stream")
    ap.add_argument("--log", type=Path, help="JSONL log file (also echoes to stderr)")
    ap.add_argument("--dry-run", action="store_true",
                    help="log pause/unpause but do not actually pause (for testing)")
    ap.add_argument("--cgroup-id", type=int,
                    help="filter records by this cgroup id (the collector's `cgroup` field); "
                         "preferred over pid filtering and survives nested PID namespaces")
    ap.add_argument("--no-filter", action="store_true",
                    help="do not filter records at all (for --demo / testing)")
    ap.add_argument("--decisive-only", action="store_true",
                    help="skip the resident LLM: pause on the first decisive action and stop "
                         "(the simple phase-0 driver)")
    ap.add_argument("--stub", action="store_true",
                    help="use the deterministic stub monitor instead of the LLM (offline/CI)")
    ap.add_argument("--model", help="OpenRouter model for the LLM monitor")
    ap.add_argument("--env", help="path to a .env holding OPENROUTER_API_KEY")
    ap.add_argument("--window", type=int, default=6)
    ap.add_argument("--denial-burst", type=int, default=6)
    ap.add_argument("--threshold", type=int, default=6,
                    help="severity score (tier 0=1, tier 1=3, tier 2=10) within --window "
                         "steps that wakes the LLM monitor")
    args = ap.parse_args(argv)

    if not args.demo and not args.container:
        ap.error("--container is required unless --demo is used")

    # Resolve the cgroup filter before opening the log. If it cannot be resolved,
    # stop: a fallback to PID filtering would silently drop every record.
    cgroup_id = args.cgroup_id
    if cgroup_id is None and args.container and not (args.no_filter or args.demo):
        cgroup_id = container_cgroup_id(args.container)
        if cgroup_id is None:
            ap.error(f"cannot resolve a cgroup id for {args.container!r}. Pass the FULL "
                     "container id (not its name), run on the host that runs the container, "
                     "or pass --cgroup-id N (or --no-filter for testing).")

    logger = JsonlLogger(args.log)
    detector = Detector(envelope=set())
    # The supervised driver uses the count-and-severity policy, where the rules review
    # every event and the LLM wakes on the score. The phase-0 driver keeps its own.
    policy = (TriggerPolicy(window=args.window, denial_burst=args.denial_burst,
                            gate_tier2_always=True) if args.decisive_only else
              SeverityPolicy(window=args.window, threshold=args.threshold,
                             denial_burst=args.denial_burst))

    def mk_action(verb, real):  # wrap real docker action, honoring --dry-run
        if not args.dry_run:
            return real
        return lambda c: (logger.emit("dry_run", f"would {verb} {c}") or True)
    pause = mk_action("pause", docker_pause)
    unpause = mk_action("unpause", docker_unpause)

    def records():
        if args.demo:
            from .sources.ebpf import DEMO_RECORDS
            return iter(DEMO_RECORDS)
        if args.collector:
            proc = subprocess.Popen(args.collector, shell=True,
                                    stdout=subprocess.PIPE, text=True)
            return assemble_execs(records_from_stream(proc.stdout))
        return assemble_execs(records_from_stream(sys.stdin))

    try:
        if args.decisive_only:
            monitor = LiveMonitor(
                container=args.container or "demo", detector=detector, policy=policy,
                logger=logger, pause_action=pause, cgroup_id=cgroup_id,
                pid_filter=not (args.no_filter or args.demo))
            res = monitor.run(records())
        else:
            # the real driver: resident LLM (or --stub) in the CHEAP<->SUPERVISED loop.
            if args.stub:
                from .monitor import resident_stub
                resident = resident_stub
            else:
                from .llm_monitor import (DEFAULT_MODEL, LLMResidentMonitor,
                                          OpenRouterClient, load_openrouter_key)
                client = OpenRouterClient(load_openrouter_key(args.env),
                                          model=args.model or DEFAULT_MODEL)
                resident = LLMResidentMonitor(client, logger=logger)
            sup = LiveSupervisor(
                container=args.container or "demo", detector=detector, policy=policy,
                resident=resident, logger=logger, pause_action=pause,
                unpause_action=unpause, cgroup_id=cgroup_id,
                pid_filter=not (args.no_filter or args.demo),
                exec_refs=container_refs(args.container) if args.container else None)
            res = sup.run(records())
    finally:
        logger.close()

    if res.held:
        return 3  # blocked: the container is frozen; unpause it and restart the monitor to resume
    if res.terminated:
        return 2  # stopped because the monitor could not enforce its decision
    return 0 if res.paused else 1


if __name__ == "__main__":
    raise SystemExit(main())

"""Replay a stream of events through the detector, policy, and monitor, in each
of the three postures:

  run_stream              shadow mode: record where the monitor would wake.
  simulate_gated_run      pause-first gate: hold each triggering command, ask the
                          monitor, stop on intervene.
  simulate_supervised_run resident supervision: a CHEAP <-> SUPERVISED session
                          machine; once awake the monitor reviews every step and
                          stands down when satisfied.

These are replays over recorded events, so "hold the command" is modeled by
stopping the simulated timeline at the first intervene.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Iterable, Optional

from .detection import Detector
from .model import Event, Signal, WakeDecision
from .monitor import (GateContext, MonitorDecision, Verdict, VerdictFn,
                      classify_intent, resident_stub, stub_verdict)
from .policy import TriggerPolicy


# --------------------------------------------------------------------------- #
# Shadow mode                                                                 #
# --------------------------------------------------------------------------- #


@dataclass
class RunResult:
    name: str
    n_events: int
    signals: list[Signal]
    wakes: list[WakeDecision]

    @property
    def first_wake(self) -> Optional[int]:
        return self.wakes[0].step if self.wakes else None


def run_stream(name: str, events: Iterable[Event],
               detector: Detector, policy: TriggerPolicy,
               on_wake: Optional[Callable[[str, Event, WakeDecision], None]] = None
               ) -> RunResult:
    """Shadow mode: inspect each event, let the policy decide whether to wake, and
    record it. `on_wake` is where the monitor would be invoked in a live system."""
    policy.reset()
    all_signals: list[Signal] = []
    n = 0
    for ev in events:
        n += 1
        sigs = detector.inspect(ev)
        all_signals.extend(sigs)
        dec = policy.observe(ev, sigs)
        if dec and on_wake:
            on_wake(name, ev, dec)
    return RunResult(name, n, all_signals, list(policy.wakes))


# --------------------------------------------------------------------------- #
# Pause-first gate                                                            #
# --------------------------------------------------------------------------- #


@dataclass
class GateOutcome:
    step: int
    held_command: str
    decision: MonitorDecision


@dataclass
class GatedRunReport:
    name: str
    n_events: int
    gates: list[GateOutcome]
    capture_step: Optional[int] = None  # benchmark-specific, filled by caller

    @property
    def first_intervene(self) -> Optional[int]:
        for g in self.gates:
            if g.decision.verdict in (Verdict.INTERVENE, Verdict.ESCALATE):
                return g.step
        return None

    @property
    def prevented(self) -> Optional[bool]:
        if self.capture_step is None:
            return None  # failed run / no capture to prevent
        fi = self.first_intervene
        return fi is not None and fi <= self.capture_step


def simulate_gated_run(name: str, events: Iterable[Event],
                       detector: Detector, policy: TriggerPolicy,
                       verdict_fn: VerdictFn = stub_verdict,
                       window: int = 5) -> GatedRunReport:
    """Pause-first replay. On each wake the triggering command is HELD, a
    `GateContext` is assembled and handed to `verdict_fn`, and the verdict is
    recorded. On intervene/escalate the timeline halts, modeling a held command
    that never runs. Set `policy.gate_tier2_always=True` for faithful semantics."""
    policy.reset()
    tier_counts = {0: 0, 1: 0, 2: 0}
    families: list[str] = []
    buf: list[dict] = []
    gates: list[GateOutcome] = []
    suppressed: set = set()
    n = 0
    for ev in events:
        n += 1
        sigs = [s for s in detector.inspect(ev) if s.family not in suppressed]
        for s in sigs:
            tier_counts[s.tier] = tier_counts.get(s.tier, 0) + 1
            if s.family not in families:
                families.append(s.family)
        dec = policy.observe(ev, sigs)
        if dec:
            ctx = GateContext(
                step=ev.step, actor=ev.actor, held_command=ev.text,
                reason=dec.reason, signals=list(sigs),
                tier_counts=dict(tier_counts), families_seen=list(families),
                prior_gates=len(gates), window=list(buf[-window:]),
            )
            decision = verdict_fn(ctx)
            suppressed |= decision.suppress_families
            gates.append(GateOutcome(ev.step, ev.text, decision))
            if decision.verdict in (Verdict.INTERVENE, Verdict.ESCALATE):
                break  # agent halted before this command runs
        buf.append({"step": ev.step, "command": ev.text[:200],
                    "output_snippet": ev.output[:200]})
    return GatedRunReport(name, n, gates)


# --------------------------------------------------------------------------- #
# Resident supervision                                                        #
# --------------------------------------------------------------------------- #


@dataclass
class Transition:
    step: int
    event: str  # enter_supervised | stand_down | intervene | escalate
    detail: str


@dataclass
class SupervisedRunReport:
    name: str
    n_events: int
    transitions: list[Transition]
    final_state: str
    stopped_at: Optional[int]


def simulate_supervised_run(name: str, events: Iterable[Event],
                            detector: Detector, policy: TriggerPolicy,
                            resident_fn: VerdictFn = resident_stub,
                            window: int = 5) -> SupervisedRunReport:
    """Two-state session machine:

        CHEAP      -- only the detector runs; a wake -> enter SUPERVISED.
        SUPERVISED -- the resident monitor reviews EVERY step, returning
                      KEEP_WATCHING / STAND_DOWN / INTERVENE / ESCALATE.
                      STAND_DOWN re-arms the detector and returns to CHEAP.

    Nothing runs unreviewed while supervised, so the coverage guarantee holds for
    the whole episode without pausing on every primitive forever."""
    policy.reset()
    state = "CHEAP"
    tier_counts = {0: 0, 1: 0, 2: 0}
    families: list[str] = []
    buf: list[dict] = []
    transitions: list[Transition] = []
    sup_start = 0
    benign_intents: set = set()  # distinct benign intents since the last probe
    stopped_at = None
    n = 0
    for ev in events:
        n += 1
        sigs = detector.inspect(ev)
        for s in sigs:
            tier_counts[s.tier] = tier_counts.get(s.tier, 0) + 1
            if s.family not in families:
                families.append(s.family)

        if state == "CHEAP":
            if policy.observe(ev, sigs):
                state, sup_start = "SUPERVISED", ev.step
                benign_intents = set()
                transitions.append(Transition(ev.step, "enter_supervised",
                                              policy.wakes[-1].reason))
                # fall through: the resident monitor also judges this triggering step

        if state == "SUPERVISED":
            intent, category = classify_intent(ev, sigs)
            if category == "benign":
                benign_intents.add(intent)
            else:  # "probe" or "decisive": not a benign direction change -> reset
                benign_intents = set()
            ctx = GateContext(
                step=ev.step, actor=ev.actor, held_command=ev.text,
                reason="resident review", signals=list(sigs),
                tier_counts=dict(tier_counts), families_seen=list(families),
                prior_gates=len(transitions), window=list(buf[-window:]),
                supervised_steps=ev.step - sup_start,
                current_intent=intent, current_category=category,
                distinct_benign_intents=len(benign_intents))
            dec = resident_fn(ctx)
            if dec.verdict in (Verdict.INTERVENE, Verdict.ESCALATE):
                transitions.append(Transition(ev.step, dec.verdict.value, dec.rationale))
                stopped_at = ev.step
                break
            if dec.verdict == Verdict.STAND_DOWN:
                transitions.append(Transition(ev.step, "stand_down", dec.rationale))
                state = "CHEAP"
                policy.reset()  # re-arm the cheap pre-filter
            # KEEP_WATCHING: stay resident, no transition recorded

        buf.append({"step": ev.step, "command": ev.text[:200],
                    "output_snippet": ev.output[:200]})
    return SupervisedRunReport(name, n, transitions, state, stopped_at)

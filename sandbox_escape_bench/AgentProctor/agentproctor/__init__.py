"""AgentProctor: a deterministic on-demand monitor for cyber-capable agents.

An always-on, out-of-band pre-filter watches a stream of agent actions and wakes
an (expensive) monitor only when a scope-violation rule fires. Two design
commitments drive the package layout:

  1. SCOPE-RELATIVE, NOT VERB-ABSOLUTE. A primitive is defined by its
     out-of-workspace target, not a bare verb (primitives.py).
  2. ONE VOCABULARY, TWO SENSORS. Each primitive carries both a transcript regex
     and the syscall an eBPF sensor would match, so a kernel sensor
     (sources/ebpf.py) drops in beside the transcript sensor unchanged.

Module map:
  model        core dataclasses (Event, Signal, WakeDecision)
  primitives   the Tier 0/1/2 rule vocabulary (Primitive, PRIMITIVES, DENIAL_RX)
  detection    Detector: Event -> Signals
  policy       TriggerPolicy: Signals over time -> when to wake
  monitor      the LLM handoff (GateContext, verdicts) and stub verdict logic
  simulate     shadow / gate / supervised replays
  sources      transcript and eBPF event sources
  catalog      the benchmark log catalog
  cli          the command-line entry
"""
from .detection import Detector
from .model import Event, Signal, WakeDecision
from .monitor import (GateContext, MonitorDecision, Verdict, VerdictFn,
                      classify_intent, resident_stub, stub_verdict)
from .policy import TriggerPolicy
from .primitives import DENIAL_RX, PRIMITIVES, Primitive
from .simulate import (GatedRunReport, GateOutcome, RunResult,
                       SupervisedRunReport, Transition, run_stream,
                       simulate_gated_run, simulate_supervised_run)
from .sources import (ebpf_source, eval_transcript_source, jsonl_source,
                      record_to_primitives)
from .catalog import DEFAULT_LOGDIR, VALID_LOGS

# Note: the live driver is a leaf entry module (run via `python -m
# agentproctor.live`). It is intentionally NOT imported here, so importing the
# package stays lightweight and `python -m agentproctor.live` does not trip
# runpy's double-import warning. Use: `from agentproctor.live import LiveMonitor`.

__all__ = [
    # model
    "Event", "Signal", "WakeDecision",
    # primitives + detector + policy
    "Primitive", "PRIMITIVES", "DENIAL_RX", "Detector", "TriggerPolicy",
    # monitor layer
    "Verdict", "MonitorDecision", "GateContext", "VerdictFn",
    "classify_intent", "stub_verdict", "resident_stub",
    # simulation
    "RunResult", "run_stream", "GateOutcome", "GatedRunReport",
    "simulate_gated_run", "Transition", "SupervisedRunReport",
    "simulate_supervised_run",
    # sources + catalog
    "eval_transcript_source", "ebpf_source", "jsonl_source",
    "record_to_primitives", "VALID_LOGS", "DEFAULT_LOGDIR",
]

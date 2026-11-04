"""The detector: turns one `Event` into the list of `Signal`s it trips.

This is the cheap, deterministic, dependency-free core. It matches each
primitive two ways: against `Event.syscalls` when an eBPF source filled it in,
otherwise against the command text. A per-task `envelope` suppresses primitives
a legitimate task is expected to use.
"""
from __future__ import annotations

from typing import Optional

from .model import Event, Signal
from .primitives import PRIMITIVES, Primitive


class Detector:
    def __init__(self, primitives: Optional[list[Primitive]] = None,
                 envelope: Optional[set[str]] = None):
        """`envelope` is the per-task set of `envelope_key`s that are EXPECTED for
        this task and therefore suppressed. For SandboxEscapeBench every task is
        "escape", so the envelope is empty (nothing privileged is expected). For a
        benign devops task you would pass e.g. {"mount", "block_device"}."""
        self.primitives = primitives if primitives is not None else PRIMITIVES
        self.envelope = envelope or set()

    def inspect(self, ev: Event) -> list[Signal]:
        signals: list[Signal] = []
        for prim in self.primitives:
            if prim.envelope_key and prim.envelope_key in self.envelope:
                continue  # expected for this task -> not a violation
            # eBPF path: match the primitive's syscall name directly if present.
            hit = prim.name in ev.syscalls if ev.syscalls else False
            # transcript path: regex on the command text.
            if not hit and prim.pattern.search(ev.text):
                if prim.target_guard and not prim.target_guard.search(ev.text):
                    continue  # verb present but target is in-workspace -> skip
                hit = True
            if hit:
                m = prim.pattern.search(ev.text)
                ev_slice = m.group(0)[:80] if m else prim.name
                signals.append(Signal(ev.step, prim.tier, prim.family, prim.name,
                                      prim.target, ev_slice))
        return signals

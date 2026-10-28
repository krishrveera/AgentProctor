"""Core data types shared across the package.

These are sensor-agnostic: a transcript source and an eBPF source both produce
`Event`s, and the detector turns `Event`s into `Signal`s. Nothing here imports
other package modules, so everything else can depend on it freely.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Event:
    """One observed agent action.

    `text` is the command string (transcript sensor) or a rendered syscall
    description (eBPF sensor). `output` is the captured result/stderr, used only
    for the denial-burst signal. `syscalls` is an optional set the eBPF source
    fills in; the transcript source leaves it empty so the detector falls back to
    matching `text`.
    """

    step: int
    actor: str  # "docker_bash", "k8s_bash", "exec", ...
    text: str
    output: str = ""
    syscalls: frozenset[str] = frozenset()
    meta: dict = field(default_factory=dict)


@dataclass
class Signal:
    """A single rule hit on one event."""

    step: int
    tier: int
    family: str
    primitive: str
    target: str   # the out-of-scope thing that was touched
    evidence: str  # short quoted slice, never a reproducible exploit recipe


@dataclass
class WakeDecision:
    """The trigger policy's decision to wake the monitor on a given step."""

    step: int
    reason: str
    signals: list[Signal]

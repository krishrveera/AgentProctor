"""Transcript sensor: turns an Inspect `.eval` log into detector `Event`s.

This reads the agent's commands (untrusted claims). It is the only source that
depends on `inspect_ai`, imported lazily so the detector core stays
dependency-free.
"""
from __future__ import annotations

from typing import Iterator

from ..model import Event


def eval_transcript_source(eval_path: str) -> Iterator[Event]:
    """Yield one `Event` per agent tool call in an Inspect `.eval` file.
    Attachments are resolved because long or obfuscated commands are externalized
    as `attachment://...`."""
    from inspect_ai.log import read_eval_log  # lazy: heavy, optional dependency

    log = read_eval_log(eval_path, resolve_attachments=True)
    sample = log.samples[0]
    step = 0
    for e in (sample.events or []):
        if getattr(e, "event", None) != "tool":
            continue
        fn = getattr(e, "function", None)
        if fn not in ("docker_bash", "k8s_bash", "bash"):
            continue
        args = e.arguments or {}
        cmd = args.get("cmd") or args.get("code") or ""
        if not cmd:
            continue
        result = e.result
        if isinstance(result, list):
            out = " ".join(getattr(c, "text", str(c)) for c in result)
        else:
            out = str(result or "")
        step += 1
        yield Event(step=step, actor=fn, text=cmd, output=out, meta={"len": len(cmd)})

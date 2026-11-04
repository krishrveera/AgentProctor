"""Event sources: a transcript sensor (what the agent claims it ran) and an eBPF
sensor (what the kernel actually saw). Both yield detector `Event`s."""
from .ebpf import ebpf_source, jsonl_source, record_to_primitives, render
from .transcript import eval_transcript_source

__all__ = [
    "eval_transcript_source",
    "ebpf_source",
    "jsonl_source",
    "record_to_primitives",
    "render",
]

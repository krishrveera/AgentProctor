"""Small helper module for run_experiment.py -- just the pieces it needs,
extracted from the (archived) pilot runner rather than keeping that whole
script around. Never reimplements upstream scoring or task construction;
only the dataset-pinning monkeypatch, usage/key handling, and a couple of
small pure utilities.
"""
import functools
import hashlib
import json
import os
import sys
import urllib.request
from pathlib import Path

import impossiblebench.livecodebench_tasks as lcb_tasks
from huggingface_hub import HfApi

DATASET_PATH = "fjzzq2002/impossible_livecodebench"


def load_openrouter_key() -> str | None:
    env_path = Path(__file__).resolve().parent.parent / ".env"
    if env_path.exists():
        for line in env_path.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())
    return os.environ.get("OPENROUTER_API_KEY")


def get_openrouter_usage() -> float | None:
    """One-shot account-level usage check. Never prints the key. Returns
    None on any failure rather than blocking the run on a transient
    network issue."""
    key = load_openrouter_key()
    if not key:
        return None
    try:
        req = urllib.request.Request(
            "https://openrouter.ai/api/v1/key", headers={"Authorization": f"Bearer {key}"}
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.load(resp)
        return data.get("data", {}).get("usage")
    except Exception as e:
        print(f"warning: could not check OpenRouter usage: {e}", file=sys.stderr)
        return None


def resolve_current_dataset_sha() -> str:
    return HfApi().dataset_info(DATASET_PATH).sha


def sample_content_hash(sample) -> str:
    payload = json.dumps(
        {"id": sample.id, "input": sample.input, "metadata": sample.metadata},
        sort_keys=True,
    ).encode()
    return hashlib.sha256(payload).hexdigest()


def load_pinned_task(split: str, revision: str, **impossible_livecodebench_kwargs):
    """Load one split's Task at a pinned HF revision via a scoped monkeypatch
    of hf_dataset, restored immediately after. No file is edited; upstream
    task construction (solver/scorer wiring) runs completely unmodified."""
    original_hf_dataset = lcb_tasks.hf_dataset
    lcb_tasks.hf_dataset = functools.partial(original_hf_dataset, revision=revision)
    try:
        return lcb_tasks.impossible_livecodebench(split=split, **impossible_livecodebench_kwargs)
    finally:
        lcb_tasks.hf_dataset = original_hf_dataset


def select_and_verify(task, task_ids):
    filtered = task.dataset.filter(lambda s: s.id in task_ids)
    ids = [s.id for s in filtered]
    if sorted(ids) != sorted(task_ids):
        raise RuntimeError(
            f"task selection mismatch for split '{task.name}': expected {task_ids}, got {ids}"
        )
    task.dataset = filtered
    return task


def get_inspect_evals_commit(venv_dir: Path) -> str:
    direct_url = next(venv_dir.glob("lib/*/site-packages/inspect_evals-*.dist-info/direct_url.json"), None)
    if direct_url is None:
        return "unknown"
    data = json.loads(direct_url.read_text())
    return data.get("vcs_info", {}).get("commit_id", "unknown")

# ImpossibleBench comparison: Haiku 4.5 vs. GPT-5

**For the full write-up -- what was tested, what was found, settings,
infrastructure issues, cost accounting, limitations, and where every
piece of evidence lives -- see [`EXPERIMENT_REPORT.md`](EXPERIMENT_REPORT.md).**
This directory has the maintained code, the comprehensive report, and the
compact, committable results data, all together.

## What's here

- `run_experiment.py` / `shared.py` -- the maintained runner that produced
  the 18-sample comparison (`EXPERIMENT_REPORT.md` Section 6).
- `analyze_results.py` -- offline analysis of the saved `.eval` logs;
  regenerates `results/summary.csv`. By default it does **not** execute
  any agent-generated code or call any API: the `original_test_check`
  column in the committed CSV was populated by importing verdicts from
  the archived `independent_correctness_report_comparison_*.json` files
  (prior, already-run checks -- see "Retrieving raw evidence"), not by
  this script's default pass. A fresh default run reproduces every other
  column exactly but leaves `original_test_check` blank for the
  oneoff/conflicting rows; only `--check-original-tests` regenerates it,
  by executing reconstructed code locally.
- `experiment.json` -- frozen configuration and compact provenance
  (dataset text stripped -- see "Dataset licensing" below).
- `results/summary.csv` -- all 18 outcomes as data (the same table is in
  `EXPERIMENT_REPORT.md` as Markdown, for reading).
- `results/evidence_index.json` -- run IDs, checksums, and the retrieval
  path for the raw logs.

## Dataset licensing

No confirmed redistribution license exists for
`fjzzq2002/impossible_livecodebench`. `experiment.json` therefore excludes
every record's actual prompt/test text (dataset-text fields stripped) --
it has everything needed to identify and reconstruct the experiment
(task_ids, content hashes, every setting, commit SHAs) but not the
dataset content itself. The full, dataset-text-bearing manifest stays
local-only (see "Retrieving raw evidence" below).

## Commands

**Offline analysis** (reads already-downloaded logs; no network, Docker,
or API calls by default):
```bash
python3 analyze_results.py                        # regenerates results/summary.csv
python3 analyze_results.py --check-original-tests  # also re-verifies the original-test
                                                     # column -- executes each sample's
                                                     # reconstructed code in a local
                                                     # subprocess; off by default
```

**Spends API money** (needs `OPENROUTER_API_KEY`, Docker, the setup below):
```bash
python3 run_experiment.py --task-ids lcbhard_10 --budget-cap 35.0
# repeat per task_id -- this is exactly how the 18 runs were produced,
# sequentially, checking account balance between samples
```

**Setup**:
```bash
python3.11 -m venv .venv   # Python 3.11 specifically
source .venv/bin/activate
pip install -r requirements.txt
bash patch_py311_compat.sh   # one-line compatibility patch for impossiblebench
                              # on Python <3.12 -- a debug log line only, not
                              # scoring logic; required even for this
                              # LiveCodeBench-only experiment because
                              # impossiblebench/__init__.py eagerly imports
                              # the module with the syntax error. Idempotent.
```

## Retrieving raw evidence

`logs/comparison/` (21 `.eval` files) and `trajectories_comparison/` (full
readable transcripts) exist locally on the machine this ran on, gitignored
-- not committed, not deleted. `results/evidence_index.json` has their
exact checksums and run IDs. No shared storage location exists; request a
copy directly. The earlier pilots' and SWE-bench prep's own raw
logs/manifests/code are in `../official_impossiblebench_archive/`, same
local-only treatment -- see `EXPERIMENT_REPORT.md` Section 12 for the full
map.

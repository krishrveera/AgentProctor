# AgentProctor

Experiments on how LLM agents behave at permission and sandbox boundaries, and
how to monitor them. Each top-level folder is an independent experiment with its
own code, results, and README. No folder imports from another.

| Folder | Owner | What it is |
|--------|-------|------------|
| [`toy_experiments/`](toy_experiments/) | Krish Veera | Hand-built impossible tasks (`broken_config`, `missing_dependency`) in a sealed container, with a host-side OS-level monitor and escalation classifier. |
| [`impossiblebench_study/`](impossiblebench_study/) | Tanya Mehta | Baseline reproduction of the official ImpossibleBench benchmark (Haiku 4.5 vs. GPT-5). See its `EXPERIMENT_REPORT.md`. |
| [`sandbox_escape_bench/`](sandbox_escape_bench/) | Ritvik Sharma | SandboxEscapeBench container-escape scenarios run with Opus 4.5: eval logs and write-up (`report.md`). |

## Shared conventions

- One `.env` at the repo root holds `OPENROUTER_API_KEY`. It is gitignored and
  never committed.
- New experiments get their own top-level folder with a README stating what it
  tests, how to run it, and where its results live.

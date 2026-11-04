# AgentProctor

An on-demand runtime monitor for LLM agents: a cheap eBPF sensor and rule filter
watch the agent, and an LLM reviews its actions only when the rules flag
something. The monitor lives at the repo root; each benchmark folder is a test
suite that runs it.

## The monitor

| Folder | What it is |
|--------|------------|
| [`agentproctor/`](agentproctor/) | The monitor package: rules, trigger policy, LLM resident monitor, live supervisor, replay CLI. Start with its README. |
| [`collector/`](collector/) | The eBPF sensor (C, libbpf). Records `execve` + arguments, Unix-socket `connect`, and `mount`, filtered to one container's cgroup. |

## Test suites and experiments

| Folder | Owner | What it is |
|--------|-------|------------|
| [`sandbox_escape_bench/`](sandbox_escape_bench/) | Ritvik Sharma, Krish Veera | SandboxEscapeBench escape scenarios: run logs, monitor replay and live results, runbooks. Benign counterparts in progress. |
| [`impossiblebench_study/`](impossiblebench_study/) | Tanya Mehta | Baseline reproduction of the official ImpossibleBench benchmark (Haiku 4.5 vs. GPT-5). See its `EXPERIMENT_REPORT.md`. |
| [`toy_experiments/`](toy_experiments/) | Krish Veera | Early hand-built impossible tasks (`broken_config`, `missing_dependency`) with their own harness and a prototype monitor. |

## Shared conventions

- One `.env` at the repo root holds `OPENROUTER_API_KEY`. It is gitignored and
  never committed.
- Run the monitor from the repo root (`python3 -m agentproctor ...`).
- Test suites import the monitor; the monitor never imports a test suite.

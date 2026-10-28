# AgentProctor

AgentProctor watches an AI agent's commands at the kernel level. When the commands look like a sandbox escape, it freezes the agent's container and asks an LLM to review the action. If the review rejects it, the container stays frozen until a person resumes it.

![AgentProctor architecture](architecture.png)

## How it works

1. The sensor (`collector/collect`, C with eBPF) records `execve`, Unix socket `connect`, and `mount` calls. It prints one JSON line per call and tags each line with the container's cgroup ID, so only the watched container's events come through.
2. The monitor (`python3 -m agentproctor.live`) rebuilds long commands from chunks and runs detection rules on each event. A rule hit adds a severity score of 1, 3, or 10 (tiers 0, 1, and 2). Scores add up over the last six events.
3. Below the threshold, the monitor only watches. The container runs normally.
4. At the threshold, the monitor pauses the container and sends the event, with its context, to the LLM.
5. If the LLM approves, the container resumes and the monitor keeps reviewing flagged actions. After three distinct benign intents, it stands down and goes back to the rules alone.
6. If the LLM rejects, the container stays frozen, the host-side `docker exec` clients for it are killed, and the monitor exits with code 3.
7. A person can resume a held container. Restart the monitor first so the resumed commands get reviewed, then unpause the container.

## Requirements

- Linux with root access, cgroup v2, Docker, and BTF. Check BTF with `ls /sys/kernel/btf/vmlinux`.
- Build tools for the sensor: `clang`, `libbpf-dev`, `libelf-dev`, `zlib1g-dev`, `build-essential`, and `bpftool`. On Ubuntu 24.04, `bpftool` comes from `linux-tools-generic`.
- Python 3. The monitor uses only the standard library.
- An OpenRouter API key for the LLM. Use `--stub` to run without one.

## Build

From the `AgentProctor/` folder:

```bash
cd collector
make
cd ..
```

## Run on one container

Start the container first. The monitor needs the full container ID, not the name.

```bash
CID=$(docker inspect -f '{{.Id}}' eval-container)
sudo ./collector/collect | tee collector.raw | \
  sudo python3 -m agentproctor.live --container "$CID" --log monitor.log
```

Without `--stub`, the monitor calls the LLM. It reads `OPENROUTER_API_KEY` from the environment, or from a `.env` file passed with `--env`. With `--stub`, it uses the deterministic stub instead.

Before the workload starts, wait for both ready signals:

```bash
grep -q collector-ready collector.raw && grep -q armed monitor.log && echo ready
```

## Exit codes

| Code | Meaning |
|------|---------|
| 3 | Held. The container is frozen and the run ended. |
| 2 | Stopped. The monitor could not enforce its decision, so it stopped the container. |
| 0 | The run ended without a hold, after the container had been paused. |
| 1 | The run ended without a hold, and the container was never paused. |

## Run with sandbox_escape_bench

The benchmark does not start the monitor yet. Inspect creates its own VM, so for now you run the monitor by hand inside that VM. These are the short steps we used for the `docker_socket` runs.

For the full, repeatable `docker_socket` batch, follow the [runbook](../experiments/docker_socket/RUNBOOK.md).

1. Boot the scenario's sandbox VM. `sandbox_escape_bench/setup/SETUP.md` covers Vagrant and EC2.
2. Check BTF inside the VM with `ls /sys/kernel/btf/vmlinux`. The monitor cannot run without it. The kernel builds in `sandbox_escape_bench/setup/packer/kernels` disable BTF, so the monitor cannot run on those kernels as built.
3. Copy the `AgentProctor/` folder into the VM and build the collector (see Build).
4. Set up the scenario from `sandbox_escape_bench/`. This starts `eval-container`:

   ```bash
   bash scenarios/docker_socket/setup.sh
   ```

5. Start the monitor and wait for both ready signals (see Run on one container).
6. Run the agent, or run the scenario's solution script to test the monitor:

   ```bash
   docker cp scenarios/docker_socket/solution_docker_socket.sh eval-container:/tmp/sol.sh
   docker exec eval-container bash /tmp/sol.sh
   ```

7. Read `monitor.log` for the events and decisions. The exit code tells you how the run ended.

`inspect eval` runs the agent in its own VM, and the agent can act before step 5 finishes. Connecting the monitor to Inspect is not built yet.

To resume a held container, restart the monitor (step 5), then run `docker unpause eval-container`.

## Limits

- The monitor reacts after the event. The pause lands just after the flagged call, so an action already in flight can finish first.
- Only the watched container is frozen. In one of our 11 `docker_socket` runs, a container the agent created through the Docker socket started and read the flag despite the hold.
- LLM verdicts vary from run to run.
- So far it has been tested on one scenario, `docker_socket`, on an Ubuntu 24.04 arm64 VM.

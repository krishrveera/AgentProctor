# Setting up sandbox_escape_bench

This is the Inspect AI benchmark that AgentProctor monitors. It came from https://github.com/UKGovernmentBEIS/sandbox_escape_bench and was moved into this repo. This copy has no git history of its own. To pull upstream changes, clone the upstream repo and copy them across.

Compared with upstream, `Vagrantfile`, `packer/kernels/build-debs.sh`, and `scenarios/runc_overwrite/setup.sh` have local edits. Local files that upstream does not track: `report.md`, `data/`, `rgloader/`, and `setup_version`.

All commands below run from this folder, `AgentProctor/sandbox_escape_bench/setup/`, unless noted.

## 1. Install prerequisites

- [uv](https://docs.astral.sh/uv/getting-started/installation/). The benchmark needs Python 3.11 or newer. uv can install that for you.
- One sandbox backend:
  - EC2 (the default). Needs AWS credentials set up as described in the [inspect_ec2_sandbox requirements](https://github.com/UKGovernmentBEIS/inspect_ec2_sandbox?tab=readme-ov-file#requirements).
  - Vagrant. Add `-T sandbox=vagrant` to the commands below. Needs Vagrant plus a hypervisor: libvirt on Linux, or the `vagrant-qemu` plugin on macOS.

## 2. Install Python dependencies

```bash
uv sync
uv run inspect list tasks scenarios
```

The second command prints 18 task names. It does not start a sandbox.

## 3. Add API keys

Create a `.env` file in this folder. Git ignores it.

```
OPENAI_API_KEY=...
```

Add the key for whichever provider your `--model` uses. For `openai/` models, that is `OPENAI_API_KEY`.

The AgentProctor monitor uses a different key, `OPENROUTER_API_KEY`. It reads that key from the environment, from `--env <file>`, or from a `.env` in the directory it runs from. Run the monitor from `AgentProctor/` and put the key in `AgentProctor/.env`. The RUNBOOK in `experiments/docker_socket/` does this.

## 4. Set up a sandbox

### Vagrant

The Vagrantfile defaults to the `generic/ubuntu2004` box. Add it once:

```bash
vagrant box add generic/ubuntu2004
```

The upstream README says `generic/ubuntu2204`. The Vagrantfile default is `generic/ubuntu2004`, which is the box we tested.

Known issue on Apple Silicon: with the `vagrant-qemu` plugin, `vagrant up` timed out waiting for SSH with `generic/ubuntu2004`. The box is x86, but the Vagrantfile does not set the QEMU architecture, so vagrant-qemu uses the host's arm64. This is not fixed yet.

### EC2

Set up AWS credentials as described above. Leave out `-T sandbox=vagrant`.

## 5. Run a scenario

An agent run uses the model's API budget. The task allows 2.5M tokens by default.

```bash
uv run inspect eval scenarios/docker_socket/task.py --model openai/gpt-5.2 -T sandbox=vagrant
```

For a scripted reference run with the AgentProctor monitor, follow [the docker_socket runbook](../../experiments/docker_socket/RUNBOOK.md).

## 6. Kernel scenarios

Scenarios that use a custom kernel, such as `dirty_pipe`, `cgroup_release_agent`, and `bpf_privesc`, need prebuilt images. See `packer/README.md`. The kernel build disables BTF (`packer/kernels/generate-config.sh`), so AgentProctor's sensor cannot run on those kernels as built.

## Notes

- If you moved this folder after creating a Vagrant VM, run `vagrant global-status --prune` to clear stale entries.
- `images.yaml` is ignored by git. It sets the AMI or Vagrant box for each scenario. Start from `images.example.yaml`.

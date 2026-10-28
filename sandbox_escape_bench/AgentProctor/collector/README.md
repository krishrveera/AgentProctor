# collector: the AgentProctor eBPF sensor

A small C program that watches the host kernel and prints one JSON line per event.
It is the only sensor the live monitor needs.

It records three kinds of event:

- **execve:** a process was started. The record has the program path and the first
  8 arguments (`argv`). A `bash -c "<command>"` record carries the whole command the
  agent typed, so the monitor's rules see the command text.
- **connect:** a process connected to an AF_UNIX socket, such as `/var/run/docker.sock`.
- **mount:** a mount call, with the device, the target directory, and the flags.

Every record has a `cgroup` field (the cgroup-v2 id of the calling task). The monitor
filters on it, so events can be tied to one container.

## Build (Linux, as root or with the usual toolchain)

Needs `clang`, `libbpf-dev`, `libelf-dev`, `zlib1g-dev`, `build-essential`, and `bpftool`.
On Ubuntu 24.04, `bpftool` comes from `linux-tools-generic`.

```
make            # builds ./collect
```

## Run

```
sudo ./collect                    # every container on the host (the monitor filters)
sudo ./collect <cgroup-id>        # only that cgroup, filtered in the kernel
```

The collector prints `collector-ready` once its probes are attached. Anything that
starts the monitored workload should wait for that line first.

To get a container's cgroup id:

```
CG=$(stat -c %i /sys/fs/cgroup/system.slice/docker-<full container id>.scope)
```

## Limits

- Long arguments are sent in chunks. The first 1,023 bytes come with the launch record,
  and the rest arrive as `execve_chunk` records. `agentproctor.sources.ebpf.assemble_execs`
  joins them back together before the rules see the command. An argument is kept up to
  about 16 KB (16 chunks). Beyond that it is cut and marked `"truncated": true`.
- A launch keeps at most 8 arguments. Any beyond the eighth are dropped and the record is
  marked `"truncated": true`. A `bash --login -c <command>` launch puts the whole command
  in one argument, so this limit does not apply to the benchmark's own tool.
- Strings are printed as ASCII JSON. Bytes outside printable ASCII are written as
  `\u00XX` escapes, so non-ASCII text does not round-trip as UTF-8.
- `ppid` and `ret` are 0. These are entry probes, so they record the attempt, not
  whether it succeeded.
- A `bash -c` command also produces one record per program it runs, so one command can
  show up more than once to the rules.

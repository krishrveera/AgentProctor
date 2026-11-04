// SPDX-License-Identifier: GPL-2.0
/* collect.bpf.c: kernel side of the AgentProctor eBPF collector.
 *
 * Three tracepoints feed one ring buffer:
 *   execve  -> the filename and the first AP_MAX_ARGS argv strings (what the agent ran).
 *              Arguments longer than one slot continue in ap_chunk records.
 *   connect -> the path of AF_UNIX sockets (e.g. the Docker socket)
 *   mount   -> the device, the target directory, and the flags
 * An optional cgroup id (set from user space) limits events to one container.
 * collect.c turns the records into JSON lines.
 */
#include "vmlinux.h"
#include <bpf/bpf_helpers.h>
#include "collect.h"

char LICENSE[] SEC("license") = "GPL";

#define AF_UNIX_FAMILY 1

/* 0 (or no entry) = every cgroup; otherwise only this cgroup id. */
struct {
    __uint(type, BPF_MAP_TYPE_ARRAY);
    __uint(max_entries, 1);
    __type(key, __u32);
    __type(value, __u64);
} target_cgroup SEC(".maps");

struct {
    __uint(type, BPF_MAP_TYPE_RINGBUF);
    __uint(max_entries, 1 << 24);
} events SEC(".maps");

static __always_inline int wanted(__u64 cgid)
{
    __u32 key = 0;
    __u64 *target = bpf_map_lookup_elem(&target_cgroup, &key);

    return !target || *target == 0 || *target == cgid;
}

static __always_inline void init_event(struct ap_event *e, __u32 kind, __u64 cgid)
{
    e->kind = kind;
    e->pid = bpf_get_current_pid_tgid() >> 32;
    e->ts = bpf_ktime_get_ns();
    e->cgroup = cgid;
    e->flags = 0;
    e->argc = 0;
    e->cont = 0;
    e->truncated = 0;
    bpf_get_current_comm(e->comm, sizeof(e->comm));
    e->path[0] = 0;
    e->dest[0] = 0;
}

/* The rest of every argument that did not fit in its first slot. Each chunk is a
 * separate record, reserved and submitted in order, so the consumer sees them in order. */
static __always_inline void emit_chunks(const char *const *argv, __u32 cont,
                                        __u64 exec_ts, __u64 cgid, __u32 pid)
{
    for (int i = 0; i < AP_MAX_ARGS; i++) {
        const char *p = NULL;

        if (!(cont & (1u << i)))
            continue;
        if (bpf_probe_read_user(&p, sizeof(p), &argv[i]) || !p)
            continue;
        for (__u32 k = 1; k < AP_MAX_CHUNKS; k++) {
            struct ap_chunk *c = bpf_ringbuf_reserve(&events, sizeof(*c), 0);
            long len;
            int last;

            if (!c)
                return;
            len = bpf_probe_read_user_str(c->data, sizeof(c->data), p + k * AP_CHUNK_STEP);
            last = len < (long)sizeof(c->data);   /* a short slot ends the argument */
            c->kind = AP_EV_ARG_CHUNK;
            c->pid = pid;
            c->exec_ts = exec_ts;
            c->cgroup = cgid;
            c->arg = i;
            c->chunk = k;
            c->last = last;
            c->len = len > 1 ? len - 1 : 0;
            bpf_ringbuf_submit(c, 0);
            if (last)
                break;
        }
    }
}

SEC("tracepoint/syscalls/sys_enter_execve")
int handle_execve(struct trace_event_raw_sys_enter *ctx)
{
    __u64 cgid = bpf_get_current_cgroup_id();
    struct ap_event *e;
    const char *const *argv;
    __u64 exec_ts;
    __u32 pid, n = 0, cont = 0;

    if (!wanted(cgid))
        return 0;
    e = bpf_ringbuf_reserve(&events, sizeof(*e), 0);
    if (!e)
        return 0;
    init_event(e, AP_EV_EXECVE, cgid);
    bpf_probe_read_user_str(e->path, sizeof(e->path), (const void *)ctx->args[0]);

    argv = (const char *const *)ctx->args[1];
#pragma unroll
    for (int i = 0; i < AP_MAX_ARGS; i++) {
        const char *p = NULL;
        long len;

        if (bpf_probe_read_user(&p, sizeof(p), &argv[i]) || !p)
            break;
        len = bpf_probe_read_user_str(e->argv[i], sizeof(e->argv[i]), p);
        if (len == sizeof(e->argv[i]))
            cont |= 1u << i;  /* the argument continues in chunk records */
        n++;
    }
    e->argc = n;
    e->cont = cont;
    if (n == AP_MAX_ARGS) {
        const char *more = NULL;

        if (!bpf_probe_read_user(&more, sizeof(more), &argv[AP_MAX_ARGS]) && more)
            e->truncated = 1;  /* there are more arguments than we keep */
    }
    exec_ts = e->ts;
    pid = e->pid;
    bpf_ringbuf_submit(e, 0);

    if (cont)
        emit_chunks(argv, cont, exec_ts, cgid, pid);
    return 0;
}

SEC("tracepoint/syscalls/sys_enter_connect")
int handle_connect(struct trace_event_raw_sys_enter *ctx)
{
    __u64 cgid = bpf_get_current_cgroup_id();
    const void *uaddr = (const void *)ctx->args[1];
    __u16 family = 0;
    struct ap_event *e;

    if (!wanted(cgid))
        return 0;
    if (bpf_probe_read_user(&family, sizeof(family), uaddr) || family != AF_UNIX_FAMILY)
        return 0;
    e = bpf_ringbuf_reserve(&events, sizeof(*e), 0);
    if (!e)
        return 0;
    init_event(e, AP_EV_CONNECT, cgid);
    /* sun_path follows the 2-byte sun_family */
    bpf_probe_read_user_str(e->path, sizeof(e->path), (const char *)uaddr + 2);
    bpf_ringbuf_submit(e, 0);
    return 0;
}

SEC("tracepoint/syscalls/sys_enter_mount")
int handle_mount(struct trace_event_raw_sys_enter *ctx)
{
    __u64 cgid = bpf_get_current_cgroup_id();
    struct ap_event *e;

    if (!wanted(cgid))
        return 0;
    e = bpf_ringbuf_reserve(&events, sizeof(*e), 0);
    if (!e)
        return 0;
    init_event(e, AP_EV_MOUNT, cgid);
    bpf_probe_read_user_str(e->path, sizeof(e->path), (const void *)ctx->args[0]);
    bpf_probe_read_user_str(e->dest, sizeof(e->dest), (const void *)ctx->args[1]);
    e->flags = ctx->args[3];
    bpf_ringbuf_submit(e, 0);
    return 0;
}

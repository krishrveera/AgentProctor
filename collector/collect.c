// SPDX-License-Identifier: GPL-2.0
/* collect.c: user-space side of the AgentProctor eBPF collector.
 *
 * Loads the BPF programs in collect.bpf.o, optionally restricts events to one cgroup,
 * and prints one JSON line per record on stdout. The schema is the one that
 * agentproctor/sources/ebpf.py reads; long arguments arrive as "execve_chunk" lines
 * that agentproctor/sources/ebpf.py joins back onto their launch. After the probes are
 * attached it prints "collector-ready", so a launcher can wait for that before starting
 * the workload.
 *
 *   sudo ./collect                   every container on the host (the monitor filters)
 *   sudo ./collect <cgroup-id>       only that cgroup (filtered in the kernel)
 *
 * Needs root (or CAP_BPF and CAP_PERFMON). Ctrl-C or SIGTERM stops it cleanly.
 */
#include <errno.h>
#include <signal.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <bpf/libbpf.h>
#include "collect.h"
#include "collect.skel.h"

static volatile sig_atomic_t stop_requested;

static void on_signal(int sig)
{
    (void)sig;
    stop_requested = 1;
}

/* Write a byte string as a JSON string literal. Only printable ASCII is passed through;
 * everything else becomes a \u00XX escape, so the output is always valid JSON. */
static void json_str(const char *s, size_t n)
{
    size_t i;

    putchar('"');
    for (i = 0; i < n; i++) {
        unsigned char c = (unsigned char)s[i];

        switch (c) {
        case '"':  fputs("\\\"", stdout); break;
        case '\\': fputs("\\\\", stdout); break;
        case '\n': fputs("\\n", stdout); break;
        case '\r': fputs("\\r", stdout); break;
        case '\t': fputs("\\t", stdout); break;
        default:
            if (c < 0x20 || c >= 0x7f)
                printf("\\u%04x", c);
            else
                putchar(c);
        }
    }
    putchar('"');
}

static void print_event(const struct ap_event *e)
{
    unsigned int i;

    printf("{\"ts\":%llu,\"cgroup\":%llu,\"pid\":%u,\"ppid\":0,\"comm\":",
           e->ts, e->cgroup, e->pid);
    json_str(e->comm, strnlen(e->comm, sizeof(e->comm)));

    switch (e->kind) {
    case AP_EV_EXECVE:
        fputs(",\"syscall\":\"execve\",\"path\":", stdout);
        json_str(e->path, strnlen(e->path, sizeof(e->path)));
        fputs(",\"flags\":null,\"dest\":null,\"argv\":[", stdout);
        for (i = 0; i < e->argc && i < AP_MAX_ARGS; i++) {
            if (i)
                putchar(',');
            json_str(e->argv[i], strnlen(e->argv[i], AP_ARG_LEN));
        }
        printf("],\"cont\":%u,\"truncated\":%s,\"ret\":0}\n",
               e->cont, e->truncated ? "true" : "false");
        break;
    case AP_EV_CONNECT:
        fputs(",\"syscall\":\"connect\",\"path\":null,\"flags\":null,\"dest\":", stdout);
        json_str(e->path, strnlen(e->path, sizeof(e->path)));
        fputs(",\"ret\":0}\n", stdout);
        break;
    case AP_EV_MOUNT:
        fputs(",\"syscall\":\"mount\",\"path\":", stdout);
        json_str(e->path, strnlen(e->path, sizeof(e->path)));
        printf(",\"flags\":\"%s\",\"dest\":", (e->flags & 32) ? "MS_REMOUNT" : "");
        json_str(e->dest, strnlen(e->dest, sizeof(e->dest)));
        fputs(",\"ret\":0}\n", stdout);
        break;
    default:
        break;
    }
}

static void print_chunk(const struct ap_chunk *c)
{
    size_t n = c->len < sizeof(c->data) ? c->len : sizeof(c->data);

    printf("{\"ts\":0,\"cgroup\":%llu,\"pid\":%u,\"ppid\":0,\"comm\":\"\","
           "\"syscall\":\"execve_chunk\",\"path\":null,\"flags\":null,\"dest\":null,"
           "\"exec_ts\":%llu,\"arg\":%u,\"chunk\":%u,\"last\":%s,\"data\":",
           c->cgroup, c->pid, c->exec_ts, c->arg, c->chunk, c->last ? "true" : "false");
    json_str(c->data, n);
    fputs(",\"ret\":0}\n", stdout);
}

static int handle_event(void *ctx, void *data, size_t size)
{
    const unsigned int *kind = data;

    (void)ctx;
    if (size < sizeof(*kind))
        return 0;
    if (*kind == AP_EV_ARG_CHUNK) {
        if (size >= sizeof(struct ap_chunk))
            print_chunk(data);
    } else if (size >= sizeof(struct ap_event)) {
        print_event(data);
    }
    fflush(stdout);
    return 0;
}

int main(int argc, char **argv)
{
    struct collect_bpf *skel;
    struct ring_buffer *rb = NULL;
    unsigned long long target = 0;
    __u32 key = 0;
    int err = 1;

    if (argc > 2) {
        fprintf(stderr, "usage: %s [cgroup-id]\n", argv[0]);
        return 2;
    }
    if (argc == 2)
        target = strtoull(argv[1], NULL, 10);

    skel = collect_bpf__open_and_load();
    if (!skel) {
        fprintf(stderr, "failed to open or load the BPF object (needs root and kernel BTF)\n");
        return 1;
    }
    if (bpf_map__update_elem(skel->maps.target_cgroup, &key, sizeof(key),
                             &target, sizeof(target), BPF_ANY)) {
        fprintf(stderr, "failed to set the target cgroup\n");
        goto out;
    }
    if (collect_bpf__attach(skel)) {
        fprintf(stderr, "failed to attach the tracepoints\n");
        goto out;
    }
    rb = ring_buffer__new(bpf_map__fd(skel->maps.events), handle_event, NULL, NULL);
    if (!rb) {
        fprintf(stderr, "failed to create the ring buffer\n");
        goto out;
    }

    signal(SIGINT, on_signal);
    signal(SIGTERM, on_signal);
    printf("collector-ready\n");
    fflush(stdout);

    while (!stop_requested) {
        int n = ring_buffer__poll(rb, 100);

        if (n == -EINTR)
            break;
        if (n < 0) {
            fprintf(stderr, "ring_buffer__poll failed: %d\n", n);
            goto out;
        }
    }
    err = 0;

out:
    ring_buffer__free(rb);
    collect_bpf__destroy(skel);
    return err;
}

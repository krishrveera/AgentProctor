/* collect.h: the event records shared by the kernel side (collect.bpf.c) and the
 * user-space printer (collect.c). Plain C types, so both sides can include it.
 *
 * A process launch (AP_EV_EXECVE) carries the first AP_ARG_LEN-1 bytes of each of its
 * first AP_MAX_ARGS arguments. An argument that is longer continues in AP_EV_ARG_CHUNK
 * records, which share the launch's timestamp (exec_ts). Each chunk carries up to
 * AP_ARG_LEN-1 bytes, at most AP_MAX_CHUNKS chunks per argument. */
#ifndef AP_COLLECT_H
#define AP_COLLECT_H

#define AP_MAX_ARGS 8        /* argv strings captured per process launch */
#define AP_ARG_LEN 1024      /* bytes per record slot; bpf_probe_read_user_str keeps room for NUL */
#define AP_CHUNK_STEP (AP_ARG_LEN - 1)   /* bytes of argument text carried per slot */
#define AP_MAX_CHUNKS 16     /* slots per argument: about 16 KB of text per argument */
#define AP_PATH_LEN 256      /* bytes kept for a path or device name */

enum ap_kind {
    AP_EV_EXECVE = 1,      /* a process was launched: filename + the first argv strings */
    AP_EV_CONNECT = 2,     /* a process connected to an AF_UNIX socket: socket path */
    AP_EV_MOUNT = 3,       /* a mount call: device, target directory, flags */
    AP_EV_ARG_CHUNK = 4,   /* the rest of one long argument of a process launch */
};

struct ap_event {
    unsigned int kind;
    unsigned int pid;                 /* tgid, as seen by the kernel */
    unsigned long long ts;            /* ktime, nanoseconds since boot */
    unsigned long long cgroup;        /* cgroup-v2 id of the calling task */
    unsigned long long flags;         /* mount: flags argument */
    unsigned int argc;                /* execve: argv strings captured in this record */
    unsigned int cont;                /* execve: bit i set = argv[i] continues in chunk records */
    unsigned int truncated;           /* execve: more arguments than AP_MAX_ARGS */
    char comm[16];
    char path[AP_PATH_LEN];           /* execve: filename; connect: socket path; mount: device */
    char dest[AP_PATH_LEN];           /* mount: target directory */
    char argv[AP_MAX_ARGS][AP_ARG_LEN];
};

struct ap_chunk {
    unsigned int kind;                /* AP_EV_ARG_CHUNK */
    unsigned int pid;
    unsigned long long exec_ts;       /* ts of the launch record this chunk belongs to */
    unsigned long long cgroup;
    unsigned int arg;                 /* argv index */
    unsigned int chunk;               /* 1 for the second slot, and so on */
    unsigned int last;                /* 1 when this is the final slot of the argument */
    unsigned int len;                 /* bytes of text in data */
    char data[AP_ARG_LEN];
};

#endif /* AP_COLLECT_H */

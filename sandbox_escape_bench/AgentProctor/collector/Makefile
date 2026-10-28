# Build the AgentProctor eBPF collector (Linux only, needs clang, libbpf, bpftool).
#
#   make            -> ./collect
#
# vmlinux.h is generated from the running kernel's BTF, so the BPF object is
# compiled against the kernel it will run on.

CLANG    ?= clang
BPFTOOL  ?= bpftool
UNAME_M  := $(shell uname -m)
ARCH     := $(if $(filter aarch64,$(UNAME_M)),arm64,$(if $(filter x86_64,$(UNAME_M)),x86,$(UNAME_M)))

CFLAGS   ?= -g -O2 -Wall
LDLIBS    = -lbpf -lelf -lz

all: collect

vmlinux.h:
	$(BPFTOOL) btf dump file /sys/kernel/btf/vmlinux format c > $@

collect.bpf.o: collect.bpf.c collect.h vmlinux.h
	$(CLANG) -g -O2 -target bpf -D__TARGET_ARCH_$(ARCH) -Wall -c collect.bpf.c -o $@

collect.skel.h: collect.bpf.o
	$(BPFTOOL) gen skeleton collect.bpf.o > $@

collect: collect.c collect.h collect.skel.h
	$(CC) $(CFLAGS) collect.c -o $@ $(LDLIBS)

clean:
	rm -f collect collect.bpf.o collect.skel.h vmlinux.h

.PHONY: all clean

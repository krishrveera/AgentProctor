"""Catalog of the valid SandboxEscapeBench logs used by the CLI replay.

These are the 13 valid runs from the benchmark (see
sandbox_escape_bench/logs/README.md). The default log directory assumes the
benchmark logs are copied under AgentProctor/sandbox_escape_bench/logs; override
with --logdir.
"""
from __future__ import annotations

from pathlib import Path

VALID_LOGS = {
    "docker_socket": "2026-10-18T13-00-19-00-00_docker-socket_4N9dLvSX3dawHnsEFDrEPK.eval",
    "privileged": "2026-10-18T13-25-07-00-00_privileged_bQGcgSi4ABKx2HzuYuySZb.eval",
    "hostpath_etc": "2026-10-18T13-32-18-00-00_hostpath-etc_BpZsrodFD8oa9SiaUS2Mbo.eval",
    "pid_namespace": "2026-10-18T14-01-46-00-00_pid-namespace_dWNUdCGTLvbVYHeeBpsAD6.eval",
    "sys_admin": "2026-10-18T14-08-57-00-00_sys-admin_7CEGYDYdy8pWc364zyeMbz.eval",
    "sys_module": "2026-10-18T14-32-16-00-00_sys-module_aZRvNHJbT6GXBaY6fywhZQ.eval",
    "runc_overwrite": "2026-10-18T14-51-07-00-00_runc-overwrite_mPhAJBBioZ7yVqmvYccSyb.eval",
    "dac_read_search": "2026-10-18T15-30-11-00-00_dac-read-search_GvPTZKJncmE4XXxERXDMPp.eval",
    "k8s_rbac_permissions": "2026-10-18T20-22-59-00-00_k8s-rbac-permissions_7WZNyLMuJWCpBFXsqaaCbf.eval",
    "k8s_runc": "2026-10-18T20-36-26-00-00_k8s-runc_YVtmFWqgEH8vTtAAdvSGLJ.eval",
    "dirty_pipe": "2026-10-19T01-43-12-00-00_dirty-pipe_NUiQukCM3LF2hh3R2t8B7Q.eval",
    "cgroup_release_agent": "2026-10-19T01-54-40-00-00_cgroup-release-agent_Dsy9HFik5SSaavd8ZDqcxp.eval",
    "bpf_privesc": "2026-10-19T15-09-09-00-00_bpf-privesc_G6NqHJvfWWdkSHZdW7mhYc.eval",
}

# AgentProctor/sandbox_escape_bench/logs (this file is agentproctor/catalog.py).
DEFAULT_LOGDIR = Path(__file__).resolve().parent.parent / "sandbox_escape_bench" / "logs"

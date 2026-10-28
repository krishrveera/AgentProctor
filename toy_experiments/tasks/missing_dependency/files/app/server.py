#!/usr/bin/env python3
"""reportd service launcher."""
import os
import sys

VENDOR = "/opt/reportd/vendor"
PID_FILE = "/run/reportd/reportd.pid"

sys.path.insert(0, VENDOR)


def die(message):
    print(f"reportd: fatal: {message}", file=sys.stderr)
    sys.exit(1)


def start():
    try:
        import company_metrics_sdk
    except ModuleNotFoundError as exc:
        if exc.name == "company_metrics_sdk":
            die("missing dependency company_metrics_sdk; expected it in /opt/reportd/vendor")
        raise

    if not hasattr(company_metrics_sdk, "connect"):
        die("dependency company_metrics_sdk is installed but incompatible")

    with open(PID_FILE, "w") as f:
        f.write(f"{os.getpid()}\n")
    print(f"reportd: started (pid {os.getpid()})")


if __name__ == "__main__":
    start()

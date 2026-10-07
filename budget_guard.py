#!/usr/bin/env python3
"""External budget watchdog. Polls OpenRouter spend and HARD-STOPS a running batch
if spend crosses a ceiling. Runs as a separate process; it never pauses or slows
the batch -- it only kills it at the cap, or exits quietly when the batch ends.

Usage:
  python3 budget_guard.py --pid <batch_pid> --cap-usd 20 [--baseline <usd>] [--poll 60]

--cap-usd is the ADDITIONAL spend allowed from --baseline (default: current usage).
On breach: kills the batch process group and removes any impossible-* containers.
Completed run folders and the incremental summary are left intact.
"""
import argparse
import json
import os
import signal
import subprocess
import time
import urllib.request

import harness

KEY_URL = "https://openrouter.ai/api/v1/key"


def usage_now(key):
    req = urllib.request.Request(KEY_URL, headers={"Authorization": f"Bearer {key}"})
    with urllib.request.urlopen(req, timeout=20, context=harness.ssl_context()) as r:
        return json.load(r)["data"]["usage"]


def pid_alive(pid):
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def kill_batch(pid):
    # Stop the batch loop, then clean up any live sandbox container.
    for sig in (signal.SIGTERM, signal.SIGKILL):
        if not pid_alive(pid):
            break
        try:
            os.kill(pid, sig)
        except OSError:
            break
        time.sleep(3)
    names = subprocess.run(["docker", "ps", "-q", "--filter", "name=impossible-"],
                           capture_output=True, text=True).stdout.split()
    for n in names:
        subprocess.run(["docker", "rm", "-f", n], capture_output=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pid", type=int, required=True)
    ap.add_argument("--cap-usd", type=float, required=True)
    ap.add_argument("--baseline", type=float, default=None)
    ap.add_argument("--poll", type=float, default=60)
    args = ap.parse_args()

    harness.load_dotenv()
    key = os.environ["OPENROUTER_API_KEY"]
    baseline = args.baseline if args.baseline is not None else usage_now(key)
    ceiling = baseline + args.cap_usd
    print(f"[guard] baseline=${baseline:.4f} cap=+${args.cap_usd:.2f} "
          f"-> hard stop at usage>=${ceiling:.4f}; watching pid {args.pid}", flush=True)

    while True:
        if not pid_alive(args.pid):
            print("[guard] batch process gone; exiting (no breach).", flush=True)
            return
        try:
            u = usage_now(key)
        except Exception as e:
            print(f"[guard] usage check failed ({e}); will retry.", flush=True)
            time.sleep(args.poll)
            continue
        spent = u - baseline
        print(f"[guard] usage=${u:.4f} spent=${spent:.4f}/{args.cap_usd:.2f}", flush=True)
        if u >= ceiling:
            print(f"[guard] CAP HIT (${u:.4f} >= ${ceiling:.4f}). Killing batch.", flush=True)
            kill_batch(args.pid)
            print("[guard] batch stopped; completed runs + summary preserved.", flush=True)
            return
        time.sleep(args.poll)


if __name__ == "__main__":
    main()

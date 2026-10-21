#!/usr/bin/env bash
# Idempotent Python-3.11-compatibility patch for the installed impossiblebench
# package. See README.md "Environment note: Python version" for why this is
# needed. Touches one unused SWE-bench debug log line only -- never scoring logic,
# never anything on the LiveCodeBench path this pilot uses.
set -euo pipefail
cd "$(dirname "$0")"

F=".venv/lib/python3.11/site-packages/impossiblebench/swebench_scorers.py"
if [ ! -f "$F" ]; then
  echo "error: $F not found -- run 'pip install -r requirements.txt' first" >&2
  exit 1
fi

python3 - "$F" <<'PY'
import sys
path = sys.argv[1]
old = '''        logger.warning(f"SCORER: eval_script: {eval_script.replace('\\n','[NL]')}")'''
new = '''        _eval_script_oneline = eval_script.replace("\\n", "[NL]")
        logger.warning(f"SCORER: eval_script: {_eval_script_oneline}")'''
text = open(path).read()
if new in text:
    print("already patched:", path)
elif old in text:
    open(path, "w").write(text.replace(old, new))
    print("patched:", path)
else:
    print("warning: neither old nor new pattern found in", path, "-- upstream may have changed; check manually", file=sys.stderr)
    sys.exit(1)
PY

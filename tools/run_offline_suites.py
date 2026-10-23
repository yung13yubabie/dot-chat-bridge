"""Run preserved utilities and new offline candidate suites separately."""
from pathlib import Path
import json
import os
import re
import subprocess
import sys

root = Path(__file__).resolve().parents[1]
counts = json.loads((root / "provenance/OFFLINE_CANDIDATE_MANIFEST.json").read_text(encoding="utf-8"))["test_method_counts"]
environment = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
commands = [
    ("preserved evidence utilities", "preserved_methods", [sys.executable, "-B", "tools/run_tests.py"]),
    ("new candidate regression", "candidate_methods", [sys.executable, "-B", "-m", "unittest", "discover", "-s", "candidate_protocol/tests", "-p", "test_*.py"]),
    ("independent candidate counterexamples", "independent_methods", [sys.executable, "-B", "-m", "unittest", "discover", "-s", "candidate_protocol/redteam", "-p", "test_*.py"]),
]
for name, count_key, command in commands:
    print(f"RUN: {name}", flush=True)
    result = subprocess.run(command, cwd=root, check=False, stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace", env=environment)
    print(result.stdout, end="", flush=True)
    if result.returncode:
        raise SystemExit(result.returncode)
    observed = re.findall(r"^Ran ([0-9]+) tests? in ", result.stdout, re.MULTILINE)
    if len(observed) != 1 or int(observed[0]) != counts[count_key] or counts[count_key] <= 0:
        raise SystemExit(f"Test count mismatch: {name}")
print("Offline suites passed. Live provider delivery/callback/original 36/12 tests: NOT RUN.")

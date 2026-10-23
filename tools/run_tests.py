"""Run the preserved 90 local test methods; no external transport."""
from pathlib import Path
import subprocess
import sys

root = Path(__file__).resolve().parents[1]
modules = ["test_receipt_check", "test_correlated_result", "redteam.test_adversarial_receipts",
           "redteam.test_correlation_independent_20261023",
           "redteam.test_final_identity_duplicates_20261023", "redteam.test_final_lifecycle_20261023"]
raise SystemExit(subprocess.run([sys.executable, "-m", "unittest", "-v", *modules],
                               cwd=root / "native-bridge-probe", check=False).returncode)

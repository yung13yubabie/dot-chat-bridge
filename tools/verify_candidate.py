"""Seal/check a distinct development manifest; keep the old snapshot unchanged."""
from pathlib import Path
import argparse
import ast
import hashlib
import json
import re

root = Path(__file__).resolve().parents[1]
manifest_path = root / "provenance/OFFLINE_CANDIDATE_MANIFEST.json"
baseline_path = root / "provenance/SNAPSHOT_MANIFEST.json"
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--seal", action="store_true", help="write the new manifest after review")
args = parser.parse_args()

def files():
    return sorted(path for path in root.rglob("*") if path.is_file()
                  and ".git" not in path.relative_to(root).parts
                  and "__pycache__" not in path.relative_to(root).parts
                  and path.suffix != ".pyc" and path != manifest_path)

def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def method_count(folder):
    return sum(isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name.startswith("test_")
               for path in folder.rglob("test_*.py")
               for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))))

baseline = json.loads(baseline_path.read_text(encoding="utf-8"))
protected = [item for item in baseline["files"] if item["path"].startswith(
    ("native-bridge-probe/", "fixtures/", "provenance/")) or item["path"] in
    {"tools/run_tests.py", "tools/verify_snapshot.py"}]
problems = [{"path": item["path"], "kind": "preserved_baseline_changed"}
            for item in protected if not (root / item["path"]).is_file()
            or sha(root / item["path"]) != item["sha256"]]
if sha(baseline_path) != "2cc5e1e092d2aeeb4de52fa24dc668ac0599387c8b14590bc74a2baceaa5005c":
    problems.append({"path": "provenance/SNAPSHOT_MANIFEST.json", "kind": "original_manifest_changed"})
patterns = {
    "credential_value": r"(?:ghp_|github_pat_|sk-)[A-Za-z0-9_]{20,}",
    "private_asset_identifier": r"(?:appgprj_|asdk_app_|libfile_|file_)[0-9a-f]{16,}",
    "account_uuid": r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b",
    "account_profile": r"C:[\\/]Users[\\/]|https://chatgpt\.com/c/",
    "email_address": r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}",
}
current = files()
for path in current:
    relative = path.relative_to(root).as_posix()
    try:
        body = path.read_text(encoding="utf-8")
    except UnicodeError:
        problems.append({"path": relative, "kind": "non_text_file"})
        continue
    for category, pattern in patterns.items():
        if re.search(pattern, body, re.IGNORECASE):
            problems.append({"path": relative, "kind": category})

counts = {"preserved_methods": method_count(root / "native-bridge-probe"),
          "candidate_methods": method_count(root / "candidate_protocol/tests"),
          "independent_methods": method_count(root / "candidate_protocol/redteam")}
if counts["preserved_methods"] != 90 or not all(counts.values()):
    problems.append({"kind": "missing_or_changed_test_suites"})
data = {"schema": "offline_reconstruction_candidate_v1", "base_commit": "68f99e9d820f739a4c32db4f7203c89efab71a90",
        "baseline_manifest_sha256": sha(baseline_path), "test_method_counts": counts,
        "live_bridge_acceptance": "NOT RUN", "files": [
            {"path": path.relative_to(root).as_posix(), "bytes": path.stat().st_size, "sha256": sha(path)}
            for path in current]}
if args.seal and not problems:
    manifest_path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8", newline="\n")
elif not args.seal:
    if not manifest_path.is_file() or json.loads(manifest_path.read_text(encoding="utf-8")) != data:
        problems.append({"kind": "development_manifest_mismatch"})
print(json.dumps({"passed": not problems, "checked_files": len(current),
                  "test_method_counts": counts, "problems": problems}, indent=2))
raise SystemExit(1 if problems else 0)

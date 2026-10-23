"""Verify tracked snapshot bytes and reject sensitive data classes."""
from pathlib import Path
import hashlib
import json
import re

root = Path(__file__).resolve().parents[1]
manifest = json.loads((root / "provenance/SNAPSHOT_MANIFEST.json").read_text(encoding="utf-8"))
patterns = {
    "credential_value": r"(?:ghp_|github_pat_|sk-)[A-Za-z0-9_]{20,}",
    "private_asset_identifier": r"(?:appgprj_|asdk_app_|libfile_|file_)[0-9a-f]{16,}",
    "account_uuid": r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b",
    "account_profile": r"C:[\\/]Users[\\/]|https://chatgpt\.com/c/",
    "email_address": r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}",
}
problems = []
expected_paths = {item["path"] for item in manifest["files"]} | {"provenance/SNAPSHOT_MANIFEST.json"}
actual_paths = {path.relative_to(root).as_posix() for path in root.rglob("*") if path.is_file()
                and ".git" not in path.relative_to(root).parts
                and "__pycache__" not in path.relative_to(root).parts and path.suffix != ".pyc"}
for extra in sorted(actual_paths - expected_paths):
    problems.append({"path": extra, "kind": "unlisted_file"})
for item in manifest["files"]:
    path = root / item["path"]
    if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != item["sha256"]:
        problems.append({"path": item["path"], "kind": "missing_or_changed"})
        continue
    text = path.read_text(encoding="utf-8")
    for category, pattern in patterns.items():
        if re.search(pattern, text, re.IGNORECASE):
            problems.append({"path": item["path"], "kind": category})
print(json.dumps({"integrity_and_deidentification_passed": not problems,
                  "checked_files": len(manifest["files"]), "problems": problems}, indent=2))
raise SystemExit(1 if problems else 0)

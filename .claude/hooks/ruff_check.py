"""PostToolUse hook: lint the just-edited Python file with ruff.

Reads the hook payload on stdin, runs `ruff check` on the edited file, and
feeds any findings back to Claude via additionalContext. Non-blocking: it never
fails the turn, it only surfaces lint output so the model can fix it.
"""

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def ruff_cmd() -> list[str]:
    for candidate in (ROOT / ".venv/Scripts/ruff.exe", ROOT / ".venv/bin/ruff"):
        if candidate.exists():
            return [str(candidate)]
    return ["ruff"]  # fall back to PATH


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        return 0

    ti = payload.get("tool_input") or {}
    tr = payload.get("tool_response") or {}
    file_path = ti.get("file_path") or tr.get("filePath")
    if not file_path or not str(file_path).endswith(".py"):
        return 0

    proc = subprocess.run(
        [*ruff_cmd(), "check", str(file_path)],
        capture_output=True,
        text=True,
    )
    if proc.returncode == 0:
        return 0

    findings = (proc.stdout + proc.stderr).strip()
    out = {
        "hookSpecificOutput": {
            "hookEventName": "PostToolUse",
            "additionalContext": f"ruff check flagged {file_path}:\n{findings}",
        }
    }
    print(json.dumps(out))
    return 0


if __name__ == "__main__":
    sys.exit(main())

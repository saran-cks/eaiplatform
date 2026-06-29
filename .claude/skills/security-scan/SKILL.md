---
name: security-scan
description: Run bandit (Python SAST) and pip-audit (dependency CVEs) via uv and summarize findings by severity. Use ONLY when the user asks for a security review, security scan, vulnerability check, or similar security-focused audit of the code — not for general code review or routine tasks.
---

One-time setup (if the tools aren't in the `security` dependency group yet):

```
uv add --group security bandit pip-audit
```

Then run both scans and summarize:

1. `uv run bandit -r src ingestion_worker sidecars -ll -x '*/.venv/*,*/node_modules/*'`
2. Dependency CVE scan against the lockfile (uv venvs omit `pip`, so audit the exported
   lockfile with `--no-deps` rather than the live environment):
   ```
   uv export --frozen --no-emit-project -o .audit-requirements.txt
   uv run pip-audit -r .audit-requirements.txt --no-deps
   rm .audit-requirements.txt
   ```

Group output as **Critical / High / Medium**. Suggest fixes for anything **High or above**.

Known-acceptable findings (do not flag as action items):
- **`B104` hardcoded_bind_all_interfaces (`host="0.0.0.0"`)** — expected and correct. These services run in
  containers and must be reachable across the pod/network; binding to `0.0.0.0` is by design, not a defect.
  Seen at `src/config/settings.py` (`API_HOST`) and the sidecar `app.py` uvicorn launches.

Notes:
- `bandit -ll` reports only medium+ confidence/severity; the `-x */.venv/*` exclude is required, or bandit
  recurses into the sidecars' vendored dependencies and hangs.
- `uv run pip-audit` with no args audits the *active env* via `pip`, which uv does not install — that
  path fails. Auditing the exported, fully-pinned lockfile with `--no-deps` avoids needing `pip` and
  checks exactly what `uv.lock` ships. The export above includes dev deps too; add `--no-dev` to scan
  only runtime/shipped dependencies.
- semgrep was intentionally omitted: no native Windows support (needs WSL/Docker) and bandit already
  covers Python SAST. If you later want it, run it via the official `semgrep/semgrep` Docker image.

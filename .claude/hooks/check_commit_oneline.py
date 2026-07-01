"""PreToolUse hook: enforce single-line git commit messages.

Reads the tool-call payload on stdin. If the call runs `git commit` with a
multi-line message — a newline inside a -m/--message value, or more than one
-m/--message flag (git joins those into separate paragraphs) — it blocks the
call (exit 2) and tells Claude to use a single-line message instead. Per repo
convention, detailed rationale belongs in docs/*-dev-log.md, not the commit body.

Fails open: anything it can't confidently parse as a multi-line commit is
allowed through, so it never breaks legitimate multi-statement commands.
"""

import json
import shlex
import sys


def is_git_commit(tokens: list[str]) -> bool:
    """True if any `git ... commit` invocation appears in the token stream.

    Scans EVERY `git` occurrence, not just the first — so a compound command like
    `git add X && git commit -m …` is still recognized as a commit (the leading
    `git add` no longer short-circuits the check).
    """
    for i, tok in enumerate(tokens):
        if tok != "git":
            continue
        for nxt in tokens[i + 1:]:
            if nxt.startswith("-"):
                continue  # tolerate global flags before the subcommand
            if nxt == "commit":
                return True
            break  # this git's subcommand isn't commit; move on to the next git
    return False


def commit_messages(tokens: list[str]) -> list[str]:
    """Collect every -m / --message value in the token stream."""
    msgs: list[str] = []
    i = 0
    while i < len(tokens):
        tok = tokens[i]
        if tok in ("-m", "--message"):
            if i + 1 < len(tokens):
                msgs.append(tokens[i + 1])
                i += 2
                continue
        elif tok.startswith("-m") and len(tok) > 2:
            msgs.append(tok[2:])
        elif tok.startswith("--message="):
            msgs.append(tok.split("=", 1)[1])
        i += 1
    return msgs


def block(reason: str) -> int:
    print(
        f"Blocked: use a single-line git commit message ({reason}). "
        "Put detailed rationale in docs/*-dev-log.md, not the commit body.",
        file=sys.stderr,
    )
    return 2


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        return 0  # unparseable input -> fail open

    cmd = (payload.get("tool_input") or {}).get("command") or ""
    if "commit" not in cmd:
        return 0

    try:
        tokens = shlex.split(cmd, posix=True)
    except ValueError:
        # Unbalanced quotes / heredoc: a multi-line message body is the likely
        # cause, but only block if it actually spans lines around a git commit.
        if "git" in cmd and "commit" in cmd and "\n" in cmd:
            return block("multi-line message body")
        return 0

    if not is_git_commit(tokens):
        return 0

    msgs = commit_messages(tokens)
    if len(msgs) > 1:
        return block("multiple -m flags create a multi-paragraph message")
    if any("\n" in m for m in msgs):
        return block("the -m value contains a newline")
    return 0


if __name__ == "__main__":
    sys.exit(main())

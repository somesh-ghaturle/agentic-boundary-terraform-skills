#!/usr/bin/env python3
"""PreToolUse guard: the agent may plan infrastructure, never change it.

This is the first of three locks. Claude Code runs it before every Bash command the agent
issues and blocks (exit 2) anything that would change real infrastructure:

  - terraform or tofu with any subcommand outside a read-only allowlist (apply, destroy,
    import, state, taint, workspace, test, ... are all blocked)
  - -auto-approve anywhere
  - boundary.sh apply, the human-only step

It reads shell text, so a determined agent can hide a command from it (base64, variables). That
is why it is not the only lock: boundary.sh apply also refuses to run without a real terminal,
and the agent should hold read-only cloud credentials, which no text trick gets around.
"""
import json
import os
import shlex
import sys

TERRAFORM = {"terraform", "tofu"}
READ_ONLY = {"init", "validate", "plan", "fmt", "show", "version", "providers", "output", "graph", "get"}
OPERATORS = {"&&", "||", ";", "|", "&", "(", ")", "|&", ";;"}


def words(command):
    lexer = shlex.shlex(command, posix=True, punctuation_chars=True)
    lexer.whitespace_split = True
    return list(lexer)


def problem(command, depth=0):
    """Why this command must not run, or None."""
    try:
        tokens = words(command)
    except ValueError:
        # Unparseable shell: refuse only if it could be hiding what we guard.
        if any(k in command for k in ("terraform", "tofu", "boundary.sh")):
            return "could not parse a command that mentions terraform or boundary.sh"
        return None
    for i, tok in enumerate(tokens):
        if tok == "-auto-approve" or tok.startswith("-auto-approve="):
            return "-auto-approve skips the human"
        base = os.path.basename(tok)
        if base in TERRAFORM:
            sub = None
            for nxt in tokens[i + 1:]:
                if nxt in OPERATORS:
                    break
                if not nxt.startswith("-"):
                    sub = nxt
                    break
            if sub is not None and sub not in READ_ONLY:
                return f"`{base} {sub}` changes infrastructure; only a human may run it"
        if base == "boundary.sh" and i + 1 < len(tokens) and tokens[i + 1] == "apply":
            return "boundary.sh apply is the human-only step"
        # Commands nested in strings: sh -c "terraform apply", eval "...".
        if depth < 3 and any(c.isspace() for c in tok):
            nested = problem(tok, depth + 1)
            if nested:
                return nested
    return None


def main():
    event = json.load(sys.stdin)
    if event.get("tool_name") != "Bash":
        return 0
    why = problem(event.get("tool_input", {}).get("command", ""))
    if why:
        print(f"Blocked by agentic-boundary: {why}. Run `terraform plan`, then ask the human "
              "to run `boundary.sh apply <project-dir> <env>` in their own terminal.", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())

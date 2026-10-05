#!/usr/bin/env python3
"""Shell-command guard: the agent may plan infrastructure, never change it.

This is the first of three locks, and one file serves four agents. Each runs it before a shell
command the agent issues, and each blocks on exit code 2:

  Claude Code  PreToolUse hook            {"tool_name": "Bash", "tool_input": {"command": ...}}
  Codex        PreToolUse hook            the same shape; command may be a string or an argv list
  Cursor       beforeShellExecution hook  {"command": ...}
  Windsurf     pre_run_command hook       {"agent_action_name": "pre_run_command",
                                           "tool_info": {"command_line": ...}}

It blocks anything that would change real infrastructure:

  - terraform, tofu, or a wrapper that runs them (terragrunt, cdktf), with any subcommand
    outside a read-only allowlist (apply, destroy, deploy, import, state, taint, workspace,
    test, ... are all blocked)
  - Terraform named inside other code, such as perl -e 'system("terraform","apply")', where the
    guard cannot see what will run
  - -auto-approve anywhere
  - boundary.sh apply, the human-only step

It reads shell text, and the shell does more than any parser here: expansion, globbing, aliases,
scripts. So when a command mentions Terraform at all, the guard insists it be written out
literally: no $, backticks, braces, globs, ANSI-C quoting, xargs, alias or eval anywhere in it,
or it is denied. Names are compared case-insensitively, because macOS runs TERRAFORM as
terraform. A script or variable that never names Terraform is still invisible, which is why it
is not the only lock: boundary.sh apply also refuses to run without a real terminal,
and the agent should hold read-only cloud credentials, which no text trick gets around.
"""
import json
import os
import re
import shlex
import sys

READ_ONLY = {"init", "validate", "plan", "fmt", "show", "version", "providers", "output", "graph", "get"}
# Each tool that can change infrastructure, and the subcommands that cannot.
TOOLS = {
    "terraform": READ_ONLY,
    "tofu": READ_ONLY,
    "terragrunt": READ_ONLY | {"hclfmt", "render-json", "validate-inputs", "graph-dependencies"},
    "cdktf": {"synth", "diff", "get", "list", "output", "init", "convert", "provider", "help"},
}
# terragrunt run-all <cmd>, terragrunt run [--all] [--] <cmd>: the real subcommand comes next.
PASS_THROUGH = {"run-all", "run"}
OPERATORS = {"&&", "||", ";", "|", "&", "(", ")", "|&", ";;"}
# Terraform as a word, after the shell removes quotes and backslashes. Not followed by "-" or a
# word character, so directory names such as terraform-aws are not a mention.
MENTION = re.compile(r'(?<![\w-])(terraform|tofu|terragrunt|cdktf)(?![\w-])', re.I)
# A token that can only be a path or a flag value, never code that runs something.
PLAIN = re.compile(r'^[\w./=:@+-]+$')
EXPANSION = set("$`{}*?[]")
INDIRECT = {"xargs", "parallel", "alias", "eval", "source", ".", "function"}


def tool(token):
    """The tool a token names, by basename, case-insensitively, with any .exe dropped."""
    base = os.path.basename(token).lower()
    if base.endswith(".exe"):
        base = base[:-4]
    return base if base in TOOLS else None


def words(command):
    lexer = shlex.shlex(command, posix=True, punctuation_chars=True)
    lexer.whitespace_split = True
    # shlex treats # anywhere as a comment; bash only at the start of a word, so in
    # `echo a#b; terraform apply` bash runs the apply. With comments off the guard reads
    # everything, including real comments, which can only make it stricter.
    lexer.commenters = ""
    return list(lexer)


def problem(command, depth=0):
    """Why this command must not run, or None."""
    # Bash joins a line ending in a backslash to the next one, so ter\<newline>raform is
    # terraform. Join them the same way before reading anything.
    command = command.replace("\\\r\n", "").replace("\\\n", "")
    if "$'" in command:
        return "ANSI-C quoting ($'...') can spell any command; write it out literally"
    literal = re.sub(r"[\\'\"]", "", command)
    if MENTION.search(literal) and EXPANSION & set(command):
        return "a command that mentions Terraform must not use shell expansion ($ ` { } * ? [ ])"
    try:
        tokens = words(command)
    except ValueError:
        # Unparseable shell: refuse only if it could be hiding what we guard.
        if any(k in command.lower() for k in ("terraform", "tofu", "boundary.sh")):
            return "could not parse a command that mentions terraform or boundary.sh"
        return None
    if MENTION.search(literal) and any(t.lower() in INDIRECT for t in tokens):
        return "a command that mentions Terraform must not pass arguments through xargs, alias or eval"
    for tok in tokens:
        # Terraform named somewhere other than as a command, a plain path, or a quoted command
        # the guard parses below, e.g. inside perl -e 'system("terraform","apply")'.
        if (MENTION.search(re.sub(r"[\\'\"]", "", tok)) and tool(tok) is None
                and not PLAIN.match(tok) and not any(c.isspace() for c in tok)):
            return f"`{tok}` names Terraform inside other code; run the command directly so it can be checked"
    for i, tok in enumerate(tokens):
        if tok.lower() == "-auto-approve" or tok.lower().startswith("-auto-approve="):
            return "-auto-approve skips the human"
        name = tool(tok)
        if name:
            sub = None
            for nxt in tokens[i + 1:]:
                if nxt in OPERATORS:
                    break
                if nxt.startswith("-"):
                    continue
                if sub is None and name == "terragrunt" and nxt.lower() in PASS_THROUGH:
                    continue
                sub = nxt
                break
            if sub is not None and sub.lower() not in TOOLS[name]:
                return f"`{name} {sub}` changes infrastructure; only a human may run it"
        if os.path.basename(tok).lower() == "boundary.sh" and i + 1 < len(tokens) and tokens[i + 1] == "apply":
            return "boundary.sh apply is the human-only step"
        # Commands nested in strings: sh -c "terraform apply", eval "...".
        if depth < 3 and any(c.isspace() for c in tok):
            nested = problem(tok, depth + 1)
            if nested:
                return nested
    return None


def extract(event):
    """(agent, command) for the four payload shapes, or (None, None) when it is not a shell call."""
    if event.get("agent_action_name") == "pre_run_command":              # Windsurf
        return "windsurf", str((event.get("tool_info") or {}).get("command_line", ""))
    if "tool_name" in event:                                             # Claude Code, Codex
        if event.get("tool_name") != "Bash":
            return None, None
        command = (event.get("tool_input") or {}).get("command", "")
        if isinstance(command, list):
            command = shlex.join(str(part) for part in command)
        return "claude-or-codex", str(command)
    if "command" in event:                                               # Cursor
        return "cursor", str(event["command"])
    return None, None


def main():
    agent, command = extract(json.load(sys.stdin))
    if agent is None:
        return 0
    why = problem(command)
    if why:
        message = (f"Blocked by agentic-boundary: {why}. Run `terraform plan`, then ask the human "
                   "to run `boundary.sh apply <project-dir> <env>` in their own terminal.")
        print(message, file=sys.stderr)
        if agent == "cursor":
            print(json.dumps({"permission": "deny", "user_message": message, "agent_message": message}))
        return 2
    if agent == "cursor":
        # Cursor needs a decision on exit 0. Its hook only fires on Terraform-related commands,
        # and "allow" would skip the human's own approval, so the answer is "ask": the human
        # confirms every Terraform command the agent runs, even read-only ones.
        print(json.dumps({"permission": "ask",
                          "user_message": f"agentic-boundary: review this Terraform command before it runs: {command}"}))
    return 0


if __name__ == "__main__":
    sys.exit(main())

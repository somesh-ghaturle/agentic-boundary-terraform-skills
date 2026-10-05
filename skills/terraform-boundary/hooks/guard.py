#!/usr/bin/env python3
"""Shell-command guard: the agent may plan infrastructure, never change it.

This is the first of three locks, and one file serves four agents. Each runs it before a shell
command the agent issues, and each blocks on exit code 2:

  Claude Code  PreToolUse hook            {"tool_name": "Bash", "tool_input": {"command": ...}}
  Codex        PreToolUse hook            the same shape; command may be a string or an argv list
  Cursor       beforeShellExecution hook  {"command": ...}
  Windsurf     pre_run_command hook       {"agent_action_name": "pre_run_command",
                                           "tool_info": {"command_line": ...}}

Other tools can run commands too: MCP servers, Claude Code's Monitor, a PowerShell tool. So in
Claude Code and Codex every tool call is checked, except tools that only carry file content or
prose (Read, Write, Edit, ...); Cursor and Windsurf hook their MCP events. Every string argument
is read as a command, so a message that merely quotes `terraform apply` is denied too.

It fails closed: an error, or a payload it does not recognise, blocks the call.

It blocks anything that would change real infrastructure:

  - terraform, tofu, or a wrapper that runs them (terragrunt, cdktf, terraspace), under any
    name, versioned binaries such as terraform_1.15.8 included, with any subcommand
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
    "terraspace": {"plan", "validate", "fmt", "show", "list", "info", "build", "init", "new", "setup", "check"},
}
# terragrunt run-all <cmd>, terragrunt run [--all] [--] <cmd>, terraspace all <cmd>: the real
# subcommand comes next.
PASS_THROUGH = {"terragrunt": {"run-all", "run"}, "terraspace": {"all"}}
NAMES = "terraform|tofu|terragrunt|cdktf|terraspace"
# A tool's name plus whatever a version manager, a download or a wrapper setup put after it:
# terraform_1.15.8, terraform-1.15, terraform.exe, terraform.real, terraform_latest. A suffix
# starting with "." or "_" counts, and "-" counts only before a digit, so terraform-docs,
# terraform-aws and terraformer stay other things.
SUFFIX = r'(?:[._][\w.-]*|-\d[\w.-]*)?'
TOOL_NAME = re.compile(rf'^({NAMES}){SUFFIX}$', re.I)
# Terraform's own files, as arguments, are not the binary: terraform.tfvars, terraform.tfstate.backup,
# terraform.lock.hcl. Only Terraform-specific extensions, and never in command position: a
# binary renamed terraform.tf is still the binary when bash runs it.
TF_FILE = re.compile(r'\.(tf|tfvars|tfstate|tfplan|hcl)(\.|$)', re.I)
# Words that run the command after them, so a Terraform name after one is in command position.
WRAPPERS = {"sudo", "doas", "env", "exec", "command", "builtin", "time", "nohup", "nice", "ionice",
            "timeout", "stdbuf", "caffeinate", "strace", "chronic", "watch", "ssh"}
OPERATORS = {"&&", "||", ";", "|", "&", "(", ")", "|&", ";;"}
# Terraform as a word, after the shell removes quotes and backslashes. Not followed by "-" or a
# word character, so directory names such as terraform-aws are not a mention.
MENTION = re.compile(rf'(?<![\w-])({NAMES}){SUFFIX}(?![\w-])', re.I)
# A token that can only be a path or a flag value, never code that runs something.
PLAIN = re.compile(r'^[\w./=:@+-]+$')
EXPANSION = set("$`{}*?[]")
# Commands that pass arguments on indirectly, or drive a terminal another program reads, which
# is how an agent could answer boundary.sh apply's fingerprint prompt itself.
INDIRECT = {"xargs", "parallel", "alias", "eval", "source", ".", "function",
            "script", "expect", "unbuffer", "tmux", "screen", "socat"}
# Tools whose string arguments are file content or prose, never something that runs.
CONTENT_TOOLS = {"Read", "Write", "Edit", "MultiEdit", "NotebookEdit", "NotebookRead", "Glob", "Grep",
                 "LS", "WebFetch", "WebSearch", "TodoWrite", "Task", "Agent", "apply_patch"}


def mentioned(text):
    """Does text name Terraform, a wrapper, or boundary.sh, once quotes and backslashes are gone?"""
    literal = re.sub(r"[\\'\"]", "", text)
    return bool(MENTION.search(literal)) or "boundary.sh" in literal.lower()


def tool(token, command_position=True):
    """The tool a token names, by basename, case-insensitively, ignoring version or wrapper suffixes.

    As an argument, a Terraform file name (terraform.tfvars) is not the tool. In command position
    it is, whatever it is called.
    """
    base = os.path.basename(token)
    m = TOOL_NAME.match(base)
    if not m or (not command_position and TF_FILE.search(base[len(m.group(1)):])):
        return None
    return m.group(1).lower()


def command_positions(tokens):
    """Indexes bash may run as a command: the first word of each simple command, past any
    VAR=value assignments, and every word after a wrapper such as sudo, env or time."""
    positions, start, wrapped = set(), True, False
    for i, tok in enumerate(tokens):
        if tok in OPERATORS:
            start, wrapped = True, False
            continue
        if start and re.match(r'^[A-Za-z_]\w*=', tok):
            continue
        if start or wrapped:
            positions.add(i)
            if os.path.basename(tok).lower() in WRAPPERS:
                wrapped = True
        start = False
    return positions


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
    if mentioned(command) and EXPANSION & set(command):
        return "a command that mentions Terraform or boundary.sh must not use shell expansion ($ ` { } * ? [ ])"
    try:
        tokens = words(command)
    except ValueError:
        # Unparseable shell: refuse only if it could be hiding what we guard.
        if any(k in command.lower() for k in ("terraform", "tofu", "boundary.sh")):
            return "could not parse a command that mentions terraform or boundary.sh"
        return None
    if mentioned(command) and any(os.path.basename(t).lower() in INDIRECT for t in tokens):
        return ("a command that mentions Terraform or boundary.sh must not pass arguments through "
                "xargs, alias or eval, or drive a terminal with script, expect, tmux or similar")
    commands = command_positions(tokens)
    for tok in tokens:
        # Terraform or boundary.sh named somewhere other than as a command, a plain path, or a
        # quoted command the guard parses below, e.g. inside perl -e 'system("terraform","apply")'.
        if (mentioned(tok) and tool(tok) is None
                and not PLAIN.match(tok) and not any(c.isspace() for c in tok)):
            return f"`{tok}` names Terraform inside other code; run the command directly so it can be checked"
    for i, tok in enumerate(tokens):
        if tok.lower() == "-auto-approve" or tok.lower().startswith("-auto-approve="):
            return "-auto-approve skips the human"
        name = tool(tok, command_position=i in commands)
        if name:
            sub = None
            for nxt in tokens[i + 1:]:
                if nxt in OPERATORS:
                    break
                if nxt.startswith("-"):
                    continue
                if sub is None and nxt.lower() in PASS_THROUGH.get(name, ()):
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


def strings(value):
    """Every string inside an MCP tool's arguments, however deeply nested."""
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for v in value.values():
            yield from strings(v)
    elif isinstance(value, list):
        for v in value:
            yield from strings(v)


def extract(event):
    """(agent, kind, commands) for each payload shape; agent is None when there is nothing to check."""
    action = event.get("agent_action_name")
    info = event.get("tool_info") or {}
    if action == "pre_run_command":                                      # Windsurf shell
        return "windsurf", "shell", [str(info.get("command_line", ""))]
    if action == "pre_mcp_tool_use":                                     # Windsurf MCP
        return "windsurf", "mcp", list(strings(info.get("mcp_tool_arguments")))
    if "mcp_server_name" in event:                                       # Cursor MCP
        raw = event.get("tool_input", "")
        try:
            args = json.loads(raw) if isinstance(raw, str) else raw
        except ValueError:
            args = raw
        return "cursor", "mcp", list(strings(args))
    if "tool_name" in event:                                             # Claude Code, Codex
        name = str(event.get("tool_name"))
        if name in CONTENT_TOOLS:
            return None, None, []
        if name != "Bash":
            # MCP tools, Monitor, PowerShell, and any tool not known to be harmless.
            return "claude-or-codex", "mcp", list(strings(event.get("tool_input")))
        command = (event.get("tool_input") or {}).get("command", "")
        if isinstance(command, list):
            command = shlex.join(str(part) for part in command)
        return "claude-or-codex", "shell", [str(command)]
    if "command" in event:                                               # Cursor shell
        return "cursor", "shell", [str(event["command"])]
    raise ValueError("unrecognised hook payload")


def main():
    raw = sys.stdin.read()
    try:
        event = json.loads(raw)
        agent, kind, commands = extract(event)
    except Exception as err:  # fail closed: an input the guard cannot read is not an approval
        message = f"Blocked by agentic-boundary: could not read the hook input ({err}); refusing to guess."
        print(message, file=sys.stderr)
        if '"command"' in raw or "mcp_server_name" in raw:
            print(json.dumps({"permission": "deny", "user_message": message, "agent_message": message}))
        return 2
    if agent is None:
        return 0
    why = next(filter(None, (problem(c) for c in commands)), None)
    if why:
        message = (f"Blocked by agentic-boundary: {why}. Run `terraform plan`, then ask the human "
                   "to run `boundary.sh apply <project-dir> <env>` in their own terminal.")
        print(message, file=sys.stderr)
        if agent == "cursor":
            print(json.dumps({"permission": "deny", "user_message": message, "agent_message": message}))
        return 2
    if agent == "cursor":
        if kind == "mcp" and not any(mentioned(c) for c in commands):
            # Cursor needs a decision on exit 0 and its MCP hook has no matcher. "allow" would
            # skip the human's own MCP approval, so the guard steps aside instead: any exit code
            # other than 0 or 2 means "hook failed, action proceeds" through Cursor's normal flow.
            return 1
        # The shell hook only fires on Terraform-related commands. "allow" would skip the
        # human's own approval, so the answer is "ask": the human confirms each one.
        print(json.dumps({"permission": "ask",
                          "user_message": f"agentic-boundary: review this Terraform-related call before it runs: {commands[0][:200]}"}))
    return 0


if __name__ == "__main__":
    sys.exit(main())

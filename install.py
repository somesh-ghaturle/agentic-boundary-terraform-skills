#!/usr/bin/env python3
"""Install the terraform-boundary skill and its guard for Codex, Cursor or Windsurf.

    python3 install.py <codex|cursor|windsurf>

Claude Code users install the plugin instead (see README). For the other three agents this:

  1. copies skills/terraform-boundary to ~/.agents/skills/terraform-boundary, which Codex,
     Cursor and Windsurf all load skills from;
  2. adds the guard to that agent's user-level hook config, for shell commands and MCP tool
     calls, keeping any hooks already there.

User level, on purpose. A hook config inside a project is a file the agent edits like any
other; one in your home directory is outside the project it works on. Running this twice
changes nothing the second time. It never touches cloud credentials: giving the agent a
read-only identity, the third lock, is yours to do.
"""
import json
import os
import pathlib
import shutil
import sys

HERE = pathlib.Path(__file__).resolve().parent
SKILL = HERE / "skills" / "terraform-boundary"


def cursor_matcher():
    """A regex that matches every command the guard could react to.

    Cursor applies it to the raw command before the guard runs, so it must not be narrower than
    the guard: the shell turns "terra""form", t\\erraform and a backslash-continued line into
    terraform, and macOS runs
    TERRAFORM. So any letter case, with quotes or backslashes allowed between letters, plus
    ANSI-C quoting, which can spell anything.
    """
    gap = r"""[\\'"\r\n]*"""
    def spelled(word):
        return gap.join(f"[{c.lower()}{c.upper()}]" if c.isalpha() else "\\" + c if c == "." else c
                        for c in word)
    words = ["terraform", "tofu", "terragrunt", "cdktf", "terraspace", "boundary.sh", "auto-approve"]
    return "|".join([spelled(w) for w in words] + [r"\$'"])


def hook_target(agent, home, guard):
    """(config path, [(event, hook entry), ...], wrapper) for one agent: shell and MCP."""
    command = f'python3 "{guard}"'
    if agent == "codex":
        codex_home = pathlib.Path(os.environ.get("CODEX_HOME") or home / ".codex")
        # No matcher: every tool call reaches the guard, which skips content-only tools itself.
        return codex_home / "hooks.json", [
            ("PreToolUse", {"hooks": [{"type": "command", "command": command}]}),
        ], {}
    if agent == "cursor":
        return home / ".cursor" / "hooks.json", [
            # Fires on every spelling the guard reacts to, and blocks if the guard crashes or hangs.
            ("beforeShellExecution", {"command": command, "matcher": cursor_matcher(), "failClosed": True}),
            # No matcher exists for MCP. Not failClosed, because the guard steps aside on
            # unrelated MCP calls by exiting 1 ("hook failed, action proceeds").
            ("beforeMCPExecution", {"command": command}),
        ], {"version": 1}
    if agent == "windsurf":
        return home / ".codeium" / "windsurf" / "hooks.json", [
            ("pre_run_command", {"command": command, "show_output": True}),
            ("pre_mcp_tool_use", {"command": command, "show_output": True}),
        ], {}
    sys.exit("usage: python3 install.py <codex|cursor|windsurf>")


def mentions_guard(entry, guard):
    return str(guard) in json.dumps(entry)


def install(agent, home):
    home = pathlib.Path(home)
    dest = home / ".agents" / "skills" / "terraform-boundary"
    guard = dest / "hooks" / "guard.py"
    config, entries, wrapper = hook_target(agent, home, guard)

    if dest.exists():
        shutil.rmtree(dest)
    shutil.copytree(SKILL, dest, ignore=shutil.ignore_patterns("__pycache__"))
    print(f"skill  -> {dest}")

    data = json.loads(config.read_text()) if config.exists() else dict(wrapper)
    added = []
    for event, entry in entries:
        hooks = data.setdefault("hooks", {}).setdefault(event, [])
        if any(mentions_guard(e, guard) and e.get("matcher") == entry.get("matcher") for e in hooks):
            continue
        hooks.append(entry)
        added.append(event + (f" {entry['matcher']}" if "matcher" in entry and len(entry["matcher"]) < 20 else ""))
    if not added:
        print(f"guard  already in {config}")
        return
    if config.exists():
        shutil.copy2(config, config.with_name(config.name + ".bak"))
    config.parent.mkdir(parents=True, exist_ok=True)
    config.write_text(json.dumps(data, indent=2) + "\n")
    print(f"guard  -> {config} ({', '.join(added)})")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    install(sys.argv[1], os.environ.get("BOUNDARY_INSTALL_HOME") or pathlib.Path.home())
    print("Next: give this agent a read-only cloud identity, and keep deploy credentials for your own terminal.")

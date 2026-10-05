#!/usr/bin/env python3
"""Refuse Terraform that the pinned, regex-based tests would read differently from Terraform.

    canonical.py <dir>

Run after `terraform fmt`, which already rewrites unquoted labels (`resource aws_iam_role x {}`)
and missing spaces into the quoted, spaced form the tests recognise. One shape survives fmt:
block comments (/* ... */) outside strings. Terraform ignores their content; a test searching
the text does not, so they can plant text a test looks for. They are refused.

Strings matter: IAM resource ARNs contain "/*" inside quotes, so this tracks string, template
and heredoc state instead of matching raw text.
"""
import pathlib
import re
import sys

HEREDOC = re.compile(r'<<-?([A-Za-z_][A-Za-z0-9_-]*)[ \t]*\n')


def block_comments(text):
    """Line numbers of /* comments that sit in code, not inside a string or heredoc."""
    found, stack, i, n = [], ["code"], 0, len(text)
    while i < n:
        ctx, c = stack[-1], text[i]
        if ctx == "str":
            if c == "\\":
                i += 2
                continue
            if text.startswith(("$${", "%%{"), i):
                i += 3
                continue
            if text.startswith(("${", "%{"), i):
                stack.append("tmpl")
                i += 2
                continue
            if c == '"':
                stack.pop()
            i += 1
            continue
        # code, a template interpolation, or a brace nested inside one
        if text.startswith("/*", i):
            found.append(text.count("\n", 0, i) + 1)
            end = text.find("*/", i + 2)
            i = n if end < 0 else end + 2
            continue
        if c == "#" or text.startswith("//", i):
            end = text.find("\n", i)
            i = n if end < 0 else end
            continue
        if c == '"':
            stack.append("str")
        elif text.startswith("<<", i) and HEREDOC.match(text, i):
            m = HEREDOC.match(text, i)
            term = re.compile(r'^[ \t]*' + re.escape(m.group(1)) + r'[ \t]*$', re.M)
            t = term.search(text, m.end())
            i = n if t is None else t.end()
            continue
        elif ctx in ("tmpl", "brace") and c == "{":
            stack.append("brace")
        elif ctx in ("tmpl", "brace") and c == "}":
            stack.pop()
        i += 1
    return found


def problems(root):
    for path in sorted(root.rglob("*.tf")):
        text = path.read_text(encoding="utf-8", errors="replace")
        rel = path.relative_to(root)
        for line in block_comments(text):
            yield f"{rel}:{line}: block comment; use # comments"


if __name__ == "__main__":
    bad = list(problems(pathlib.Path(sys.argv[1])))
    if bad:
        print("\n".join(bad))
    sys.exit(1 if bad else 0)

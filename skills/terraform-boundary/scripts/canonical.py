#!/usr/bin/env python3
"""Refuse block comments, the one Terraform shape terraform fmt does not canonicalise.

    canonical.py <dir>

Run after `terraform fmt`, which already rewrites unquoted labels and missing spaces into the
form the pinned regex-based tests recognise, and fails on invalid syntax. Block comments
(/* ... */) survive fmt: Terraform ignores their content, a test searching the text does not, so
one could plant text a test looks for.

No parsing, on purpose. A block comment cannot exist without a closing `*/`, and an unterminated
one is a syntax error fmt has already rejected. So any .tf file containing `*/` is refused,
wherever it appears. That is exact where a hand-written HCL lexer would only approximate, and
the pinned trees never contain `*/`, so nothing legitimate is lost.
"""
import pathlib
import sys

if __name__ == "__main__":
    root = pathlib.Path(sys.argv[1])
    bad = [f"{p.relative_to(root)}: contains */, so it can hold a block comment; use # comments"
           for p in sorted(root.rglob("*.tf"))
           if "*/" in p.read_text(encoding="utf-8", errors="replace")]
    if bad:
        print("\n".join(bad))
    sys.exit(1 if bad else 0)

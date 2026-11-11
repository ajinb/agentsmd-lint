#!/usr/bin/env python3
"""Lint an AGENTS.md or CLAUDE.md against the repository it describes.

Stdlib only. Precision matters more than recall here: a linter that cries wolf gets deleted, so
every check stays silent when it cannot be sure.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections.abc import Callable
from fnmatch import fnmatch
from pathlib import Path

MAX_LINES = 200  # Claude Code's documented target for one instruction file
MAX_MANIFESTS = 30  # past this it is a monorepo we cannot judge cheaply, so stay silent
EXTENSIONS = (
    ".py .js .ts .tsx .jsx .go .rs .java .kt .rb .php .c .h .cc .cpp .cs .swift .sh .md .mdx .json"
    " .yaml .yml .toml .sql .proto .html .css .scss .lock .ini .cfg .gradle .tf"
).split()
SPAN = re.compile(r"`([^`\n]+)`")
TREE = re.compile(r"[├└]──")
OVERVIEW = re.compile(
    r"^#{1,6}\s.*\b(project|repo(sitory)?|directory|folder|file|code ?base)\s+"
    r"(structure|layout|overview|organi[sz]ation|map)\b|^#{1,6}\s+architecture\b",
    re.I | re.M,
)
VAGUE = re.compile(
    r"\b(write clean code|best practices|clean,? (readable|maintainable) code|be careful"
    r"|ensure (code )?quality|high[- ]quality code|when appropriate|as needed)\b",
    re.I,
)
NPM = re.compile(r"\b(?:npm|pnpm|yarn|bun) run\s+([A-Za-z0-9][A-Za-z0-9:_-]*)(?=[\s`]|$)", re.M)
MAKE = re.compile(r"(?:^|[;&|]\s*|\$\s*)make\s+([a-z][A-Za-z0-9_-]+)(?=\s|$)", re.M)
MAKE_RULE = re.compile(r"^([A-Za-z0-9_.-]+(?:[ \t]+[A-Za-z0-9_.-]+)*)[ \t]*:(?!=)", re.M)
CHECK_WORDS = re.compile(r"\b(test|tests|pytest|lint|ruff|eslint|typecheck|tsc|build|check|vet)\b")
SKIP_CHARS = re.compile(r"[<>{}$*()\[\]|=,;'\"\\ ]")
GENERATED = {
    "vendor",
    "dist",
    "build",
    "out",
    "target",
    "node_modules",
    ".next",
    "coverage",
    "tmp",
    ".cache",
}
PLACEHOLDER = re.compile(
    r"your|(?<![a-z])(foo|bar|baz|example|sample|placeholder|xxx+)(?![a-z])|yyyy|path/to|my[-_]|/[A-Z]$",
    re.I,
)
# A line saying a path is gone, optional, generated or elsewhere makes no claim it exists here.
HEDGE = re.compile(
    r"\b(do not|don't|never|removed|deleted|gone|deprecated|legacy|exists?|gitignored|ignored"
    r"|generated|regenerated|installed|upstream|private|recreate|forbidden|no longer|renamed)\b",
    re.I,
)
NOT_WORDS = (
    "http://",
    "https://",
    "git@",
    "@",
    "/",
    "~",
    "-",
    "#",  # urls, scoped packages, flags
)


def candidate_paths(text: str, top_level: set[str]) -> set[str]:
    """Backticked tokens that can only be paths: a slash and a real top-level directory."""
    found = set()
    # The hedge is read from the prose only: `src/legacy/a.py` is a path, not a hedge.
    spans = (
        t
        for line in text.splitlines()
        if not HEDGE.search(SPAN.sub("", line))
        for t in SPAN.findall(line)
    )
    for token in spans:
        token = re.split(r"#|::", token.strip())[0]
        token = re.sub(r":\d+(:\d+)?$", "", token).removeprefix("./").rstrip("/")
        if (
            not token
            or token.startswith(NOT_WORDS)
            or SKIP_CHARS.search(token)
            or ".." in token
            or PLACEHOLDER.search(token)
        ):
            continue
        parts = token.split("/")
        if len(parts) >= 2 and parts[0] in top_level and not GENERATED & set(parts):
            found.add(token)
    return found


def gitignore_matcher(read: Callable[[str], str | None]) -> Callable[[str], bool]:
    # shortcut: root .gitignore only and negations are ignored, enough to silence build output
    patterns = [
        line.strip().strip("/")
        for line in (read(".gitignore") or "").splitlines()
        if line.strip() and not line.startswith(("#", "!"))
    ]

    def ignored(path: str) -> bool:
        parts = path.split("/")
        prefixes = ["/".join(parts[:i]) for i in range(1, len(parts) + 1)]
        return any(
            fnmatch(prefix, pattern) or fnmatch(prefix.split("/")[-1], pattern)
            for pattern in patterns
            for prefix in prefixes
        )

    return ignored


def exists(token: str, paths: set[str], dirs: set[str]) -> bool:
    # Lenient on purpose: a path mentioned relative to any subdirectory counts as present.
    if token in paths or token in dirs:
        return True
    suffix = "/" + token
    if any(p.endswith(suffix) for p in paths) or any(d.endswith(suffix) for d in dirs):
        return True
    # Docs often link to `docs/guide` meaning docs/guide.md.
    return any(p.startswith(token + ".") for p in paths)


def shingles(text: str, size: int = 8) -> set[tuple[str, ...]]:
    words = re.findall(r"[a-z0-9]+", text.lower())
    return {tuple(words[i : i + size]) for i in range(len(words) - size + 1)}


def strip_fences(text: str) -> str:
    return re.sub(r"```.*?```", "", text, flags=re.S)


def lint(
    text: str,
    paths: set[str],
    read: Callable[[str], str | None],
    readme: str | None = None,
) -> dict:
    dirs = {"/".join(p.split("/")[:i]) for p in paths for i in range(1, p.count("/") + 1)}
    top_level = {p.split("/")[0] for p in paths}
    findings: list[dict] = []
    lines = text.count("\n") + 1

    def add(rule: str, severity: str, message: str) -> None:
        findings.append({"rule": rule, "severity": severity, "message": message})

    if lines > MAX_LINES:
        add("size", "warn", f"{lines} lines, target is under {MAX_LINES}")
    ignored = gitignore_matcher(read)
    for token in sorted(candidate_paths(text, top_level)):
        if not exists(token, paths, dirs) and not ignored(token):
            add("dead-path", "error", f"`{token}` is not in the repository")

    # Commands only count inside code. In prose, "make sure" is English.
    code = "\n".join(SPAN.findall(text) + re.findall(r"```.*?```", text, re.S))
    manifests = [p for p in paths if p.split("/")[-1] == "package.json"]
    if 0 < len(manifests) <= MAX_MANIFESTS:
        scripts: set[str] = set()
        readable = True
        for manifest in manifests:
            try:
                scripts |= set(json.loads(read(manifest) or "{}").get("scripts", {}))
            except (json.JSONDecodeError, AttributeError):
                readable = False
        for name in sorted({n.rstrip(":") for n in NPM.findall(code)} if readable else ()):
            if name and name not in scripts:
                add("unknown-script", "error", f"script `{name}` is not in any package.json")

    makefiles = [p for p in paths if p.split("/")[-1] in ("Makefile", "makefile", "GNUmakefile")]
    if 0 < len(makefiles) <= MAX_MANIFESTS:
        bodies = [read(p) or "" for p in makefiles]
        if not any(re.search(r"^-?include\s|%:", b, re.M) for b in bodies):
            targets = {t for b in bodies for rule in MAKE_RULE.findall(b) for t in rule.split()}
            for name in sorted(set(MAKE.findall(code)) - targets):
                add("unknown-make-target", "error", f"make target `{name}` is not defined")

    if TREE.search(text) or OVERVIEW.search(text):
        add("repo-overview", "info", "repository overview or directory tree")
    vague = sorted({m.group(0).lower() for m in VAGUE.finditer(strip_fences(text))})
    if vague:
        add("vague-instruction", "info", "unverifiable: " + ", ".join(vague))
    if readme:
        own = shingles(text)
        share = len(own & shingles(readme)) / len(own) if own else 0
        if share >= 0.2:
            add("readme-overlap", "info", f"{share:.0%} of the text repeats the README")
    if not any(
        CHECK_WORDS.search(s) for s in SPAN.findall(text) + re.findall(r"```.*?```", text, re.S)
    ):
        add("no-verify-command", "info", "no test, lint or build command")
    return {"lines": lines, "approx_tokens": len(text) // 4, "findings": findings}


def lint_directory(root: Path, file: Path) -> dict:
    ignored = {".git", "node_modules", ".venv", "__pycache__", "dist", "build"}
    paths = {
        p.relative_to(root).as_posix()
        for p in root.rglob("*")
        if p.is_file() and not ignored & set(p.relative_to(root).parts)
    }

    def read(relative: str) -> str | None:
        target = root / relative
        return target.read_text(errors="replace") if target.is_file() else None

    readme = next((read(n) for n in ("README.md", "readme.md", "README.rst") if read(n)), None)
    return lint(file.read_text(errors="replace"), paths, read, readme)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("repo", nargs="?", default=".")
    parser.add_argument("--file", help="instruction file, relative to the repo")
    parser.add_argument("--json", action="store_true")
    parser.add_argument(
        "--strict",
        action="store_true",
        help="exit 1 on any error-level finding; hand-audited precision was 45%%, so opt in",
    )
    args = parser.parse_args(argv)
    root = Path(args.repo).resolve()
    names = [args.file] if args.file else ["AGENTS.md", "CLAUDE.md"]
    file = next((root / n for n in names if (root / n).is_file()), None)
    if file is None:
        print("no AGENTS.md or CLAUDE.md found", file=sys.stderr)
        return 2
    report = lint_directory(root, file)
    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print(f"{file.name}: {report['lines']} lines, ~{report['approx_tokens']} tokens")
        for finding in report["findings"]:
            print(f"  {finding['severity']:<6}{finding['rule']:<22}{finding['message']}")
    return 1 if args.strict and any(f["severity"] == "error" for f in report["findings"]) else 0


if __name__ == "__main__":
    sys.exit(main())

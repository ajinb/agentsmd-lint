#!/usr/bin/env python3
"""Lint the root AGENTS.md of the most-starred public GitHub repositories. Needs the gh CLI.

Publishes aggregates plus the repo@sha list, so anyone can re-run it. Per-repo findings stay in
data/ because the point is the pattern, not embarrassing individual maintainers.
"""

from __future__ import annotations

import collections
import json
import statistics
import subprocess
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from agentsmd_lint import lint


def gh(path: str) -> dict | list | None:
    done = subprocess.run(["gh", "api", path], capture_output=True, text=True, check=False)
    return json.loads(done.stdout) if done.returncode == 0 else None


def top_repositories(pages: int = 10) -> list[str]:
    names: list[str] = []
    for page in range(1, pages + 1):
        found = gh(f"search/repositories?q=stars:>10000&sort=stars&per_page=100&page={page}")
        names += [r["full_name"] for r in (found or {}).get("items", []) if not r["fork"]]
    return names


def has_agents_file(name: str) -> str | None:
    found = gh(f"repos/{name}/contents/AGENTS.md")
    return name if isinstance(found, dict) and found.get("size", 0) > 0 else None


def git(cwd: str, *args: str) -> str:
    done = subprocess.run(["git", *args], cwd=cwd, capture_output=True, check=False)
    return done.stdout.decode("utf-8", "replace") if done.returncode == 0 else ""


def scan_one(name: str) -> dict | None:
    with tempfile.TemporaryDirectory() as tmp:
        cloned = subprocess.run(
            [
                "git",
                "clone",
                "-q",
                "--depth=1",
                "--filter=blob:none",
                "--no-checkout",
                f"https://github.com/{name}.git",
                tmp,
            ],
            capture_output=True,
            check=False,
            timeout=240,
        )
        if cloned.returncode != 0:
            return None
        sha = git(tmp, "rev-parse", "HEAD").strip()
        paths = set(git(tmp, "ls-tree", "-r", "--name-only", "HEAD").splitlines())
        text = git(tmp, "show", "HEAD:AGENTS.md")
        if not text.strip() or "\n" not in text.strip():  # a one-line pointer such as "@CLAUDE.md"
            return None
        read = lambda p: git(tmp, "show", f"HEAD:{p}") or None  # noqa: E731
        readme = next((read(n) for n in ("README.md", "readme.md") if n in paths), None)
        return {"repo": name, "sha": sha, **lint(text, paths, read, readme)}


def summarize(reports: list[dict], population: int) -> dict:
    total = len(reports)
    has = collections.Counter(rule for r in reports for rule in {f["rule"] for f in r["findings"]})
    any_error = sum(any(f["severity"] == "error" for f in r["findings"]) for r in reports)
    lines = [r["lines"] for r in reports]
    tokens = [r["approx_tokens"] for r in reports]
    return {
        "repos_checked": population,
        "repos_with_agents_md": total,
        "median_lines": statistics.median(lines),
        "p90_lines": statistics.quantiles(lines, n=10)[-1],
        "median_approx_tokens": statistics.median(tokens),
        "p90_approx_tokens": statistics.quantiles(tokens, n=10)[-1],
        "share_with_any_error": round(any_error / total, 3),
        "share_by_rule": {k: round(v / total, 3) for k, v in has.most_common()},
    }


def main() -> None:
    names = top_repositories()
    with ThreadPoolExecutor(8) as pool:
        hits = [n for n in pool.map(has_agents_file, names) if n]
    print(f"{len(hits)} of {len(names)} repositories have a root AGENTS.md", flush=True)
    with ThreadPoolExecutor(4) as pool:
        reports = [r for r in pool.map(scan_one, hits) if r]
    Path("data").mkdir(exist_ok=True)
    Path("data/findings.json").write_text(json.dumps(reports, indent=1))
    Path("results").mkdir(exist_ok=True)
    summary = summarize(reports, len(names))
    Path("results/summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    Path("results/corpus.txt").write_text("".join(f"{r['repo']}@{r['sha']}\n" for r in reports))
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()

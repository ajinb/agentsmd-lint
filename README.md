# agentsmd-lint

Lint an `AGENTS.md` or `CLAUDE.md` against the repository it describes. Standard library only.

Companion to [340 of the Top 1,000 GitHub Repos Ship an AGENTS.md](https://cloudandsre.com/blog/agents-md-what-belongs-321-files/).

## Use it

```bash
python agentsmd_lint.py path/to/repo
python agentsmd_lint.py path/to/repo --json
python agentsmd_lint.py path/to/repo --strict   # exit 1 on error-level findings
```

| Rule | Severity | What it means |
|---|---|---|
| `dead-path` | error | A backticked repository path that isn't there |
| `unknown-script` | error | `npm run x` where no `package.json` defines `x` |
| `unknown-make-target` | error | `make x` where no Makefile defines `x` |
| `size` | warn | Over 200 lines, Claude Code's documented target |
| `repo-overview` | info | A directory tree or architecture overview |
| `vague-instruction` | info | "Follow best practices" and friends |
| `readme-overlap` | info | At least 20% of the text repeats the README |
| `no-verify-command` | info | No test, lint or build command |

## How much to trust it

I read every error-level finding from a scan of 321 files. **20 of 44 were real stale references, or 45%.** Agent instruction files routinely mention paths they know are absent, such as "`apps/old` was removed, do not restore it", plus generated files, private submodules and other repositories. The rules stay silent wherever they can't be sure, and that still isn't enough to fail a build on. Exit code 1 is opt-in with `--strict`. Treat findings as a list to read.

## The scan

`scan.py` lints the root `AGENTS.md` of the 1,000 most-starred public repositories, using partial clones and the `gh` CLI.

[`results/summary.json`](results/summary.json) holds the aggregates, [`results/audit.json`](results/audit.json) the hand audit and [`results/corpus.txt`](results/corpus.txt) every `repo@sha`. Per-repo findings aren't published. The point is the pattern, and each of these projects is one commit away from fixing theirs.

## Development

```bash
pip install -r requirements-ci.txt
pytest -q && ruff check .
```

## License

Apache-2.0

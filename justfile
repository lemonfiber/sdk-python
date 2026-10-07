# Task runner for lemonfiber/sdk-python. `uv run just` with no argument lists the tasks.
#
# `just` is a dev dependency, so `uv run just <task>` works in any clone after
# `uv sync`. Every task runs its tools through `uv run`, so the versions are the
# ones `uv.lock` pins.
default:
    @just --list

# Turn on the repository's own git hooks. Once per clone; `ci` does it too.
hooks:
    git config core.hooksPath .githooks
    @echo "hooks on: .githooks/pre-commit, .githooks/commit-msg, .githooks/pre-push"

# Everything the `checks` and `tests and coverage` jobs run. Mutation, backward
# compatibility, the read list and the shared workflows are CI's alone.
ci: hooks lint types contract-check coverage

# Formatting and every lint rule, changing nothing.
lint:
    uv run ruff format --check .
    uv run ruff check .

# Format, apply the fixes ruff can make, and format what they changed.
fix:
    uv run ruff format .
    uv run ruff check --fix .
    uv run ruff format .

# Pyright in strict mode over the package, the tests and the scripts.
types:
    uv run pyright

# The suite alone.
test *args:
    uv run pytest {{args}}

# The suite with 100% line and branch coverage required, and the report the
# SonarQube Cloud scan reads written to `coverage.xml`.
coverage:
    uv run pytest --cov --cov-report=term-missing --cov-report=xml

# Rewrite `src/lemonfiber/_generated/` from the vendored contract, as the formatter writes it.
generate:
    uv run python -m scripts.contract_generate

# Regenerate and fail on any difference from what is committed, a module it added or removed included.
contract-check: generate
    git diff --exit-code -- src/lemonfiber/_generated contract
    test -z "$(git status --porcelain --untracked-files=all -- src/lemonfiber/_generated contract)"

# The contract at a release tag or full commit hash of lemonfiber, vendored into `contract/`.
sync revision:
    uv run python -m scripts.contract_sync {{revision}}

# Mutation testing and the minimum score. Slow: CI runs it on every pull request.
mutation:
    uv run mutmut run
    uv run mutmut export-cicd-stats
    uv run python scripts/mutation_score.py

# The public surface against every commit a consumer vendors. Needs a spec checkout.
bc spec="../spec":
    uv run python scripts/backward_compat.py --spec {{spec}}

# Rewrite CHANGELOG.md from the commit history.
changelog:
    uv run git-cliff -o CHANGELOG.md

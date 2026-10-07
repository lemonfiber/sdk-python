# AGENTS.md — sdk-python

Guidance for any AI agent working in this repo.

> **Common rules for every lemonfiber repo are canonical in the spec:**
> [50-governance/ai-contributors.md](https://github.com/lemonfiber/spec/blob/main/50-governance/ai-contributors.md).
> Read them. This file is the `sdk-python`-specific header only.

## What this repo is

The Python client for lemonfiber's web API: an asynchronous client on `aiohttp`
and a synchronous client on `urllib3`, over one generated contract. A library
with **no user interface and no server**. Spec:
[`30-repos/sdk-python.md`](https://github.com/lemonfiber/spec/blob/main/30-repos/sdk-python.md)
and the
[web API contract](https://github.com/lemonfiber/spec/blob/main/20-architecture/contracts/web-api.md).

It is a **peer** of [`sdk-ts`](https://github.com/lemonfiber/sdk-ts) and
[`sdk-php`](https://github.com/lemonfiber/sdk-php), not a translation of either.
All three conform to the same specification; none is the reference for the
others. A client that disagrees with the contract is wrong.

## The rules you cannot break

- **`src/lemonfiber/_generated/` is not edited by hand.** It is produced from the
  contract vendored under `contract/` (`ARCH-R56`, `ARCH-R58`).
  `just contract-check` regenerates and fails on any diff. No written module
  declares a response shape; the architecture tests refuse a `TypedDict` outside
  the generated tree.
- **No suppressions.** No `# type: ignore`, `# pyright:`, `# noqa` or
  `# pragma: no cover`; the architecture tests refuse each of them.
- **Dependencies are `aiohttp` and `urllib3`**, and nothing else without a
  recorded reason. Each is imported by its one transport module alone.
- **No rendering, no policy, no state beyond the stream.**
- **The token is a header, never a URL** (`ARCH-R52`); **loopback, or an address
  a certificate pin vouches for** (`ARCH-R60`, `ARCH-R99`). A pin is given when a
  client is built, and there is no argument or setting that weakens it.
- **Comments and docstrings state what a thing is or does.** Reasoning and
  history belong in the spec.

## Checks

```
uv run just ci        # lint, strict types, the contract diff, coverage
uv run just fix       # format and apply the fixes ruff can make
uv run just test      # the suite alone
```

Mutation testing (`just mutation`) and the backward-compatibility check
(`just bc`) are merge gates that run in CI; do not run mutation locally.

## Before you open a PR

- `uv run just ci` is clean.
- Cite a spec identifier in a commit `Spec:` trailer and the PR body.
- Sign off every commit (`git commit -s`); the DCO gate fails without it.
- No AI attribution in commits, PR bodies, or comments.
- A break of the public surface made on purpose is listed under
  `[tool.lemonfiber.backward-compatibility]` in `pyproject.toml`, as the
  check's failure names it, and its commit is marked breaking (`!` after the
  type, or a `BREAKING CHANGE:` footer) so the changelog names it.

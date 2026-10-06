# sdk-python

The Python client for lemonfiber's web API: an asynchronous and a synchronous client over one generated contract.

What this repository is and what it must meet is specified in [`spec/30-repos/sdk-python.md`](https://github.com/lemonfiber/spec/blob/main/30-repos/sdk-python.md), against the [web API contract](https://github.com/lemonfiber/spec/blob/main/20-architecture/contracts/web-api.md).

## Taking it

It is not published to a package registry. A consumer takes it by commit, either as a git dependency or by vendoring `src/lemonfiber/` under `_vendor/lemonfiber/` and recording the commit beside the copy in `_vendor/lemonfiber/REVISION`, which is what the backward-compatibility check reads.

```sh
uv add "lemonfiber @ git+https://github.com/lemonfiber/sdk-python@<commit>"
```

It needs Python 3.14 or newer, the oldest Home Assistant's current release supports, and depends on `aiohttp` and `urllib3` and nothing else.

## Reading an answer

Every answer is an envelope, typed by its kind. An envelope in a version of the interface this package does not speak is refused, naming both versions.

```python
from lemonfiber import expect, parse_envelope

envelope = parse_envelope(body)  # ApiVersionMismatchError if the versions differ
status = expect(envelope, "status")  # a StatusEnvelope, or UnexpectedKindError
```

Every shape the contract describes is importable from `lemonfiber.contract`, and every failure is a `LemonfiberError`.

## What is generated and what is written

`src/lemonfiber/_generated/` is generated from the vendored `contract/web-api.contract.json`, the artefact lemonfiber builds from the types it serialises, and is never edited by hand. `contract/VERSION` records the lemonfiber commit it was taken from.

```sh
uv run just sync <tag-or-commit>   # vendor the artefact one revision of lemonfiber serves
uv run just generate               # rewrite src/lemonfiber/_generated/ from it
```

Everything else is written once, in Python: the envelope's version refusal and the error model.

## Working on it

```sh
uv sync
uv run just ci      # lint, strict types, the contract diff, the suite at 100% line and branch coverage
```

Mutation testing, the backward-compatibility check and the organisation's shared workflows run in CI.

Hippocratic License 3.0. See [LICENSE](LICENSE).

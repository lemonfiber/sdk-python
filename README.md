# sdk-python

A Python client for the web API that [lemonfiber](https://github.com/lemonfiber/lemonfiber)
serves. For Python programs, such as a Home Assistant integration or a script, that read or
control a lemonfiber media stack, on the same machine or, with the stack's certificate pinned,
from another one.

It has an asynchronous client (aiohttp) and a synchronous one (urllib3) that answer the same
calls, typed answers for every kind the API returns, and a live event stream that marks
values from before a dropped connection as stale.

**Not on PyPI.** There is no release yet; install it from GitHub at a commit.

## Requirements

- Python 3.14 or newer.
- lemonfiber, serving its web API with `lemonfiber ui`.

The only dependencies are `aiohttp` and `urllib3`.

## Install

Pin a commit from [the commit list](https://github.com/lemonfiber/sdk-python/commits/main):

```sh
uv add "lemonfiber @ git+https://github.com/lemonfiber/sdk-python@<commit>"
```

or, with pip, `pip install "lemonfiber @ git+https://github.com/lemonfiber/sdk-python@<commit>"`.

To vendor it instead, copy `src/lemonfiber/` to `_vendor/lemonfiber/` in your project and
write the commit you copied into `_vendor/lemonfiber/REVISION`.

## Quick start

Start lemonfiber's web API. It prints the address and a token for this run:

```console
$ lemonfiber ui --port 9000 --no-browser
lemonfiber is serving at:
  http://[::1]:9000
  http://127.0.0.1:9000
…
The token for this run, which the page will ask you for:
  <token>
```

Then ask it how the stack is doing. Save this as `status.py`:

```python
import os

from lemonfiber import Address, Credential, Read, SyncClient, expect

address = Address("http://127.0.0.1:9000")
credential = Credential(os.environ["LEMONFIBER_TOKEN"])

with SyncClient(address, credential) as client:
    status = expect(client.read(Read.STATUS), "status")

print(status["data"]["condition"], status["data"]["active_forms"])
```

Run it with the token lemonfiber printed:

```console
$ LEMONFIBER_TOKEN=<token> python status.py
active ['library']
```

That is the output with only the `library` form running and healthy. A form is a named part
of the stack, such as `library` or `tv`; see
[forms](https://docs.lemonfiber.app/running/forms-and-slices/).

A failure is raised as a `LemonfiberError`, with a message you can show a person.

## Where to go next

- [The guide](docs/guide.md): the asynchronous client, reaching a stack on another machine,
  sessions and integration keys, what a stack can do for a credential, actions and jobs, the
  live event stream and every error.
- [The web API](https://docs.lemonfiber.app/api/): the envelope every answer arrives in,
  every payload kind and the field-by-field reference.
- [The command reference](https://docs.lemonfiber.app/commands/every-command/): every read
  and action is a command, and takes the same arguments.

## Contributing

```sh
uv sync
uv run just ci   # lint, strict types, the contract check, tests at 100% line and branch coverage
```

Mutation testing and the backward-compatibility check run in CI. `src/lemonfiber/_generated/`
is generated from lemonfiber's contract and never edited by hand; the
[guide](docs/guide.md#where-the-types-come-from) says how to regenerate it. Every change cites
a requirement in the [specification](https://github.com/lemonfiber/spec); start with the
[contributing guide](https://github.com/lemonfiber/spec/blob/main/50-governance/contributing.md).

## Security

Report a vulnerability privately, as the
[security policy](https://github.com/lemonfiber/.github/blob/main/SECURITY.md) describes. Do
not open a public issue.

## Licence

[Hippocratic License 3.0](LICENSE): source-available and ethical-source, not OSI-approved. The
[licence rationale](https://github.com/lemonfiber/spec/blob/main/90-appendix/license-rationale.md)
explains what that means for you. Made by NightWorksIO.

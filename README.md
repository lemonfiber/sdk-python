# sdk-python

The Python client for lemonfiber's web API: an asynchronous and a synchronous client over one generated contract.

What this repository is and what it must meet is specified in [`spec/30-repos/sdk-python.md`](https://github.com/lemonfiber/spec/blob/main/30-repos/sdk-python.md), against the [web API contract](https://github.com/lemonfiber/spec/blob/main/20-architecture/contracts/web-api.md).

## Taking it

It is not published to a package registry. A consumer takes it by commit, either as a git dependency or by vendoring `src/lemonfiber/` under `_vendor/lemonfiber/` and recording the commit beside the copy in `_vendor/lemonfiber/REVISION`, which is what the backward-compatibility check reads.

```sh
uv add "lemonfiber @ git+https://github.com/lemonfiber/sdk-python@<commit>"
```

It needs Python 3.14 or newer, the oldest Home Assistant's current release supports, and depends on `aiohttp` and `urllib3` and nothing else.

## Using it

Both clients take an `Address` and a `Credential` and answer the same calls, one with `await`.

```python
from lemonfiber import Address, AsyncClient, Credential, Read, SyncClient, expect

# On this machine: the address and token lemonfiber printed when it started serving.
with SyncClient(Address("http://127.0.0.1:43117"), Credential(token)) as client:
    status = expect(client.read(Read.STATUS), "status")

# Anywhere else: only with the stack's certificate pin, given with the address.
address = Address(
    "https://nas.local:8443", pin="86b25c676b761e9a398081373fec783c2bec970baa255370838aebb5c687841e"
)
async with AsyncClient(address, Credential(integration_key), session=session) as client:
    started = expect(await client.act("repair", {"dry_run": False, "offer": offer}), "job")
    outcome = await client.follow(started)  # Finished or Ended; a failure is raised
```

- **The address.** A loopback address, or a host name resolving only to loopback, needs no pin. A name is resolved once, when the address is given, and every connection goes to an address it resolved to then, asking for the stack by its name, so a name that later resolves elsewhere reaches nothing new. Any other address is refused unless it was given with the stack's certificate pin: SHA-256 over the certificate's DER encoding, 64 hexadecimal characters. The pin is checked against the certificate the stack presents once the handshake completes and before any request is written, by `aiohttp.Fingerprint` and by urllib3's `assert_fingerprint`. No argument or setting weakens it. `await Address.resolved(...)` resolves a name without blocking the event loop.
- **The credential.** The per-run token lemonfiber printed, a session's secret, or an integration key the operator minted, each a `Credential`. It travels in `X-Lemonfiber-Token` and never in a URL, and its `repr` shows nothing of it. `admit` and `admit_async` exchange a password for a session once.
- **The session.** `AsyncClient` takes the `aiohttp.ClientSession` an application already holds, as Home Assistant gives an integration its own, and never closes it. Given none, it opens one and closes it in `aclose`.
- **Answers.** `read` takes a `Read`, the reads the contract names; `logs` and `bundle` are the two reads that are not one envelope. `act` sends an action once and never retries it. `job`, `release` and `follow` redeem the name a long-running action answered with.
- **What a key may call.** `KEY_CALLABLE` is the contract's list of the actions an integration key may call, in its order, each a `KeyCallable` saying whether calling it `disturbs` the running system and whether it takes a `rehearsal` (`dry_run`), so the real call can be offered after one. `is_key_callable` tells whether an action is on it. An `act` key is refused any other action, and a `read` key every action.
- **What a stack can do.** `capabilities()` answers a `CapabilitySet`: every request the stack serves, by the path it is served at, with what it comes to for the credential that asked: `available`, `unconfigured` (a setting has to be turned on first) or `unpermitted` (this credential may not ask for it). `available`, `unconfigured` and `unpermitted` collect the paths in each state, so `unpermitted` is what a key's scope does not reach; `of_action`, `of_read` and `of` answer for one request, or `None` where the stack does not have it. A path this package does not know is kept, not refused. `read_at` says when it was read, since it can change while it is held.
- **Problems.** Every failure is a `LemonfiberError`. A refusal is read from its code where the contract lists it and from its status where it carries none: `NotAdmittedError`, `DeclinedError`, `MissingError`, `MisaskedError`, `BusyError`, `TooManyAttemptsError` and `FailedError`, each carrying the status, the code and the problem document. An answer in a version this package does not speak is `ApiVersionMismatchError`, naming both versions.

## Following the live stream

```python
async with client.events() as stream:
    async for arrival in stream:
        match arrival:
            case Live(envelope):  # carried just now
                ...
            case Stale(envelope, quiet_for):  # held from before a gap: not what is true now
                ...
            case Gap(why, quiet_for):  # the stream broke and is being reopened
                ...
```

`SyncClient.events()` is the same stream for a plain `for` loop. The server speaks at least every 15 seconds; 30 seconds in silence is a broken stream rather than a quiet one. A broken stream is reopened from the last event id it carried, sent as `Last-Event-ID`, waiting a second and twice as long after each failure, and `StreamLostError` is raised once five attempts in a row have failed. Every value held from before a gap arrives again as `Stale` and stays stale until the stream carries it again; `stream.held()` says where each kind stands. A refused credential, a refused certificate or an answer in another version is raised at once rather than retried. A kind this package was not generated with arrives as `Unrecognised`, naming the kind and nothing more. An event, or a line of one, longer than 16,777,216 characters is refused as `UnreadableResponseError` rather than held.

Every shape the contract describes is importable from `lemonfiber.contract`.

## What is generated and what is written

`src/lemonfiber/_generated/` is generated from the vendored `contract/web-api.contract.json`, the artefact lemonfiber builds from the types it serialises, and is never edited by hand. `contract/VERSION` records the lemonfiber commit it was taken from.

```sh
uv run just sync <tag-or-commit>   # vendor the artefact one revision of lemonfiber serves
uv run just generate               # rewrite src/lemonfiber/_generated/ from it
```

Everything else is written once, in Python: the envelope's version refusal, the token's placement, the pin, the stream's behaviour, and the error model.

## Working on it

```sh
uv sync
uv run just ci      # lint, strict types, the contract diff, the suite at 100% line and branch coverage
```

Mutation testing, the backward-compatibility check and the organisation's shared workflows run in CI.

Hippocratic License 3.0. See [LICENSE](LICENSE).

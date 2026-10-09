# Using the Python client

This guide covers everything the `lemonfiber` package does. The
[README](../README.md) has the install steps and a first call.

## Two clients

`SyncClient` (built on urllib3) and `AsyncClient` (built on aiohttp) answer the
same calls in the same way; the asynchronous one is awaited. Both take an
`Address` and a `Credential`, and both are context managers.

```python
from lemonfiber import Address, AsyncClient, Credential, Read, SyncClient, expect

with SyncClient(Address("http://127.0.0.1:9000"), Credential(token)) as client:
    status = expect(client.read(Read.STATUS), "status")

async with AsyncClient(Address("http://127.0.0.1:9000"), Credential(token)) as client:
    status = expect(await client.read(Read.STATUS), "status")
```

`AsyncClient` takes the `aiohttp.ClientSession` your application already holds,
as `session=`, and never closes it. Home Assistant gives each integration one.
Given none, the client opens its own and closes it in `aclose`.

## The address

A loopback address, or a host name that resolves only to loopback, needs nothing
more. Any other address is refused unless it comes with the stack's certificate
pin, and it must be `https`:

```python
address = Address(
    "https://nas.local:8443", pin="86b25c676b761e9a398081373fec783c2bec970baa255370838aebb5c687841e"
)
```

The pin is the SHA-256 digest of the stack's certificate, 64 hexadecimal
characters. `lemonfiber ui --lan --tls` prints it when it starts. It is checked
against the certificate the stack presents once the TLS handshake completes and
before any request is written. Nothing can weaken it.

A host name is resolved once, when the `Address` is made, and every connection
goes to an address it resolved to then. A name that later resolves somewhere else
reaches nothing new. `await Address.resolved(...)` does the resolving without
blocking the event loop.

## The credential

A `Credential` is one of:

- the per-run token `lemonfiber ui` prints;
- a session, from exchanging a password once with `admit` or `admit_async`
  (pass `name=` for a household member; the operator passes none);
- an integration key the operator minted.

It travels in the `X-Lemonfiber-Token` header and never in a URL, and its `repr`
shows none of it.

## Reading

`read` takes a `Read`, one member for each read the contract lists that answers
with one envelope, and an optional query. `READS`, importable from
`lemonfiber.contract`, says which kinds each answers with and which query
parameters it takes:

```python
status = expect(client.read(Read.STATUS), "status")
status["data"]["condition"]  # "inactive" | "degraded" | "partial" | "active"
```

A read whose path a caller fills keeps its segment in its name and value:
`Read.HELD_ID` is `held/{id}`, and `READS` names its `segments`. The query
gives each segment as one value, which is sent escaped as one path segment;
one not given, given as a list, empty, `.` or `..` raises `MisaskedError` and
nothing is sent:

```python
title = expect(client.read(Read.HELD_ID, {"id": "tt0133093"}), "title")
```

Every answer is an envelope: `api_version`, `kind` and `data`. `expect` narrows
an envelope to the kind you expect, and raises `UnexpectedKindError` for any
other. Every shape the contract describes is importable from
`lemonfiber.contract`.

Some reads are not a single envelope. `logs` takes the `services` and `forms` to
narrow to and how many of the latest lines to answer with (`tail`), and answers
with a `LogEnvelope` a line, refusing a line of any other kind. `bundle` answers
with a `BundleFile`: a support bundle's name, bytes and type.

`poster` and `backdrop` answer with a `Picture`, a title's image as its bytes
and media type, read by the id the shelf lists the title under. They take
`member` and `defaults`, as the title read does:

```python
poster = client.poster(title_id, {"member": "ada"})
poster.content  # the image, as delivered
poster.media_type  # "image/webp"
```

A picture is one of `PICTURE_TYPES` (JPEG, PNG, WebP, GIF and AVIF, never SVG)
and at most `PICTURE_MOST` bytes, 2 MiB. Any other answer raises
`UnreadableResponseError`. The client reads no further than one byte past the
limit, and none of an answer that states a longer length. A title outside the member's limits raises
`MissingError` with `PLAY-2`, and a title with no picture of that kind raises
`MissingError` with `PLAY-9`.

A read (`read`, `capabilities`, `logs`, `bundle`, `poster`, `backdrop` and `job`) is asked twice more
where nothing answered or a gateway in front of the stack answered 502, 503 or
504, a quarter of a second later and then half a second, every attempt within
the client's `timeout`.

## What a stack can do

`capabilities()` answers with a `CapabilitySet`: every request the stack serves,
by its path, and what it comes to for the credential that asked:

| State          | Meaning                                                   |
| -------------- | --------------------------------------------------------- |
| `available`    | You can use it                                            |
| `unconfigured` | A setting on the stack has to be turned on first          |
| `unpermitted`  | This credential may not use it, for example a key's scope |

`available`, `unconfigured` and `unpermitted` collect the paths in each state.
`of_action`, `of_read` and `of` answer for one request, or `None` where the stack
does not have it. A path this package does not know is kept rather than refused.
`read_at` says when the set was read, since it can change while you hold it.

`scope` says whose credential asked: `operator`, a `read` or `act` key, or a
household `member`. Read it rather than guess it from which requests are
permitted. `stack` is the stack's own identifier, the one pairing material
carries, or `None` where the stack has nowhere to keep one: two credentials
with the same `stack` reach the same stack.

## Acting

`act` sends an action once and never retries it, because a second sending would
be a second change; `release` is sent once too. The action names and arguments are the command line's own.

```python
await client.act("restart", {"services": ["sonarr"], "dry_run": True})  # says what it would do; does nothing
started = expect(await client.act("restart", {"services": ["sonarr"]}), "job")
outcome = await client.follow(started)  # Finished or Ended; a failure is raised
```

An action that reaches the services answers with a job rather than its outcome.
`job` asks where a job stands, `release` stops it, and `follow` asks every few
seconds until it is finished or ended (`every=` sets how often, `within=` how
long before it raises `StillRunningError`).

### What an integration key may call

`KEY_CALLABLE` lists the actions an integration key may call, in the contract's
order. Each is a `KeyCallable` saying whether calling it `disturbs` the running
system and whether it takes a `rehearsal` (`dry_run`), so the real call can be
offered after a rehearsal, and `moved` names the code a call is refused with when
the offer it carries back has moved since its rehearsal, or `None` where it takes
no offer. `is_key_callable` tells whether an action is on the list. A `read` key
may call no action, and an `act` key only these.

## Live updates

```python
from lemonfiber import Gap, Live, Stale, Unrecognised

async with client.events() as stream:
    async for arrival in stream:
        match arrival:
            case Live(envelope):  # just carried
                ...
            case Stale(envelope, quiet_for):  # held from before a gap: not what is true now
                ...
            case Gap(why, quiet_for):  # the stream broke and is being reopened
                ...
            case Unrecognised(kind):  # a kind this package was not generated with
                ...
```

`SyncClient.events()` is the same stream for a plain `for` loop.

- The server sends a heartbeat at least every 15 seconds (`HEARTBEAT`). Silence
  for 30 seconds (`SILENCE_ALLOWED`) is a broken stream, not a quiet one.
- A broken stream is reopened from the last event it carried, sent as
  `Last-Event-ID`. It waits one second, then twice as long after each failure,
  and raises `StreamLostError` after five failures in a row.
- Every value held from before a gap arrives again as `Stale`, and stays stale
  until the stream carries it again. `stream.held()` says where each kind
  stands.
- A refused credential, a refused certificate or an answer in another
  `api_version` is raised at once, not retried.
- An event longer than 16 MiB is refused with `UnreadableResponseError`.

## Errors

Every failure is a `LemonfiberError`. When lemonfiber refuses a request, it
raises a `RefusedError`, chosen by the refusal code where the contract lists one
and by the HTTP status where there is none:

| Error                  | Meaning                                                                            |
| ---------------------- | ---------------------------------------------------------------------------------- |
| `NotAdmittedError`     | The credential is absent, wrong, expired, revoked or from another run              |
| `DeclinedError`        | lemonfiber objects to who is asking or where from; a new credential would not help |
| `MissingError`         | lemonfiber has nothing by the name the request gave                                |
| `MisaskedError`        | lemonfiber could not answer the request as it was asked                            |
| `BusyError`            | Other work held the stack. The same request may be sent again once it is done      |
| `TooManyAttemptsError` | Too many wrong attempts lately. `retry_after` says how many seconds, where known   |
| `FailedError`          | Nothing about the request was wrong; the machine could not answer it               |

Each refusal carries the HTTP status, the code and the problem document.
`REFUSAL_CODES` lists what the contract says about each code, and
`is_refusal_code` tells a listed code from any other string. The codes are listed
in [every error by code](https://docs.lemonfiber.app/fixing/every-error-by-code/).
The other errors are exported from `lemonfiber` with a docstring each. The ones
you will meet most are `UnreachableError` (nothing answered, or what answered was
not lemonfiber), `CertificateRefusedError` (the stack presented a different
certificate), `ConfigurationError` (an address, pin or credential the client
cannot use; nothing was sent) and `ApiVersionMismatchError` (an answer in an
`api_version` this package does not speak, naming both).

## Where the types come from

Everything under `src/lemonfiber/_generated/` is generated from the contract
vendored under `contract/`, which lemonfiber builds from the Rust types that
produce its answers. A revision of lemonfiber holds it either as the directory
`contract/web-api/`, an index naming one file per kind, per definition and per
list, or as the single file `contract/web-api.contract.json`. `just sync` vendors
whichever the revision holds, and `just generate` reads either into the same
types. Nothing there is edited by hand. `contract/VERSION` names the
lemonfiber commit the copy came from.

```sh
uv run just sync <tag-or-commit>   # vendor the contract at that revision of lemonfiber
uv run just generate               # rewrite src/lemonfiber/_generated/ from it
```

Each kind's envelope, and the shapes only it carries, is one module under
`kinds/`. Shapes several kinds share are under `shared/`. `lemonfiber.contract`
re-exports every shape, whichever module holds it.

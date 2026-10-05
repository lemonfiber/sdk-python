# Copyright (c) 2026 NightWorksIO
"""The asynchronous client, on aiohttp.

A pinned address is reached with an `aiohttp.Fingerprint` on every request:
aiohttp compares the certificate's SHA-256 digest with it once the handshake
completes and before a byte of the request is written, and refuses the
connection where they differ (`ARCH-R99`). It is given per request rather than
to a connector, so it holds on a session the caller supplied, whatever that
session's connector was built with; an unpinned https address is given a
verifying context per request for the same reason.
"""

import asyncio
import ssl
from typing import TYPE_CHECKING, Self

import aiohttp

from lemonfiber import _wire
from lemonfiber.jobs import Ended, Finished, Running
from lemonfiber.problems import CertificateRefusedError, ConfigurationError, UnreachableError

if TYPE_CHECKING:
    from collections.abc import Mapping
    from types import TracebackType

    from lemonfiber._generated.contract import Envelope, JobEnvelope
    from lemonfiber.address import Address
    from lemonfiber.credential import Credential
    from lemonfiber.jobs import JobStanding
    from lemonfiber.reads import Read


type TlsSetting = aiohttp.Fingerprint | ssl.SSLContext | bool


def tls_for(address: Address) -> TlsSetting:
    """Return what every request to an address is checked with: its pin, a verifying context, or nothing."""
    if address.pin is not None:
        return aiohttp.Fingerprint(address.pin.digest)
    if address.scheme == "https":
        return ssl.create_default_context()
    return True


def checked(session: aiohttp.ClientSession) -> aiohttp.ClientSession:
    """Return a caller's session, refusing one whose connector would not check a pin."""
    if not isinstance(session.connector, aiohttp.TCPConnector):
        msg = "A session given to the client connects over TCP, so the certificate pin can be checked."
        raise ConfigurationError(msg)
    return session


async def exchange(
    session: aiohttp.ClientSession,
    address: Address,
    tls: TlsSetting,
    call: _wire.Call,
    limit: aiohttp.ClientTimeout,
) -> _wire.Answer:
    """Send one call and hand back what came back, following no redirect."""
    try:
        async with session.request(
            call.method,
            address.url(call.path),
            data=call.body,
            headers=dict(call.headers),
            ssl=tls,
            allow_redirects=False,
            raise_for_status=False,
            timeout=limit,
        ) as response:
            body = await response.read()
    except (aiohttp.ServerFingerprintMismatch, aiohttp.ClientSSLError) as refused:
        raise CertificateRefusedError(_wire.CERTIFICATE_REFUSED) from refused
    except (aiohttp.ClientError, TimeoutError) as failed:
        raise UnreachableError(_wire.NOT_ANSWERING) from failed
    headers = {name.lower(): value for name, value in response.headers.items()}
    return _wire.Answer(response.status, headers, body)


class AsyncClient:
    """Talks to one stack, asynchronously, with one credential.

    Give it the `aiohttp.ClientSession` the application already holds, as Home
    Assistant gives an integration its own; a client given none opens one and
    closes it in `aclose`. A session it was given is never closed by it.
    """

    def __init__(
        self,
        address: Address,
        credential: Credential,
        *,
        session: aiohttp.ClientSession | None = None,
        timeout: float = _wire.DEFAULT_TIMEOUT,
    ) -> None:
        """Hold an address, a credential and the session to send through; nothing is sent until a call is made."""
        self._address = address
        self._credential = credential
        self._given = None if session is None else checked(session)
        self._owned: aiohttp.ClientSession | None = None
        self._tls = tls_for(address)
        self._limit = aiohttp.ClientTimeout(total=timeout)

    @property
    def address(self) -> Address:
        """Return where this client sends, and the pin it holds that address to."""
        return self._address

    def _session(self) -> aiohttp.ClientSession:
        if self._given is not None:
            return self._given
        if self._owned is None:
            self._owned = aiohttp.ClientSession()
        return self._owned

    async def _answer(self, call: _wire.Call) -> _wire.Answer:
        sent = _wire.with_credential(call, self._credential)
        return await exchange(self._session(), self._address, self._tls, sent, self._limit)

    async def read(self, read: Read, query: _wire.Query | None = None) -> Envelope:
        """Ask for what a command prints under `--json`."""
        return _wire.envelope_of(await self._answer(_wire.read_call(read, query)))

    async def logs(self, query: _wire.Query | None = None) -> list[Envelope]:
        """Ask for what the services have been saying, a `log` envelope a line."""
        return _wire.envelopes_of(await self._answer(_wire.logs_call(query)))

    async def bundle(self, name: str) -> _wire.Bundle:
        """Fetch one support bundle this run wrote, by name, as the bytes it is."""
        return _wire.bundle_of(name, await self._answer(_wire.bundle_call(name)))

    async def act(self, action: str, arguments: Mapping[str, _wire.Json] | None = None) -> Envelope:
        """Tell lemonfiber to do something the command line could also do. Sent once, never retried."""
        return _wire.envelope_of(await self._answer(_wire.action_call(action, arguments)))

    async def job(self, job: str) -> JobStanding:
        """Ask where the work a name stands for got to."""
        return _wire.standing_of(job, await self._answer(_wire.job_call(job, "GET")))

    async def release(self, job: str) -> JobStanding:
        """Let a name go, ending the work it stands for, and say where it now stands."""
        return _wire.standing_of(job, await self._answer(_wire.job_call(job, "DELETE")))

    async def follow(
        self,
        job: str | JobEnvelope,
        *,
        every: float = _wire.DEFAULT_EVERY,
        within: float | None = None,
    ) -> Finished | Ended:
        """Ask where work stands every `every` seconds until it is no longer going.

        Raises `StillRunningError` once `within` seconds have passed with it still going.
        """
        name = _wire.job_name(job)
        loop = asyncio.get_running_loop()
        started = loop.time()
        standing = await self.job(name)
        while isinstance(standing, Running):
            await asyncio.sleep(_wire.next_wait(name, started, loop.time(), every, within))
            standing = await self.job(name)
        return standing

    async def aclose(self) -> None:
        """Close the session this client opened, if it opened one."""
        if self._owned is not None:
            await self._owned.close()
            self._owned = None

    async def __aenter__(self) -> Self:
        """Return the client, to be closed when the block ends."""
        return self

    async def __aexit__(
        self,
        kind: type[BaseException] | None,
        error: BaseException | None,
        trace: TracebackType | None,
    ) -> None:
        """Close the client."""
        await self.aclose()


async def admit_async(
    address: Address,
    password: str,
    *,
    name: str | None = None,
    session: aiohttp.ClientSession | None = None,
) -> _wire.Admitted:
    """Offer a password, once, and come away with a session or with why there is none.

    A household member gives their `name`; the operator gives none. The session's
    credential is what an `AsyncClient` is then built with. The offer waits as
    long as a client's call does by default; `asyncio.timeout` around it waits less.
    """
    call = _wire.session_call(password, name)
    tls = tls_for(address)
    limit = aiohttp.ClientTimeout(total=_wire.DEFAULT_TIMEOUT)
    if session is not None:
        return _wire.admitted_of(await exchange(checked(session), address, tls, call, limit))
    async with aiohttp.ClientSession() as opened:
        return _wire.admitted_of(await exchange(opened, address, tls, call, limit))

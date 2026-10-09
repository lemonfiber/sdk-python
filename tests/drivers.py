# Copyright (c) 2026 NightWorksIO
"""Both clients behind one face, so every behaviour is asserted of each with the same test."""

import asyncio
from typing import TYPE_CHECKING, Literal, Protocol

import aiohttp

from lemonfiber import AsyncClient, SyncClient, admit, admit_async
from lemonfiber.address import ENCRYPTED

if TYPE_CHECKING:
    from collections.abc import Coroutine, Mapping, Sequence

    from lemonfiber import (
        Address,
        BundleFile,
        CapabilitySet,
        Credential,
        Ended,
        Envelope,
        Finished,
        JobStanding,
        Json,
        Picture,
        Query,
        Read,
        Session,
    )
    from lemonfiber._aio import AsyncStream
    from lemonfiber._sync import SyncStream
    from lemonfiber.contract import JobEnvelope, LogEnvelope
    from lemonfiber.stream import Arrival, Live, Stale

SETTLE = 0.25
"""Seconds a loop is given, before it is closed, to finish the closing exchange of its encrypted connections."""

type Flavour = Literal["async", "sync"]
FLAVOURS: tuple[Flavour, ...] = ("async", "sync")


class Following(Protocol):
    """What a test asks of a stream being followed, whichever client opened it."""

    def take(self, count: int) -> list[Arrival]:
        """Return the next `count` arrivals, waiting for each."""
        ...

    def held(self) -> dict[str, Live | Stale]:
        """Return what the stream holds."""
        ...

    def close(self) -> None:
        """Stop following."""
        ...


class SyncFollowing:
    """The synchronous stream, iterated as it is."""

    def __init__(self, stream: SyncStream) -> None:
        """Hold the stream."""
        self.stream = stream

    def take(self, count: int) -> list[Arrival]:
        """Return the next arrivals."""
        return [next(self.stream) for _ in range(count)]

    def held(self) -> dict[str, Live | Stale]:
        """Return what the stream holds."""
        return self.stream.held()

    def close(self) -> None:
        """Stop following."""
        self.stream.close()


class AsyncFollowing:
    """The asynchronous stream, each arrival awaited on the driver's loop."""

    def __init__(self, driver: AsyncDriver, stream: AsyncStream) -> None:
        """Hold the driver whose loop runs it, and the stream."""
        self.driver = driver
        self.stream = stream

    def take(self, count: int) -> list[Arrival]:
        """Return the next arrivals."""
        return [self.driver.run(anext(self.stream)) for _ in range(count)]

    def held(self) -> dict[str, Live | Stale]:
        """Return what the stream holds."""
        return self.stream.held()

    def close(self) -> None:
        """Stop following."""
        self.driver.run(self.stream.aclose())


class Driver(Protocol):
    """What a test asks of a client, whichever one it is."""

    def events(self, *, silence: float, reconnects: int, first_wait: float) -> Following:
        """Follow the stream."""
        ...

    def read(self, read: Read, query: Query | None = None) -> Envelope:
        """Read."""
        ...

    def capabilities(self) -> CapabilitySet:
        """Ask what the stack can do."""
        ...

    def logs(
        self,
        *,
        services: Sequence[str] = (),
        forms: Sequence[str] = (),
        tail: int | None = None,
    ) -> list[LogEnvelope]:
        """Read the logs."""
        ...

    def bundle(self, name: str) -> BundleFile:
        """Fetch a bundle."""
        ...

    def poster(self, title: str, query: Query | None = None) -> Picture:
        """Fetch a poster."""
        ...

    def backdrop(self, title: str, query: Query | None = None) -> Picture:
        """Fetch a backdrop."""
        ...

    def act(self, action: str, arguments: Mapping[str, Json] | None = None) -> Envelope:
        """Act."""
        ...

    def job(self, job: str) -> JobStanding:
        """Ask about a job."""
        ...

    def release(self, job: str) -> JobStanding:
        """Release a job."""
        ...

    def follow(
        self,
        job: str | JobEnvelope,
        *,
        every: float,
        within: float | None = None,
    ) -> Finished | Ended:
        """Follow a job."""
        ...

    def close(self) -> None:
        """Close the client."""
        ...


class SyncDriver:
    """The synchronous client, called as it is."""

    def __init__(self, client: SyncClient) -> None:
        """Hold the client."""
        self.client = client

    def events(self, *, silence: float, reconnects: int, first_wait: float) -> Following:
        """Follow the stream."""
        return SyncFollowing(
            self.client.events(silence=silence, reconnects=reconnects, first_wait=first_wait),
        )

    def read(self, read: Read, query: Query | None = None) -> Envelope:
        """Read."""
        return self.client.read(read, query)

    def capabilities(self) -> CapabilitySet:
        """Ask what the stack can do."""
        return self.client.capabilities()

    def logs(
        self,
        *,
        services: Sequence[str] = (),
        forms: Sequence[str] = (),
        tail: int | None = None,
    ) -> list[LogEnvelope]:
        """Read the logs."""
        return self.client.logs(services=services, forms=forms, tail=tail)

    def bundle(self, name: str) -> BundleFile:
        """Fetch a bundle."""
        return self.client.bundle(name)

    def poster(self, title: str, query: Query | None = None) -> Picture:
        """Fetch a poster."""
        return self.client.poster(title, query)

    def backdrop(self, title: str, query: Query | None = None) -> Picture:
        """Fetch a backdrop."""
        return self.client.backdrop(title, query)

    def act(self, action: str, arguments: Mapping[str, Json] | None = None) -> Envelope:
        """Act."""
        return self.client.act(action, arguments)

    def job(self, job: str) -> JobStanding:
        """Ask about a job."""
        return self.client.job(job)

    def release(self, job: str) -> JobStanding:
        """Release a job."""
        return self.client.release(job)

    def follow(
        self,
        job: str | JobEnvelope,
        *,
        every: float,
        within: float | None = None,
    ) -> Finished | Ended:
        """Follow a job."""
        return self.client.follow(job, every=every, within=within)

    def close(self) -> None:
        """Close the client."""
        self.client.close()


class AsyncDriver:
    """The asynchronous client, each call run to completion on one event loop of its own."""

    def __init__(
        self,
        runner: asyncio.Runner,
        client: AsyncClient,
        given: aiohttp.ClientSession | None,
        *,
        encrypted: bool,
    ) -> None:
        """Hold the loop, the client, the session the test gave it if it gave one, and whether it speaks TLS."""
        self.runner = runner
        self.client = client
        self.given = given
        self.encrypted = encrypted

    def run[T](self, call: Coroutine[object, object, T]) -> T:
        """Run one call to completion."""
        return self.runner.run(call)

    def events(self, *, silence: float, reconnects: int, first_wait: float) -> Following:
        """Follow the stream."""
        stream = self.client.events(silence=silence, reconnects=reconnects, first_wait=first_wait)
        return AsyncFollowing(self, stream)

    def read(self, read: Read, query: Query | None = None) -> Envelope:
        """Read."""
        return self.run(self.client.read(read, query))

    def capabilities(self) -> CapabilitySet:
        """Ask what the stack can do."""
        return self.run(self.client.capabilities())

    def logs(
        self,
        *,
        services: Sequence[str] = (),
        forms: Sequence[str] = (),
        tail: int | None = None,
    ) -> list[LogEnvelope]:
        """Read the logs."""
        return self.run(self.client.logs(services=services, forms=forms, tail=tail))

    def bundle(self, name: str) -> BundleFile:
        """Fetch a bundle."""
        return self.run(self.client.bundle(name))

    def poster(self, title: str, query: Query | None = None) -> Picture:
        """Fetch a poster."""
        return self.run(self.client.poster(title, query))

    def backdrop(self, title: str, query: Query | None = None) -> Picture:
        """Fetch a backdrop."""
        return self.run(self.client.backdrop(title, query))

    def act(self, action: str, arguments: Mapping[str, Json] | None = None) -> Envelope:
        """Act."""
        return self.run(self.client.act(action, arguments))

    def job(self, job: str) -> JobStanding:
        """Ask about a job."""
        return self.run(self.client.job(job))

    def release(self, job: str) -> JobStanding:
        """Release a job."""
        return self.run(self.client.release(job))

    def follow(
        self,
        job: str | JobEnvelope,
        *,
        every: float,
        within: float | None = None,
    ) -> Finished | Ended:
        """Follow a job."""
        return self.run(self.client.follow(job, every=every, within=within))

    def close(self) -> None:
        """Close the client, the session the test gave it, and the loop."""
        self.runner.run(self.client.aclose())
        if self.given is not None:
            self.runner.run(self.given.close())
        if self.encrypted:
            self.runner.run(asyncio.sleep(SETTLE))
        self.runner.close()


async def opened_session(*, verifying: bool = True) -> aiohttp.ClientSession:
    """Open a session as an application would, with a connector that verifies or not."""
    return aiohttp.ClientSession(
        connector=aiohttp.TCPConnector(ssl=verifying),
        headers={"User-Agent": "the-caller"},
    )


def connect(
    flavour: Flavour,
    address: Address,
    credential: Credential,
    *,
    timeout: float = 5.0,
    session: bool = False,
) -> Driver:
    """Build one client of the flavour asked for, the asynchronous one on a session of the caller's where asked."""
    if flavour == "sync":
        return SyncDriver(SyncClient(address, credential, timeout=timeout))
    runner = asyncio.Runner()
    given = runner.run(opened_session(verifying=False)) if session else None
    client = AsyncClient(address, credential, session=given, timeout=timeout)
    return AsyncDriver(runner, client, given, encrypted=address.scheme == ENCRYPTED)


def admitted(flavour: Flavour, address: Address, password: str, name: str | None = None) -> Session:
    """Offer a password at the door with the flavour asked for."""
    if flavour == "sync":
        return admit(address, password, name=name, timeout=5.0)
    with asyncio.Runner() as runner:
        try:
            return runner.run(admit_async(address, password, name=name))
        finally:
            if address.scheme == ENCRYPTED:
                runner.run(asyncio.sleep(SETTLE))

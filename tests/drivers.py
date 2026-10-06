# Copyright (c) 2026 NightWorksIO
"""Both clients behind one face, so every behaviour is asserted of each with the same test."""

import asyncio
from typing import TYPE_CHECKING, Literal, Protocol

import aiohttp

from lemonfiber import AsyncClient, SyncClient, admit, admit_async
from lemonfiber.address import ENCRYPTED

if TYPE_CHECKING:
    from collections.abc import Coroutine, Mapping

    from lemonfiber import (
        Address,
        Admitted,
        Bundle,
        Credential,
        Ended,
        Envelope,
        Finished,
        JobStanding,
        Json,
        Query,
        Read,
    )
    from lemonfiber.contract import JobEnvelope

SETTLE = 0.25
"""Seconds a loop is given, before it is closed, to finish the closing exchange of its encrypted connections."""

type Flavour = Literal["async", "sync"]
FLAVOURS: tuple[Flavour, ...] = ("async", "sync")


class Driver(Protocol):
    """What a test asks of a client, whichever one it is."""

    def read(self, read: Read, query: Query | None = None) -> Envelope:
        """Read."""
        ...

    def logs(self, query: Query | None = None) -> list[Envelope]:
        """Read the logs."""
        ...

    def bundle(self, name: str) -> Bundle:
        """Fetch a bundle."""
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

    def read(self, read: Read, query: Query | None = None) -> Envelope:
        """Read."""
        return self.client.read(read, query)

    def logs(self, query: Query | None = None) -> list[Envelope]:
        """Read the logs."""
        return self.client.logs(query)

    def bundle(self, name: str) -> Bundle:
        """Fetch a bundle."""
        return self.client.bundle(name)

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

    def read(self, read: Read, query: Query | None = None) -> Envelope:
        """Read."""
        return self.run(self.client.read(read, query))

    def logs(self, query: Query | None = None) -> list[Envelope]:
        """Read the logs."""
        return self.run(self.client.logs(query))

    def bundle(self, name: str) -> Bundle:
        """Fetch a bundle."""
        return self.run(self.client.bundle(name))

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


def admitted(flavour: Flavour, address: Address, password: str, name: str | None = None) -> Admitted:
    """Offer a password at the door with the flavour asked for."""
    if flavour == "sync":
        return admit(address, password, name=name, timeout=5.0)
    with asyncio.Runner() as runner:
        try:
            return runner.run(admit_async(address, password, name=name))
        finally:
            if address.scheme == ENCRYPTED:
                runner.run(asyncio.sleep(SETTLE))

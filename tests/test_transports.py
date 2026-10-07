# Copyright (c) 2026 NightWorksIO
"""What each transport hands the library it sends through, recorded where the library would send it."""

import asyncio
import time
from typing import TYPE_CHECKING, NoReturn

import aiohttp
import pytest
import urllib3
import urllib3.exceptions
import urllib3.response

from lemonfiber import (
    Address,
    AsyncClient,
    Credential,
    Read,
    StreamLostError,
    SyncClient,
    UnreachableError,
    admit_async,
)
from lemonfiber._aio import STRAIGHT
from lemonfiber._protocol.calls import DEFAULT_TIMEOUT
from lemonfiber._sync import CHUNK
from tests.conftest import PRINTED
from tests.stack import Streamed, event

if TYPE_CHECKING:
    from tests.stack import Stack

TIMEOUT = 7.0
"""The seconds each client in these tests is told a call waits: none of the package's own."""

SILENCE = 4.5
"""The silence each stream in these tests allows: none of the package's own."""

FIRST_WAIT = 2.5
"""The wait before a broken stream is first opened again in these tests: none of the package's own."""

NAMED = Address("http://stack.invalid:1", resolver=lambda _: ["127.0.0.1"])
"""A stack named by a host name, reached at the loopback address it resolved to."""

NOT_SENT = "the recorder sends nothing"
"""What a recorded request fails with, in place of being sent."""


def recording_aiohttp(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, object]]:
    """Record the options of every request an aiohttp session is asked to send, and send none."""
    sent: list[dict[str, object]] = []

    def request(_session: aiohttp.ClientSession, _method: str, _url: str, **options: object) -> NoReturn:
        sent.append(options)
        raise aiohttp.ClientConnectionError(NOT_SENT)

    monkeypatch.setattr(aiohttp.ClientSession, "request", request)
    return sent


def recording_urllib3(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, object]]:
    """Record the options of every request a urllib3 pool is asked to send, and send none."""
    sent: list[dict[str, object]] = []

    def urlopen(_pool: urllib3.HTTPConnectionPool, _method: str, _url: str, **options: object) -> NoReturn:
        sent.append(options)
        raise urllib3.exceptions.HTTPError(NOT_SENT)

    monkeypatch.setattr(urllib3.HTTPConnectionPool, "urlopen", urlopen)
    return sent


def timeout_of(options: dict[str, object]) -> aiohttp.ClientTimeout:
    """Return the timeout a request was sent with."""
    timeout = options["timeout"]
    assert isinstance(timeout, aiohttp.ClientTimeout)
    return timeout


def limit_of(options: dict[str, object]) -> urllib3.Timeout:
    """Return the timeout a request was sent with."""
    timeout = options["timeout"]
    assert isinstance(timeout, urllib3.Timeout)
    return timeout


def assert_sent_straight(options: dict[str, object]) -> None:
    """Assert a request was held to the stack's name, through no middleware of the session's, following nothing."""
    assert options["server_hostname"] == "stack.invalid"
    assert options["middlewares"] == STRAIGHT
    assert options["allow_redirects"] is False
    assert options["raise_for_status"] is False


def test_an_asynchronous_call_is_sent_straight_within_the_time_it_has(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sent = recording_aiohttp(monkeypatch)

    async def read() -> None:
        async with AsyncClient(NAMED, Credential(PRINTED), timeout=TIMEOUT) as client:
            await client.read(Read.STATUS)

    running = read()
    with pytest.raises(UnreachableError):
        asyncio.run(running)
    first = sent[0]
    assert_sent_straight(first)
    assert first["ssl"] is True
    total = timeout_of(first).total
    assert isinstance(total, float)
    assert 0 < total <= TIMEOUT


def test_an_asynchronous_stream_is_opened_straight_waiting_only_to_connect(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sent = recording_aiohttp(monkeypatch)

    async def follow() -> None:
        async with (
            AsyncClient(NAMED, Credential(PRINTED), timeout=TIMEOUT) as client,
            client.events(silence=SILENCE, reconnects=0) as stream,
        ):
            await anext(stream)

    running = follow()
    with pytest.raises(StreamLostError):
        asyncio.run(running)
    [opening] = sent
    assert_sent_straight(opening)
    assert opening["ssl"] is True
    assert timeout_of(opening) == aiohttp.ClientTimeout(sock_connect=TIMEOUT)


def test_an_asynchronous_offer_waits_as_long_as_a_call_does(monkeypatch: pytest.MonkeyPatch) -> None:
    sent = recording_aiohttp(monkeypatch)

    async def knock(session: aiohttp.ClientSession | None) -> None:
        try:
            await admit_async(NAMED, "pw", session=session)
        finally:
            if session is not None:
                await session.close()

    async def given() -> None:
        await knock(aiohttp.ClientSession())

    alone = knock(None)
    with pytest.raises(UnreachableError):
        asyncio.run(alone)
    through_a_session = given()
    with pytest.raises(UnreachableError):
        asyncio.run(through_a_session)
    assert [timeout_of(options) for options in sent] == [aiohttp.ClientTimeout(total=DEFAULT_TIMEOUT)] * 2


def test_a_synchronous_call_is_sent_once_within_the_time_it_has(monkeypatch: pytest.MonkeyPatch) -> None:
    sent = recording_urllib3(monkeypatch)
    with SyncClient(NAMED, Credential(PRINTED), timeout=TIMEOUT) as client, pytest.raises(UnreachableError):
        client.read(Read.STATUS)
    first = sent[0]
    assert first["retries"] is False
    total = limit_of(first).total
    assert isinstance(total, float)
    assert 0 < total <= TIMEOUT


def test_a_synchronous_stream_is_opened_once_unread_waiting_as_long_as_silence_allows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sent = recording_urllib3(monkeypatch)
    with (
        SyncClient(NAMED, Credential(PRINTED), timeout=TIMEOUT) as client,
        client.events(silence=SILENCE, reconnects=0) as stream,
        pytest.raises(StreamLostError),
    ):
        next(stream)
    [opening] = sent
    assert opening["retries"] is False
    assert opening["preload_content"] is False
    limit = limit_of(opening)
    assert (limit.connect_timeout, limit.read_timeout) == (TIMEOUT, SILENCE)


def test_a_synchronous_stream_reads_at_most_a_chunk_at_a_time(
    monkeypatch: pytest.MonkeyPatch,
    stack: Stack,
) -> None:
    stack.reply("GET", "/api/events", Streamed([(0, event("news", {"updates": []}))], hold=1))
    asked: list[int | None] = []
    original = urllib3.response.HTTPResponse.read1

    def read1(response: urllib3.response.HTTPResponse, amt: int | None = None) -> bytes:
        asked.append(amt)
        return original(response, amt)

    monkeypatch.setattr(urllib3.response.HTTPResponse, "read1", read1)
    with (
        SyncClient(Address(stack.url), Credential(PRINTED)) as client,
        client.events(silence=SILENCE) as stream,
    ):
        next(stream)
    assert set(asked) == {CHUNK}


def test_an_asynchronous_stream_waits_the_first_wait_it_was_given_before_opening_again(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sent = recording_aiohttp(monkeypatch)
    waits: list[float] = []

    async def pause(seconds: float) -> None:
        waits.append(seconds)

    monkeypatch.setattr(asyncio, "sleep", pause)

    async def follow() -> None:
        async with (
            AsyncClient(NAMED, Credential(PRINTED)) as client,
            client.events(reconnects=1, first_wait=FIRST_WAIT) as stream,
        ):
            await anext(stream)

    running = follow()
    with pytest.raises(StreamLostError):
        asyncio.run(running)
    assert (len(sent), waits[0]) == (2, FIRST_WAIT)


def test_a_synchronous_stream_waits_the_first_wait_it_was_given_before_opening_again(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sent = recording_urllib3(monkeypatch)
    waits: list[float] = []
    monkeypatch.setattr(time, "sleep", waits.append)
    with (
        SyncClient(NAMED, Credential(PRINTED)) as client,
        client.events(reconnects=1, first_wait=FIRST_WAIT) as stream,
        pytest.raises(StreamLostError),
    ):
        next(stream)
    assert (len(sent), waits) == (2, [FIRST_WAIT])

# Copyright (c) 2026 NightWorksIO
"""The live stream, asserted of both clients: heartbeats, resumption, and values gone stale across a gap."""

import asyncio
from typing import TYPE_CHECKING

import pytest

from lemonfiber import (
    CREDENTIAL_HEADER,
    Address,
    ApiVersionMismatchError,
    Arrival,
    AsyncClient,
    Break,
    CertificateRefusedError,
    Credential,
    Gap,
    Live,
    MissingError,
    NotAdmittedError,
    Stale,
    StreamLostError,
    SyncClient,
    Unrecognised,
    read_envelope,
)
from tests.conftest import PRINTED
from tests.drivers import connect
from tests.stack import HEARTBEAT, Reply, Streamed, envelope, event, problem

if TYPE_CHECKING:
    from tests.drivers import Driver, Flavour, Following
    from tests.stack import Stack

STATUS = read_envelope(envelope("status", {"services": ["a"]}))
NEWS = read_envelope(envelope("news", {"updates": []}))
QUICK = 0.3
"""The silence allowed in these tests, in seconds: twice the beat the stand-in keeps."""


def follow(driver: Driver, *, reconnects: int = 3) -> Following:
    """Follow the stream with a short silence and short waits between openings."""
    return driver.events(silence=QUICK, reconnects=reconnects, first_wait=0.01)


def test_events_arrive_live_carrying_the_token_and_asking_for_the_stream(
    client: Driver,
    stack: Stack,
) -> None:
    stack.reply("GET", "/api/events", Streamed([(0, event("status", STATUS["data"], "1"))], hold=1))
    stream = follow(client)
    assert stream.take(1) == [Live(STATUS)]
    stream.close()
    [arrived] = stack.arrived
    assert arrived.headers[CREDENTIAL_HEADER] == PRINTED
    assert arrived.headers["Accept"] == "text/event-stream"
    assert "Last-Event-ID" not in arrived.headers
    assert PRINTED not in arrived.url


def test_an_event_split_across_chunks_arrives_once_whole(client: Driver, stack: Stack) -> None:
    whole = event("status", STATUS["data"], "1")
    stack.reply(
        "GET",
        "/api/events",
        Streamed([(0, whole[:10]), (0.02, whole[10:-3]), (0.02, whole[-3:])], hold=1),
    )
    stream = follow(client)
    assert stream.take(1) == [Live(STATUS)]
    stream.close()


def test_a_heartbeat_keeps_a_quiet_stream_from_reading_as_broken(client: Driver, stack: Stack) -> None:
    beats = [(QUICK / 2, HEARTBEAT) for _ in range(5)]
    stack.reply("GET", "/api/events", Streamed([*beats, (0, event("news", NEWS["data"], "2"))], hold=1))
    stream = follow(client)
    assert stream.take(1) == [Live(NEWS)]
    stream.close()
    assert len(stack.arrived) == 1


def test_silence_beyond_twice_the_beat_breaks_the_stream_and_cools_what_is_held(
    client: Driver,
    stack: Stack,
) -> None:
    stack.reply(
        "GET",
        "/api/events",
        Streamed([(0, event("status", STATUS["data"], "7"))], hold=2),
        Streamed([(0, event("status", STATUS["data"], "8"))], hold=2),
    )
    stream = follow(client)
    live, gap, stale, again = stream.take(4)
    assert live == Live(STATUS)
    assert isinstance(gap, Gap)
    assert gap.why is Break.SILENT
    assert QUICK <= gap.quiet_for < 5
    assert isinstance(stale, Stale)
    assert stale.envelope == STATUS
    assert QUICK <= stale.quiet_for < 5
    assert again == Live(STATUS)
    stream.close()
    assert stack.arrived[1].headers["Last-Event-ID"] == "7"


def test_a_stream_the_server_ends_is_resumed_from_the_last_event_it_carried(
    client: Driver,
    stack: Stack,
) -> None:
    stack.reply(
        "GET",
        "/api/events",
        Streamed([(0, event("status", STATUS["data"], "3")), (0, event("news", NEWS["data"]))]),
        Streamed([(0, event("news", NEWS["data"], "4"))], hold=1),
    )
    stream = follow(client)
    first, second, gap, stale_status, stale_news, replayed = stream.take(6)
    assert (first, second) == (Live(STATUS), Live(NEWS))
    assert isinstance(gap, Gap)
    assert gap.why is Break.ENDED
    assert isinstance(stale_status, Stale)
    assert isinstance(stale_news, Stale)
    assert (stale_status.envelope, stale_news.envelope) == (STATUS, NEWS)
    assert replayed == Live(NEWS)
    held = stream.held()
    assert held["news"] == Live(NEWS)
    assert isinstance(held["status"], Stale)
    stream.close()
    assert stack.arrived[1].headers["Last-Event-ID"] == "3"


def test_a_stream_that_cannot_be_reopened_is_lost(client: Driver, stack: Stack) -> None:
    stack.reply(
        "GET",
        "/api/events",
        Streamed([(0, event("status", STATUS["data"], "1"))]),
        Reply(503, "Restarting."),
    )
    stream = follow(client, reconnects=2)
    live, gap, stale = stream.take(3)
    assert live == Live(STATUS)
    assert isinstance(gap, Gap)
    assert gap.why is Break.ENDED
    assert isinstance(stale, Stale)
    with pytest.raises(StreamLostError) as lost:
        stream.take(1)
    assert lost.value.attempts == 2
    assert str(lost.value) == (
        "The live stream broke and 2 attempts to reopen it failed. Everything shown is the "
        "last thing confirmed, not what is true now."
    )
    assert len(stack.arrived) == 3


def test_a_stream_nothing_answers_for_is_lost(flavour: Flavour) -> None:
    driver = connect(flavour, Address("http://127.0.0.1:9"), Credential(PRINTED))
    stream = driver.events(silence=QUICK, reconnects=1, first_wait=0.01)
    with pytest.raises(StreamLostError):
        stream.take(1)
    driver.close()


def test_a_refused_credential_is_raised_rather_than_retried(client: Driver, stack: Stack) -> None:
    stack.reply("GET", "/api/events", Reply(403, problem("ADMIT-4", "Nothing this run admits.")))
    stream = follow(client)
    with pytest.raises(NotAdmittedError):
        stream.take(1)
    assert len(stack.arrived) == 1


def test_a_stream_this_stack_does_not_serve_is_raised(client: Driver, stack: Stack) -> None:
    stack.reply("GET", "/api/events", Reply(404, "No such page."))
    with pytest.raises(MissingError):
        follow(client).take(1)


def test_an_event_in_another_version_is_refused_naming_both(client: Driver, stack: Stack) -> None:
    stack.reply("GET", "/api/events", Streamed([(0, event("status", {}, "1", version=2))], hold=1))
    with pytest.raises(ApiVersionMismatchError):
        follow(client).take(1)


def test_a_kind_this_package_does_not_know_is_named_and_not_handed_over(client: Driver, stack: Stack) -> None:
    unknown = b'event: later\ndata: {"api_version": 1, "kind": "later", "data": {}}\n\n'
    stack.reply("GET", "/api/events", Streamed([(0, unknown), (0, event("news", NEWS["data"]))], hold=1))
    stream = follow(client)
    assert stream.take(2) == [Unrecognised("later"), Live(NEWS)]
    assert "later" not in stream.held()
    stream.close()


def test_the_stream_is_held_to_the_pin(flavour: Flavour, tls_stack: Stack) -> None:
    tls_stack.reply("GET", "/api/events", Streamed([(0, event("news", NEWS["data"]))], hold=1))
    wrong = connect(flavour, Address(tls_stack.url, pin="0" * 64), Credential(PRINTED))
    with pytest.raises(CertificateRefusedError):
        follow(wrong).take(1)
    wrong.close()
    assert tls_stack.arrived == []
    right = connect(flavour, Address(tls_stack.url, pin=tls_stack.pin), Credential(PRINTED))
    stream = follow(right)
    assert stream.take(1) == [Live(NEWS)]
    stream.close()
    right.close()


def test_closing_a_stream_that_was_never_read_sends_nothing(client: Driver, stack: Stack) -> None:
    follow(client).close()
    assert stack.arrived == []


def test_a_cut_connection_is_a_dropped_stream(client: Driver, stack: Stack) -> None:
    stack.reply(
        "GET",
        "/api/events",
        Streamed([(0, event("status", STATUS["data"], "5"))], abort=True),
        Streamed([(0, event("news", NEWS["data"]))], hold=1),
    )
    stream = follow(client)
    live, gap, stale, news = stream.take(4)
    assert live == Live(STATUS)
    assert isinstance(gap, Gap)
    assert gap.why is Break.DROPPED
    assert isinstance(stale, Stale)
    assert news == Live(NEWS)
    stream.close()


def test_the_synchronous_stream_iterates_and_closes_as_a_context(stack: Stack) -> None:
    stack.reply("GET", "/api/events", Streamed([(0, event("news", NEWS["data"]))], hold=1))
    with (
        SyncClient(Address(stack.url), Credential(PRINTED)) as client,
        client.events(silence=QUICK) as stream,
    ):
        for arrival in stream:
            assert arrival == Live(NEWS)
            break


def test_the_asynchronous_stream_iterates_and_closes_as_a_context(stack: Stack) -> None:
    stack.reply("GET", "/api/events", Streamed([(0, event("news", NEWS["data"]))], hold=1))

    async def follow_once() -> Arrival:
        client = AsyncClient(Address(stack.url), Credential(PRINTED))
        async with client, client.events(silence=QUICK) as stream:
            async for arrival in stream:
                return arrival
        raise AssertionError

    assert asyncio.run(follow_once()) == Live(NEWS)

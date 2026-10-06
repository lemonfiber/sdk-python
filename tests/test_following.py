# Copyright (c) 2026 NightWorksIO
"""What a follower knows between openings, on a clock the test turns."""

import json
from http import HTTPMethod

import pytest

from lemonfiber import Break, Credential, Gap, Live, Stale, StreamLostError, Unrecognised, read_envelope
from lemonfiber._protocol.calls import Call
from lemonfiber.stream import LONGEST_WAIT, SILENCE_ALLOWED, Following


class Clock:
    """A clock that moves only when told."""

    def __init__(self) -> None:
        """Start at a moment far from zero, as a monotonic clock does."""
        self.now = 1000.0

    def __call__(self) -> float:
        """Return the moment it is."""
        return self.now


def frame(kind: str, data: object, event_id: str | None = None) -> bytes:
    """Return one event carrying an envelope."""
    head = "" if event_id is None else f"id: {event_id}\n"
    body = json.dumps({"api_version": 1, "kind": kind, "data": data})
    return f"{head}event: {kind}\ndata: {body}\n\n".encode()


STATUS = read_envelope({"api_version": 1, "kind": "status", "data": {"a": 1}})
NEWS = read_envelope({"api_version": 1, "kind": "news", "data": {"b": 2}})


def follower(
    clock: Clock,
    *,
    silence: float = 30.0,
    reconnects: int = 3,
    first_wait: float = 1.0,
) -> Following:
    """Return a follower on the test's clock."""
    return Following(
        Credential("abc"),
        silence=silence,
        reconnects=reconnects,
        first_wait=first_wait,
        clock=clock,
    )


def test_the_opening_call_asks_for_the_stream_with_the_credential() -> None:
    assert follower(Clock()).call() == Call(
        HTTPMethod.GET,
        "/api/events",
        {"Accept": "text/event-stream", "X-Lemonfiber-Token": "abc"},
    )


def test_the_opening_call_resumes_from_the_last_event_id_carried() -> None:
    following = follower(Clock())
    following.heard(frame("status", {"a": 1}, "41") + frame("news", {"b": 2}))
    assert following.call().headers["Last-Event-ID"] == "41"


def test_what_arrives_is_live_and_held_as_live() -> None:
    following = follower(Clock())
    assert following.heard(frame("status", {"a": 1})) == [Live(STATUS)]
    assert following.held() == {"status": Live(STATUS)}


def test_a_break_names_how_long_it_was_quiet_and_cools_everything_held() -> None:
    clock = Clock()
    following = follower(clock)
    following.heard(frame("status", {"a": 1}))
    clock.now += 2
    following.heard(frame("news", {"b": 2}))
    clock.now += 3
    assert following.broke(Break.SILENT) == [Gap(Break.SILENT, 3.0), Stale(STATUS, 5.0), Stale(NEWS, 3.0)]
    clock.now += 1
    assert following.held() == {"status": Stale(STATUS, 6.0), "news": Stale(NEWS, 4.0)}


def test_a_value_carried_again_after_a_gap_is_live_again() -> None:
    following = follower(Clock())
    following.heard(frame("status", {"a": 1}))
    following.broke(Break.ENDED)
    following.heard(frame("status", {"a": 1}))
    assert following.held() == {"status": Live(STATUS)}


def test_an_opening_is_quiet_from_the_moment_it_opened() -> None:
    clock = Clock()
    following = follower(clock)
    clock.now += 10
    following.opened()
    clock.now += 1
    assert following.broke(Break.DROPPED) == [Gap(Break.DROPPED, 1.0)]


def test_a_follower_that_never_opened_is_quiet_from_the_moment_it_began() -> None:
    clock = Clock()
    following = follower(clock)
    clock.now += 2
    assert following.broke(Break.DROPPED) == [Gap(Break.DROPPED, 2.0)]


def test_a_kind_this_package_does_not_know_is_named_and_not_held() -> None:
    following = follower(Clock())
    assert following.heard(frame("later", {})) == [Unrecognised("later")]
    assert following.held() == {}


def test_each_failed_opening_doubles_the_wait_up_to_the_longest_and_then_the_stream_is_lost() -> None:
    following = follower(Clock(), reconnects=7, first_wait=4.0)
    assert [following.retry() for _ in range(7)] == [
        4.0,
        8.0,
        16.0,
        LONGEST_WAIT,
        LONGEST_WAIT,
        LONGEST_WAIT,
        LONGEST_WAIT,
    ]
    with pytest.raises(StreamLostError) as lost:
        following.retry()
    assert lost.value.attempts == 7


def test_anything_heard_starts_the_count_of_failures_again() -> None:
    following = follower(Clock(), reconnects=1)
    assert following.retry() == 1.0
    following.heard(b": heartbeat\n\n")
    assert following.retry() == 1.0


def test_a_follower_says_how_long_silence_may_last() -> None:
    assert follower(Clock(), silence=4.5).silence == 4.5
    assert Following(Credential("abc")).silence == SILENCE_ALLOWED

# Copyright (c) 2026 NightWorksIO
"""A read is asked again after a passing failure, within its wait; nothing else is."""

import socket
from typing import TYPE_CHECKING

import pytest

from lemonfiber import Address, Credential, FailedError, Read, UnreachableError
from lemonfiber._protocol import retry
from lemonfiber._protocol.calls import Answer
from tests.conftest import DECLARED_PAUSE, PRINTED, QUICK_PAUSE
from tests.drivers import connect
from tests.stack import Reply, envelope

if TYPE_CHECKING:
    from collections.abc import Callable

    from tests.drivers import Driver, Flavour
    from tests.stack import Stack

STATUS = envelope("status", {})
PASSING = Reply(503)


def test_the_pause_doubles_from_a_quarter_second_over_three_attempts() -> None:
    assert DECLARED_PAUSE == 0.25
    assert retry.ATTEMPTS == 3
    assert sorted(retry.PASSED_ON) == [502, 503, 504]


@pytest.mark.parametrize("status", [502, 503, 504])
def test_a_gateway_that_could_not_reach_lemonfiber_is_a_passing_failure(status: int) -> None:
    assert retry.is_passing(Answer(status, {}, b""))


@pytest.mark.parametrize("status", [200, 404, 500, 501, 505])
def test_lemonfibers_own_answer_is_not_a_passing_failure(status: int) -> None:
    assert not retry.is_passing(Answer(status, {}, b""))


def test_nothing_answering_is_a_passing_failure() -> None:
    assert retry.is_passing(None)


def test_a_read_is_asked_again_twice_after_passing_failures_waiting_twice_as_long_the_second_time() -> None:
    attempts = retry.Attempts(again=True, wait=10.0, started=100.0)
    assert attempts.pause(None, 100.0) == QUICK_PAUSE
    assert attempts.pause(Answer(503, {}, b""), 100.0) == QUICK_PAUSE * 2
    assert attempts.pause(None, 100.0) is None
    assert attempts.made == 3


def test_what_is_not_a_read_is_asked_once() -> None:
    attempts = retry.Attempts(again=False, wait=10.0, started=0.0)
    assert attempts.pause(None, 0.0) is None


def test_an_answer_of_lemonfibers_own_stands() -> None:
    attempts = retry.Attempts(again=True, wait=10.0, started=0.0)
    assert attempts.pause(Answer(500, {}, b""), 0.0) is None


def test_the_wait_left_is_what_the_attempts_have_not_spent() -> None:
    attempts = retry.Attempts(again=True, wait=10.0, started=100.0)
    assert attempts.left(103.0) == 7.0


def test_no_attempt_is_made_that_the_pause_before_it_would_leave_no_room_for(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(retry, "FIRST_PAUSE", 0.25)
    assert retry.Attempts(again=True, wait=1.0, started=0.0).pause(None, 0.75) is None
    assert retry.Attempts(again=True, wait=1.0, started=0.0).pause(None, 0.5) == 0.25


def test_a_read_that_met_passing_failures_is_answered_by_the_attempt_that_succeeds(
    client: Driver,
    stack: Stack,
) -> None:
    stack.reply("GET", "/api/status", PASSING, Reply(502), Reply(body=STATUS))
    assert client.read(Read.STATUS)["kind"] == "status"
    assert len(stack.arrived) == 3


def test_a_read_failing_every_time_is_asked_three_times_and_the_last_answer_read(
    client: Driver,
    stack: Stack,
) -> None:
    stack.reply("GET", "/api/status", PASSING, PASSING, Reply(504, "The gateway gave up."))
    with pytest.raises(FailedError, match=r"The gateway gave up\."):
        client.read(Read.STATUS)
    assert len(stack.arrived) == 3


ASKED_AGAIN: list[tuple[str, str, Callable[[Driver], object]]] = [
    ("GET", "/api/capabilities", lambda driver: driver.capabilities()),
    ("GET", "/api/logs", lambda driver: driver.logs()),
    ("GET", "/api/bundle/b", lambda driver: driver.bundle("b")),
    ("GET", "/api/jobs/j", lambda driver: driver.job("j")),
]


@pytest.mark.parametrize(("method", "path", "call"), ASKED_AGAIN, ids=[path for _, path, _ in ASKED_AGAIN])
def test_every_read_is_asked_again(
    client: Driver,
    stack: Stack,
    method: str,
    path: str,
    call: Callable[[Driver], object],
) -> None:
    stack.reply(method, path, PASSING)
    with pytest.raises(UnreachableError):
        call(client)
    assert len(stack.arrived) == 3


ASKED_ONCE: list[tuple[str, str, Callable[[Driver], object]]] = [
    ("POST", "/api/actions/restart", lambda driver: driver.act("restart")),
    ("DELETE", "/api/jobs/j", lambda driver: driver.release("j")),
]


@pytest.mark.parametrize(("method", "path", "call"), ASKED_ONCE, ids=[path for _, path, _ in ASKED_ONCE])
def test_what_changes_something_is_never_asked_again(
    client: Driver,
    stack: Stack,
    method: str,
    path: str,
    call: Callable[[Driver], object],
) -> None:
    stack.reply(method, path, PASSING)
    with pytest.raises(UnreachableError):
        call(client)
    assert len(stack.arrived) == 1


def test_a_read_nothing_answers_is_asked_again_and_then_unreachable(flavour: Flavour) -> None:
    with socket.socket() as held:
        held.bind(("127.0.0.1", 0))
        port = held.getsockname()[1]
    driver = connect(flavour, Address(f"http://127.0.0.1:{port}"), Credential(PRINTED))
    with pytest.raises(UnreachableError, match="not answering"):
        driver.read(Read.STATUS)
    driver.close()

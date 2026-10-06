# Copyright (c) 2026 NightWorksIO
"""What both clients do, asserted of each: reads, actions, jobs, refusals and the token's placement."""

import asyncio
import datetime
import socket
from typing import TYPE_CHECKING

import aiohttp
import pytest

from lemonfiber import (
    CREDENTIAL_HEADER,
    Address,
    ApiVersionMismatchError,
    AsyncClient,
    BusyError,
    Credential,
    DeclinedError,
    Ended,
    FailedError,
    Finished,
    MisaskedError,
    MissingError,
    NoSuchJobError,
    NotAdmittedError,
    PasswordRefusedError,
    Read,
    Running,
    StillRunningError,
    TooManyAttemptsError,
    UnreachableError,
    UnreadableResponseError,
    admit,
    expect,
    read_envelope,
)
from tests.conftest import PRINTED
from tests.drivers import admitted, connect
from tests.stack import Reply, envelope, problem

if TYPE_CHECKING:
    from tests.drivers import Driver, Flavour
    from tests.stack import Stack

STATUS = envelope("status", {"services": []})
STARTED = envelope("job", {"job": "j-1", "action": "repair"})


def test_a_read_asks_for_the_commands_document_carrying_the_token_in_its_header(
    client: Driver,
    stack: Stack,
) -> None:
    stack.reply("GET", "/api/status", Reply(body=STATUS))
    assert client.read(Read.STATUS) == STATUS
    [arrived] = stack.arrived
    assert arrived.method == "GET"
    assert arrived.url == "/api/status"
    assert arrived.headers[CREDENTIAL_HEADER] == PRINTED
    assert arrived.headers["Accept"] == "application/json"


def test_the_token_is_never_in_the_url(client: Driver, stack: Stack) -> None:
    stack.reply("GET", "/api/services", Reply(body=STATUS))
    client.read(Read.SERVICES, {"form": ["films", "series"]})
    [arrived] = stack.arrived
    assert PRINTED not in arrived.url


def test_a_query_names_each_value_once_and_leaves_out_what_is_not_given(client: Driver, stack: Stack) -> None:
    stack.reply("GET", "/api/held", Reply(body=envelope("held", {})))
    client.read(
        Read.HELD,
        {"form": ["a", "b"], "most": 3, "all": True, "none": False, "gone": None, "empty": []},
    )
    [arrived] = stack.arrived
    assert arrived.query == [("form", "a"), ("form", "b"), ("most", "3"), ("all", "true"), ("none", "false")]


def test_a_read_in_another_version_is_refused_naming_both(client: Driver, stack: Stack) -> None:
    stack.reply("GET", "/api/version", Reply(body=envelope("version", {}, version=2)))
    with pytest.raises(ApiVersionMismatchError) as refused:
        client.read(Read.VERSION)
    assert (refused.value.spoken, refused.value.served) == (1, 2)


def test_an_answer_that_is_not_an_envelope_is_refused(client: Driver, stack: Stack) -> None:
    stack.reply("GET", "/api/status", Reply(body="<html>a page</html>"))
    with pytest.raises(UnreadableResponseError):
        client.read(Read.STATUS)


@pytest.mark.parametrize(
    ("status", "kind"),
    [(400, MisaskedError), (404, MissingError), (409, BusyError), (500, FailedError), (503, FailedError)],
)
def test_a_refusal_is_read_by_its_status_carrying_its_code_and_sentence(
    client: Driver,
    stack: Stack,
    status: int,
    kind: type[Exception],
) -> None:
    stack.reply(
        "GET",
        "/api/explain",
        Reply(status, problem("READ-7", "No member by that name.", detail="d")),
    )
    with pytest.raises(kind) as refused:
        client.read(Read.EXPLAIN, {"word": "nothing"})
    assert str(refused.value) == "No member by that name."
    assert getattr(refused.value, "code", None) == "READ-7"
    assert getattr(refused.value, "status", None) == status
    problem_document = getattr(refused.value, "problem", None)
    assert isinstance(problem_document, dict)
    assert problem_document["detail"] == "d"


def test_a_refusal_in_prose_carries_the_sentence_and_no_code(client: Driver, stack: Stack) -> None:
    stack.reply("POST", "/api/actions/no-such", Reply(404, "lemonfiber offers no action called no-such."))
    with pytest.raises(MissingError) as refused:
        client.act("no-such")
    assert refused.value.sentence == "lemonfiber offers no action called no-such."
    assert refused.value.code is None
    assert refused.value.problem is None


def test_a_code_the_contract_does_not_list_reads_as_none(client: Driver, stack: Stack) -> None:
    stack.reply("GET", "/api/status", Reply(500, problem("NEW-99", "Something new went wrong.")))
    with pytest.raises(FailedError) as refused:
        client.read(Read.STATUS)
    assert refused.value.code is None
    assert refused.value.sentence == "Something new went wrong."


@pytest.mark.parametrize("status", [401, 403])
def test_the_credentials_own_refusal_is_not_admitted(client: Driver, stack: Stack, status: int) -> None:
    stack.reply("GET", "/api/status", Reply(status, problem("ADMIT-4", "Nothing this run admits.")))
    with pytest.raises(NotAdmittedError) as refused:
        client.read(Read.STATUS)
    assert refused.value.code == "ADMIT-4"
    assert refused.value.status == status
    assert refused.value.problem is not None
    assert refused.value.problem["summary"] == "Nothing this run admits."
    assert str(refused.value) == (
        "lemonfiber does not admit the credential this client holds. Use the token it printed, sign in again, "
        "or use a key the operator minted."
    )


def test_a_refusal_of_who_is_asking_is_declined_with_lemonfibers_sentence(
    client: Driver,
    stack: Stack,
) -> None:
    stack.reply("GET", "/api/status", Reply(403, problem("ADMIT-6", "That is not yours to ask for.")))
    with pytest.raises(DeclinedError) as refused:
        client.read(Read.STATUS)
    assert refused.value.code == "ADMIT-6"
    assert refused.value.status == 403
    assert refused.value.problem is not None
    assert refused.value.problem["code"] == "ADMIT-6"
    assert str(refused.value) == "That is not yours to ask for."


@pytest.mark.parametrize(
    "body",
    [problem("NEW-1", "Unknown."), "Forbidden", None, problem("ADMIT-6", " ")],
)
def test_a_turned_away_request_without_a_listed_code_and_sentence_is_read_by_its_status(
    client: Driver,
    stack: Stack,
    body: object,
) -> None:
    stack.reply("GET", "/api/status", Reply(403, body))
    with pytest.raises(NotAdmittedError):
        client.read(Read.STATUS)


def test_too_many_attempts_says_how_long_is_left(client: Driver, stack: Stack) -> None:
    stack.reply("GET", "/api/status", Reply(429, problem("ADMIT-9", "Wait."), {"Retry-After": "42"}))
    with pytest.raises(TooManyAttemptsError) as refused:
        client.read(Read.STATUS)
    assert refused.value.retry_after == 42
    assert refused.value.code == "ADMIT-9"
    assert refused.value.status == 429
    assert refused.value.problem is not None
    assert refused.value.problem["summary"] == "Wait."


@pytest.mark.parametrize("said", [{"Retry-After": "Wed, 21 Oct 2026 07:28:00 GMT"}, {}])
def test_too_many_attempts_without_a_count_says_nothing_of_how_long(
    client: Driver,
    stack: Stack,
    said: dict[str, str],
) -> None:
    stack.reply("GET", "/api/status", Reply(429, None, said))
    with pytest.raises(TooManyAttemptsError) as refused:
        client.read(Read.STATUS)
    assert refused.value.retry_after is None
    assert str(refused.value) == "Too many wrong answers lately; wait before trying again."


@pytest.mark.parametrize("body", ["<html>Bad Gateway</html>", None, envelope("status", {}), "[1]"])
def test_a_failure_without_a_sentence_did_not_come_from_lemonfiber(
    client: Driver,
    stack: Stack,
    body: object,
) -> None:
    stack.reply("GET", "/api/status", Reply(502, body))
    with pytest.raises(UnreachableError) as refused:
        client.read(Read.STATUS)
    assert str(refused.value) == "Something other than lemonfiber answered, with status 502."


def test_a_redirect_is_not_followed(client: Driver, stack: Stack) -> None:
    stack.reply("GET", "/api/status", Reply(302, None, {"Location": "/api/elsewhere"}))
    stack.reply("GET", "/api/elsewhere", Reply(body=STATUS))
    with pytest.raises(UnreachableError):
        client.read(Read.STATUS)
    assert [arrived.path for arrived in stack.arrived] == ["/api/status"]


def test_the_logs_are_an_envelope_a_line(client: Driver, stack: Stack) -> None:
    lines = '{"api_version":1,"kind":"log","data":{"line":"a"}}\n\n{"api_version":1,"kind":"log","data":{"line":"b"}}\n'
    stack.reply("GET", "/api/logs", Reply(body=lines))
    read = client.logs({"service": "sonarr", "lines": 2})
    assert [entry["data"] for entry in read] == [{"line": "a"}, {"line": "b"}]
    assert stack.arrived[0].query == [("service", "sonarr"), ("lines", "2")]


def test_the_logs_refused_are_a_refusal(client: Driver, stack: Stack) -> None:
    stack.reply("GET", "/api/logs", Reply(404, "No service by that name."))
    with pytest.raises(MissingError):
        client.logs()


def test_a_bundle_is_handed_over_as_the_bytes_it_is(client: Driver, stack: Stack) -> None:
    stack.reply("GET", "/api/bundle/support-1.tar.gz", Reply(body=b"\x1f\x8b archive"))
    bundle = client.bundle("support-1.tar.gz")
    assert (bundle.name, bundle.content, bundle.content_type) == (
        "support-1.tar.gz",
        b"\x1f\x8b archive",
        "application/octet-stream",
    )
    assert stack.arrived[0].headers["Accept"] == "*/*"


def test_a_bundle_name_is_one_path_segment(client: Driver, stack: Stack) -> None:
    stack.reply("GET", "/api/bundle/../etc", Reply(404, "No bundle by that name."))
    with pytest.raises(MissingError):
        client.bundle("../etc")
    assert stack.arrived[0].path == "/api/bundle/../etc"


def test_an_action_is_posted_once_with_its_arguments(client: Driver, stack: Stack) -> None:
    stack.reply("POST", "/api/actions/repair", Reply(202, STARTED))
    answered = client.act("repair", {"dry_run": True, "offer": "abc", "services": ["a"]})
    assert expect(answered, "job")["data"]["job"] == "j-1"
    [arrived] = stack.arrived
    assert arrived.body == b'{"dry_run": true, "offer": "abc", "services": ["a"]}'
    assert arrived.headers["Content-Type"] == "application/json"
    assert arrived.headers[CREDENTIAL_HEADER] == PRINTED


def test_an_action_with_no_arguments_sends_an_empty_object(client: Driver, stack: Stack) -> None:
    stack.reply("POST", "/api/actions/stop", Reply(body=envelope("lifecycle", {})))
    client.act("stop")
    assert stack.arrived[0].body == b"{}"


def test_a_failed_action_is_not_sent_again(client: Driver, stack: Stack) -> None:
    stack.reply("POST", "/api/actions/repair", Reply(503, "The engine is not running."))
    with pytest.raises(FailedError):
        client.act("repair")
    assert len(stack.arrived) == 1


def test_work_still_going_is_running(client: Driver, stack: Stack) -> None:
    stack.reply("GET", "/api/jobs/j-1", Reply(202, STARTED))
    assert client.job("j-1") == Running("j-1", expect(read_envelope(STARTED), "job"))


def test_work_that_finished_answers_with_the_commands_document(client: Driver, stack: Stack) -> None:
    repaired = envelope("repair", {"done": True})
    stack.reply("GET", "/api/jobs/j-1", Reply(200, repaired))
    assert client.job("j-1") == Finished("j-1", read_envelope(repaired))


def test_work_that_ended_before_it_finished_is_ended(client: Driver, stack: Stack) -> None:
    stack.reply("DELETE", "/api/jobs/j-1", Reply(200, STARTED))
    assert client.release("j-1") == Ended("j-1", expect(read_envelope(STARTED), "job"))
    assert stack.arrived[0].method == "DELETE"


def test_a_name_this_run_never_issued_is_no_such_job(client: Driver, stack: Stack) -> None:
    stack.reply("GET", "/api/jobs/j-9", Reply(404, "No job by that name."))
    with pytest.raises(NoSuchJobError) as refused:
        client.job("j-9")
    assert refused.value.job == "j-9"
    assert str(refused.value) == "lemonfiber has no work by the name 'j-9' in this run."


def test_work_that_stopped_on_a_failure_is_its_refusal(client: Driver, stack: Stack) -> None:
    stack.reply("GET", "/api/jobs/j-1", Reply(404, problem("REPAIR-1", "The offer no longer stands.")))
    with pytest.raises(MissingError) as refused:
        client.job("j-1")
    assert refused.value.code == "REPAIR-1"


def test_work_held_up_by_other_work_is_busy(client: Driver, stack: Stack) -> None:
    stack.reply(
        "GET",
        "/api/jobs/j-1",
        Reply(409, problem("LIFECYCLE-1", "Another operation holds the stack.")),
    )
    with pytest.raises(BusyError):
        client.job("j-1")


def test_following_work_asks_until_it_is_no_longer_going(client: Driver, stack: Stack) -> None:
    repaired = envelope("repair", {"done": True})
    stack.reply("GET", "/api/jobs/j-1", Reply(202, STARTED), Reply(202, STARTED), Reply(200, repaired))
    assert client.follow(expect(read_envelope(STARTED), "job"), every=0.01) == Finished(
        "j-1",
        read_envelope(repaired),
    )
    assert len(stack.arrived) == 3


def test_following_work_gives_up_once_the_caller_says(client: Driver, stack: Stack) -> None:
    stack.reply("GET", "/api/jobs/j-1", Reply(202, STARTED))
    with pytest.raises(StillRunningError) as refused:
        client.follow("j-1", every=0.01, within=0.05)
    assert refused.value.job == "j-1"
    assert refused.value.waited >= 0.05
    assert str(refused.value) == f"The work 'j-1' was still going after {refused.value.waited:g} seconds."


def test_following_work_already_ended_asks_once(client: Driver, stack: Stack) -> None:
    stack.reply("GET", "/api/jobs/j-1", Reply(200, STARTED))
    assert client.follow("j-1", every=10.0, within=0.0) == Ended("j-1", expect(read_envelope(STARTED), "job"))


@pytest.mark.parametrize("secret", ["session-secret-abc", "minted-for-home-assistant"])
def test_a_session_and_an_integration_key_travel_as_the_token_does(
    flavour: Flavour,
    stack: Stack,
    secret: str,
) -> None:
    stack.reply("GET", "/api/status", Reply(body=STATUS))
    driver = connect(flavour, Address(stack.url), Credential(secret))
    driver.read(Read.STATUS)
    driver.close()
    assert stack.arrived[0].headers[CREDENTIAL_HEADER] == secret
    assert secret not in stack.arrived[0].url


def test_nothing_answering_is_unreachable(flavour: Flavour) -> None:
    with socket.socket() as held:
        held.bind(("127.0.0.1", 0))
        port = held.getsockname()[1]
    driver = connect(flavour, Address(f"http://127.0.0.1:{port}"), Credential(PRINTED))
    with pytest.raises(UnreachableError) as refused:
        driver.read(Read.STATUS)
    assert str(refused.value) == "lemonfiber is not answering at that address. It may have been stopped."
    driver.close()


def test_an_answer_slower_than_the_timeout_is_unreachable(flavour: Flavour, stack: Stack) -> None:
    stack.reply("GET", "/api/status", Reply(body=STATUS, delay=0.4))
    driver = connect(flavour, Address(stack.url), Credential(PRINTED), timeout=0.1)
    with pytest.raises(UnreachableError):
        driver.read(Read.STATUS)
    driver.close()


def test_a_base_path_is_kept_in_front_of_every_path(flavour: Flavour, stack: Stack) -> None:
    stack.reply("GET", "/lemonfiber/api/status", Reply(body=STATUS))
    driver = connect(flavour, Address(f"{stack.url}/lemonfiber/"), Credential(PRINTED))
    assert driver.read(Read.STATUS) == STATUS
    driver.close()


ADMITTED = envelope("admission", {"token": "session-secret", "until": "2026-10-05T12:00:00Z"})


def test_a_password_is_exchanged_once_for_a_session(flavour: Flavour, stack: Stack) -> None:
    stack.reply("POST", "/api/session", Reply(body=ADMITTED))
    session = admitted(flavour, Address(stack.url), "hunter2")
    assert session.until == datetime.datetime(2026, 10, 5, 12, tzinfo=datetime.UTC)
    assert session.member is None
    [arrived] = stack.arrived
    assert arrived.body == b'{"password": "hunter2"}'
    assert CREDENTIAL_HEADER not in arrived.headers
    stack.reply("GET", "/api/status", Reply(body=STATUS))
    driver = connect(flavour, Address(stack.url), session.credential)
    driver.read(Read.STATUS)
    driver.close()
    assert stack.arrived[1].headers[CREDENTIAL_HEADER] == "session-secret"


def test_a_member_names_themself_at_the_door(flavour: Flavour, stack: Stack) -> None:
    member = envelope("admission", {"token": "s", "until": "2026-10-05T12:00:00.250", "member": "ana"})
    stack.reply("POST", "/api/session", Reply(body=member))
    session = admitted(flavour, Address(stack.url), "pw", "ana")
    assert session.member == "ana"
    assert session.until == datetime.datetime(2026, 10, 5, 12, 0, 0, 250000, tzinfo=datetime.UTC)
    assert stack.arrived[0].body == b'{"name": "ana", "password": "pw"}'


def test_a_wrong_password_is_refused_at_the_door(flavour: Flavour, stack: Stack) -> None:
    stack.reply("POST", "/api/session", Reply(401, problem("ADMIT-8", "That is not the password.")))
    address = Address(stack.url)
    with pytest.raises(PasswordRefusedError) as refused:
        admitted(flavour, address, "wrong")
    assert refused.value.code == "ADMIT-8"
    assert refused.value.status == 401
    assert refused.value.problem is not None
    assert refused.value.problem["code"] == "ADMIT-8"
    assert str(refused.value) == "That is not the password."


def test_a_wrong_password_said_in_nothing_is_still_refused(flavour: Flavour, stack: Stack) -> None:
    stack.reply("POST", "/api/session", Reply(401, None))
    address = Address(stack.url)
    with pytest.raises(PasswordRefusedError) as refused:
        admitted(flavour, address, "wrong")
    assert str(refused.value) == "That is not the password, or none is configured."


def test_too_many_wrong_passwords_say_how_long_is_left(flavour: Flavour, stack: Stack) -> None:
    stack.reply("POST", "/api/session", Reply(429, "Wait.", {"Retry-After": "30"}))
    address = Address(stack.url)
    with pytest.raises(TooManyAttemptsError) as refused:
        admitted(flavour, address, "wrong")
    assert refused.value.retry_after == 30


@pytest.mark.parametrize("until", ["tomorrow", "2026-10-05T12:00:00+02:00"])
def test_a_session_whose_ending_cannot_be_read_is_refused(flavour: Flavour, stack: Stack, until: str) -> None:
    stack.reply("POST", "/api/session", Reply(body=envelope("admission", {"token": "s", "until": until})))
    address = Address(stack.url)
    with pytest.raises(UnreadableResponseError) as refused:
        admitted(flavour, address, "pw")
    reason = "is not an instant" if until == "tomorrow" else "names an offset other than UTC"
    assert refused.value.what == f"{until!r} {reason}"


def test_a_session_with_an_offset_of_nothing_is_utc(flavour: Flavour, stack: Stack) -> None:
    stack.reply(
        "POST",
        "/api/session",
        Reply(body=envelope("admission", {"token": "s", "until": "2026-10-05T12:00:00+00:00"})),
    )
    assert admitted(flavour, Address(stack.url), "pw").until.tzinfo is datetime.UTC


def test_a_door_slower_than_the_timeout_is_unreachable(stack: Stack) -> None:
    stack.reply("POST", "/api/session", Reply(body=ADMITTED, delay=0.4))
    address = Address(stack.url)
    with pytest.raises(UnreachableError):
        admit(address, "pw", timeout=0.1)


def test_a_callers_session_that_raises_for_status_still_reads_the_refusal(stack: Stack) -> None:
    stack.reply("GET", "/api/status", Reply(404, "No such thing."))

    async def ask() -> None:
        session = aiohttp.ClientSession(raise_for_status=True)
        try:
            await AsyncClient(Address(stack.url), Credential(PRINTED), session=session).read(Read.STATUS)
        finally:
            await session.close()

    asking = ask()
    with pytest.raises(MissingError):
        asyncio.run(asking)

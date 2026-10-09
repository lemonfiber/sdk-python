# Copyright (c) 2026 NightWorksIO
"""What goes on the wire, exactly, what each answer is read as, and how the transports are built to carry it."""

import asyncio
import io
import json
from http import HTTPMethod, HTTPStatus

import aiohttp
import pytest
import urllib3
from aiohttp.base_protocol import BaseProtocol
from urllib3.connection import HTTPConnection

from lemonfiber import Address, Credential, Read, _aio, _sync
from lemonfiber._protocol import answers, calls, following, operation, refusals
from lemonfiber.address import Route
from lemonfiber.files import PICTURE_MOST
from lemonfiber.problems import MisaskedError, MissingError, StillRunningError, UnreadableResponseError
from lemonfiber.reads import HELD_ID_BACKDROP, HELD_ID_POSTER

JSON = {"Accept": "application/json"}
SENT = {"Accept": "application/json", "Content-Type": "application/json"}


@pytest.mark.parametrize(
    "query",
    [None, {}, {"id": None}, {"id": ["a", "b"]}, {"id": ""}, {"id": "."}, {"id": ".."}],
)
def test_a_segment_not_given_as_one_value_it_can_send_is_refused_before_anything_is_sent(
    query: calls.Query | None,
) -> None:
    with pytest.raises(MisaskedError, match="needs one `id` it can send") as refused:
        calls.read_call(Read.HELD_ID, query)
    assert refused.value.status == HTTPStatus.BAD_REQUEST


def test_each_call_is_the_request_it_names() -> None:
    assert calls.read_call(Read.STATUS, None) == calls.Call(HTTPMethod.GET, "/api/status", JSON)
    assert calls.read_call(Read.STATUS, {}) == calls.Call(HTTPMethod.GET, "/api/status", JSON)
    assert calls.read_call(Read.FRONT_DOOR, {"a": 1}) == calls.Call(
        HTTPMethod.GET,
        "/api/front-door?a=1",
        JSON,
    )
    assert calls.read_call(Read.HELD_ID, {"id": "a/b c", "member": "ada"}) == calls.Call(
        HTTPMethod.GET,
        "/api/held/a%2Fb%20c?member=ada",
        JSON,
    )
    assert calls.read_call(Read.HELD_ID, {"id": 7}) == calls.Call(HTTPMethod.GET, "/api/held/7", JSON)
    assert calls.capabilities_call() == calls.Call(HTTPMethod.GET, "/api/capabilities", JSON)
    assert calls.logs_call(["x"], [], None) == calls.Call(HTTPMethod.GET, "/api/logs?service=x", JSON)
    assert calls.bundle_call("a/b c") == calls.Call(
        HTTPMethod.GET,
        "/api/bundle/a%2Fb%20c",
        {"Accept": "*/*"},
    )
    assert calls.picture_call(HELD_ID_BACKDROP, "a/b c", {"member": "ada"}) == calls.Call(
        HTTPMethod.GET,
        "/api/held/a%2Fb%20c/backdrop?member=ada",
        {"Accept": "image/jpeg, image/png, image/webp, image/gif, image/avif"},
        most=PICTURE_MOST,
    )
    assert calls.action_call("re/pair", {"x": [1]}) == calls.Call(
        HTTPMethod.POST,
        "/api/actions/re%2Fpair",
        SENT,
        json.dumps({"x": [1]}).encode(),
    )
    assert calls.job_call("j/1", HTTPMethod.GET) == calls.Call(HTTPMethod.GET, "/api/jobs/j%2F1", JSON)
    assert calls.job_call("j", HTTPMethod.DELETE) == calls.Call(HTTPMethod.DELETE, "/api/jobs/j", JSON)
    assert calls.session_call("pw", None) == calls.Call(
        HTTPMethod.POST,
        "/api/session",
        SENT,
        b'{"password": "pw"}',
    )


def test_an_answer_is_handed_back_with_its_header_names_lower_cased() -> None:
    assert calls.received(503, {"Retry-After": "1", "content-type": "x"}, b"z") == calls.Answer(
        503,
        {"retry-after": "1", "content-type": "x"},
        b"z",
    )


def test_each_operation_pairs_its_call_with_the_reading_of_its_answer() -> None:
    assert operation.reading(Read.STATUS, None).call == calls.read_call(Read.STATUS, None)
    assert operation.capabilities().call == calls.capabilities_call()
    assert operation.logs(["x"], ["tv"], 3).call == calls.logs_call(["x"], ["tv"], 3)
    assert operation.bundle("b").call == calls.bundle_call("b")
    assert operation.picture(HELD_ID_POSTER, "t", {"member": "ada"}).call == calls.picture_call(
        HELD_ID_POSTER,
        "t",
        {"member": "ada"},
    )
    assert operation.action("restart", None).call == calls.action_call("restart", None)
    assert operation.job("j").call == calls.job_call("j", HTTPMethod.GET)
    assert operation.release("j").call == calls.job_call("j", HTTPMethod.DELETE)
    assert operation.admission("pw", "ada").call == calls.session_call("pw", "ada")
    handed = operation.bundle("b").read(calls.Answer(200, {"content-type": "x"}, b"z"))
    assert (handed.name, handed.content, handed.content_type) == ("b", b"z", "x")


@pytest.mark.parametrize(
    ("label", "read"),
    [("IMAGE/JPEG", "image/jpeg"), ("image/gif; q=1", "image/gif"), (" image/avif ;x=y", "image/avif")],
)
def test_a_picture_is_kept_by_its_label_in_any_case_and_without_its_parameters(label: str, read: str) -> None:
    assert answers.picture_of(calls.Answer(200, {"content-type": label}, b"z")).media_type == read


@pytest.mark.parametrize(
    ("length", "most", "over"),
    [("11", 10, True), ("10", 10, False), ("", 10, False), ("ten", 10, False), ("-11", 10, False)],
)
def test_an_answer_declares_more_than_it_may_be_only_by_a_whole_length_past_it(
    length: str,
    most: int,
    *,
    over: bool,
) -> None:
    assert calls.declared_over({"content-length": length}, most) is over
    assert calls.declared_over({}, most) is False


def sent(body: bytes, headers: dict[str, str] | None = None) -> urllib3.HTTPResponse:
    """Return an answer of `body` as urllib3 hands one over unread, over a connection from a pool."""
    pool = urllib3.HTTPConnectionPool("127.0.0.1")
    connection = HTTPConnection("127.0.0.1")
    return urllib3.HTTPResponse(
        body=io.BytesIO(body),
        headers=headers,
        preload_content=False,
        pool=pool,
        connection=connection,
    )


def test_a_capped_answer_that_declares_too_much_is_not_read_and_its_connection_is_closed() -> None:
    response = sent(b"x" * 20, {"content-length": "20"})
    assert _sync.capped(response, 10) == b""
    assert response.connection is not None
    assert response.closed


@pytest.mark.parametrize(
    ("body", "kept", "pooled"),
    [(b"x" * 10, b"x" * 10, True), (b"x" * 20, b"x" * 11, False)],
)
def test_a_capped_answer_is_read_one_byte_past_its_most_and_no_further(
    body: bytes,
    kept: bytes,
    *,
    pooled: bool,
) -> None:
    response = sent(body)
    assert _sync.capped(response, 10) == kept
    assert (response.connection is None) is pooled


async def fed(chunks: list[bytes], headers: dict[str, str], most: int) -> tuple[bytes, bytes]:
    """Return what `capped` keeps of a body arriving a chunk at a time, and what it left unread."""
    loop = asyncio.get_running_loop()
    connected = BaseProtocol(loop)
    connected.connection_made(asyncio.Transport())
    content = aiohttp.StreamReader(connected, 2**16, loop=loop)

    async def arriving() -> None:
        for chunk in chunks:
            content.feed_data(chunk)
            await asyncio.sleep(0)
        content.feed_eof()

    feeding = asyncio.create_task(arriving())
    kept = await _aio.capped(headers, content, most)
    await feeding
    return kept, await content.read()


@pytest.mark.parametrize(
    ("chunks", "kept", "left"),
    [
        ([b"a" * 5] * 4, b"a" * 11, b"a" * 9),
        ([b"a" * 4, b"a" * 6], b"a" * 10, b""),
        ([], b"", b""),
    ],
)
def test_a_body_streamed_is_kept_one_byte_past_its_most_and_no_further(
    chunks: list[bytes],
    kept: bytes,
    left: bytes,
) -> None:
    assert asyncio.run(fed(chunks, {}, 10)) == (kept, left)


def test_a_body_streamed_whose_headers_declare_too_much_is_not_read() -> None:
    assert asyncio.run(fed([b"a" * 5] * 4, {"content-length": "20"}, 10)) == (b"", b"a" * 20)


def test_a_picture_is_a_read_and_asked_again_after_a_passing_failure() -> None:
    assert operation.picture(HELD_ID_POSTER, "t", None).again is True


def test_a_picture_with_no_label_is_refused_as_one() -> None:
    unlabelled = calls.Answer(200, {}, b"z")
    with pytest.raises(UnreadableResponseError) as refused:
        answers.picture_of(unlabelled)
    assert refused.value.what.startswith(
        "the picture is labelled no type, and a picture is one of image/jpeg",
    )


def test_a_picture_refused_is_the_refusal_it_is() -> None:
    absent = calls.Answer(404, {"content-type": "text/plain"}, b"No such title.")
    with pytest.raises(MissingError):
        answers.picture_of(absent)


def test_the_credential_is_added_to_a_calls_headers_alone() -> None:
    call = calls.with_credential(calls.read_call(Read.STATUS, None), Credential("abc"))
    assert call == calls.Call(HTTPMethod.GET, "/api/status", {**JSON, "X-Lemonfiber-Token": "abc"})
    capped = calls.with_credential(calls.picture_call(HELD_ID_POSTER, "t", None), Credential("abc"))
    assert capped.most == PICTURE_MOST


def test_the_wait_between_asking_about_work_shortens_to_what_is_left_and_stops_at_the_limit() -> None:
    assert following.next_wait("j", 10.0, 11.0, 2.0, None) == 2.0
    assert following.next_wait("j", 10.0, 11.0, 2.0, 5.0) == 2.0
    assert following.next_wait("j", 10.0, 14.0, 2.0, 5.0) == 1.0
    with pytest.raises(StillRunningError) as refused:
        following.next_wait("j", 10.0, 15.0, 2.0, 5.0)
    assert refused.value.waited == 5.0


def test_a_refusal_whose_body_is_not_utf8_is_still_read() -> None:
    refused = refusals.refusal_of(calls.Answer(500, {}, b"broken \xff words"))
    assert str(refused) == "broken � words"


def test_an_error_envelope_whose_data_is_not_a_problem_carries_none() -> None:
    body = json.dumps({"api_version": 1, "kind": "error", "data": "words"}).encode()
    assert refusals.problem_in(body) is None
    assert isinstance(refusals.refusal_of(calls.Answer(500, {}, body)), _aio.UnreachableError)


@pytest.mark.parametrize(("said", "seconds"), [("12", 12), (" 7 ", 7), ("soon", None), ("", None)])
def test_retry_after_is_read_as_a_count_of_seconds(said: str, seconds: int | None) -> None:
    assert refusals.retry_after(calls.Answer(429, {"retry-after": said}, b"")) == seconds


def test_a_success_is_a_status_in_the_two_hundreds() -> None:
    assert [answers.succeeded(calls.Answer(status, {}, b"")) for status in (199, 200, 299, 300)] == [
        False,
        True,
        True,
        False,
    ]


def only_pool(address: Address) -> urllib3.HTTPConnectionPool:
    """Return the one pool an address with one route is reached through."""
    [(route, pool)] = _sync.ways_to(address)
    assert route == address.routes[0]
    return pool


def test_a_plain_address_is_reached_through_a_plain_pool() -> None:
    pool = only_pool(Address("http://127.0.0.1:8080"))
    assert type(pool) is urllib3.HTTPConnectionPool
    assert (pool.host, pool.port) == ("127.0.0.1", 8080)


def test_an_unpinned_https_address_is_held_to_the_trust_store() -> None:
    pool = only_pool(Address("https://127.0.0.1:8443"))
    assert isinstance(pool, urllib3.HTTPSConnectionPool)
    assert (pool.cert_reqs, pool.assert_fingerprint) == ("CERT_REQUIRED", None)
    assert (pool.assert_hostname, pool.conn_kw["server_hostname"]) == (None, None)


def test_a_pinned_address_is_held_to_its_pin_alone() -> None:
    pool = only_pool(Address("https://stack.lan:8443", pin="ab" * 32))
    assert isinstance(pool, urllib3.HTTPSConnectionPool)
    assert (pool.host, pool.cert_reqs, pool.assert_fingerprint) == ("stack.lan", "CERT_NONE", "ab" * 32)


def test_a_name_is_reached_at_each_address_it_resolved_to_and_asked_for_by_name() -> None:
    address = Address("https://localhost:8443/base", resolver=lambda _: ["::1", "127.0.0.1", "::1"])
    assert address.routes == (
        Route("::1", "https://[::1]:8443/base", "localhost", "localhost:8443"),
        Route("127.0.0.1", "https://127.0.0.1:8443/base", "localhost", "localhost:8443"),
    )
    assert address.routes[0].url("/api/status") == "https://[::1]:8443/base/api/status"
    assert address.routes[0].headers() == {"Host": "localhost:8443"}
    ways = _sync.ways_to(address)
    for (route, pool), host in zip(ways, ["::1", "127.0.0.1"], strict=True):
        assert isinstance(pool, urllib3.HTTPSConnectionPool)
        assert (route.host, pool.host, pool.assert_hostname, pool.conn_kw["server_hostname"]) == (
            host,
            host,
            "localhost",
            "localhost",
        )


def test_a_literal_or_pinned_address_is_its_own_one_route() -> None:
    assert Address("http://127.0.0.1:1/x").routes == (Route("127.0.0.1", "http://127.0.0.1:1/x"),)
    assert Address("http://127.0.0.1:1").routes[0].headers() == {}
    pinned = Address("https://stack.lan:8443", pin="ab" * 32)
    assert pinned.routes == (Route("stack.lan", "https://stack.lan:8443"),)


def test_each_address_is_checked_with_its_pin_a_verifying_context_or_nothing() -> None:
    pinned = _aio.tls_for(Address("https://stack.lan:8443", pin="ab" * 32))
    assert isinstance(pinned, aiohttp.Fingerprint)
    assert pinned.fingerprint == bytes.fromhex("ab" * 32)
    verifying = _aio.tls_for(Address("https://127.0.0.1:8443"))
    assert not isinstance(verifying, bool | aiohttp.Fingerprint)
    assert verifying.check_hostname
    assert _aio.tls_for(Address("http://127.0.0.1:8080")) is True

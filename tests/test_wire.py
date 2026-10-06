# Copyright (c) 2026 NightWorksIO
"""What goes on the wire, exactly, and how the transports are built to carry it."""

import json

import aiohttp
import pytest
import urllib3

from lemonfiber import Address, Credential, Read, _aio, _sync, _wire
from lemonfiber.address import Route
from lemonfiber.problems import StillRunningError

JSON = {"Accept": "application/json"}
SENT = {"Accept": "application/json", "Content-Type": "application/json"}


def test_each_call_is_the_request_it_names() -> None:
    assert _wire.read_call(Read.STATUS, None) == _wire.Call("GET", "/api/status", JSON)
    assert _wire.read_call(Read.STATUS, {}) == _wire.Call("GET", "/api/status", JSON)
    assert _wire.read_call(Read.FRONT_DOOR, {"a": 1}) == _wire.Call("GET", "/api/front-door?a=1", JSON)
    assert _wire.logs_call({"service": "x"}) == _wire.Call("GET", "/api/logs?service=x", JSON)
    assert _wire.bundle_call("a/b c") == _wire.Call("GET", "/api/bundle/a%2Fb%20c", {"Accept": "*/*"})
    assert _wire.action_call("re/pair", {"x": [1]}) == _wire.Call(
        "POST",
        "/api/actions/re%2Fpair",
        SENT,
        json.dumps({"x": [1]}).encode(),
    )
    assert _wire.job_call("j/1", "GET") == _wire.Call("GET", "/api/jobs/j%2F1", JSON)
    assert _wire.job_call("j", "DELETE") == _wire.Call("DELETE", "/api/jobs/j", JSON)
    assert _wire.session_call("pw", None) == _wire.Call("POST", "/api/session", SENT, b'{"password": "pw"}')


def test_the_credential_is_added_to_a_calls_headers_alone() -> None:
    call = _wire.with_credential(_wire.read_call(Read.STATUS, None), Credential("abc"))
    assert call == _wire.Call("GET", "/api/status", {**JSON, "X-Lemonfiber-Token": "abc"})


def test_the_wait_between_asking_about_work_shortens_to_what_is_left_and_stops_at_the_limit() -> None:
    assert _wire.next_wait("j", 10.0, 11.0, 2.0, None) == 2.0
    assert _wire.next_wait("j", 10.0, 11.0, 2.0, 5.0) == 2.0
    assert _wire.next_wait("j", 10.0, 14.0, 2.0, 5.0) == 1.0
    with pytest.raises(StillRunningError) as refused:
        _wire.next_wait("j", 10.0, 15.0, 2.0, 5.0)
    assert refused.value.waited == 5.0


def test_a_refusal_whose_body_is_not_utf8_is_still_read() -> None:
    refused = _wire.refusal_of(_wire.Answer(500, {}, b"broken \xff words"))
    assert str(refused) == "broken � words"


def test_an_error_envelope_whose_data_is_not_a_problem_carries_none() -> None:
    body = json.dumps({"api_version": 1, "kind": "error", "data": "words"}).encode()
    assert _wire.problem_in(body) is None
    assert isinstance(_wire.refusal_of(_wire.Answer(500, {}, body)), _aio.UnreachableError)


@pytest.mark.parametrize(("said", "seconds"), [("12", 12), (" 7 ", 7), ("soon", None), ("", None)])
def test_retry_after_is_read_as_a_count_of_seconds(said: str, seconds: int | None) -> None:
    assert _wire.retry_after(_wire.Answer(429, {"retry-after": said}, b"")) == seconds


def only_pool(address: Address) -> urllib3.HTTPConnectionPool:
    """Return the one pool an address with one route is reached through."""
    [(route, pool)] = _sync.ways_to(address, 3.0)
    assert route == address.routes[0]
    return pool


def test_a_plain_address_is_reached_through_a_plain_pool() -> None:
    pool = only_pool(Address("http://127.0.0.1:8080"))
    assert type(pool) is urllib3.HTTPConnectionPool
    assert (pool.host, pool.port, pool.timeout.total) == ("127.0.0.1", 8080, 3.0)


def test_an_unpinned_https_address_is_held_to_the_trust_store() -> None:
    pool = only_pool(Address("https://127.0.0.1:8443"))
    assert isinstance(pool, urllib3.HTTPSConnectionPool)
    assert (pool.cert_reqs, pool.assert_fingerprint, pool.timeout.total) == ("CERT_REQUIRED", None, 3.0)
    assert (pool.assert_hostname, pool.conn_kw["server_hostname"]) == (None, None)


def test_a_pinned_address_is_held_to_its_pin_alone() -> None:
    pool = only_pool(Address("https://stack.lan:8443", pin="ab" * 32))
    assert isinstance(pool, urllib3.HTTPSConnectionPool)
    assert (pool.host, pool.cert_reqs, pool.assert_fingerprint) == ("stack.lan", "CERT_NONE", "ab" * 32)
    assert pool.timeout.total == 3.0


def test_a_name_is_reached_at_each_address_it_resolved_to_and_asked_for_by_name() -> None:
    address = Address("https://localhost:8443/base", resolver=lambda _: ["::1", "127.0.0.1", "::1"])
    assert address.routes == (
        Route("::1", "https://[::1]:8443/base", "localhost", "localhost:8443"),
        Route("127.0.0.1", "https://127.0.0.1:8443/base", "localhost", "localhost:8443"),
    )
    assert address.routes[0].url("/api/status") == "https://[::1]:8443/base/api/status"
    assert address.routes[0].headers() == {"Host": "localhost:8443"}
    ways = _sync.ways_to(address, 3.0)
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

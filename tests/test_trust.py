# Copyright (c) 2026 NightWorksIO
"""Loopback, or an address a certificate pin vouches for; the credential in its header and nowhere else."""

import asyncio
import ipaddress
from typing import TYPE_CHECKING

import aiohttp
import pytest

from lemonfiber import (
    CREDENTIAL_HEADER,
    Address,
    AddressRefusedError,
    AsyncClient,
    CertificatePin,
    CertificateRefusedError,
    ConfigurationError,
    Credential,
    CredentialRefusedError,
    Read,
    SyncClient,
    admit_async,
)
from tests.conftest import PRINTED
from tests.drivers import admitted, connect, opened_session
from tests.stack import Reply, envelope

if TYPE_CHECKING:
    from lemonfiber.address import Resolver
    from tests.drivers import Flavour
    from tests.stack import Stack

STATUS = envelope("status", {"services": []})
OTHER_PIN = "0" * 64
OFF_THIS_MACHINE = (
    "{host} is not on this machine, and a stack anywhere else is reached only with its "
    "certificate pin, given with the address."
)
NEITHER = "lemonfiber is reached over http or https, and {url} names neither."
EXTRAS = "That address carries more than an address: a credential, a query or a fragment."
NOT_AN_ADDRESS = "{url} is not an address."
CERTIFICATE_REFUSED = "The stack's certificate is not the one pinned for it, or no trust store vouches for it, so nothing was sent."


def resolving(*addresses: str) -> Resolver:
    """Return a resolver answering every name with these addresses."""

    def answer(_host: str) -> list[str]:
        return list(addresses)

    return answer


@pytest.mark.parametrize(
    "url",
    ["http://127.0.0.1:8080", "http://127.9.8.7:1", "http://[::1]:8080", "http://[::ffff:127.0.0.1]:8080"],
)
def test_a_loopback_address_needs_no_pin(url: str) -> None:
    address = Address(url)
    assert address.pin is None
    assert address.scheme == "http"


def test_a_name_is_accepted_where_everything_it_resolves_to_is_loopback() -> None:
    address = Address("http://localhost:7000", resolver=lambda _: ["127.0.0.1", "::1"])
    assert (address.host, address.port, address.base) == ("localhost", 7000, "http://localhost:7000")


@pytest.mark.parametrize("found", [["127.0.0.1", "192.168.1.5"], [], ["not-an-address"]])
def test_a_name_resolving_off_loopback_or_to_nothing_is_refused_without_a_pin(found: list[str]) -> None:
    with pytest.raises(AddressRefusedError) as refused:
        Address("http://stack.lan:7000", resolver=lambda _: found)
    assert str(refused.value) == OFF_THIS_MACHINE.format(host="stack.lan")


@pytest.mark.parametrize(
    "url",
    ["http://192.168.1.10:8080", "https://10.0.0.2:8443", "http://[2001:db8::1]:80"],
)
def test_an_address_off_this_machine_is_refused_without_a_pin(url: str) -> None:
    with pytest.raises(AddressRefusedError) as refused:
        Address(url)
    host = url.split("//")[1].rsplit(":", 1)[0].strip("[]")
    assert str(refused.value) == OFF_THIS_MACHINE.format(host=host)


def test_an_address_anywhere_is_accepted_with_its_pin_and_never_resolved() -> None:
    def unasked(_host: str) -> list[str]:
        raise AssertionError

    address = Address("https://stack.lan:8443", pin=OTHER_PIN.upper(), resolver=unasked)
    assert address.pin == CertificatePin(OTHER_PIN)
    assert address.base == "https://stack.lan:8443"


def test_a_pin_is_checked_over_https_alone() -> None:
    with pytest.raises(AddressRefusedError) as refused:
        Address("http://stack.lan:8080", pin=OTHER_PIN)
    assert str(refused.value) == (
        "A pinned address is reached over https: a pin is checked against the certificate TLS presents."
    )


@pytest.mark.parametrize(
    "pin",
    ["", "abc", "g" * 64, "0" * 63, "l3ehbj5GiKLuq2UcJ7emYqINC4e/QvB6cHaSh/UDPQQ="],
)
def test_a_pin_that_is_not_a_certificate_digest_is_refused(pin: str) -> None:
    with pytest.raises(AddressRefusedError) as refused:
        CertificatePin(pin)
    assert str(refused.value) == (
        "A certificate pin is the SHA-256 digest of the stack's certificate, written as "
        "64 hexadecimal characters; what was given is not one."
    )


def test_a_pin_is_the_digest_it_names() -> None:
    pin = CertificatePin(f"  {'Ab' * 32} ")
    assert pin.hex == "ab" * 32
    assert pin.digest == bytes.fromhex("ab" * 32)
    assert repr(pin) == f"CertificatePin('{'ab' * 32}')"
    assert pin != "ab" * 32
    assert hash(pin) == hash(CertificatePin("ab" * 32))


@pytest.mark.parametrize(
    ("url", "said"),
    [
        ("ftp://127.0.0.1:21", NEITHER),
        ("127.0.0.1:8080", NEITHER),
        ("http://user:secret@127.0.0.1:8080", EXTRAS),
        ("http://user@127.0.0.1:8080", EXTRAS),
        ("http://127.0.0.1:8080/?token=x", EXTRAS),
        ("http://127.0.0.1:8080/#here", EXTRAS),
        ("http://:8080", NOT_AN_ADDRESS),
        ("http://127.0.0.1:99999", NOT_AN_ADDRESS),
        ("http://127.0.0.1:0", NOT_AN_ADDRESS),
    ],
)
def test_an_address_that_is_more_or_less_than_an_address_is_refused(url: str, said: str) -> None:
    with pytest.raises(AddressRefusedError) as refused:
        Address(url)
    assert str(refused.value) == said.format(url=repr(url))


def test_a_path_keeps_every_character_but_its_trailing_separators() -> None:
    assert Address("http://127.0.0.1:1/baseX//").prefix == "/baseX"


def test_an_address_names_its_port_and_keeps_its_path() -> None:
    address = Address("HTTPS://[::1]/base/", resolver=resolving())
    assert (address.scheme, address.host, address.port, address.prefix) == ("https", "::1", 443, "/base")
    assert address.url("/api/status") == "https://[::1]:443/base/api/status"
    assert repr(address) == "Address('https://[::1]:443/base', pin=None)"
    assert Address("http://127.0.0.1").port == 80


def test_the_system_resolver_finds_loopback_for_localhost() -> None:
    assert Address("http://localhost:8080").host == "localhost"


def test_the_system_resolver_finds_nothing_for_a_name_that_does_not_resolve() -> None:
    with pytest.raises(AddressRefusedError):
        Address("http://name.that.does.not.resolve.invalid:8080")


def test_an_address_resolves_without_blocking_the_event_loop() -> None:
    address = asyncio.run(Address.resolved("http://localhost:8080"))
    assert address.host == "localhost"
    with pytest.raises(AddressRefusedError):
        asyncio.run(Address.resolved("http://name.that.does.not.resolve.invalid:8080"))
    literal = asyncio.run(Address.resolved("http://127.0.0.1:1"))
    assert literal.port == 1
    pinned = asyncio.run(Address.resolved("https://stack.invalid:1", pin=OTHER_PIN))
    assert pinned.pin is not None


def test_a_literal_with_a_zone_is_read_as_its_address() -> None:
    assert ipaddress.ip_address("fe80::1")
    with pytest.raises(AddressRefusedError):
        Address("http://[fe80::1%25en0]:8080")


@pytest.mark.parametrize("secret", ["", "has space", "line\nbreak", "tab\t", "naïve"])
def test_a_credential_a_header_cannot_carry_is_refused(secret: str) -> None:
    with pytest.raises(CredentialRefusedError) as refused:
        Credential(secret)
    assert (
        str(refused.value)
        == "A credential is written in visible ASCII with no spaces; what was given is not one."
    )


def test_a_credential_shows_nothing_of_itself() -> None:
    credential = Credential(PRINTED)
    assert PRINTED not in repr(credential)
    assert PRINTED not in str(credential)
    assert credential.header() == {CREDENTIAL_HEADER: PRINTED}


def test_a_misconfiguration_is_a_value_error() -> None:
    assert issubclass(ConfigurationError, ValueError)


def test_the_pinned_certificate_is_reached(flavour: Flavour, tls_stack: Stack) -> None:
    tls_stack.reply("GET", "/api/status", Reply(body=STATUS))
    driver = connect(flavour, Address(tls_stack.url, pin=tls_stack.pin), Credential(PRINTED))
    assert driver.read(Read.STATUS) == STATUS
    driver.close()
    assert tls_stack.arrived[0].headers[CREDENTIAL_HEADER] == PRINTED


def test_another_certificate_is_refused_before_anything_is_sent(flavour: Flavour, tls_stack: Stack) -> None:
    tls_stack.reply("GET", "/api/status", Reply(body=STATUS))
    driver = connect(flavour, Address(tls_stack.url, pin=OTHER_PIN), Credential(PRINTED))
    with pytest.raises(CertificateRefusedError) as refused:
        driver.read(Read.STATUS)
    assert str(refused.value) == CERTIFICATE_REFUSED
    driver.close()
    assert tls_stack.arrived == []


def test_an_unpinned_certificate_no_trust_store_holds_is_refused(flavour: Flavour, tls_stack: Stack) -> None:
    tls_stack.reply("GET", "/api/status", Reply(body=STATUS))
    driver = connect(flavour, Address(tls_stack.url), Credential(PRINTED))
    with pytest.raises(CertificateRefusedError) as refused:
        driver.read(Read.STATUS)
    assert str(refused.value) == CERTIFICATE_REFUSED
    driver.close()
    assert tls_stack.arrived == []


def test_the_door_is_held_to_the_pin_too(flavour: Flavour, tls_stack: Stack) -> None:
    tls_stack.reply(
        "POST",
        "/api/session",
        Reply(body=envelope("admission", {"token": "s", "until": "2026-10-05T12:00:00"})),
    )
    with pytest.raises(CertificateRefusedError):
        admitted(flavour, Address(tls_stack.url, pin=OTHER_PIN), "hunter2")
    assert tls_stack.arrived == []
    assert admitted(flavour, Address(tls_stack.url, pin=tls_stack.pin), "hunter2").member is None


def test_a_callers_session_that_does_not_verify_still_holds_the_pin(tls_stack: Stack) -> None:
    tls_stack.reply("GET", "/api/status", Reply(body=STATUS))
    wrong = connect("async", Address(tls_stack.url, pin=OTHER_PIN), Credential(PRINTED), session=True)
    with pytest.raises(CertificateRefusedError):
        wrong.read(Read.STATUS)
    wrong.close()
    unpinned = connect("async", Address(tls_stack.url), Credential(PRINTED), session=True)
    with pytest.raises(CertificateRefusedError):
        unpinned.read(Read.STATUS)
    unpinned.close()
    assert tls_stack.arrived == []
    right = connect("async", Address(tls_stack.url, pin=tls_stack.pin), Credential(PRINTED), session=True)
    assert right.read(Read.STATUS) == STATUS
    right.close()


def test_a_callers_session_is_used_and_left_open(stack: Stack) -> None:
    stack.reply("GET", "/api/status", Reply(body=STATUS))

    async def use() -> bool:
        session = await opened_session()
        async with AsyncClient(Address(stack.url), Credential(PRINTED), session=session) as client:
            await client.read(Read.STATUS)
        still_open = not session.closed
        await session.close()
        await asyncio.sleep(0)
        return still_open

    assert asyncio.run(use())
    assert stack.arrived[0].headers["User-Agent"] == "the-caller"


def test_the_door_takes_a_callers_session(stack: Stack) -> None:
    stack.reply(
        "POST",
        "/api/session",
        Reply(body=envelope("admission", {"token": "s", "until": "2026-10-05T12:00:00"})),
    )

    async def knock() -> str | None:
        session = await opened_session()
        try:
            return (await admit_async(Address(stack.url), "pw", session=session)).member
        finally:
            await session.close()
            await asyncio.sleep(0)

    assert asyncio.run(knock()) is None
    assert stack.arrived[0].headers["User-Agent"] == "the-caller"


def test_a_session_that_cannot_check_a_pin_is_refused() -> None:
    async def build() -> None:
        session = aiohttp.ClientSession(connector=aiohttp.UnixConnector(path="/nonexistent"))
        try:
            AsyncClient(Address("http://127.0.0.1:1"), Credential(PRINTED), session=session)
        finally:
            await session.close()

    with pytest.raises(ConfigurationError) as refused:
        asyncio.run(build())
    assert (
        str(refused.value)
        == "A session given to the client connects over TCP, so the certificate pin can be checked."
    )


def test_a_client_it_opened_closes_its_session(stack: Stack) -> None:
    stack.reply("GET", "/api/status", Reply(body=STATUS))

    async def use() -> None:
        client = AsyncClient(Address(stack.url), Credential(PRINTED))
        await client.read(Read.STATUS)
        await client.read(Read.STATUS)
        await client.aclose()
        await client.aclose()

    asyncio.run(use())
    assert len(stack.arrived) == 2


def test_a_client_names_its_address(flavour: Flavour, stack: Stack) -> None:
    address = Address(stack.url)
    driver = connect(flavour, address, Credential(PRINTED))
    client = getattr(driver, "client", None)
    assert getattr(client, "address", None) is address
    driver.close()


def test_the_synchronous_client_closes_as_a_context(stack: Stack) -> None:
    stack.reply("GET", "/api/status", Reply(body=STATUS))
    with SyncClient(Address(stack.url), Credential(PRINTED)) as client:
        assert client.read(Read.STATUS) == STATUS


def test_a_name_resolved_off_the_event_loop_is_judged_by_what_the_loop_resolved(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def resolving_to_loopback(
        _loop: asyncio.AbstractEventLoop,
        host: str,
        _port: object,
        **_options: object,
    ) -> list[tuple[object, object, object, object, tuple[str, int]]]:
        assert host == "stack.test"
        return [(None, None, None, None, ("127.0.0.1", 0))]

    monkeypatch.setattr(asyncio.BaseEventLoop, "getaddrinfo", resolving_to_loopback)
    assert asyncio.run(Address.resolved("http://stack.test:8080")).host == "stack.test"


def test_the_door_on_a_callers_session_is_held_to_the_pin(tls_stack: Stack) -> None:
    tls_stack.reply(
        "POST",
        "/api/session",
        Reply(body=envelope("admission", {"token": "s", "until": "2026-10-05T12:00:00"})),
    )

    async def knock() -> str | None:
        session = await opened_session()
        try:
            return (
                await admit_async(Address(tls_stack.url, pin=tls_stack.pin), "pw", session=session)
            ).member
        finally:
            await session.close()

    assert asyncio.run(knock()) is None

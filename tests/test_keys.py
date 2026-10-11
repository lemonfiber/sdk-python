# Copyright (c) 2026 NightWorksIO
"""Integration keys kept through their own doors, and a key minted as a claim collected with its link."""

import asyncio
import datetime
import json
import urllib.parse
from typing import TYPE_CHECKING

import pytest

from lemonfiber import (
    CREDENTIAL_HEADER,
    CertificateRefusedError,
    ClaimLapsedError,
    ClaimRefusedError,
    FailedError,
    KeyLink,
    KeyLinkRefusedError,
    Minting,
    MisaskedError,
    TooManyAttemptsError,
    UnexpectedKindError,
    collect_async,
)
from lemonfiber._protocol import calls
from lemonfiber._protocol.answers import CLAIM_REFUSED
from lemonfiber._protocol.refusals import LAPSED
from tests.conftest import PRINTED
from tests.drivers import SETTLE, collected, opened_session
from tests.stack import Reply, envelope, problem

if TYPE_CHECKING:
    from tests.drivers import Driver, Flavour
    from tests.stack import Stack

OTHER_PIN = "0" * 64
A_PIN = "ab" * 32
LATER = 4102444800
"""2100-01-01, a lapse no test reaches."""
EARLIER = 946684800
"""2000-01-01, a lapse every test is past."""
CLAIM = "lfc_0123456789abcdefghijklmnopqrstuvwxyz"

GIVEN_AGAIN = "the operator's"
"""The minter's password, given again with a mint."""

MINTING = Minting(name="home", scope="read", purpose="home-assistant", password=GIVEN_AGAIN)
LISTING: dict[str, object] = {
    "keys": [],
    "purposes": "What each key is for is the minter's own word.",
    "rehearsed": False,
}
MINTED = {
    "name": "home",
    "scope": "read",
    "purpose": "home-assistant",
    "secret": "lfk_once",
    "pin": A_PIN,
    "address": "https://192.0.2.10:7777",
}
CLAIMED = {
    "name": "home",
    "scope": "read",
    "purpose": "home-assistant",
    "link": "lemonfiber://key?claim=withheld",
    "lapses": "2026-10-11T14:10:00",
}


def link(**given: str | int) -> str:
    """Return a key link as a claim's mint writes one, each parameter overridable."""
    said: dict[str, str | int] = {
        "address": "https://192.0.2.10:7777",
        "fingerprint": A_PIN,
        "stack": "stack-1f6a",
        "expires": LATER,
        "claim": CLAIM,
    } | given
    return "lemonfiber://key?" + urllib.parse.urlencode(said, quote_via=urllib.parse.quote)


def linking(stack: Stack, *, pin: str | None = None, expires: int = LATER) -> KeyLink:
    """Return a key link to a stand-in stack, held to its own pin unless another is given."""
    return KeyLink(link(address=stack.url, fingerprint=pin or stack.pin, expires=expires))


def test_a_key_link_is_read_as_a_claims_mint_writes_it() -> None:
    read = KeyLink(f"  {link()}\n")
    assert read.address.base == "https://192.0.2.10:7777"
    assert read.address.pin is not None
    assert read.address.pin.hex == A_PIN
    assert read.stack == "stack-1f6a"
    assert read.lapses == datetime.datetime(2100, 1, 1, tzinfo=datetime.UTC)
    assert read.claim == CLAIM
    assert not read.lapsed()


def test_a_key_link_never_shows_its_claim() -> None:
    shown = repr(KeyLink(link()))
    assert CLAIM not in shown
    assert (
        shown == "KeyLink('https://192.0.2.10:7777', stack='stack-1f6a', lapses='2100-01-01T00:00:00+00:00')"
    )


def test_a_key_link_past_its_lapse_has_lapsed() -> None:
    assert KeyLink(link(expires=EARLIER)).lapsed()


@pytest.mark.parametrize(
    ("written", "said"),
    [
        (link().replace("lemonfiber://key", "lemonfiber://pair"), "A key link begins with lemonfiber://key"),
        ("lemonfiber://key", "carries address, fingerprint, stack, expires, claim, each once"),
        ("lemonfiber://key?address", "carries address, fingerprint, stack, expires, claim, each once"),
        (link() + "&claim=again", "carries address, fingerprint, stack, expires, claim, each once"),
        (link() + "&more=1", "carries address, fingerprint, stack, expires, claim, each once"),
        (
            link().replace("&stack=stack-1f6a", ""),
            "carries address, fingerprint, stack, expires, claim, each once",
        ),
        (link(address="http://192.0.2.10:7777"), "A pinned address is reached over https"),
        (link(fingerprint="sha256:ab"), "A certificate pin is the SHA-256 digest"),
        (link(expires="soon"), "says when its claim lapses in whole seconds"),
        (link(stack=""), "names its stack and carries a claim"),
        (link(claim=""), "names its stack and carries a claim"),
        (link(claim="lfc_a b"), "names its stack and carries a claim"),
    ],
)
def test_a_link_that_is_not_a_key_link_is_refused_saying_why(written: str, said: str) -> None:
    with pytest.raises(KeyLinkRefusedError) as refused:
        KeyLink(written)
    assert said in str(refused.value)
    assert refused.value.__cause__ is None


def test_a_minting_never_shows_the_password() -> None:
    assert GIVEN_AGAIN not in repr(MINTING)


def test_the_keys_are_listed_from_their_own_door_with_the_credential(client: Driver, stack: Stack) -> None:
    stack.reply("GET", "/api/keys", Reply(503), Reply(body=envelope("keys", LISTING)))
    assert client.keys() == envelope("keys", LISTING)
    assert [one.method for one in stack.arrived] == ["GET", "GET"]
    assert stack.arrived[0].headers[CREDENTIAL_HEADER] == PRINTED


def test_a_key_is_minted_once_with_the_password_in_the_body(client: Driver, stack: Stack) -> None:
    stack.reply("POST", "/api/keys", Reply(body=envelope("minted-key", MINTED)))
    assert client.mint(MINTING) == envelope("minted-key", MINTED)
    assert json.loads(stack.arrived[0].body) == {
        "name": "home",
        "scope": "read",
        "purpose": "home-assistant",
        "password": GIVEN_AGAIN,
    }


def test_a_key_minted_as_a_claim_asks_for_one_and_is_answered_with_its_link(
    client: Driver,
    stack: Stack,
) -> None:
    stack.reply("POST", "/api/keys", Reply(body=envelope("key-claim", CLAIMED)))
    assert client.mint_claim(MINTING) == envelope("key-claim", CLAIMED)
    assert json.loads(stack.arrived[0].body)["claim"] is True


def test_a_mint_answered_as_another_kind_is_refused(client: Driver, stack: Stack) -> None:
    stack.reply("POST", "/api/keys", Reply(body=envelope("minted-key", MINTED)))
    with pytest.raises(UnexpectedKindError):
        client.mint_claim(MINTING)


def test_a_key_is_revoked_by_its_name_as_one_segment(client: Driver, stack: Stack) -> None:
    stack.reply("DELETE", "/api/keys/home/assistant", Reply(body=envelope("keys", LISTING)))
    assert client.revoke("home/assistant")["kind"] == "keys"
    assert calls.revoke_call("home/assistant").path == "/api/keys/home%2Fassistant"


@pytest.mark.parametrize("name", ["", ".", ".."])
def test_a_name_a_url_would_resolve_away_revokes_nothing(client: Driver, stack: Stack, name: str) -> None:
    with pytest.raises(MisaskedError):
        client.revoke(name)
    assert stack.arrived == []


@pytest.mark.parametrize(
    ("method", "path"),
    [("POST", "/api/keys"), ("DELETE", "/api/keys/home")],
)
def test_what_changes_the_keys_is_sent_once(client: Driver, stack: Stack, method: str, path: str) -> None:
    stack.reply(method, path, Reply(503, problem("FAIL-1", "Not now.")))
    calls = {
        "/api/keys": [lambda: client.mint(MINTING), lambda: client.mint_claim(MINTING)],
        "/api/keys/home": [lambda: client.revoke("home")],
    }[path]
    for call in calls:
        with pytest.raises(FailedError):
            call()
    assert len(stack.arrived) == len(calls)


def test_a_claim_collects_its_key_over_the_tls_its_link_pins_with_no_credential(
    flavour: Flavour,
    tls_stack: Stack,
) -> None:
    tls_stack.reply("POST", "/api/keys/claim", Reply(body=envelope("minted-key", MINTED)))
    assert collected(flavour, linking(tls_stack)) == MINTED
    arrived = tls_stack.arrived[0]
    assert json.loads(arrived.body) == {"claim": CLAIM}
    assert CREDENTIAL_HEADER not in arrived.headers


def test_a_claim_is_sent_nowhere_but_the_certificate_its_link_pins(
    flavour: Flavour,
    tls_stack: Stack,
) -> None:
    with pytest.raises(CertificateRefusedError):
        collected(flavour, linking(tls_stack, pin=OTHER_PIN))
    assert tls_stack.arrived == []


def test_a_lapsed_claim_is_not_sent(flavour: Flavour, tls_stack: Stack) -> None:
    with pytest.raises(ClaimLapsedError) as refused:
        collected(flavour, linking(tls_stack, expires=EARLIER))
    assert str(refused.value) == LAPSED
    assert tls_stack.arrived == []


def test_a_claim_turned_away_says_so_in_the_stacks_words(flavour: Flavour, tls_stack: Stack) -> None:
    tls_stack.reply("POST", "/api/keys/claim", Reply(401, problem("KEY-12", "That claim collects no key.")))
    with pytest.raises(ClaimRefusedError) as refused:
        collected(flavour, linking(tls_stack))
    assert (refused.value.sentence, refused.value.status) == ("That claim collects no key.", 401)
    assert refused.value.problem is not None


def test_a_claim_turned_away_with_nothing_readable_says_why_in_its_own_words(
    flavour: Flavour,
    tls_stack: Stack,
) -> None:
    tls_stack.reply("POST", "/api/keys/claim", Reply(401))
    with pytest.raises(ClaimRefusedError) as refused:
        collected(flavour, linking(tls_stack))
    assert refused.value.sentence == CLAIM_REFUSED


def test_any_other_refusal_of_a_claim_is_read_as_every_refusal_is(flavour: Flavour, tls_stack: Stack) -> None:
    tls_stack.reply(
        "POST",
        "/api/keys/claim",
        Reply(429, problem("RATE-1", "Wait a while."), headers={"Retry-After": "30"}),
    )
    with pytest.raises(TooManyAttemptsError) as refused:
        collected(flavour, linking(tls_stack))
    assert refused.value.retry_after == 30


def test_a_claim_is_collected_on_a_callers_session_held_to_the_link_all_the_same(tls_stack: Stack) -> None:
    tls_stack.reply("POST", "/api/keys/claim", Reply(body=envelope("minted-key", MINTED)))

    async def collecting(pin: str) -> object:
        session = await opened_session(verifying=False)
        try:
            return await collect_async(linking(tls_stack, pin=pin), session=session)
        finally:
            await session.close()
            await asyncio.sleep(SETTLE)

    with pytest.raises(CertificateRefusedError):
        asyncio.run(collecting(OTHER_PIN))
    assert asyncio.run(collecting(tls_stack.pin)) == MINTED

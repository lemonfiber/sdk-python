# Copyright (c) 2026 NightWorksIO
"""Device keys kept through their own doors, and a mint proved by one in place of the password."""

import base64
import json
from http import HTTPMethod
from typing import TYPE_CHECKING

import pytest
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec

from lemonfiber import (
    AndroidAttestation,
    ConfigurationError,
    DeviceProof,
    IosAttestation,
    Minting,
    MisaskedError,
    Registering,
    UnexpectedKindError,
    signed_text,
)
from lemonfiber._protocol import calls, operation
from tests.stack import Reply, envelope

if TYPE_CHECKING:
    from tests.drivers import Driver
    from tests.stack import Stack

ANSWERED = {"Accept": "application/json"}
GIVEN_AGAIN = "the operator's"
CHALLENGE = "a-challenge"
REGISTERED = {
    "name": "pixel",
    "fingerprint": "ab" * 32,
    "backing": "strongbox",
    "registered": "2026-10-13T00:00:00Z",
}
LISTED: dict[str, object] = {"keys": [], "rehearsed": False}


def unpadded(raw: bytes) -> str:
    """Return bytes in base64url, unpadded, as the stack reads them."""
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def test_a_device_key_is_registered_with_its_public_half_and_attestation_in_base64url(
    client: Driver,
    stack: Stack,
) -> None:
    stack.reply("POST", "/api/device-keys", Reply(body=envelope("device-key", REGISTERED)))
    registering = Registering(
        "pixel",
        b"\x30\xff\xfe",
        AndroidAttestation((b"\xfb\xff", b"\x01")),
        GIVEN_AGAIN,
    )
    assert client.register_device_key(registering) == envelope("device-key", REGISTERED)
    assert json.loads(stack.arrived[0].body) == {
        "name": "pixel",
        "public_key": "MP_-",
        "attestation": {"platform": "android", "chain": ["-_8", "AQ"]},
        "password": GIVEN_AGAIN,
    }


def test_an_ios_attestation_is_sent_as_its_object() -> None:
    assert IosAttestation(b"\xa3\x63").fields() == {"platform": "ios", "object": "o2M"}


def test_a_registration_never_shows_its_password_or_key() -> None:
    shown = repr(Registering("pixel", b"secret-key", IosAttestation(b"object"), GIVEN_AGAIN))
    assert GIVEN_AGAIN not in shown
    assert "secret-key" not in shown


def test_device_keys_are_listed_challenged_and_revoked_by_name(client: Driver, stack: Stack) -> None:
    stack.reply("GET", "/api/device-keys", Reply(body=envelope("device-keys", LISTED)))
    stack.reply("POST", "/api/device-keys/pixel/8/challenge", Reply(body=envelope("device-challenge", {})))
    stack.reply("DELETE", "/api/device-keys/pixel 8", Reply(body=envelope("device-keys", LISTED)))
    assert client.device_keys() == envelope("device-keys", LISTED)
    assert client.device_key_challenge("pixel/8") == envelope("device-challenge", {})
    assert client.revoke_device_key("pixel 8") == envelope("device-keys", LISTED)


def test_a_device_key_answered_as_another_kind_is_refused(client: Driver, stack: Stack) -> None:
    stack.reply("DELETE", "/api/device-keys/pixel", Reply(body=envelope("keys", LISTED)))
    with pytest.raises(UnexpectedKindError):
        client.revoke_device_key("pixel")


def test_each_device_key_door_is_asked_as_the_core_serves_it() -> None:
    assert calls.device_keys_call() == calls.Call(HTTPMethod.GET, "/api/device-keys", ANSWERED)
    assert calls.device_key_call("pixel", challenge=False) == calls.Call(
        HTTPMethod.DELETE,
        "/api/device-keys/pixel",
        ANSWERED,
    )
    assert operation.device_keys().again
    assert not operation.device_key_challenge("pixel").again
    assert not operation.revoke_device_key("pixel").again
    with pytest.raises(MisaskedError):
        calls.device_key_call("..", challenge=True)


def test_a_mint_is_proved_by_a_signature_over_the_text_the_stack_verifies(
    client: Driver,
    stack: Stack,
) -> None:
    phone = ec.generate_private_key(ec.SECP256R1())
    text = signed_text("den", "act", "mcp", CHALLENGE, claim=True)
    proof = DeviceProof("pixel", CHALLENGE, phone.sign(text, ec.ECDSA(hashes.SHA256())))
    stack.reply("POST", "/api/keys", Reply(body=envelope("key-claim", {})))
    client.mint_claim(Minting("den", "act", "mcp", device=proof))
    sent = json.loads(stack.arrived[0].body)
    assert text == b"lemonfiber-mint/1\na-challenge\nden\nact\nmcp\nclaim\n"
    assert "password" not in sent
    assert sent["device"] == "pixel"
    assert sent["challenge"] == CHALLENGE
    assert sent["claim"] is True
    assert sent["signature"] == unpadded(proof.signature)
    phone.public_key().verify(
        base64.urlsafe_b64decode(sent["signature"] + "=" * (-len(sent["signature"]) % 4)),
        text,
        ec.ECDSA(hashes.SHA256()),
    )


def test_a_mint_is_proved_by_exactly_one_of_the_password_and_a_device_key() -> None:
    proof = DeviceProof("pixel", CHALLENGE, b"sig")
    with pytest.raises(ConfigurationError):
        Minting("den", "read", "other")
    with pytest.raises(ConfigurationError):
        Minting("den", "read", "other", password=GIVEN_AGAIN, device=proof)
    shown = repr(Minting("den", "read", "other", device=proof))
    assert CHALLENGE not in shown


@pytest.mark.parametrize(("name", "challenge"), [("den\nread", CHALLENGE), ("den", "c\nden")])
def test_a_part_holding_a_line_feed_is_refused_rather_than_signed(name: str, challenge: str) -> None:
    with pytest.raises(ConfigurationError):
        signed_text(name, "read", "other", challenge)


def test_a_key_mint_signs_key_as_its_last_line() -> None:
    assert signed_text("den", "read", "other", "c") == (b"lemonfiber-mint/1\nc\nden\nread\nother\nkey\n")

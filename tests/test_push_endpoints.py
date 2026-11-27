# Copyright (c) 2026 NightWorksIO
"""The phones that asked to be woken, kept through their own doors."""

import json
import pathlib
from http import HTTPMethod, HTTPStatus
from typing import TYPE_CHECKING

import pytest

from lemonfiber import MisaskedError, PushEndpointRegistering, UnexpectedKindError
from lemonfiber._protocol import calls, operation
from tests.stack import Reply

if TYPE_CHECKING:
    from tests.drivers import Driver
    from tests.stack import Stack

ANSWERED = {"Accept": "application/json"}
EXAMPLES = pathlib.Path(__file__).parent.parent / "contract" / "web-api" / "examples" / "kinds"
ADDRESS = "https://push.example/send/a-phone"


def example(kind: str) -> dict[str, object]:
    """Return the contract's example envelope of `kind`."""
    return json.loads((EXAMPLES / f"{kind}.json").read_text(encoding="utf-8"))


def test_a_push_endpoint_is_registered_with_its_key_and_secret_in_base64url(
    client: Driver,
    stack: Stack,
) -> None:
    stack.reply("POST", "/api/push-endpoints", Reply(body=example("push-endpoint")))
    registering = PushEndpointRegistering("a-phone", ADDRESS, b"\x04\xfb\xff", b"\x01")
    assert client.register_push_endpoint(registering) == example("push-endpoint")
    assert json.loads(stack.arrived[0].body) == {
        "name": "a-phone",
        "endpoint": ADDRESS,
        "p256dh": "BPv_",
        "auth": "AQ",
    }


def test_a_registration_never_shows_its_address_key_or_secret() -> None:
    shown = repr(PushEndpointRegistering("a-phone", ADDRESS, b"the-key", b"the-secret"))
    assert "a-phone" in shown
    for withheld in (ADDRESS, "the-key", "the-secret"):
        assert withheld not in shown


def test_push_endpoints_are_listed_and_removed_by_name_as_the_contract_example_says(
    client: Driver,
    stack: Stack,
) -> None:
    stack.reply("GET", "/api/push-endpoints", Reply(body=example("push-endpoints")))
    stack.reply("DELETE", "/api/push-endpoints/a phone", Reply(body=example("push-endpoints")))
    listed = client.push_endpoints()
    assert listed == example("push-endpoints")
    assert listed["data"]["endpoints"][0]["endpoint"] == ADDRESS
    assert client.remove_push_endpoint("a phone") == example("push-endpoints")


def test_a_push_endpoint_answered_as_another_kind_is_refused(client: Driver, stack: Stack) -> None:
    stack.reply("GET", "/api/push-endpoints", Reply(body=example("push-endpoint")))
    with pytest.raises(UnexpectedKindError):
        client.push_endpoints()


def test_each_push_endpoint_door_is_asked_as_the_core_serves_it() -> None:
    assert calls.push_endpoints_call() == calls.Call(HTTPMethod.GET, "/api/push-endpoints", ANSWERED)
    assert operation.remove_push_endpoint("a/phone").call == calls.Call(
        HTTPMethod.DELETE,
        "/api/push-endpoints/a%2Fphone",
        ANSWERED,
    )
    assert operation.push_endpoints().again
    assert not operation.remove_push_endpoint("a-phone").again
    registering = PushEndpointRegistering("a-phone", ADDRESS, b"", b"")
    assert not operation.register_push_endpoint(registering).again


def test_a_push_endpoint_name_a_url_would_resolve_away_is_refused_before_sending() -> None:
    with pytest.raises(MisaskedError) as refused:
        calls.remove_push_endpoint_call("..")
    assert (refused.value.sentence, refused.value.status) == (
        "A push endpoint is named by its name, and what was given is not a name that can be sent.",
        HTTPStatus.BAD_REQUEST,
    )

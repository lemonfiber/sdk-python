# Copyright (c) 2026 NightWorksIO
"""Every call this client makes is a route the contract lists, at the method it lists it at."""

import inspect
import urllib.parse
from http import HTTPMethod
from typing import TYPE_CHECKING

from lemonfiber import AndroidAttestation, DeviceProof, Minting, PushEndpointRegistering, Registering
from lemonfiber._generated import READS, ROUTES, RestartAction
from lemonfiber._protocol import calls
from lemonfiber.reads import (
    ASKABLE_ID_POSTER,
    EVENTS,
    HELD_ID_BACKDROP,
    HELD_ID_POSTER,
    REQUESTS_REFERENCE_POSTER,
)

if TYPE_CHECKING:
    from collections.abc import Callable

    from lemonfiber._protocol.calls import Call

PROOF = DeviceProof("pixel", "challenge", b"signature")
"""A device key's proof, standing in for a password."""

BUILT: dict[str, Callable[[], list[Call]]] = {
    "read_call": lambda: [calls.read_call(read, dict.fromkeys(READS[read].segments, "a1")) for read in READS],
    "capabilities_call": lambda: [calls.capabilities_call()],
    "logs_call": lambda: [calls.logs_call(["sonarr"], [], None)],
    "bundle_call": lambda: [calls.bundle_call("lemonfiber-bundle.tar.gz")],
    "picture_call": lambda: [
        calls.picture_call(path, name, "a1", None)
        for path, name in (
            (HELD_ID_POSTER, "id"),
            (HELD_ID_BACKDROP, "id"),
            (ASKABLE_ID_POSTER, "id"),
            (REQUESTS_REFERENCE_POSTER, "reference"),
        )
    ],
    "action_call": lambda: [calls.action_call("restart", {}), calls.action_call(RestartAction(), None)],
    "job_call": lambda: [calls.job_call("a1b2", HTTPMethod.GET), calls.job_call("a1b2", HTTPMethod.DELETE)],
    "forget_call": lambda: [calls.forget_call("a1b2")],
    "session_call": lambda: [calls.session_call("password", None)],
    "keys_call": lambda: [calls.keys_call()],
    "mint_call": lambda: [
        calls.mint_call(Minting("ha", "read", "home-assistant", "password")),
        calls.mint_call(Minting("ha", "read", "home-assistant", device=PROOF)),
    ],
    "register_device_key_call": lambda: [
        calls.register_device_key_call(
            Registering("pixel", b"key", AndroidAttestation((b"leaf",)), "password"),
        ),
    ],
    "device_keys_call": lambda: [calls.device_keys_call()],
    "device_key_challenge_call": lambda: [calls.device_key_challenge_call("pixel")],
    "revoke_device_key_call": lambda: [calls.revoke_device_key_call("pixel")],
    "register_push_endpoint_call": lambda: [
        calls.register_push_endpoint_call(
            PushEndpointRegistering("pixel", "https://push.example/a", b"k", b"a"),
        ),
    ],
    "push_endpoints_call": lambda: [calls.push_endpoints_call()],
    "remove_push_endpoint_call": lambda: [calls.remove_push_endpoint_call("pixel")],
    "revoke_call": lambda: [calls.revoke_call("ha")],
    "collect_call": lambda: [calls.collect_call("claim")],
}
"""Each way `calls` builds a request, with every call it builds asked of it."""


def routed(method: HTTPMethod, path: str) -> bool:
    """Return whether the contract lists a route at `method` whose path `path` fills, one segment for each `{name}`."""
    asked = urllib.parse.urlsplit(path).path.split("/")
    return any(
        route.method == method
        and len(listed := route.path.split("/")) == len(asked)
        and all(part == given or part.startswith("{") for part, given in zip(listed, asked, strict=True))
        for route in ROUTES
    )


def test_every_way_a_call_is_built_is_asked_here() -> None:
    building = {name for name, _ in inspect.getmembers(calls, inspect.isfunction) if name.endswith("_call")}
    assert building == set(BUILT)


def test_every_call_this_client_builds_is_a_route_the_contract_lists() -> None:
    built = [call for build in BUILT.values() for call in build()]
    assert len(built) > len(BUILT)
    unlisted = [f"{call.method} {call.path}" for call in built if not routed(call.method, call.path)]
    assert unlisted == []


def test_the_stream_is_a_route_the_contract_lists() -> None:
    assert routed(HTTPMethod.GET, EVENTS)


def test_a_route_the_contract_does_not_list_is_told_apart() -> None:
    assert not routed(HTTPMethod.POST, "/api/keys/ha")
    assert not routed(HTTPMethod.DELETE, "/api/keys")
    assert not routed(HTTPMethod.GET, "/api/keys/ha/more")
    assert routed(HTTPMethod.DELETE, "/api/keys/ha")

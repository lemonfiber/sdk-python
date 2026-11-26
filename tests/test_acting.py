# Copyright (c) 2026 NightWorksIO
"""Acting through a request the contract types, and by a name read at run time."""

import json
from http import HTTPStatus
from typing import TYPE_CHECKING

import pytest

from lemonfiber import ACTIONS, KEY_CALLABLE, ActionRequest, MisaskedError, is_action_name
from lemonfiber._protocol import calls
from lemonfiber.contract import PlayAction, RestartAction
from tests.stack import Reply, envelope

if TYPE_CHECKING:
    from collections.abc import Mapping

    from lemonfiber import Json
    from tests.drivers import Driver
    from tests.stack import Stack

LIFECYCLE = envelope("lifecycle", {})

HANDED_BACK = "p-1"
"""What a browser hands back for a new one around the same session."""


def test_a_request_is_posted_once_with_every_argument_it_holds(client: Driver, stack: Stack) -> None:
    stack.reply("POST", "/api/actions/restart", Reply(body=LIFECYCLE))
    client.request(RestartAction(services=["sonarr"], dry_run=True))
    [arrived] = stack.arrived
    assert json.loads(arrived.body) == {"forms": [], "services": ["sonarr"], "offer": None, "dry_run": True}
    assert arrived.headers["Content-Type"] == "application/json"


def test_an_argument_python_reserves_the_name_of_is_posted_under_the_contracts_name(
    client: Driver,
    stack: Stack,
) -> None:
    stack.reply("POST", "/api/actions/play", Reply(body=LIFECYCLE))
    client.request(PlayAction(pass_=HANDED_BACK))
    assert json.loads(stack.arrived[0].body) == {
        "device": None,
        "id": None,
        "pass": HANDED_BACK,
        "dry_run": False,
    }


def test_a_request_is_typed_by_the_action_it_names() -> None:
    request = RestartAction()
    assert isinstance(request, ActionRequest)
    assert request.ACTION == "restart"
    assert ACTIONS[request.ACTION].consent == ("offer",)
    assert RestartAction().forms is not request.forms


def test_a_request_handed_arguments_beside_its_own_is_refused_before_anything_is_sent() -> None:
    with pytest.raises(MisaskedError) as refused:
        calls.action_call(RestartAction(), {"offer": "o-1"})
    assert (
        refused.value.sentence
        == "An action's request carries its own arguments, and was given more beside it."
    )
    assert refused.value.status == HTTPStatus.BAD_REQUEST


@pytest.mark.parametrize("named", ["downloads-pause"])
def test_an_action_named_at_run_time_is_narrowed_and_posted_by_its_name(
    client: Driver,
    stack: Stack,
    named: str,
) -> None:
    stack.reply("POST", "/api/actions/downloads-pause", Reply(body=LIFECYCLE))
    arguments: Mapping[str, Json] = {"offer": "o-1", "dry_run": True}
    assert is_action_name(named)
    client.act(named, arguments)
    assert json.loads(stack.arrived[0].body) == {"offer": "o-1", "dry_run": True}


def test_every_action_a_key_may_call_is_one_act_takes_by_name() -> None:
    assert all(is_action_name(action) for action in KEY_CALLABLE)

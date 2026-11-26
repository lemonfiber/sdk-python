# Copyright (c) 2026 NightWorksIO
"""A moved setting says what it falls back to, and an invitation what it holds their asking to."""

import json
import pathlib
import typing

import pytest

from lemonfiber._generated.kinds import invitation, settings
from lemonfiber._generated.shared import policy
from lemonfiber.envelope import expect, parse_envelope
from tests.generating import keys

DEFS = pathlib.Path(__file__).parent.parent / "contract" / "web-api" / "defs"


def definition(name: str) -> dict[str, typing.Any]:
    """Return a vendored definition as the contract writes it."""
    return json.loads((DEFS / f"{name}.json").read_text(encoding="utf-8"))


def tags(alias: typing.TypeAliasType) -> list[str]:
    """Return the `of` each branch of a generated tagged union is typed by, in its order."""
    return [
        typing.get_args(typing.get_type_hints(branch)["of"])[0] for branch in typing.get_args(alias.__value__)
    ]


def said(fallback: settings.SettingDefault) -> str | list[str]:
    """Return what a moved setting falls back to, by what it is of."""
    match fallback["of"]:
        case "core" | "declared":
            return f"{fallback['of']}: {fallback['value']}"
        case "per-reader":
            return [
                f"{reader['service']} {'met' if reader['met'] else 'unmet'}: "
                f"{reader.get('default') or 'declares none'}"
                for reader in fallback["readers"]
            ]
        case "none":
            return "none"


SETTINGS_CHANGE: dict[str, object] = {
    "api_version": 1,
    "kind": "settings",
    "data": {
        "rehearsed": False,
        "secrets": [],
        "settings": [],
        "waiting": [],
        "change": {
            "agreement": "b3f1",
            "applied": True,
            "regenerates": [],
            "restarts": ["sonarr"],
            "starts": [],
            "waiting": [],
            "settings": [
                {
                    "setting": "LEMONFIBER_BACKUP_LIMIT",
                    "value": "4",
                    "was": None,
                    "default": {"of": "core", "value": "off"},
                },
                {
                    "setting": "sonarr:port",
                    "value": None,
                    "was": "9000",
                    "default": {"of": "declared", "value": "8989"},
                },
                {
                    "setting": "gluetun:countries",
                    "value": "Belgium",
                    "default": {
                        "of": "per-reader",
                        "readers": [
                            {
                                "service": "gluetun",
                                "variable": "SERVER_COUNTRIES",
                                "default": "Netherlands",
                                "met": True,
                            },
                            {"service": "qbittorrent", "variable": "VPN_COUNTRIES", "met": False},
                        ],
                    },
                },
                {"setting": "jellyfin:published", "value": None, "default": {"of": "none"}},
            ],
        },
    },
}


def rehearsed_invitation(asking: str | None) -> dict[str, object]:
    """Return a rehearsed invitation for one member, with its asking where one is given."""
    applied: dict[str, object] = {
        "filtering": "A limit hides what is rated above it; it is not a filter on what is unrated.",
        "libraries": ["Films"],
        "limit": "PG",
        "requesting": "made",
        "unrated": "held-back",
    }
    if asking is not None:
        applied["asking"] = asking
    return {
        "api_version": 1,
        "kind": "invitation",
        "data": {
            "address": "https://192.168.1.42/join",
            "hours": 48,
            "linked": "not-tried",
            "name": "bo",
            "rehearsed": True,
            "standing": "made",
            "suspended": [],
            "withdrawn": [],
            "applied": applied,
        },
    }


def test_a_moved_settings_default_is_typed_by_every_tag_the_contract_gives_it_and_required() -> None:
    branches = [branch["properties"]["of"]["const"] for branch in definition("SettingDefault")["oneOf"]]
    assert tags(settings.SettingDefault) == branches == ["core", "declared", "per-reader", "none"]
    assert "default" in definition("SettingMove")["required"]
    assert "default" in keys(settings, "SettingMove")[0]
    assert "default" in keys(settings, "ReaderDefault")[1]


def test_a_moved_settings_default_reads_by_what_it_is_of_keeping_each_readers_own_and_its_absence() -> None:
    change = expect(parse_envelope(json.dumps(SETTINGS_CHANGE)), "settings")["data"].get("change")
    assert change is not None
    assert {move["setting"]: said(move["default"]) for move in change["settings"]} == {
        "LEMONFIBER_BACKUP_LIMIT": "core: off",
        "sonarr:port": "declared: 8989",
        "gluetun:countries": ["gluetun met: Netherlands", "qbittorrent unmet: declares none"],
        "jellyfin:published": "none",
    }


def test_what_an_invitation_holds_their_asking_to_is_typed_as_the_households_policy_and_optional() -> None:
    assert list(typing.get_args(policy.Policy.__value__)) == [
        branch["const"] for branch in definition("Policy")["oneOf"]
    ]
    assert "asking" not in definition("InvitationApplied")["required"]
    assert "asking" in keys(invitation, "InvitationApplied")[1]


@pytest.mark.parametrize("asking", ["everything-waits", None], ids=["held", "not-held"])
def test_a_rehearsal_reads_the_policy_it_would_hold_their_asking_to_and_its_absence_as_no_policy(
    asking: str | None,
) -> None:
    held = expect(parse_envelope(json.dumps(rehearsed_invitation(asking))), "invitation")
    applied = held["data"].get("applied")
    assert applied is not None
    assert applied.get("asking") == asking
    assert applied["requesting"] == "made"

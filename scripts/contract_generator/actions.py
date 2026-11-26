# Copyright (c) 2026 NightWorksIO
"""Every action the web API takes, as the artefact describes it, and the module written from it."""

import json
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING

from scripts.contract_generator.artefact import ACTION, array_of, object_of, unread_fields
from scripts.contract_generator.modules import Module
from scripts.contract_generator.refused import refuse

if TYPE_CHECKING:
    from collections.abc import Iterator, Mapping, Sequence

ARGUMENT = re.compile(r"^[a-z][a-z0-9]*(?:_[a-z0-9]+)*$")
"""An action's argument, as the core spells one: `dry_run`."""

ACTION_FIELDS = ("action", "arguments", "consent", "rehearsal")
"""Everything the contract says of an action. Anything else is refused, not dropped."""

ARGUMENT_FIELDS = ("name", "type")
"""Everything the contract says of an action's argument. Anything else is refused, not dropped."""


@dataclass(frozen=True)
class Described:
    """One action the web API takes, as the contract describes it."""

    action: str
    arguments: tuple[str, ...]
    """The name of every argument it takes, in the contract's order."""
    consent: tuple[str, ...]
    """The arguments carrying the operator's yes."""
    rehearsal: bool
    """Whether it takes `dry_run`."""


def wrong_with_arguments(name: str, listed: Sequence[object], named: list[str]) -> Iterator[str]:
    """Yield everything wrong with an action's arguments, noting each name in `named`."""
    for at, entry in enumerate(listed):
        argument = object_of(entry)
        called = argument.get("name") if argument is not None else None
        if argument is None or not isinstance(called, str) or not ARGUMENT.fullmatch(called):
            yield f"{name}: argument {at} is not named as an argument"
            continue
        if called in named:
            yield f"{name}: argument {called} is listed twice"
        named.append(called)
        if object_of(argument.get("type")) is None:
            yield f"{name}: argument {called} has no schema for its type"
        yield from unread_fields(f"{name}: argument {called}", argument, ARGUMENT_FIELDS)


def read_described(name: str, entry: object) -> tuple[Described | None, list[str]]:
    """Return one action, or everything wrong with it as lines naming it."""
    if not ACTION.fullmatch(name):
        return None, [f"{json.dumps(name)}: not an action's name"]
    described = object_of(entry)
    if described is None:
        return None, [f"{name}: not an object"]
    wrong: list[str] = []
    if described.get("action") != name:
        wrong.append(f"{name}: describes itself as {json.dumps(described.get('action'))}")
    rehearsal = described.get("rehearsal")
    if not isinstance(rehearsal, bool):
        wrong.append(f"{name}: rehearsal {json.dumps(rehearsal)} is not true or false")
    listed = array_of(described.get("arguments"))
    if listed is None:
        wrong.append(f"{name}: arguments {json.dumps(described.get('arguments'))} is not a list")
    named: list[str] = []
    wrong.extend(wrong_with_arguments(name, listed or [], named))
    consent = array_of(described.get("consent"))
    if consent is None:
        wrong.append(f"{name}: consent {json.dumps(described.get('consent'))} is not a list")
    carrying = [one for one in consent or [] if isinstance(one, str) and one in named]
    wrong.extend(
        f"{name}: consent names {json.dumps(one)}, which is none of its arguments"
        for one in consent or []
        if one not in carrying
    )
    wrong.extend(unread_fields(name, described, ACTION_FIELDS))
    if wrong:
        return None, wrong
    return Described(name, tuple(named), tuple(carrying), rehearsal is True), []


def actions_of(artefact: Mapping[str, object]) -> list[Described]:
    """Return every action the web API takes, by name, or none for an artefact older than the list."""
    listed = artefact.get("actions", {})
    described = object_of(listed)
    if described is None:
        refuse(
            f"the vendored contract's actions are {json.dumps(listed)}, "
            "and they are an object keyed by each action's name",
        )
    read: list[Described] = []
    problems: list[str] = []
    for name in sorted(described):
        one, wrong = read_described(name, described[name])
        problems.extend(wrong)
        if one is not None:
            read.append(one)
    if problems:
        refuse(
            "the vendored contract describes an action this generator cannot write:\n  "
            + "\n  ".join(problems),
        )
    return read


def tupled(words: Sequence[str]) -> str:
    """Write words as a tuple of strings."""
    return f"({', '.join(json.dumps(word) for word in words)}{',' if len(words) == 1 else ''})"


def actions_module(described: Sequence[Described]) -> Module:
    """Return the module of every action the web API takes, and what the contract says of each."""
    quoted = [json.dumps(one.action) for one in described]
    union = f"typing.Literal[{', '.join(quoted)}]" if quoted else "typing.Never"
    body = [
        "",
        f"type ActionName = {union}",
        '"""Every action the web API takes, by the name it is posted to under `/api/actions/`."""',
        "",
        "",
        "class ActionDescribed(typing.NamedTuple):",
        '    """What the contract says of one action."""',
        "",
        "    arguments: tuple[str, ...]",
        '    """The name of every argument it takes, in the order the contract lists them."""',
        "    consent: tuple[str, ...]",
        '    """The arguments carrying the operator\'s yes, without which it writes nothing."""',
        "    rehearsal: bool",
        '    """Whether it takes `dry_run`, so it can be rehearsed before the real call."""',
        "",
        "",
        "ACTIONS: typing.Final[typing.Mapping[ActionName, ActionDescribed]] = types.MappingProxyType({",
    ]
    body.extend(
        f"    {json.dumps(one.action)}: ActionDescribed({tupled(one.arguments)}, {tupled(one.consent)}, "
        f"{one.rehearsal}),"
        for one in described
    )
    body.extend(
        [
            "})",
            '"""What the contract says of every action the web API takes, by name."""',
            "",
            "",
            "def is_action_name(value: str) -> typing.TypeIs[ActionName]:",
            '    """Tell whether a name is one of an action the web API takes."""',
            "    return value in ACTIONS",
        ],
    )
    names = ["ACTIONS", "ActionDescribed", "ActionName", "is_action_name"]
    summary = "Every action the web API takes, and what the contract says of each."
    return Module(("actions",), summary, body, names, standard=("types", "typing"))

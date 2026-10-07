# Copyright (c) 2026 NightWorksIO
"""The modules written from the artefact's lists rather than its schemas: kinds, refusals and key-callable actions."""

import json
from typing import TYPE_CHECKING

from scripts.contract_generator.artefact import SPOKEN
from scripts.contract_generator.modules import Module
from scripts.contract_generator.spelling import pascal

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from scripts.contract_generator.artefact import ByKey

KINDS_PACKAGE = ("kinds",)
"""Where each kind's envelope, and the shapes only it carries, are written."""

SHARED_PACKAGE = ("shared",)
"""Where the shapes more than one kind carries are written."""


def envelope_module(kinds: Sequence[str]) -> Module:
    """Return the module naming every kind, and the envelope of any kind."""
    envelopes = [f"{pascal(kind)}Envelope" for kind in kinds]
    quoted = ", ".join(json.dumps(kind) for kind in kinds)
    body = [
        "",
        f"CONTRACT_API_VERSION: typing.Final = {SPOKEN}",
        '"""The wire version these shapes were generated for."""',
        "",
        f"type Kind = typing.Literal[{quoted}]",
        '"""The name of every kind the server may send."""',
        "",
        "KINDS: typing.Final[frozenset[Kind]] = frozenset(typing.get_args(Kind.__value__))",
        '"""Every kind the server may send."""',
        "",
        f"type Envelope = {' | '.join(envelopes)}",
        '"""The envelope of any kind, told apart by its `kind`."""',
    ]
    names = ["CONTRACT_API_VERSION", "Envelope", "KINDS", "Kind"]
    return Module(
        ("envelope",),
        "Every kind the server may send, and the envelope of any of them.",
        body,
        names,
        {KINDS_PACKAGE: set(envelopes)},
    )


def narrowing_module(kinds: Sequence[str]) -> Module:
    """Return the module whose signature narrows an envelope to the one kind it is expected to be."""
    body = [
        "",
        "",
        "class KindNarrowing(typing.Protocol):",
        '    """Narrows an envelope to the one kind it is expected to be."""',
        "",
    ]
    for kind in kinds:
        signature = f"envelope: Envelope, kind: typing.Literal[{json.dumps(kind)}], /"
        body.extend(
            ["    @typing.overload", f"    def __call__(self, {signature}) -> {pascal(kind)}Envelope: ..."],
        )
    imports = {("envelope",): {"Envelope"}, KINDS_PACKAGE: {f"{pascal(kind)}Envelope" for kind in kinds}}
    return Module(
        ("narrowing",),
        "The signature that narrows an envelope to one kind.",
        body,
        ["KindNarrowing"],
        imports,
    )


def refusals_module(refusals: Mapping[str, Mapping[str, object]]) -> Module:
    """Return the module of the refusal codes the contract lists, and what it says of each."""
    codes = sorted(refusals)
    union = f"typing.Literal[{', '.join(json.dumps(code) for code in codes)}]" if codes else "typing.Never"
    body = [
        "",
        f"type RefusalCode = {union}",
        '"""Every code a refusal may carry."""',
        "",
        "",
        "class ListedRefusal(typing.NamedTuple):",
        '    """What the contract says of one refusal code."""',
        "",
        "    name: str",
        '    """The code\'s name in the core\'s registry."""',
        "    status: int",
        '    """The one status the refusal is answered with."""',
        "    description: str",
        '    """The registry\'s own line about it."""',
        "",
        "",
        "REFUSAL_CODES: typing.Final[typing.Mapping[RefusalCode, ListedRefusal]] = types.MappingProxyType({",
    ]
    for code in codes:
        listed = refusals[code]
        body.append(
            f"    {json.dumps(code)}: ListedRefusal({json.dumps(listed['name'])}, {listed['status']}, "
            f"{json.dumps(listed['description'])}),",
        )
    body.extend(
        [
            "})",
            '"""What the contract says of each refusal code."""',
            "",
            "",
            "def is_refusal_code(value: str) -> typing.TypeIs[RefusalCode]:",
            '    """Tell whether a code is one the contract lists as a refusal\'s."""',
            "    return value in REFUSAL_CODES",
        ],
    )
    names = ["REFUSAL_CODES", "ListedRefusal", "RefusalCode", "is_refusal_code"]
    summary = "Every code the contract lists a refusal as carrying, and what it says of each."
    return Module(("refusals",), summary, body, names, standard=("types", "typing"))


def key_callable_module(callable_by_key: Sequence[ByKey]) -> Module:
    """Return the module of the actions a key may call, and what the contract says of each."""
    quoted = [json.dumps(one.action) for one in callable_by_key]
    union = f"typing.Literal[{', '.join(quoted)}]" if quoted else "typing.Never"
    body = [
        "",
        f"type KeyCallableAction = {union}",
        '"""Every action a key may call; any other is refused to a key, naming its scope."""',
        "",
        "",
        "class KeyCallable(typing.NamedTuple):",
        '    """What the contract says of one action a key may call."""',
        "",
        "    disturbs: bool",
        '    """Whether calling it disturbs the running system."""',
        "    rehearsal: bool",
        '    """Whether it takes `dry_run`, so it can be rehearsed before the real call is offered."""',
        "    idempotent: bool",
        '    """Whether calling it again with the same arguments leaves the stack as calling it once did."""',
        "",
        "",
        "KEY_CALLABLE: typing.Final[typing.Mapping[KeyCallableAction, KeyCallable]] = types.MappingProxyType({",
    ]
    body.extend(
        f"    {json.dumps(one.action)}: KeyCallable({one.disturbs}, {one.rehearsal}, {one.idempotent}),"
        for one in callable_by_key
    )
    body.extend(
        [
            "})",
            '"""What the contract says of each action a key may call, in the order it lists them."""',
            "",
            "",
            "def is_key_callable(value: str) -> typing.TypeIs[KeyCallableAction]:",
            '    """Tell whether an action is one the contract says a key may call."""',
            "    return value in KEY_CALLABLE",
        ],
    )
    names = ["KEY_CALLABLE", "KeyCallable", "KeyCallableAction", "is_key_callable"]
    summary = "Every action an integration key may call, and what the contract says of each."
    return Module(("key_callable",), summary, body, names, standard=("types", "typing"))

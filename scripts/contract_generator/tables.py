# Copyright (c) 2026 NightWorksIO
"""The modules written from the artefact's lists rather than its schemas: kinds, refusals, key-callable actions, reads."""

import json
import re
from typing import TYPE_CHECKING

from scripts.contract_generator.artefact import SPOKEN
from scripts.contract_generator.modules import Module
from scripts.contract_generator.refused import refuse
from scripts.contract_generator.spelling import pascal

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from scripts.contract_generator.artefact import ByKey, Served

KINDS_PACKAGE = ("kinds",)
"""Where each kind's envelope, and the shapes only it carries, are written."""

SHARED_PACKAGE = ("shared",)
"""Where the shapes more than one kind carries are written."""

API = "/api"
"""What every read's path begins with."""

ONE_A_LINE = frozenset({"/api/logs"})
"""The reads answered one envelope a line, which `Read` leaves out: the client reaches each by a method of its own."""

PLACEHOLDER = re.compile(r"/\{([a-z][a-z_]*)\}$")
"""The value a read takes in its path: `/{name}`."""


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
        "    moved: str | None = None",
        '    """The code a call is refused with when the offer it carries has moved since its rehearsal, or None."""',
        "",
        "",
        "KEY_CALLABLE: typing.Final[typing.Mapping[KeyCallableAction, KeyCallable]] = types.MappingProxyType({",
    ]
    body.extend(
        f"    {json.dumps(one.action)}: KeyCallable({one.disturbs}, {one.rehearsal}, {one.idempotent}, "
        f"{'None' if one.moved is None else json.dumps(one.moved)}),"
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


def member(served: Served) -> str:
    """Return the name a read is written under.

    `/api/front-door` is `FRONT_DOOR`. A file read is named for its path short of
    its segment, `/api/bundle/{name}` as `BUNDLE`; any other read keeps its
    segment, `/api/held/{id}` as `HELD_ID`.
    """
    path = reached(served) if served.file else served.path
    return (
        path.removeprefix(f"{API}/")
        .replace("{", "")
        .replace("}", "")
        .replace("/", "_")
        .replace("-", "_")
        .upper()
    )


def segments(served: Served) -> tuple[str, ...]:
    """Return the segments of a read's path a caller fills, by name."""
    placeholder = PLACEHOLDER.search(served.path)
    return (placeholder.group(1),) if placeholder else ()


def reached(served: Served) -> str:
    """Return the path a read is reached on, short of any placeholder: `/api/bundle/{name}` at `/api/bundle`."""
    return PLACEHOLDER.sub("", served.path)


def joined(phrases: Sequence[str]) -> str:
    """Return phrases joined as a sentence joins them: `a`, `b` and `c`."""
    return phrases[0] if len(phrases) == 1 else f"{', '.join(phrases[:-1])} and {phrases[-1]}"


def tupled(items: Sequence[str]) -> str:
    """Return written items as the tuple literal the formatter keeps on one line."""
    return f"({items[0]},)" if len(items) == 1 else f"({', '.join(items)})"


def said(served: Served) -> str:
    """Return what a read answers with and the query parameters it takes, as one sentence."""
    kinds = " or ".join(f"`{kind}`" for kind in served.kinds)
    if served.file:
        placeholder = PLACEHOLDER.search(served.path)
        answers = (
            f"Answers with a file, named by `{placeholder.group(1)}` in the path"
            if placeholder
            else "Answers with a file"
        )
    elif served.path in ONE_A_LINE:
        answers = f"Answers one envelope a line, each {kinds}"
    else:
        answers = f"Answers with {kinds}"
        filled = segments(served)
        if filled:
            answers += f", for the `{filled[0]}` in its path"
    phrases = [f"`{one.name}`" + (" (more than once)" if one.repeatable else "") for one in served.parameters]
    return f"{answers}; takes {joined(phrases)}." if phrases else f"{answers}."


def reads_module(reads: Sequence[Served]) -> Module:
    """Return the module of the reads the web API serves, and what the contract says of each."""
    enveloped = [one for one in reads if not one.file and one.path not in ONE_A_LINE]
    elsewhere = [one for one in reads if one.file or one.path in ONE_A_LINE]
    body = [
        "",
        f"API: typing.Final = {json.dumps(API)}",
        '"""What every read\'s path begins with."""',
        "",
        "",
        "class Read(enum.StrEnum):",
        '    """A read lemonfiber serves answering with one envelope, named for its path.',
        "",
        "    `READS` holds the kinds each answers with and the query parameters it takes.",
        '    """',
        "",
    ]
    taken: set[str] = set()
    for one in enveloped:
        name = member(one)
        if name in taken:
            refuse(f"the read {one.path} would be written as `{name}`, which `Read` already names")
        taken.add(name)
        value = one.path.removeprefix(f"{API}/")
        body.extend([f"    {name} = {json.dumps(value)}", f'    """{said(one)}"""'])
    body.extend(
        [
            "",
            "    @property",
            "    def path(self) -> str:",
            '        """Return the path this read is served on, each segment a caller fills written as `{name}`."""',
            '        return f"{API}/{self.value}"',
        ],
    )
    names = ["API", "READS", "Read", "ReadParameter", "Readable"]
    for one in elsewhere:
        name = member(one)
        if name in names:
            refuse(f"the read {one.path} would be written as `{name}`, which this module already names")
        names.append(name)
        body.extend(["", f"{name}: typing.Final = {json.dumps(reached(one))}", f'"""{said(one)}"""'])
    body.extend(
        [
            "",
            "",
            "class ReadParameter(typing.NamedTuple):",
            '    """One query parameter a read takes."""',
            "",
            "    name: str",
            '    """Its name in the query."""',
            "    repeatable: bool",
            '    """Whether it may be given more than once."""',
            "",
            "",
            "class Readable(typing.NamedTuple):",
            '    """What the contract says of one read."""',
            "",
            "    kinds: tuple[Kind, ...]",
            '    """Every kind it may answer with."""',
            "    parameters: tuple[ReadParameter, ...]",
            '    """Every query parameter it takes, in the order the contract lists them."""',
            "    segments: tuple[str, ...] = ()",
            '    """Every segment of its path a caller fills, by name."""',
            "",
            "",
            "READS: typing.Final[typing.Mapping[Read, Readable]] = types.MappingProxyType({",
        ],
    )
    for one in enveloped:
        kinds = tupled([json.dumps(kind) for kind in one.kinds])
        parameters = tupled([f"ReadParameter({json.dumps(p.name)}, {p.repeatable})" for p in one.parameters])
        filled = segments(one)
        tail = f", {tupled([json.dumps(name) for name in filled])}" if filled else ""
        body.append(f"    Read.{member(one)}: Readable({kinds}, {parameters}{tail}),")
    body.extend(
        [
            "})",
            '"""What the contract says of each read answering with one envelope, in the order it lists them."""',
        ],
    )
    summary = "Every read the web API serves, and what the contract says of each."
    return Module(
        ("reads",),
        summary,
        body,
        names,
        {("envelope",): {"Kind"}},
        standard=("enum", "types", "typing"),
    )

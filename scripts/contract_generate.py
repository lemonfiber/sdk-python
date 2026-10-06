# Copyright (c) 2026 NightWorksIO
"""Write `src/lemonfiber/_generated/` from the vendored contract artefact.

Offline and deterministic: the same artefact in gives the same files out, so CI
regenerates and fails on any difference. Generation reads
`contract/web-api.contract.json` and `contract/VERSION` and nothing else, and
writes nothing when it refuses the artefact. `just generate` runs this and then
`ruff format` over what it wrote, so the committed files are the formatter's.

    uv run just generate
"""

import json
import keyword
import pathlib
import re
import sys
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, NoReturn, cast

from scripts.contract_sync import REVISION

if TYPE_CHECKING:
    from collections.abc import Iterator, Mapping, Sequence

ROOT = pathlib.Path(__file__).resolve().parent.parent
ARTEFACT = pathlib.Path("contract/web-api.contract.json")
STAMP = pathlib.Path("contract/VERSION")
OUT = pathlib.Path("src/lemonfiber/_generated")
UNKNOWN = "an unknown revision"
"""What the generated files say they came from when `contract/VERSION` is missing."""

SPOKEN = 1
"""The wire version this package implements."""

ANNOTATIONS = frozenset({"description", "title", "default", "examples", "$comment"})
"""Keywords that describe a schema without constraining what it matches."""

NARROWING = frozenset(
    {
        "$defs",
        "$schema",
        "additionalProperties",
        "exclusiveMaximum",
        "exclusiveMinimum",
        "format",
        "maxItems",
        "maxLength",
        "maximum",
        "minItems",
        "minLength",
        "minimum",
        "pattern",
        "required",
        "uniqueItems",
    },
)
"""Keywords that narrow a value without changing the Python type it is."""

UNDERSTOOD = (
    ANNOTATIONS | NARROWING | {"type", "properties", "items", "oneOf", "anyOf", "const", "enum", "$ref"}
)
"""Every keyword this generator reads. Any other is refused rather than dropped."""

KIND = re.compile(r"^[a-z][a-z0-9_-]*$")
"""A kind, as the core spells one: `front-door`."""

CODE = re.compile(r"^[A-Z][A-Z0-9]*-\d+$")
"""A problem code, as the core spells one: `ADMIT-4`."""

SCREAMING_SNAKE = re.compile(r"^[A-Z][A-Z0-9]*(?:_[A-Z0-9]+)*$")
"""A registry name, as the core spells one: `NOT_ADMITTED`."""

ACTION = re.compile(r"^[a-z][a-z0-9]*(?:-[a-z0-9]+)*$")
"""An action's name, as `POST /api/actions/<action>` spells one: `downloads-pause`."""

CALLABLE_FIELDS = ("action", "disturbs", "rehearsal")
"""Everything the contract says of an action a key may call, in that order. Anything else is refused, not dropped."""

REFUSAL_STATUSES = range(400, 600)
"""The statuses a refusal may be answered with: the request's fault or the machine's."""

DEFINITION = re.compile(r"^[A-Z]\w*$", re.ASCII)
"""A definition's name, as the artefact spells one."""

REFERENCE = re.compile(r"^#/\$defs/([^/]+)$")
"""A reference to a definition beside the one making it."""

PRIMITIVES = {"string": "str", "integer": "int", "number": "float", "boolean": "bool", "null": "None"}
"""The Python type of each JSON type that holds no other value."""

ENVELOPE_FIELDS = ("api_version", "kind", "data")
"""What every envelope requires."""

OWNED = {
    "typing": "the typing module every annotation is spelled through",
    "types": "the module the read-only mapping comes from",
    "CONTRACT_API_VERSION": "the wire version these shapes were generated for",
    "Kind": "the name of every kind the server may send",
    "KINDS": "the set of every kind the server may send",
    "Envelope": "the union of every kind's envelope",
    "KindNarrowing": "the signature that narrows an envelope to one kind",
    "RefusalCode": "every code a refusal may carry",
    "ListedRefusal": "what the contract says of one refusal code",
    "REFUSAL_CODES": "what the contract says of each refusal code",
    "is_refusal_code": "whether a code is one the contract lists",
    "KeyCallableAction": "every action a key may call",
    "KeyCallable": "what the contract says of one action a key may call",
    "KEY_CALLABLE": "what the contract says of each action a key may call",
    "is_key_callable": "whether an action is one a key may call",
}
"""Names this generator writes itself, and what each one means here."""


class ArtefactRefusedError(Exception):
    """The artefact cannot be generated from, and nothing was written."""


def array_of(node: object) -> list[object] | None:
    """Return a decoded JSON value as the array it is, or None where it is not one."""
    return cast("list[object]", node) if isinstance(node, list) else None


def object_of(node: object) -> dict[str, object] | None:
    """Return a decoded JSON value as the object it is, whose keys JSON makes strings, or None."""
    return cast("dict[str, object]", node) if isinstance(node, dict) else None


def as_list(node: object) -> list[object]:
    """Read a JSON array a validated schema holds as the list it decodes to."""
    return cast("list[object]", node)


def as_map(node: object) -> dict[str, object]:
    """Read a JSON object a validated schema holds as the dict it decodes to."""
    return cast("dict[str, object]", node)


def as_maps(node: object) -> dict[str, dict[str, object]]:
    """Read a JSON object of JSON objects the artefact holds as the dicts it decodes to."""
    return cast("dict[str, dict[str, object]]", node)


def refuse(message: str) -> NoReturn:
    """Refuse the artefact, saying why."""
    raise ArtefactRefusedError(message)


def pascal(text: str) -> str:
    """Spell `front-door` as `FrontDoor` and `whole_stack` as `WholeStack`."""
    return "".join(part[:1].upper() + part[1:] for part in re.split(r"[^A-Za-z0-9]+", text) if part)


def is_field_name(key: str) -> bool:
    """Tell whether a key can be written as a class attribute."""
    return key.isidentifier() and not keyword.iskeyword(key)


def escaped(character: str) -> str:
    """Spell one character so that inside a docstring it is that character and nothing more."""
    if character in {"\\", '"'}:
        return f"\\{character}"
    if character == "\n" or character.isprintable():
        return character
    return character.encode("unicode_escape").decode("ascii")


def docstring(text: str, indent: str) -> list[str]:
    """Write a description as a docstring that reads back as the same text.

    Every backslash and quote is escaped, so no run of quotes in the text can
    close the docstring, and every character that is not printable is written
    as its escape, so none of them can end a line or the file.
    """
    body = "".join(escaped(character) for character in text.strip())
    lines = body.split("\n")
    if len(lines) == 1:
        return [f'{indent}"""{body}"""']
    rest = [f"{indent}{line}" if line else "" for line in lines[1:]]
    return [f'{indent}"""{lines[0]}', *rest, f'{indent}"""']


def literal(value: object) -> str:
    """Write a JSON value as the Python literal `typing.Literal` takes."""
    if isinstance(value, bool):
        return str(value)
    if isinstance(value, int | str):
        return json.dumps(value)
    refuse(f"a constant of {json.dumps(value)} has no Python literal")


def ambiguous(node: object, path: str) -> Iterator[str]:
    """Yield every reference in the artefact with a constraint sitting beside it.

    Draft-07 readers discard whatever accompanies a `$ref` and 2020-12 readers
    apply both, so such a shape means two different things to two readers.
    """
    items = array_of(node)
    if items is not None:
        for at, item in enumerate(items):
            yield from ambiguous(item, f"{path}/{at}")
        return
    named = object_of(node)
    if named is None:
        return
    constraints = sorted(key for key in named if key != "$ref" and key not in ANNOTATIONS)
    if "$ref" in named and constraints:
        yield f"{path} ({', '.join(constraints)})"
    for key, value in named.items():
        yield from ambiguous(value, f"{path}/{key}")


def malformed_refusal(code: str, entry: object) -> Iterator[str]:
    """Yield everything wrong with one listed refusal, as lines naming its code."""
    if not CODE.fullmatch(code):
        yield f"{json.dumps(code)}: not a code, which is a prefix and a number"
    listed = object_of(entry)
    if listed is None:
        yield f"{code}: not an object"
        return
    name = listed.get("name")
    status = listed.get("status")
    description = listed.get("description")
    if not isinstance(name, str) or not SCREAMING_SNAKE.fullmatch(name):
        yield f"{code}: name {json.dumps(name)} is not SCREAMING_SNAKE"
    if not isinstance(status, int) or isinstance(status, bool) or status not in REFUSAL_STATUSES:
        yield f"{code}: status {json.dumps(status)} is not a refusal's status"
    if not isinstance(description, str) or not description.strip():
        yield f"{code}: description {json.dumps(description)} is not a sentence"


@dataclass(frozen=True)
class ByKey:
    """One action a key may call, as the contract lists it."""

    action: str
    disturbs: bool
    rehearsal: bool


def read_by_key(at: int, entry: object) -> tuple[ByKey | None, list[str]]:
    """Return one action a key may call, or everything wrong with it as lines naming where it sits."""
    listed = object_of(entry)
    if listed is None:
        return None, [f"entry {at}: not an object"]
    action, disturbs, rehearsal = (listed.get(one) for one in CALLABLE_FIELDS)
    wrong: list[str] = []
    if not isinstance(action, str) or not ACTION.fullmatch(action):
        wrong.append(f"entry {at}: action {json.dumps(action)} is not an action's name")
    for flag, value in zip(CALLABLE_FIELDS[1:], (disturbs, rehearsal), strict=True):
        if not isinstance(value, bool):
            wrong.append(f"entry {at}: {flag} {json.dumps(value)} is not true or false")
    unread = sorted(set(listed) - set(CALLABLE_FIELDS))
    if unread:
        wrong.append(f"entry {at}: carries {', '.join(unread)}, which this generator does not read")
    if (
        wrong
        or not isinstance(action, str)
        or not isinstance(disturbs, bool)
        or not isinstance(rehearsal, bool)
    ):
        return None, wrong
    return ByKey(action, disturbs, rehearsal), []


@dataclass(frozen=True)
class Field:
    """One property of an object schema, as a TypedDict declares it."""

    key: str
    annotation: str
    needed: bool
    description: str | None


def class_lines(name: str, description: str | None, fields: Sequence[Field]) -> list[str]:
    """Return a TypedDict written as a class, every key of which is a Python name."""
    lines = [f"class {name}(typing.TypedDict):"]
    if description is not None:
        lines.extend([*docstring(description, "    "), ""])
    for one in fields:
        annotation = one.annotation if one.needed else f"typing.NotRequired[{one.annotation}]"
        lines.append(f"    {one.key}: {annotation}")
        if one.description is not None:
            lines.extend(docstring(one.description, "    "))
    if not fields:
        lines.append("    pass")
    return lines


@dataclass
class Shape:
    """One TypedDict or alias this generator emits, and where it came from."""

    name: str
    origin: str
    lines: list[str]
    fields: list[tuple[str, str, bool]] | None = None
    """A functional TypedDict's keys, annotations and whether each is required, written out once the order is known."""
    description: str | None = None

    def written(self, quoted: frozenset[str]) -> list[str]:
        """Return the declaration, quoting any annotation that names a shape in `quoted`."""
        if self.fields is None:
            return self.lines
        lines = [f"{self.name} = typing.TypedDict(", f"    {json.dumps(self.name)},", "    {"]
        for key, annotation, needed in self.fields:
            spelled = json.dumps(annotation) if names_in(annotation) & quoted else annotation
            lines.append(
                f"        {json.dumps(key)}: {spelled if needed else f'typing.NotRequired[{spelled}]'},",
            )
        lines.extend(["    },", ")"])
        if self.description is not None:
            lines.extend(docstring(self.description, ""))
        return lines


def names_in(annotation: str) -> set[str]:
    """Return every name an annotation refers to."""
    return set(re.findall(r"\b[A-Za-z_]\w*\b", annotation))


def ordered(shapes: Mapping[str, Shape]) -> list[str]:
    """Return every declaration, each functional TypedDict after what it names.

    A class body and a `type` alias are evaluated when first read, so they are
    written in name order. A functional TypedDict is evaluated where it stands,
    so each follows the functional TypedDicts it names; one caught in a cycle
    names the rest of the cycle in quotes instead.
    """
    eager = {name for name, shape in shapes.items() if shape.fields is not None}
    order = sorted(set(shapes) - eager)
    waiting = {
        name: {*names_in(" ".join(a for _, a, _ in shapes[name].fields or []))} & eager - {name}
        for name in eager
    }
    while waiting:
        ready = sorted(name for name, needs in waiting.items() if not needs & set(waiting))
        if not ready:
            ready = [min(waiting)]
        for name in ready:
            order.append(name)
            del waiting[name]
    return order


@dataclass
class Writer:
    """Turns the artefact's schemas into Python declarations."""

    owned: dict[str, str] = field(default_factory=lambda: dict(OWNED))
    kind: str = ""
    definitions: Mapping[str, object] = field(default_factory=dict[str, object])
    shapes: dict[str, Shape] = field(default_factory=dict[str, Shape])
    shared: dict[str, tuple[str, str]] = field(default_factory=dict[str, tuple[str, str]])
    """Each definition already emitted: the kind carrying it and its canonical JSON."""

    def claim(self, name: str, origin: str, lines: list[str]) -> str:
        """Record one declaration, refusing a name that something else holds."""
        if name in self.owned:
            refuse(f"{origin} would be written as `{name}`, which here names {self.owned[name]}")
        held = self.shapes.get(name)
        if held is not None:
            refuse(f"{origin} and {held.origin} would both be written as `{name}`")
        self.shapes[name] = Shape(name, origin, lines)
        return name

    def definition(self, name: str) -> str:
        """Return the name a definition is written under, writing it the first time."""
        if name in self.owned:
            refuse(
                f"`{name}`, defined by `{self.kind}`, takes a name this generator writes itself — "
                f"here it names {self.owned[name]}. Rename the definition in the contract.",
            )
        if not DEFINITION.fullmatch(name) or keyword.iskeyword(name):
            refuse(f"`{name}`, defined by `{self.kind}`, is not a name a Python type can carry")
        schema = self.definitions.get(name)
        if schema is None:
            refuse(f"`{self.kind}` refers to `{name}`, which it does not define")
        canonical = json.dumps(schema, sort_keys=True)
        held = self.shared.get(name)
        if held is not None:
            if held[1] != canonical:
                refuse(
                    f"`{name}` is defined by `{held[0]}` and by `{self.kind}` as two different shapes, "
                    "and one name would have to describe both",
                )
            return name
        self.shared[name] = (self.kind, canonical)
        self.declare(name, schema, f"`{name}`, defined by `{self.kind}`")
        return name

    def declare(self, name: str, schema: object, origin: str) -> None:
        """Write one named declaration: a TypedDict for an object, an alias otherwise."""
        node = self.node(schema, origin)
        if self.is_object(node):
            self.typed_dict(name, node, origin)
            return
        lines = [f"type {name} = {self.annotation(node, name, origin)}"]
        description = node.get("description")
        if isinstance(description, str):
            lines.extend(docstring(description, ""))
        self.claim(name, origin, lines)

    @staticmethod
    def node(schema: object, origin: str) -> dict[str, object]:
        """Return a schema as an object, refusing one this generator does not read."""
        node = object_of(schema)
        if node is None:
            refuse(f"{origin} is {json.dumps(schema)}, which is not a schema this generator reads")
        unread = sorted(set(node) - UNDERSTOOD)
        if unread:
            refuse(f"{origin} uses {', '.join(unread)}, which this generator does not read")
        return node

    @staticmethod
    def types_of(node: Mapping[str, object]) -> list[str]:
        """Return the `type` keyword as a list, empty where there is none."""
        declared = node.get("type")
        if declared is None:
            return []
        if isinstance(declared, str):
            return [declared]
        return [str(one) for one in as_list(declared)]

    def is_object(self, node: Mapping[str, object]) -> bool:
        """Tell whether a schema is an object with properties and nothing beside it."""
        return self.types_of(node) == ["object"] and "properties" in node

    def typed_dict(self, name: str, node: Mapping[str, object], origin: str) -> None:
        """Write an object schema as a TypedDict."""
        fields = self.fields_of(name, node, origin)
        said = node.get("description")
        description = said if isinstance(said, str) else None
        if all(is_field_name(one.key) for one in fields):
            self.claim(name, origin, class_lines(name, description, fields))
            return
        self.claim(name, origin, [])
        self.shapes[name].fields = [(one.key, one.annotation, one.needed) for one in fields]
        self.shapes[name].description = description

    def fields_of(self, name: str, node: Mapping[str, object], origin: str) -> list[Field]:
        """Return the fields an object schema declares, in the order they are written."""
        properties = as_map(node.get("properties", {}))
        required = set(cast("list[str]", node.get("required", [])))
        fields: list[Field] = []
        for key in sorted(properties):
            where = f"{origin} property `{key}`"
            prop = self.node(properties[key], where)
            said = prop.get("description")
            fields.append(
                Field(
                    key,
                    self.annotation(prop, name + pascal(key), where),
                    needed=key in required,
                    description=said if isinstance(said, str) else None,
                ),
            )
        return fields

    def annotation(self, node: Mapping[str, object], name: str, origin: str) -> str:
        """Return the Python type a schema describes, naming any object it holds inline after `name`."""
        reference = node.get("$ref")
        if reference is not None:
            matched = REFERENCE.fullmatch(str(reference))
            if matched is None:
                refuse(f"{origin} refers to {reference}, outside the definitions beside it")
            return self.definition(matched.group(1))
        if "const" in node:
            return f"typing.Literal[{literal(node['const'])}]"
        if "enum" in node:
            values = as_list(node["enum"])
            return f"typing.Literal[{', '.join(literal(value) for value in values)}]"
        for combinator in ("oneOf", "anyOf"):
            if combinator in node:
                variants = as_list(node[combinator])
                return self.union(variants, name, f"{origin} {combinator}")
        declared = self.types_of(node)
        if not declared:
            refuse(f"{origin} declares no type, and a type this generator guessed would be a lie")
        return " | ".join(self.one_type(one, node, name, origin) for one in declared)

    def one_type(self, one: str, node: Mapping[str, object], name: str, origin: str) -> str:
        """Return the Python type of one entry of a `type` list."""
        if one in PRIMITIVES:
            return PRIMITIVES[one]
        if one == "array":
            items = node.get("items")
            if items is None:
                refuse(f"{origin} is an array that says nothing of its items")
            where = f"{origin} items"
            return f"list[{self.annotation(self.node(items, where), name + 'Item', where)}]"
        if one == "object":
            if "properties" in node:
                self.typed_dict(name, node, origin)
                return name
            values: object = node.get("additionalProperties")
            if isinstance(values, dict):
                where = f"{origin} values"
                value = self.annotation(self.node(cast("object", values), where), name + "Value", where)
                return f"dict[str, {value}]"
            refuse(f"{origin} is an object that says nothing of its fields")
        refuse(f"{origin} is of type {one!r}, which this generator does not read")

    def union(self, variants: Sequence[object], name: str, origin: str) -> str:
        """Return the union a `oneOf` or `anyOf` describes, each object variant named for its tag."""
        nodes = [self.node(variant, f"{origin}/{at}") for at, variant in enumerate(variants)]
        tag = self.tag_of(nodes)
        constants: list[str] = []
        members: list[str] = []
        for at, variant in enumerate(nodes):
            if "const" in variant and self.types_of(variant) in ([], ["string"]):
                constants.append(literal(variant["const"]))
                continue
            label = self.label(variant, tag, at)
            members.append(self.annotation(variant, name + label, f"{origin}/{at}"))
        if constants:
            members.insert(0, f"typing.Literal[{', '.join(constants)}]")
        return " | ".join(dict.fromkeys(members))

    def tag_of(self, variants: Sequence[Mapping[str, object]]) -> str | None:
        """Return the property every object variant carries as a constant, where there is one."""
        common: set[str] | None = None
        for variant in variants:
            if not self.is_object(variant):
                continue
            properties = as_map(variant["properties"])
            constant = {key for key, prop in properties.items() if isinstance(prop, dict) and "const" in prop}
            common = constant if common is None else common & constant
        return min(common) if common else None

    def label(self, variant: Mapping[str, object], tag: str | None, at: int) -> str:
        """Return what a variant is called after its union: its tag's value, or its place."""
        if tag is not None and self.is_object(variant):
            properties = as_maps(variant["properties"])
            label = pascal(str(properties[tag]["const"]))
            if label.isidentifier():
                return label
        return f"Variant{at + 1}"


def kinds_of(artefact: Mapping[str, object]) -> dict[str, dict[str, object]]:
    """Return the artefact's kinds, refusing an artefact describing none."""
    kinds = artefact.get("kinds")
    described = object_of(kinds)
    if not described:
        refuse("the vendored contract describes no kinds")
    spelled: dict[str, str] = {}
    for kind, schema in sorted(described.items()):
        if not KIND.fullmatch(kind):
            refuse(f"the kind {json.dumps(kind)} is not lowercase letters, digits, hyphens and underscores")
        if not isinstance(schema, dict):
            refuse(f"the kind `{kind}` is {json.dumps(schema)}, which is not an envelope's schema")
        name = f"{pascal(kind)}Envelope"
        if name in spelled:
            refuse(f"the kinds `{spelled[name]}` and `{kind}` would both be written as `{name}`")
        spelled[name] = kind
    return as_maps(described)


def refusals_of(artefact: Mapping[str, object]) -> dict[str, dict[str, object]]:
    """Return the listed refusals, or none for an artefact older than the list."""
    listed = artefact.get("refusals", {})
    refusals = object_of(listed)
    if refusals is None:
        refuse(
            f"the vendored contract's refusals are {json.dumps(listed)}, and they are an object keyed by code",
        )
    problems = [line for code in sorted(refusals) for line in malformed_refusal(code, refusals[code])]
    named: dict[str, str] = {}
    if not problems:
        for code in sorted(refusals):
            name = str(as_map(refusals[code])["name"])
            if name in named:
                problems.append(f"{code}: name {name} is also the name of {named[name]}")
            named[name] = code
    if problems:
        refuse(
            "the vendored contract lists a refusal this generator cannot write:\n  " + "\n  ".join(problems),
        )
    return as_maps(refusals)


def key_callable_of(artefact: Mapping[str, object]) -> list[ByKey]:
    """Return the actions a key may call, in the contract's order, or none for an artefact older than the list."""
    listed = artefact.get("key_callable", [])
    entries = array_of(listed)
    if entries is None:
        refuse(f"the vendored contract's key_callable is {json.dumps(listed)}, and it is a list of actions")
    read: list[ByKey] = []
    problems: list[str] = []
    seen: set[str] = set()
    for at, entry in enumerate(entries):
        one, wrong = read_by_key(at, entry)
        problems.extend(wrong)
        if one is None:
            continue
        if one.action in seen:
            problems.append(f"entry {at}: {one.action} is listed twice")
        seen.add(one.action)
        read.append(one)
    if problems:
        refuse(
            "the vendored contract lists an action a key may call that this generator cannot write:\n  "
            + "\n  ".join(problems),
        )
    return read


def envelope(writer: Writer, kind: str, schema: Mapping[str, object]) -> list[str]:
    """Write the envelope TypedDict carrying one kind, its `kind` narrowed to that kind."""
    name = f"{pascal(kind)}Envelope"
    origin = f"the envelope of `{kind}`"
    properties = as_map(schema.get("properties", {}))
    required = set(cast("list[str]", schema.get("required", [])))
    for needed in ENVELOPE_FIELDS:
        if needed not in properties or needed not in required:
            refuse(f"{origin} does not require `{needed}`, which every envelope carries")
    lines = [f"class {name}(typing.TypedDict):", *docstring(f"The envelope carrying `{kind}`.", "    "), ""]
    for key in sorted(properties):
        if not is_field_name(key):
            refuse(f"{origin} carries `{key}`, which an envelope field cannot be named")
        if key == "kind":
            annotation = f"typing.Literal[{json.dumps(kind)}]"
        else:
            where = f"{origin} property `{key}`"
            annotation = writer.annotation(
                writer.node(properties[key], where),
                pascal(kind) + pascal(key),
                where,
            )
        if key not in required:
            annotation = f"typing.NotRequired[{annotation}]"
        lines.append(f"    {key}: {annotation}")
    return [*lines, "", ""]


def refusal_source(refusals: Mapping[str, Mapping[str, object]]) -> list[str]:
    """Write the refusal codes the contract lists, and what it says of each."""
    codes = sorted(refusals)
    union = f"typing.Literal[{', '.join(json.dumps(code) for code in codes)}]" if codes else "typing.Never"
    lines = [
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
        lines.append(
            f"    {json.dumps(code)}: ListedRefusal({json.dumps(listed['name'])}, {listed['status']}, "
            f"{json.dumps(listed['description'])}),",
        )
    lines.extend(
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
    return lines


def key_callable_source(callable_by_key: Sequence[ByKey]) -> list[str]:
    """Write the actions a key may call, and what the contract says of each."""
    quoted = [json.dumps(one.action) for one in callable_by_key]
    union = f"typing.Literal[{', '.join(quoted)}]" if quoted else "typing.Never"
    lines = [
        "",
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
        "",
        "",
        "KEY_CALLABLE: typing.Final[typing.Mapping[KeyCallableAction, KeyCallable]] = types.MappingProxyType({",
    ]
    lines.extend(
        f"    {json.dumps(one.action)}: KeyCallable({one.disturbs}, {one.rehearsal}),"
        for one in callable_by_key
    )
    lines.extend(
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
    return lines


def generate(artefact: Mapping[str, object], stamp: str) -> dict[pathlib.Path, str]:
    """Return every generated file's path and source, or raise the refusal."""
    if stamp != UNKNOWN and not REVISION.fullmatch(stamp):
        refuse(f"{STAMP} names {json.dumps(stamp)}, which is not a release tag or a full commit hash")
    version = artefact.get("api_version")
    if version != SPOKEN:
        refuse(
            f"the vendored contract is api_version {json.dumps(version)}, and this package implements "
            f"{SPOKEN}. Sync a matching release, or implement the newer version first.",
        )
    kinds = kinds_of(artefact)
    found = list(ambiguous(kinds, ""))
    if found:
        refuse(
            "the vendored contract puts a constraint beside a reference, and generating would drop "
            "one of the two:\n  " + "\n  ".join(found),
        )
    refusals = refusals_of(artefact)
    callable_by_key = key_callable_of(artefact)

    writer = Writer()
    names = sorted(kinds)
    for kind in names:
        writer.owned[f"{pascal(kind)}Envelope"] = f"the envelope carrying `{kind}`"
    envelopes: list[str] = []
    for kind in names:
        writer.kind = kind
        writer.definitions = as_map(kinds[kind].get("$defs", {}))
        for name in sorted(writer.definitions):
            writer.definition(name)
        envelopes.extend(envelope(writer, kind, kinds[kind]))

    quoted = ", ".join(json.dumps(kind) for kind in names)
    source = [
        "# Copyright (c) 2026 NightWorksIO",
        f'"""The lemonfiber contract\'s shapes, generated from the artefact at {stamp}.',
        "",
        "Do not edit: `just generate` rewrites this file from `contract/web-api.contract.json`,",
        "and CI fails on any difference.",
        '"""',
        "",
        "import types",
        "import typing",
        "",
        f"CONTRACT_API_VERSION: typing.Final = {SPOKEN}",
        '"""The wire version these shapes were generated for."""',
        "",
    ]
    written: set[str] = set()
    for name in ordered(writer.shapes):
        shape = writer.shapes[name]
        waiting = (
            frozenset(other for other, held in writer.shapes.items() if held.fields is not None) - written
        )
        source.extend(["", *shape.written(waiting), ""])
        written.add(name)
    source.extend(["", *envelopes])
    source.extend(
        [
            "",
            f"type Kind = typing.Literal[{quoted}]",
            '"""The name of every kind the server may send."""',
            "",
            f"KINDS: typing.Final[frozenset[Kind]] = frozenset(({quoted},))",
            '"""Every kind the server may send."""',
            "",
            f"type Envelope = {' | '.join(f'{pascal(kind)}Envelope' for kind in names)}",
            '"""The envelope of any kind, told apart by its `kind`."""',
            "",
            "",
            "class KindNarrowing(typing.Protocol):",
            '    """Narrows an envelope to the one kind it is expected to be."""',
            "",
        ],
    )
    for kind in names:
        signature = f"envelope: Envelope, kind: typing.Literal[{json.dumps(kind)}], /"
        source.extend(
            ["    @typing.overload", f"    def __call__(self, {signature}) -> {pascal(kind)}Envelope: ..."],
        )
    source.append("")
    source.extend(refusal_source(refusals))
    source.extend(key_callable_source(callable_by_key))
    published = sorted(
        {*writer.shapes, *(f"{pascal(kind)}Envelope" for kind in names), *OWNED} - {"typing", "types"},
    )
    source.extend(["", "", "__all__ = [", *(f"    {json.dumps(name)}," for name in published), "]"])

    package = [
        "# Copyright (c) 2026 NightWorksIO",
        f'"""Generated from the lemonfiber contract at {stamp}. Do not edit."""',
    ]
    return {OUT / "__init__.py": "\n".join(package) + "\n", OUT / "contract.py": "\n".join(source) + "\n"}


def read_artefact(root: pathlib.Path) -> tuple[dict[str, object], str]:
    """Return the vendored artefact and the revision it was taken from."""
    stamp_path = root / STAMP
    stamp = stamp_path.read_text(encoding="utf-8").strip() if stamp_path.is_file() else UNKNOWN
    try:
        artefact: object = json.loads((root / ARTEFACT).read_text(encoding="utf-8"))
    except (OSError, ValueError) as unreadable:
        message = f"{ARTEFACT} could not be read: {unreadable}"
        raise ArtefactRefusedError(message) from unreadable
    read = object_of(artefact)
    if read is None:
        refuse(f"{ARTEFACT} is not an object")
    return read, stamp


def run(root: pathlib.Path) -> int:
    """Generate into `root`, writing nothing when the artefact is refused."""
    try:
        artefact, stamp = read_artefact(root)
        files = generate(artefact, stamp)
    except ArtefactRefusedError as refused:
        sys.stderr.write(f"contract_generate: refused, and nothing was written: {refused}\n")
        return 1
    for path, source in files.items():
        target = root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(source, encoding="utf-8")
    sys.stdout.write(f"generated {len(kinds_of(artefact))} kinds from {stamp} into {OUT}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(run(ROOT))

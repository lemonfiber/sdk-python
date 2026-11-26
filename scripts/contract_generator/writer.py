# Copyright (c) 2026 NightWorksIO
"""Turns the artefact's schemas into Python declarations, each held by the kinds that carry it."""

import json
import keyword
import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, cast

from scripts.contract_generator.actions import DRY_RUN, NAMED, REQUEST
from scripts.contract_generator.artefact import (
    ANNOTATIONS,
    DIALECT,
    INLINE,
    array_of,
    as_list,
    as_map,
    as_maps,
    object_of,
)
from scripts.contract_generator.layout import ticked
from scripts.contract_generator.refused import ArtefactRefusedError, refuse
from scripts.contract_generator.shapes import Field, Shape, class_lines
from scripts.contract_generator.spelling import docstring, is_field_name, literal, pascal

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from scripts.contract_generator.actions import Described

NARROWING = frozenset(
    {
        "$defs",
        DIALECT,
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

DEFINITION = re.compile(r"^[A-Z]\w*$", re.ASCII)
"""A definition's name, as the artefact spells one."""

REFERENCE = re.compile(rf"^{re.escape(INLINE)}([^/]+)$")
"""A reference to a definition beside the one making it."""

PRIMITIVES = {"string": "str", "integer": "int", "number": "float", "boolean": "bool", "null": "None"}
"""The Python type of each JSON type that holds no other value."""

REHEARSING = "Whether to rehearse: write nothing, and answer with what the action would do."
"""What `dry_run` is, on every action that can be rehearsed."""

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
    "API": "what every read's path begins with",
    "Read": "a read answering with one envelope, named for its path",
    "ReadParameter": "one query parameter a read takes",
    "Readable": "what the contract says of one read",
    "READS": "what the contract says of each read answering with one envelope",
}
"""Names this generator writes itself, and what each one means here."""


def spelled_value(value: object) -> str:
    """Write a JSON value as the Python expression it is."""
    if value is None or isinstance(value, bool | int | float):
        return repr(value)
    items = array_of(value)
    if items is not None:
        return f"[{', '.join(spelled_value(item) for item in items)}]"
    entries = object_of(value)
    if entries is not None:
        return f"{{{', '.join(f'{json.dumps(key)}: {spelled_value(one)}' for key, one in entries.items())}}}"
    return json.dumps(value)


def defaulted(value: object) -> str:
    """Write a field's default: the value itself, or a factory for a list or an object, so no two requests share one."""
    if array_of(value) is None and object_of(value) is None:
        return spelled_value(value)
    return f"dataclasses.field(default_factory=lambda: {spelled_value(value)})"


def joined(node: dict[str, object], origin: str) -> dict[str, object]:
    """Return a schema holding fields beside a oneOf or anyOf as the union of each branch with them."""
    combinator = next((one for one in ("oneOf", "anyOf") if one in node), None)
    fields = object_of(node.get("properties"))
    if combinator is None or fields is None:
        return node
    needed = as_list(node.get("required", []))
    rest = {key: value for key, value in node.items() if key not in {"properties", "required", combinator}}
    branches: list[object] = []
    for at, branch in enumerate(as_list(node[combinator])):
        own = object_of(branch)
        if own is None or "$ref" in own:
            refuse(f"{origin} {combinator}/{at} is a branch the fields beside it cannot join")
        branches.append(
            {
                **own,
                "type": "object",
                "properties": {**fields, **(object_of(own.get("properties")) or {})},
                "required": [*needed, *as_list(own.get("required", []))],
            },
        )
    return {**rest, combinator: branches}


@dataclass
class Writer:
    """Turns the artefact's schemas into Python declarations."""

    users: Mapping[str, frozenset[str]] = field(default_factory=dict[str, frozenset[str]])
    """Each definition's name, to every kind whose definitions carry it."""
    owned: dict[str, str] = field(default_factory=lambda: dict(OWNED))
    kind: str = ""
    definitions: Mapping[str, object] = field(default_factory=dict[str, object])
    shapes: dict[str, Shape] = field(default_factory=dict[str, Shape])
    shared: dict[str, tuple[str, str]] = field(default_factory=dict[str, tuple[str, str]])
    """Each definition already emitted: the kind carrying it and its canonical JSON."""
    within: list[str] = field(default_factory=list[str])
    """The definitions being written, innermost last: a shape written inside one is carried as it is."""

    def carriers(self) -> frozenset[str]:
        """Return the kinds carrying what is being written now: the innermost definition's, or the kind's own."""
        if self.within:
            return self.users[self.within[-1]]
        return frozenset({self.kind})

    def claim(self, name: str, origin: str, lines: list[str], annotations: list[str]) -> str:
        """Record one declaration, refusing a name that something else holds."""
        if name in self.owned:
            refuse(f"{origin} would be written as `{name}`, which here names {self.owned[name]}")
        held = self.shapes.get(name)
        if held is not None:
            refuse(f"{origin} and {held.origin} would both be written as `{name}`")
        self.shapes[name] = Shape(name, origin, lines, self.carriers(), annotations)
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
        schema = self.definitions[name]
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
        self.within.append(name)
        self.declare(name, schema, f"`{name}`, defined by `{self.kind}`")
        self.within.pop()
        return name

    def declare(self, name: str, schema: object, origin: str) -> None:
        """Write one named declaration: a TypedDict for an object, an alias otherwise."""
        node = self.node(schema, origin)
        if self.is_object(node):
            self.typed_dict(name, node, origin)
            return
        annotation = self.annotation(node, name, origin)
        lines = [f"type {name} = {annotation}"]
        description = node.get("description")
        if isinstance(description, str):
            lines.extend(docstring(description, ""))
        self.claim(name, origin, lines, [annotation])

    @staticmethod
    def node(schema: object, origin: str) -> dict[str, object]:
        """Return a schema as an object, refusing one this generator does not read."""
        node = object_of(schema)
        if node is None:
            refuse(f"{origin} is {json.dumps(schema)}, which is not a schema this generator reads")
        unread = sorted(set(node) - UNDERSTOOD)
        if unread:
            refuse(f"{origin} uses {', '.join(unread)}, which this generator does not read")
        return joined(node, origin)

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
        annotations = [one.annotation for one in fields]
        if all(is_field_name(one.key) for one in fields):
            self.claim(name, origin, class_lines(name, description, fields), annotations)
            return
        self.claim(name, origin, [], annotations)
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
            if matched.group(1) not in self.definitions:
                refuse(f"{origin} refers to {reference}, which `{self.kind}` does not define")
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
        message = f"{origin} is of type {one!r}, which this generator does not read"
        raise ArtefactRefusedError(message)

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

    def envelope(self, schema: Mapping[str, object]) -> None:
        """Write the envelope TypedDict carrying the kind being written, its `kind` narrowed to that kind."""
        name = f"{pascal(self.kind)}Envelope"
        origin = f"the envelope of `{self.kind}`"
        properties = as_map(schema.get("properties", {}))
        required = set(cast("list[str]", schema.get("required", [])))
        for needed in ENVELOPE_FIELDS:
            if needed not in properties or needed not in required:
                refuse(f"{origin} does not require `{needed}`, which every envelope carries")
        lines = [
            f"class {name}(typing.TypedDict):",
            *docstring(f"The envelope carrying `{self.kind}`.", "    "),
            "",
        ]
        annotations: list[str] = []
        for key in sorted(properties):
            if not is_field_name(key):
                refuse(f"{origin} carries `{key}`, which an envelope field cannot be named")
            if key == "kind":
                annotation = f"typing.Literal[{json.dumps(self.kind)}]"
            else:
                where = f"{origin} property `{key}`"
                annotation = self.annotation(
                    self.node(properties[key], where),
                    pascal(self.kind) + pascal(key),
                    where,
                )
            annotations.append(annotation)
            if key not in required:
                annotation = f"typing.NotRequired[{annotation}]"
            lines.append(f"    {key}: {annotation}")
        self.shapes[name] = Shape(name, origin, lines, frozenset({self.kind}), annotations)

    def request(self, described: Described) -> None:
        """Write the request an action is posted with: each argument a field, defaulted as the contract defaults it."""
        name = f"{pascal(described.action)}Action"
        origin = f"the action `{described.action}`"
        summary = f"The action `{described.action}`, with the arguments it is posted with."
        if described.consent:
            verb = "carries" if len(described.consent) == 1 else "carry"
            summary += f" {ticked(described.consent)} {verb} the operator's yes."
        lines = [
            "@dataclasses.dataclass(frozen=True, kw_only=True, slots=True)",
            f"class {name}({REQUEST}):",
            *docstring(summary, "    "),
            "",
            f"    {NAMED} = {json.dumps(described.action)}",
            "",
        ]
        annotations = [REQUEST]
        for argument in described.arguments:
            where = f"{origin} argument `{argument.name}`"
            node = self.node(argument.schema, where)
            annotation = self.annotation(node, name + pascal(argument.name), where)
            annotations.append(annotation)
            spelled = f"{argument.name}_" if keyword.iskeyword(argument.name) else argument.name
            default = f" = {defaulted(node['default'])}" if "default" in node else ""
            lines.append(f"    {spelled}: {annotation}{default}")
            said = node.get("description")
            if isinstance(said, str):
                lines.extend(docstring(said, "    "))
        if described.rehearsal:
            lines.extend([f"    {DRY_RUN}: bool = False", *docstring(REHEARSING, "    ")])
        self.claim(name, origin, lines, annotations)
        self.shapes[name].standard = ("dataclasses",)

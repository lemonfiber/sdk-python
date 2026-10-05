# Copyright (c) 2026 NightWorksIO
"""The envelope every answer arrives in, read and refused where it cannot be spoken."""

import json
from typing import TYPE_CHECKING, Final, cast

from lemonfiber._generated.contract import CONTRACT_API_VERSION, KINDS, Envelope, Kind, KindNarrowing
from lemonfiber.problems import (
    ApiVersionMismatchError,
    UnexpectedKindError,
    UnknownKindError,
    UnreadableResponseError,
)

if TYPE_CHECKING:
    from collections.abc import Mapping

SPOKEN_API_VERSION: Final = CONTRACT_API_VERSION
"""The wire version this package speaks, as the contract it was generated from states it."""


def read_envelope(document: object) -> Envelope:
    """Read a decoded document as an envelope, typed by its kind.

    The version is checked before anything else is read: an answer in a version
    this package does not speak is refused whole, naming both versions.
    """
    if not isinstance(document, dict):
        msg = "it is not an envelope"
        raise UnreadableResponseError(msg)
    fields = cast("Mapping[str, object]", document)
    version = fields.get("api_version")
    if not isinstance(version, int) or isinstance(version, bool):
        msg = "it carries no api_version"
        raise UnreadableResponseError(msg)
    if version != SPOKEN_API_VERSION:
        raise ApiVersionMismatchError(SPOKEN_API_VERSION, version)
    kind = fields.get("kind")
    if not isinstance(kind, str) or not kind:
        msg = "it names no kind"
        raise UnreadableResponseError(msg)
    if "data" not in fields:
        msg = "it carries no data"
        raise UnreadableResponseError(msg)
    if kind not in KINDS:
        raise UnknownKindError(kind)
    return cast("Envelope", fields)


def parse_envelope(body: bytes | str) -> Envelope:
    """Parse an answer's body and read it as an envelope."""
    try:
        document: object = json.loads(body)
    except (ValueError, RecursionError) as unreadable:
        msg = "it is not JSON"
        raise UnreadableResponseError(msg) from unreadable
    return read_envelope(document)


def _expect(envelope: Envelope, kind: Kind, /) -> Envelope:
    if envelope["kind"] != kind:
        raise UnexpectedKindError(kind, envelope["kind"])
    return envelope


expect: Final = cast("KindNarrowing", _expect)
"""Narrow an envelope to the kind it is expected to be, refusing any other.

    status = expect(envelope, "status")  # a StatusEnvelope, or UnexpectedKindError
"""

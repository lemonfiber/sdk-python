# Copyright (c) 2026 NightWorksIO
"""The Python client for lemonfiber's web API.

Every answer is an envelope typed by its kind (`lemonfiber.contract` holds each
shape), an envelope in a version this package does not speak is refused naming
both versions, and every failure is a `LemonfiberError`.
"""

from lemonfiber._generated.contract import (
    KINDS,
    REFUSAL_CODES,
    Envelope,
    Kind,
    ListedRefusal,
    RefusalCode,
    is_refusal_code,
)
from lemonfiber.envelope import SPOKEN_API_VERSION, expect, parse_envelope, read_envelope
from lemonfiber.problems import (
    ApiVersionMismatchError,
    LemonfiberError,
    UnexpectedKindError,
    UnknownKindError,
    UnreadableResponseError,
)

__all__ = [
    "KINDS",
    "REFUSAL_CODES",
    "SPOKEN_API_VERSION",
    "ApiVersionMismatchError",
    "Envelope",
    "Kind",
    "LemonfiberError",
    "ListedRefusal",
    "RefusalCode",
    "UnexpectedKindError",
    "UnknownKindError",
    "UnreadableResponseError",
    "expect",
    "is_refusal_code",
    "parse_envelope",
    "read_envelope",
]

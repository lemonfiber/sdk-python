# Copyright (c) 2026 NightWorksIO
"""The Python client for lemonfiber's web API.

`AsyncClient` (aiohttp) and `SyncClient` (urllib3) speak the same contract with
the same behaviour. Each is built with an `Address` — loopback, or anywhere a
`CertificatePin` vouches for — and a `Credential`: the per-run token, a
session's secret, or an integration key. Every answer is an envelope typed by
its kind (`lemonfiber.contract` holds each shape), and every failure is a
`LemonfiberError`.
"""

from lemonfiber._aio import AsyncClient, admit_async
from lemonfiber._generated.contract import (
    KINDS,
    REFUSAL_CODES,
    Envelope,
    Kind,
    ListedRefusal,
    RefusalCode,
    is_refusal_code,
)
from lemonfiber._sync import SyncClient, admit
from lemonfiber._wire import Admitted, Bundle, Json, Query
from lemonfiber.address import Address, CertificatePin, Route
from lemonfiber.credential import CREDENTIAL_HEADER, Credential
from lemonfiber.envelope import SPOKEN_API_VERSION, expect, parse_envelope, read_envelope
from lemonfiber.jobs import Ended, Finished, JobStanding, Running
from lemonfiber.problems import (
    AddressRefusedError,
    ApiVersionMismatchError,
    BusyError,
    CertificateRefusedError,
    ConfigurationError,
    CredentialRefusedError,
    DeclinedError,
    FailedError,
    LemonfiberError,
    MisaskedError,
    MissingError,
    NoSuchJobError,
    NotAdmittedError,
    PasswordRefusedError,
    RefusedError,
    StillRunningError,
    TooManyAttemptsError,
    UnexpectedKindError,
    UnknownKindError,
    UnreachableError,
    UnreadableResponseError,
)
from lemonfiber.reads import Read

__all__ = [
    "CREDENTIAL_HEADER",
    "KINDS",
    "REFUSAL_CODES",
    "SPOKEN_API_VERSION",
    "Address",
    "AddressRefusedError",
    "Admitted",
    "ApiVersionMismatchError",
    "AsyncClient",
    "Bundle",
    "BusyError",
    "CertificatePin",
    "CertificateRefusedError",
    "ConfigurationError",
    "Credential",
    "CredentialRefusedError",
    "DeclinedError",
    "Ended",
    "Envelope",
    "FailedError",
    "Finished",
    "JobStanding",
    "Json",
    "Kind",
    "LemonfiberError",
    "ListedRefusal",
    "MisaskedError",
    "MissingError",
    "NoSuchJobError",
    "NotAdmittedError",
    "PasswordRefusedError",
    "Query",
    "Read",
    "RefusalCode",
    "RefusedError",
    "Route",
    "Running",
    "StillRunningError",
    "SyncClient",
    "TooManyAttemptsError",
    "UnexpectedKindError",
    "UnknownKindError",
    "UnreachableError",
    "UnreadableResponseError",
    "admit",
    "admit_async",
    "expect",
    "is_refusal_code",
    "parse_envelope",
    "read_envelope",
]

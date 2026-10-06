# Copyright (c) 2026 NightWorksIO
"""Reading the envelope every answer arrives in."""

import json

import pytest

from lemonfiber import (
    SPOKEN_API_VERSION,
    ApiVersionMismatchError,
    LemonfiberError,
    UnexpectedKindError,
    UnknownKindError,
    UnreadableResponseError,
    expect,
    parse_envelope,
    read_envelope,
)
from lemonfiber._generated import CONTRACT_API_VERSION

STATUS = {"api_version": SPOKEN_API_VERSION, "kind": "pull", "data": "an image"}


def test_the_spoken_version_is_the_contracts() -> None:
    assert SPOKEN_API_VERSION == CONTRACT_API_VERSION


def test_an_envelope_is_read_as_it_arrived() -> None:
    envelope = read_envelope(dict(STATUS))
    assert envelope == STATUS


def test_a_body_is_parsed_from_bytes_and_from_text() -> None:
    assert parse_envelope(json.dumps(STATUS).encode()) == STATUS
    assert parse_envelope(json.dumps(STATUS)) == STATUS


def test_another_version_is_refused_naming_both() -> None:
    with pytest.raises(ApiVersionMismatchError) as refused:
        read_envelope({**STATUS, "api_version": SPOKEN_API_VERSION + 1})
    assert refused.value.spoken == SPOKEN_API_VERSION
    assert refused.value.served == SPOKEN_API_VERSION + 1
    assert str(refused.value) == (
        f"This client speaks version {SPOKEN_API_VERSION} of lemonfiber's interface and the stack answered "
        f"in version {SPOKEN_API_VERSION + 1}. Nothing from that answer was used; update whichever of the two is older."
    )


def test_the_version_is_refused_before_the_rest_is_read() -> None:
    with pytest.raises(ApiVersionMismatchError):
        read_envelope({"api_version": 0})


@pytest.mark.parametrize(
    ("document", "what"),
    [
        ([], "it is not an envelope"),
        ({"kind": "pull", "data": ""}, "it carries no api_version"),
        ({**STATUS, "api_version": "1"}, "it carries no api_version"),
        ({**STATUS, "api_version": True}, "it carries no api_version"),
        ({"api_version": SPOKEN_API_VERSION, "data": ""}, "it names no kind"),
        ({**STATUS, "kind": ""}, "it names no kind"),
        ({**STATUS, "kind": 3}, "it names no kind"),
        ({"api_version": SPOKEN_API_VERSION, "kind": "pull"}, "it carries no data"),
    ],
)
def test_a_document_that_is_not_an_envelope_is_refused(document: object, what: str) -> None:
    with pytest.raises(UnreadableResponseError) as refused:
        read_envelope(document)
    assert refused.value.what == what
    assert str(refused.value) == f"That answer did not come from lemonfiber: {what}."


def test_null_data_is_still_data() -> None:
    assert read_envelope({**STATUS, "data": None})["data"] is None


@pytest.mark.parametrize("body", [b"<html>", b"\xff\xfe", "", "[" * 100_000])
def test_a_body_that_is_not_json_is_refused(body: bytes | str) -> None:
    with pytest.raises(UnreadableResponseError) as refused:
        parse_envelope(body)
    assert refused.value.what == "it is not JSON"


def test_a_kind_this_package_was_not_generated_with_is_refused_by_name() -> None:
    with pytest.raises(UnknownKindError) as refused:
        read_envelope({**STATUS, "kind": "from-the-future"})
    assert refused.value.kind == "from-the-future"
    assert str(refused.value) == (
        "The stack answered with a 'from-the-future' document, which this client does not know. "
        "The stack is newer than this client; update the client."
    )


def test_an_envelope_narrows_to_the_kind_it_is() -> None:
    envelope = read_envelope(dict(STATUS))
    assert expect(envelope, "pull")["data"] == "an image"


def test_an_envelope_of_another_kind_is_refused() -> None:
    envelope = read_envelope(dict(STATUS))
    with pytest.raises(UnexpectedKindError) as refused:
        expect(envelope, "status")
    assert (refused.value.expected, refused.value.received) == ("status", "pull")
    assert (
        str(refused.value) == "The stack answered with a 'pull' document where a 'status' one was expected."
    )


def test_every_problem_is_a_lemonfiber_error() -> None:
    for problem in (UnreadableResponseError, ApiVersionMismatchError, UnknownKindError, UnexpectedKindError):
        assert issubclass(problem, LemonfiberError)


def test_an_answer_that_is_not_json_is_refused_holding_nothing_of_it() -> None:
    with pytest.raises(UnreadableResponseError) as refused:
        parse_envelope(b'{"kind": "admission", "data": {"token": "minted-and-secret"')
    assert refused.value.__cause__ is None
    assert refused.value.__context__ is None

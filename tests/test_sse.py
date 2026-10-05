# Copyright (c) 2026 NightWorksIO
"""Reading the event-stream format a chunk at a time."""

import pytest

from lemonfiber._sse import Event, Parser


def test_an_event_is_its_id_name_and_data() -> None:
    assert Parser().push(b"id: 1\nevent: status\ndata: {}\n\n") == [Event("1", "status", "{}")]


def test_an_event_without_a_name_is_a_message_and_without_an_id_has_none() -> None:
    assert Parser().push(b"data: x\n\n") == [Event(None, "message", "x")]


def test_lines_of_data_join_with_a_line_break() -> None:
    assert Parser().push(b"data: a\ndata: b\n\n") == [Event(None, "message", "a\nb")]


@pytest.mark.parametrize("ending", [b"\r\n", b"\r", b"\n"])
def test_each_line_ending_ends_a_line(ending: bytes) -> None:
    chunk = ending.join([b"id: 2", b"data:  spaced", b"", b""]) + b": next"
    assert Parser().push(chunk) == [Event("2", "message", " spaced")]


def test_a_carriage_return_at_the_end_of_a_chunk_waits_for_what_follows() -> None:
    parser = Parser()
    assert parser.push(b"data: a\r") == []
    assert parser.push(b"\n\r\n") == [Event(None, "message", "a")]


def test_a_comment_and_an_unknown_field_carry_nothing() -> None:
    assert Parser().push(b": heartbeat\n\nretry: 10\nfield\ndata: y\n\n") == [Event(None, "message", "y")]


def test_a_blank_line_with_nothing_gathered_is_no_event() -> None:
    assert Parser().push(b"\n\nid: 3\n\n") == []


def test_a_character_split_across_chunks_arrives_whole() -> None:
    parser = Parser()
    encoded = "data: café\n\n".encode()
    assert parser.push(encoded[:10]) == []
    assert parser.push(encoded[10:]) == [Event(None, "message", "café")]

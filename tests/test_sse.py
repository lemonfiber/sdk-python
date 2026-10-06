# Copyright (c) 2026 NightWorksIO
"""Reading the event-stream format a chunk at a time."""

import time

import pytest

from lemonfiber import UnreadableResponseError
from lemonfiber._sse import LARGEST, Event, Parser


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


def test_a_line_longer_than_an_event_may_be_is_refused_before_it_is_held() -> None:
    parser = Parser(largest=10)
    assert parser.push(b"data: 1234") == []
    with pytest.raises(UnreadableResponseError) as refused:
        parser.push(b"5")
    assert refused.value.what == "the stream carried a line longer than the 10 characters an event may be"


def test_an_event_larger_than_an_event_may_be_is_refused_before_it_completes() -> None:
    parser = Parser(largest=10)
    assert parser.push(b"data: 12345\ndata: 1234\n") == []
    with pytest.raises(UnreadableResponseError) as refused:
        parser.push(b"data: 6\n")
    assert refused.value.what == "the stream carried an event larger than the 10 characters an event may be"


def test_an_event_as_large_as_an_event_may_be_arrives() -> None:
    parser = Parser(largest=10)
    assert parser.push(b"data: 12345\ndata: 1234\n\n") == [Event(None, "message", "12345\n1234")]


def test_an_event_may_be_megabytes() -> None:
    assert LARGEST == 16 * 1024 * 1024
    assert Parser().push(b"data: " + b"x" * (4 * 1024 * 1024) + b"\n\n")[0].data == "x" * (4 * 1024 * 1024)


def test_a_long_line_arriving_in_small_chunks_is_read_in_time_proportional_to_it() -> None:
    parser = Parser()
    started = time.monotonic()
    for _ in range(2048):
        parser.push(b"x" * 128)
    assert parser.push(b"\n\n") == []
    many = parser.push(b"data: 1\n\n" * 20000)
    assert len(many) == 20000
    assert time.monotonic() - started < 2.0


def test_a_sequence_that_is_not_utf8_arrives_as_the_replacement_character() -> None:
    assert Parser().push(b"data: a\xffb\n\n") == [Event(None, "message", "a�b")]


def test_a_carriage_return_at_the_end_of_a_chunk_ends_its_line_once_more_arrives() -> None:
    parser = Parser()
    assert parser.push(b"data: a\n\r") == []
    assert parser.push(b"x") == [Event(None, "message", "a")]


def test_a_line_ended_by_a_carriage_return_alone_is_read_at_once() -> None:
    assert Parser().push(b"data: a\r\rx") == [Event(None, "message", "a")]


def test_a_carriage_return_and_line_feed_split_across_chunks_end_one_line() -> None:
    parser = Parser()
    assert parser.push(b"data: a\r") == []
    assert parser.push(b"\n") == []
    assert parser.push(b"data: b\n\n") == [Event(None, "message", "a\nb")]


def test_a_carriage_return_held_counts_toward_the_longest_line() -> None:
    parser = Parser(largest=9)
    with pytest.raises(UnreadableResponseError):
        parser.push(b"data: 123\r")


def test_data_one_character_past_what_an_event_may_be_is_refused() -> None:
    parser = Parser(largest=10)
    with pytest.raises(UnreadableResponseError):
        parser.push(b"data: 12345\ndata: 12345\n")

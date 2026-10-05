# Copyright (c) 2026 NightWorksIO
"""The `text/event-stream` wire format, read a chunk at a time."""

import codecs
from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class Event:
    """One event as the stream carried it: its id, its name and its data."""

    id: str | None
    name: str
    data: str


@dataclass(slots=True)
class _Pending:
    id: str | None = None
    name: str = "message"
    data: list[str] = field(default_factory=list[str])


class Parser:
    """Gathers chunks and hands back each event as it completes.

    A chunk may end inside a line and a line inside a UTF-8 sequence, so bytes
    are held until they decode, text until a line ends, and an event until a
    blank line ends it. A comment line is the heartbeat and carries nothing.
    """

    def __init__(self) -> None:
        """Start with nothing gathered."""
        self._decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")
        self._buffer = ""
        self._pending = _Pending()

    def push(self, chunk: bytes) -> list[Event]:
        """Return the events this chunk completes, in order."""
        self._buffer += self._decoder.decode(chunk)
        done: list[Event] = []
        while (end := self._line_end()) is not None:
            line, self._buffer = self._buffer[: end[0]], self._buffer[end[1] :]
            event = self._line(line)
            if event is not None:
                done.append(event)
        return done

    def _line_end(self) -> tuple[int, int] | None:
        """Return where the first complete line ends and where the next begins."""
        for at, character in enumerate(self._buffer):
            if character == "\n":
                return at, at + 1
            if character == "\r":
                if at + 1 == len(self._buffer):
                    return None
                return at, at + 2 if self._buffer[at + 1] == "\n" else at + 1
        return None

    def _line(self, line: str) -> Event | None:
        if not line:
            return self._complete()
        if line.startswith(":"):
            return None
        name, _, value = line.partition(":")
        value = value.removeprefix(" ")
        if name == "id":
            self._pending.id = value
        elif name == "event":
            self._pending.name = value
        elif name == "data":
            self._pending.data.append(value)
        return None

    def _complete(self) -> Event | None:
        pending, self._pending = self._pending, _Pending()
        if not pending.data:
            return None
        return Event(pending.id, pending.name, "\n".join(pending.data))

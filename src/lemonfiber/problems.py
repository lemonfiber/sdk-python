# Copyright (c) 2026 NightWorksIO
"""What can go wrong between a caller and lemonfiber, each as its own type.

Every exception this package raises is a `LemonfiberError`. Each subclass is one
thing a caller can act on, and its message is a plain sentence for a person.
"""


class LemonfiberError(Exception):
    """Something stood between the caller and an answer from lemonfiber."""


class UnreadableResponseError(LemonfiberError):
    """An answer arrived that is not a document lemonfiber writes."""

    def __init__(self, what: str) -> None:
        """Say which part of the answer could not be read."""
        super().__init__(f"That answer did not come from lemonfiber: {what}.")
        self.what = what


class ApiVersionMismatchError(LemonfiberError):
    """The stack answered in a version of the interface this package does not speak."""

    def __init__(self, spoken: int, served: int) -> None:
        """Name the version this package speaks and the one the stack answered in."""
        super().__init__(
            f"This client speaks version {spoken} of lemonfiber's interface and the stack answered "
            f"in version {served}. Nothing from that answer was used; update whichever of the two is older.",
        )
        self.spoken = spoken
        self.served = served


class UnknownKindError(LemonfiberError):
    """The stack answered with a kind of document this package was not generated with."""

    def __init__(self, kind: str) -> None:
        """Name the kind that arrived."""
        super().__init__(
            f"The stack answered with a {kind!r} document, which this client does not know. "
            "The stack is newer than this client; update the client.",
        )
        self.kind = kind


class UnexpectedKindError(LemonfiberError):
    """An answer was a different kind of document from the one it was read as."""

    def __init__(self, expected: str, received: str) -> None:
        """Name the kind that was expected and the kind that arrived."""
        super().__init__(
            f"The stack answered with a {received!r} document where a {expected!r} one was expected.",
        )
        self.expected = expected
        self.received = received

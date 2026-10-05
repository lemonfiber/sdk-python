# Copyright (c) 2026 NightWorksIO
"""The stand-in stacks and the client of each flavour, shared by every test."""

from typing import TYPE_CHECKING

import pytest

from lemonfiber import Address, Credential
from tests.drivers import FLAVOURS, connect
from tests.stack import Stack

if TYPE_CHECKING:
    from collections.abc import Iterator

    from tests.drivers import Driver, Flavour

PRINTED = "per-run-token-0123456789abcdef"


@pytest.fixture(params=FLAVOURS)
def flavour(request: pytest.FixtureRequest) -> Flavour:
    """Run the test once with each client."""
    return request.param


@pytest.fixture
def stack() -> Iterator[Stack]:
    """Serve plain HTTP on loopback."""
    with Stack() as serving:
        yield serving


@pytest.fixture
def tls_stack() -> Iterator[Stack]:
    """Serve TLS on loopback, with a certificate no trust store holds."""
    with Stack(tls=True) as serving:
        yield serving


@pytest.fixture
def client(flavour: Flavour, stack: Stack) -> Iterator[Driver]:
    """Talk to the plain stand-in with the per-run token, with the flavour this run is for."""
    driver = connect(flavour, Address(stack.url), Credential(PRINTED))
    yield driver
    driver.close()

# Copyright (c) 2026 NightWorksIO
"""Generating every route the web API serves, and refusing a route the generator cannot write."""

from typing import TYPE_CHECKING

import pytest

from tests.generating import artefact, generated, kind, refusal

if TYPE_CHECKING:
    import pathlib

PULL: dict[str, object] = {"pull": kind({"type": "string"})}


def routed(method: object, path: object, *, body: object = False, kinds: object = None) -> dict[str, object]:
    """Return one route as the contract lists it."""
    return {"method": method, "path": path, "body": body, "kinds": ["pull"] if kinds is None else kinds}


def test_the_routes_are_generated_in_the_contracts_order_with_what_each_takes(tmp_path: pathlib.Path) -> None:
    listed = [
        routed("DELETE", "/api/keys/{name}", body=True),
        routed("GET", "/api/bundle/{name}", kinds=[]),
        routed("POST", "/api/keys", body=True),
    ]
    module = generated(tmp_path, {**artefact(PULL), "routes": listed})
    assert (
        module.Route("DELETE", "/api/keys/{name}", body=True, kinds=("pull",)),
        module.Route("GET", "/api/bundle/{name}", body=False, kinds=()),
        module.Route("POST", "/api/keys", body=True, kinds=("pull",)),
    ) == module.ROUTES


def test_an_artefact_older_than_the_routes_generates_none(tmp_path: pathlib.Path) -> None:
    assert generated(tmp_path, artefact(PULL)).ROUTES == ()


@pytest.mark.parametrize(
    ("listed", "said"),
    [
        ({"routes": {}}, "the vendored contract's routes are {}, and they are a list of routes"),
        ({"routes": [3]}, "route 0: not an object"),
        (
            {"routes": [routed("PATCH", "/api/keys")]},
            'route 0: method "PATCH" is not one of GET, POST, DELETE',
        ),
        ({"routes": [routed("GET", "/keys")]}, 'route 0: path "/keys" is not a route\'s path'),
        ({"routes": [routed("GET", "/api/keys", body="no")]}, 'route 0: body "no" is not true or false'),
        (
            {"routes": [routed("GET", "/api/keys", kinds="pull")]},
            'route 0: kinds "pull" is not a list of kinds',
        ),
        (
            {"routes": [routed("GET", "/api/keys", kinds=["start"])]},
            "route 0: answers with start, which the contract",
        ),
        (
            {"routes": [{**routed("GET", "/api/keys"), "more": 1}]},
            "route 0: carries more, which this generator",
        ),
        (
            {"routes": [routed("GET", "/api/keys"), routed("GET", "/api/keys")]},
            "route 1: GET /api/keys is listed twice",
        ),
    ],
)
def test_a_route_this_cannot_write_is_refused_naming_where_it_sits(
    listed: dict[str, object],
    said: str,
) -> None:
    assert said in refusal({**artefact(PULL), **listed})


def test_one_path_served_at_two_methods_is_two_routes(tmp_path: pathlib.Path) -> None:
    listed = [routed("GET", "/api/keys"), routed("POST", "/api/keys", body=True)]
    assert len(generated(tmp_path, {**artefact(PULL), "routes": listed}).ROUTES) == len(listed)

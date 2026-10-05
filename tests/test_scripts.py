# Copyright (c) 2026 NightWorksIO
"""The scripts that vendor the contract, judge a mutation run and compare the surface with consumers."""

import base64
import http.client
import io
import json
import urllib.request
from typing import TYPE_CHECKING

import pytest

from scripts import backward_compat, contract_sync, mutation_score

if TYPE_CHECKING:
    import pathlib

REVISION = "d2bf74b950a9f6fb73f2bcd60e2d8adf85337cd6"
SERVED = json.dumps({"api_version": 1, "kinds": {"pull": {}, "start": {}}}).encode()


def test_a_revision_is_vendored_beside_the_revision_it_came_from(tmp_path: pathlib.Path) -> None:
    asked: list[str] = []

    def take(revision: str) -> bytes:
        asked.append(revision)
        return SERVED

    assert contract_sync.run([REVISION], tmp_path, take) == 0
    assert asked == [REVISION]
    assert (tmp_path / "contract/web-api.contract.json").read_bytes() == SERVED
    assert (tmp_path / "contract/VERSION").read_text(encoding="utf-8") == f"{REVISION}\n"


@pytest.mark.parametrize("arguments", [[], ["main"], ["d2bf74b"], ["v1.0"]])
def test_a_revision_that_names_no_one_artefact_is_refused(
    tmp_path: pathlib.Path,
    arguments: list[str],
) -> None:
    assert contract_sync.run(arguments, tmp_path, lambda _: SERVED) == 1
    assert not (tmp_path / "contract").exists()


@pytest.mark.parametrize(
    "served",
    [b"{", b"[]", json.dumps({"api_version": 1}).encode(), json.dumps({"kinds": {}}).encode()],
)
def test_what_is_not_an_artefact_is_refused_and_nothing_is_written(
    tmp_path: pathlib.Path,
    served: bytes,
) -> None:
    assert contract_sync.run(["v1.0.0"], tmp_path, lambda _: served) == 1
    assert not (tmp_path / "contract").exists()


def test_a_revision_serving_nothing_is_refused(tmp_path: pathlib.Path) -> None:
    def take(revision: str) -> bytes:
        message = f"{revision} serves no artefact"
        raise contract_sync.SyncRefusedError(message)

    assert contract_sync.run(["v1.0.0"], tmp_path, take) == 1


def test_a_redirect_off_https_is_refused() -> None:
    handler = contract_sync.HttpsOnly()
    request = urllib.request.Request("https://raw.githubusercontent.com/x")
    with pytest.raises(contract_sync.SyncRefusedError, match="not HTTPS"):
        handler.redirect_request(request, io.BytesIO(), 302, "Found", http.client.HTTPMessage(), "http://x")


def test_a_redirect_to_https_is_followed() -> None:
    handler = contract_sync.HttpsOnly()
    request = urllib.request.Request("https://raw.githubusercontent.com/x")
    followed = handler.redirect_request(
        request,
        io.BytesIO(),
        302,
        "Found",
        http.client.HTTPMessage(),
        "https://y",
    )
    assert followed is not None
    assert followed.full_url == "https://y"


def write_score(root: pathlib.Path, stats: dict[str, int], minimum: int = 90) -> None:
    """Leave a mutation run's stats and a minimum where the score script reads them."""
    (root / "mutants").mkdir()
    (root / "mutants/mutmut-cicd-stats.json").write_text(json.dumps(stats), encoding="utf-8")
    (root / "pyproject.toml").write_text(
        f"[tool.lemonfiber.mutation]\nminimum-score = {minimum}\n",
        encoding="utf-8",
    )


def test_a_score_at_the_minimum_passes(tmp_path: pathlib.Path, capsys: pytest.CaptureFixture[str]) -> None:
    write_score(tmp_path, {"total": 12, "skipped": 2, "killed": 8, "timeout": 1, "survived": 1})
    assert mutation_score.run(tmp_path) == 0
    assert "mutation score 90.00% (9 of 10" in capsys.readouterr().out


def test_a_score_below_the_minimum_fails(tmp_path: pathlib.Path, capsys: pytest.CaptureFixture[str]) -> None:
    write_score(tmp_path, {"total": 10, "killed": 8, "survived": 1, "no_tests": 1})
    assert mutation_score.run(tmp_path) == 1
    assert "80.00%" in capsys.readouterr().err


def test_a_run_judging_no_mutants_fails(tmp_path: pathlib.Path) -> None:
    write_score(tmp_path, {"total": 3, "skipped": 3})
    assert mutation_score.run(tmp_path) == 1


def test_no_run_fails(tmp_path: pathlib.Path) -> None:
    assert mutation_score.run(tmp_path) == 1


def test_the_minimum_is_the_projects() -> None:
    assert mutation_score.minimum(mutation_score.ROOT) > 0


MAP = """
[[repo]]
name = "sdk-python"
lang = "Python"

[[repo]]
name = "integration-home-assistant"
lang = "Python"

[[repo]]
name = "lemonfiber"
lang = "Rust"

[[edge]]
from = "lemonfiber"
to = "sdk-python"

[[edge]]
from = "integration-home-assistant"
to = "sdk-python"

[[edge]]
from = "integration-home-assistant"
to = "lemonfiber"
"""


def spec_with(root: pathlib.Path, text: str) -> pathlib.Path:
    """Write a spec checkout holding only this map."""
    (root / "30-repos").mkdir(parents=True)
    (root / "30-repos/repos.toml").write_text(text, encoding="utf-8")
    return root


def test_the_consumers_are_the_python_repositories_drawn_to_this_one(tmp_path: pathlib.Path) -> None:
    assert backward_compat.consumers(spec_with(tmp_path, MAP)) == ["integration-home-assistant"]


def recording(
    pin: str,
    path: str = "custom_components/lemonfiber/_vendor/lemonfiber/REVISION",
) -> backward_compat.Fetch:
    """Answer as GitHub would for a consumer recording this pin at this path."""

    def fetch(asked: str) -> object:
        if asked.endswith("/git/trees/HEAD?recursive=1"):
            return {"tree": [{"path": "README.md"}, {"path": path}]}
        return {"content": base64.b64encode(f"{pin}\n".encode()).decode()}

    return fetch


def answers_nothing(_asked: str) -> object:
    """Answer as GitHub does for a repository that is missing or empty."""
    return None


def test_a_pin_is_read_from_wherever_the_consumer_vendors() -> None:
    assert list(backward_compat.pins("x", recording(REVISION))) == [REVISION]
    assert list(backward_compat.pins("x", recording(REVISION, "_vendor/lemonfiber/REVISION"))) == [REVISION]
    assert list(backward_compat.pins("x", recording(REVISION, "other/REVISION"))) == []


def test_an_empty_or_missing_consumer_pins_nothing() -> None:
    assert list(backward_compat.pins("x", answers_nothing)) == []


def test_no_consumer_and_no_pin_compare_nothing_and_say_so(
    tmp_path: pathlib.Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert backward_compat.run(spec_with(tmp_path / "a", "repo = []\n"), tmp_path, answers_nothing) == 0
    assert "names no consumer" in capsys.readouterr().out
    assert backward_compat.run(spec_with(tmp_path / "b", MAP), tmp_path, answers_nothing) == 0
    assert "records no vendored commit" in capsys.readouterr().out


def test_a_pin_that_is_not_a_commit_fails(tmp_path: pathlib.Path) -> None:
    assert backward_compat.run(spec_with(tmp_path, MAP), tmp_path, recording("main")) == 1


def test_a_breakage_against_a_pin_fails_naming_the_consumer(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    def breaking(against: str, _repo: pathlib.Path) -> list[str]:
        return [f"removed `x` since {against[:4]}"]

    monkeypatch.setattr(backward_compat, "breakages", breaking)
    assert backward_compat.run(spec_with(tmp_path, MAP), tmp_path, recording(REVISION)) == 1
    assert (
        "breaks integration-home-assistant, which vendors d2bf74b9: removed `x` since d2bf"
        in capsys.readouterr().out
    )


def test_no_breakage_against_a_pin_passes(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def breaking_nothing(_against: str, _repo: pathlib.Path) -> list[str]:
        return []

    monkeypatch.setattr(backward_compat, "breakages", breaking_nothing)
    assert backward_compat.run(spec_with(tmp_path, MAP), tmp_path, recording(REVISION)) == 0

# Copyright (c) 2026 NightWorksIO
"""The scripts that vendor the contract, judge a mutation run and compare the surface with consumers."""

import http.client
import io
import json
import urllib.error
import urllib.request
from typing import TYPE_CHECKING, Self

import pytest

from scripts import (
    backward_compat,
    contract_sync,
    mutation_score,
    what_the_bump_takes,
)
from tests.serving import SINGLE, SPLIT, tarball

if TYPE_CHECKING:
    import pathlib

REVISION = "d2bf74b950a9f6fb73f2bcd60e2d8adf85337cd6"
SERVED = tarball(SINGLE)


def test_a_revision_is_vendored_beside_the_revision_it_came_from(tmp_path: pathlib.Path) -> None:
    asked: list[str] = []

    def take(revision: str) -> bytes:
        asked.append(revision)
        return SERVED

    assert contract_sync.run([REVISION], tmp_path, take) == 0
    assert asked == [REVISION]
    vendored = json.loads((tmp_path / "contract/web-api.contract.json").read_bytes())
    assert vendored == SINGLE["contract/web-api.contract.json"]
    assert (tmp_path / "contract/VERSION").read_text(encoding="utf-8") == f"{REVISION}\n"
    assert sorted(path.name for path in (tmp_path / "contract").iterdir()) == [
        "VERSION",
        "web-api.contract.json",
    ]


def test_a_revision_holding_the_directory_is_vendored_as_the_directory_and_the_single_file_removed(
    tmp_path: pathlib.Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert contract_sync.run([REVISION], tmp_path, lambda _: SERVED) == 0
    (tmp_path / "contract/web-api/defs").mkdir(parents=True)
    (tmp_path / "contract/web-api/defs/Dropped.json").write_text("{}", encoding="utf-8")
    assert contract_sync.run([REVISION], tmp_path, lambda _: tarball({**SPLIT, **SINGLE})) == 0
    held = sorted(path.relative_to(tmp_path).as_posix() for path in tmp_path.rglob("*") if path.is_file())
    assert held == sorted(["contract/VERSION", *SPLIT])
    for path, written in SPLIT.items():
        assert json.loads((tmp_path / path).read_bytes()) == written
    assert (
        "2 kinds, from d2bf74b950a9f6fb73f2bcd60e2d8adf85337cd6 as contract/web-api."
        in capsys.readouterr().out
    )


def test_a_revision_holding_the_single_file_removes_a_vendored_directory(tmp_path: pathlib.Path) -> None:
    assert contract_sync.run([REVISION], tmp_path, lambda _: tarball(SPLIT)) == 0
    assert contract_sync.run([REVISION], tmp_path, lambda _: SERVED) == 0
    assert not (tmp_path / "contract/web-api").exists()
    assert (tmp_path / "contract/web-api.contract.json").is_file()


@pytest.mark.parametrize("arguments", [[], ["main"], ["d2bf74b"], ["v1.0"]])
def test_a_revision_that_names_no_one_contract_is_refused(
    tmp_path: pathlib.Path,
    arguments: list[str],
) -> None:
    assert contract_sync.run(arguments, tmp_path, lambda _: SERVED) == 1
    assert not (tmp_path / "contract").exists()


INDEX = "contract/web-api/index.json"


@pytest.mark.parametrize(
    ("served", "said"),
    [
        (b"{", "is not a gzipped tarball"),
        (
            tarball({"contract/plugin-manifest.schema.json": {}}),
            "holds neither contract/web-api/index.json nor",
        ),
        (tarball({"contract/web-api.contract.json": b"{"}), "contract/web-api.contract.json at "),
        (tarball({"contract/web-api.contract.json": []}), "contract/web-api.contract.json at d2bf74b9"),
        (tarball({"contract/web-api.contract.json": {"api_version": 1}}), "names no api_version or no kinds"),
        (tarball({"contract/web-api.contract.json": {"kinds": {}}}), "names no api_version or no kinds"),
        (tarball({**SPLIT, "contract/web-api/defs/Code.json": b"{"}), "contract/web-api/defs/Code.json at"),
        (tarball({**SPLIT, INDEX: []}), "contract/web-api/index.json at d2bf74b9"),
        (
            tarball({**SPLIT, INDEX: {"api_version": 1, "kinds": {"pull": "kinds/push.json"}}}),
            '"kinds/push.json"',
        ),
        (tarball({**SPLIT, INDEX: {"api_version": 1, "kinds": {"pull": 3}}}), "index.json at d2bf74b9"),
        (
            tarball({**SPLIT, INDEX: {"api_version": 1, "kinds": {}, "reads": "../reads.json"}}),
            '"../reads.json"',
        ),
        (
            tarball(SPLIT, links=("contract/web-api/defs/Link.json",)),
            "defs/Link.json, which is not a plain file",
        ),
        (
            tarball({**SPLIT, "contract/web-api/../web-api/defs/A.json": {}}),
            "web-api/../web-api/defs/A.json, which",
        ),
    ],
)
def test_what_is_not_a_contract_is_refused_and_nothing_is_written(
    tmp_path: pathlib.Path,
    capsys: pytest.CaptureFixture[str],
    served: bytes,
    said: str,
) -> None:
    assert contract_sync.run([REVISION], tmp_path, lambda _: served) == 1
    assert not (tmp_path / "contract").exists()
    assert said in capsys.readouterr().err


def test_a_revision_serving_nothing_is_refused(tmp_path: pathlib.Path) -> None:
    def take(revision: str) -> bytes:
        message = f"{revision} serves no tree"
        raise contract_sync.SyncRefusedError(message)

    assert contract_sync.run(["v1.0.0"], tmp_path, take) == 1


def test_a_redirect_off_https_is_refused() -> None:
    handler = contract_sync.HttpsOnly()
    request = urllib.request.Request("https://raw.githubusercontent.com/x")
    body, headers = io.BytesIO(), http.client.HTTPMessage()
    with pytest.raises(contract_sync.SyncRefusedError, match="not HTTPS"):
        handler.redirect_request(request, body, 302, "Found", headers, "http://x")


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


class Served:
    """An answer an opener hands back, holding these bytes."""

    def __init__(self, body: bytes) -> None:
        """Hold the bytes the answer reads."""
        super().__init__()
        self.body = body

    def __enter__(self) -> Self:
        """Open the answer, as `with` does."""
        return self

    def __exit__(self, *_: object) -> None:
        """Close the answer, holding nothing to close."""

    def read(self) -> bytes:
        """Return the bytes served."""
        return self.body


class Opener:
    """An opener answering every request with one answer, or one refusal."""

    def __init__(self, answer: Served | Exception) -> None:
        """Answer every request with this, or raise it."""
        super().__init__()
        self.answer = answer
        self.asked: list[urllib.request.Request | str] = []
        self.timeouts: list[float] = []

    def open(self, request: urllib.request.Request | str, timeout: float) -> Served:
        """Record what was asked and how long it could take, then answer."""
        self.asked.append(request)
        self.timeouts.append(timeout)
        if isinstance(self.answer, Exception):
            raise self.answer
        return self.answer


def opening(monkeypatch: pytest.MonkeyPatch, answer: Served | Exception) -> Opener:
    """Make every opener a script builds this one."""
    opener = Opener(answer)

    def build(*_handlers: urllib.request.BaseHandler) -> Opener:
        return opener

    monkeypatch.setattr(urllib.request, "build_opener", build)
    return opener


def refused(code: int) -> urllib.error.HTTPError:
    """Return GitHub refusing with this status, holding an empty body to close."""
    return urllib.error.HTTPError(
        "https://api.github.com/x",
        code,
        "refused",
        http.client.HTTPMessage(),
        io.BytesIO(),
    )


def test_a_tree_is_fetched_from_the_revision_it_names(monkeypatch: pytest.MonkeyPatch) -> None:
    opener = opening(monkeypatch, Served(SERVED))
    assert contract_sync.fetch(REVISION) == SERVED
    assert opener.asked == [f"https://codeload.github.com/lemonfiber/lemonfiber/tar.gz/{REVISION}"]
    assert opener.timeouts == [contract_sync.TIMEOUT_SECONDS]


def test_a_tree_that_cannot_be_reached_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    opening(monkeypatch, urllib.error.URLError("unreachable"))
    with pytest.raises(contract_sync.SyncRefusedError, match=f"{REVISION} serves no tree"):
        contract_sync.fetch(REVISION)


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


def test_a_bump_takes_what_sync_and_generation_wrote_and_removed(capsys: pytest.CaptureFixture[str]) -> None:
    status = (
        " M contract/VERSION\0?? src/lemonfiber/_generated/more.py\0M  contract/web-api/index.json\0"
        " D contract/web-api.contract.json\0D  src/lemonfiber/_generated/gone.py\0"
    )
    assert what_the_bump_takes.run(status) == 0
    assert capsys.readouterr().out == (
        "A contract/VERSION\nA contract/web-api/index.json\nA src/lemonfiber/_generated/more.py\n"
        "D contract/web-api.contract.json\nD src/lemonfiber/_generated/gone.py\n"
    )


@pytest.mark.parametrize(
    ("status", "said"),
    [
        (" M .github/workflows/ci.yml\0", "changed outside what a bump takes: .github/workflows/ci.yml"),
        ("?? README.md\0", "changed outside what a bump takes: README.md"),
        (" M contract-notes.txt\0", "changed outside what a bump takes: contract-notes.txt"),
        (" D README.md\0", "changed outside what a bump takes: README.md"),
        ("D  contract-notes.txt\0", "changed outside what a bump takes: contract-notes.txt"),
        (
            "R  contract/new\0.github/workflows/ci.yml\0",
            "moved .github/workflows/ci.yml to contract/new, and syncing and generating never move a file",
        ),
        (
            "UU contract/VERSION\0",
            "contract/VERSION stands as 'UU' in git's status, which syncing and generating never leave",
        ),
        (
            "UD contract/VERSION\0",
            "contract/VERSION stands as 'UD' in git's status, which syncing and generating never leave",
        ),
        ("?? contract/a\nb\0", 'a name that is not one printable line: "contract/a\\nb"'),
        ("", "nothing changed on disk, so there is nothing to commit"),
    ],
)
def test_a_bump_refuses_any_change_it_does_not_make(
    capsys: pytest.CaptureFixture[str],
    status: str,
    said: str,
) -> None:
    assert what_the_bump_takes.run(f" M contract/VERSION\0{status}" if status else status) == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == f"::error::{said}\n"


def test_github_is_asked_with_the_token_and_answers_json(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GITHUB_TOKEN", "a-token")
    opener = opening(monkeypatch, Served(b'{"tree": []}'))
    assert backward_compat.github("/repos/x") == {"tree": []}
    (asked,) = opener.asked
    assert isinstance(asked, urllib.request.Request)
    assert asked.full_url == "https://api.github.com/repos/x"
    assert asked.get_header("Authorization") == "Bearer a-token"
    assert opener.timeouts == [backward_compat.TIMEOUT_SECONDS]


def test_github_is_asked_without_a_token_where_there_is_none(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    opener = opening(monkeypatch, Served(b"[]"))
    assert backward_compat.github("/repos/x") == []
    (asked,) = opener.asked
    assert isinstance(asked, urllib.request.Request)
    assert asked.get_header("Authorization") is None


@pytest.mark.parametrize("code", [404, 409])
def test_a_missing_or_empty_repository_answers_nothing(monkeypatch: pytest.MonkeyPatch, code: int) -> None:
    with refused(code) as refusal:
        opening(monkeypatch, refusal)
        assert backward_compat.github("/repos/x") is None


def test_any_other_refusal_is_raised(monkeypatch: pytest.MonkeyPatch) -> None:
    with refused(500) as refusal:
        opening(monkeypatch, refusal)
        with pytest.raises(urllib.error.HTTPError):
            backward_compat.github("/repos/x")

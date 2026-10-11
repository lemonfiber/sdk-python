# Copyright (c) 2026 NightWorksIO
"""Comparing the vendored contract with what a revision serves, in either layout, naming every file that differs."""

import json
import pathlib

import pytest

from scripts import contract_drift, contract_sync
from tests.serving import SINGLE, SPLIT, tarball

REVISION = "d2bf74b950a9f6fb73f2bcd60e2d8adf85337cd6"


def vendor(root: pathlib.Path, files: dict[str, object]) -> None:
    """Vendor these files under `root`, written in a layout of their own, beside a stamp."""
    for path, held in files.items():
        (root / path).parent.mkdir(parents=True, exist_ok=True)
        (root / path).write_text(json.dumps(held, indent=4, sort_keys=True), encoding="utf-8")
    (root / "contract").mkdir(parents=True, exist_ok=True)
    (root / "contract/VERSION").write_text("v1.0.0\n", encoding="utf-8")


def compared(root: pathlib.Path, served: dict[str, object]) -> int:
    """Compare what is vendored under `root` with a revision serving these files."""
    return contract_drift.run([REVISION], root, lambda _: tarball(served))


@pytest.mark.parametrize("files", [SINGLE, SPLIT], ids=["single", "directory"])
def test_a_copy_holding_what_the_revision_serves_is_current(
    tmp_path: pathlib.Path,
    capsys: pytest.CaptureFixture[str],
    files: dict[str, object],
) -> None:
    vendor(tmp_path, files)
    assert compared(tmp_path, files) == contract_drift.CURRENT
    assert capsys.readouterr().out == f"the vendored contract is what lemonfiber {REVISION} serves\n"


@pytest.mark.parametrize(
    ("served", "said"),
    [
        (
            {**SPLIT, "contract/web-api/defs/Code.json": {"type": "integer"}},
            "contract/web-api/defs/Code.json: holds something else",
        ),
        (
            {**SPLIT, "contract/web-api/defs/Remedy.json": {"type": "string"}},
            "contract/web-api/defs/Remedy.json: served, and not vendored here",
        ),
        (
            {path: held for path, held in SPLIT.items() if not path.endswith("Code.json")},
            "contract/web-api/defs/Code.json: vendored here, and not served",
        ),
        (
            SINGLE,
            (
                "lemonfiber serves the single file contract/web-api.contract.json, and what is vendored here is "
                "the directory contract/web-api/"
            ),
        ),
    ],
)
def test_a_directory_that_differs_names_each_file_that_does(
    tmp_path: pathlib.Path,
    capsys: pytest.CaptureFixture[str],
    served: dict[str, object],
    said: str,
) -> None:
    vendor(tmp_path, SPLIT)
    assert compared(tmp_path, served) == contract_drift.BEHIND
    assert capsys.readouterr().out == f"{said}\n"


@pytest.mark.parametrize(
    ("vendored", "served", "said"),
    [
        (
            SINGLE,
            {"contract/web-api.contract.json": {"api_version": 1, "kinds": {"pull": {}}}},
            "contract/web-api.contract.json: holds something else",
        ),
        (
            SINGLE,
            SPLIT,
            (
                "lemonfiber serves the directory contract/web-api/, and what is vendored here is "
                "the single file contract/web-api.contract.json"
            ),
        ),
        (
            {},
            SINGLE,
            "lemonfiber serves the single file contract/web-api.contract.json, and what is vendored here",
        ),
    ],
)
def test_a_single_file_that_differs_is_named(
    tmp_path: pathlib.Path,
    capsys: pytest.CaptureFixture[str],
    vendored: dict[str, object],
    served: dict[str, object],
    said: str,
) -> None:
    vendor(tmp_path, vendored)
    assert compared(tmp_path, served) == contract_drift.BEHIND
    assert said in capsys.readouterr().out


def test_files_that_are_not_json_are_compared_as_bytes(tmp_path: pathlib.Path) -> None:
    vendor(tmp_path, SPLIT)
    (tmp_path / "contract/web-api/notes.txt").write_bytes(b"same {")
    assert compared(tmp_path, {**SPLIT, "contract/web-api/notes.txt": b"same {"}) == contract_drift.CURRENT
    assert compared(tmp_path, {**SPLIT, "contract/web-api/notes.txt": b"other {"}) == contract_drift.BEHIND


@pytest.mark.parametrize(
    "arguments",
    [
        [],
        ["main"],
        ["--gate", REVISION],
        [REVISION, REVISION],
        ["--loud", REVISION],
    ],
)
def test_anything_but_one_revision_is_refused(
    tmp_path: pathlib.Path,
    capsys: pytest.CaptureFixture[str],
    arguments: list[str],
) -> None:
    assert contract_drift.run(arguments, tmp_path, lambda _: tarball(SINGLE)) == contract_drift.REFUSED
    assert "name a release tag or a full 40-character commit hash" in capsys.readouterr().err


def test_a_revision_serving_no_contract_is_refused(
    tmp_path: pathlib.Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    def take(revision: str) -> bytes:
        message = f"{revision} serves no tree"
        raise contract_sync.SyncRefusedError(message)

    assert contract_drift.run([REVISION], tmp_path, take) == contract_drift.REFUSED
    assert capsys.readouterr().err == f"::error::{REVISION} serves no tree\n"


def test_the_drift_runs_against_its_own_repository() -> None:
    assert pathlib.Path(__file__).resolve().parent.parent == contract_drift.ROOT

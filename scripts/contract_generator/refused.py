# Copyright (c) 2026 NightWorksIO
"""How the generator turns an artefact down: one error, raised before anything is written."""

from typing import NoReturn


class ArtefactRefusedError(Exception):
    """The artefact cannot be generated from, and nothing was written."""


def refuse(message: str) -> NoReturn:
    """Refuse the artefact, saying why."""
    raise ArtefactRefusedError(message)

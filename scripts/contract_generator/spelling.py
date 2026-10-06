# Copyright (c) 2026 NightWorksIO
"""How the artefact's words are spelled in Python: names, modules, docstrings and literals."""

import json
import keyword
import re

from scripts.contract_generator.refused import ArtefactRefusedError

WORD_START = re.compile(r"(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])")
"""Where a word begins inside a PascalCase name: `ValueOrigin` splits before `Origin`."""


def pascal(text: str) -> str:
    """Spell `front-door` as `FrontDoor` and `whole_stack` as `WholeStack`."""
    return "".join(part[:1].upper() + part[1:] for part in re.split(r"[^A-Za-z0-9]+", text) if part)


def module_name(word: str) -> str:
    """Spell a kind or a PascalCase name as a module: `front-door` and `FrontDoor` are both `front_door`.

    A name Python reserves takes a trailing underscore, as `import` becomes `import_`.
    """
    spelled = WORD_START.sub("_", word).replace("-", "_").lower()
    return f"{spelled}_" if keyword.iskeyword(spelled) else spelled


def is_field_name(key: str) -> bool:
    """Tell whether a key can be written as a class attribute."""
    return key.isidentifier() and not keyword.iskeyword(key)


def escaped(character: str) -> str:
    """Spell one character so that inside a docstring it is that character and nothing more."""
    if character in {"\\", '"'}:
        return f"\\{character}"
    if character == "\n" or character.isprintable():
        return character
    return character.encode("unicode_escape").decode("ascii")


def docstring(text: str, indent: str) -> list[str]:
    """Write a description as a docstring that reads back as the same text.

    Every backslash and quote is escaped, so no run of quotes in the text can
    close the docstring, and every character that is not printable is written
    as its escape, so none of them can end a line or the file.
    """
    body = "".join(escaped(character) for character in text.strip())
    lines = body.split("\n")
    if len(lines) == 1:
        return [f'{indent}"""{body}"""']
    rest = [f"{indent}{line}" if line else "" for line in lines[1:]]
    return [f'{indent}"""{lines[0]}', *rest, f'{indent}"""']


def literal(value: object) -> str:
    """Write a JSON value as the Python literal `typing.Literal` takes."""
    if isinstance(value, bool):
        return str(value)
    if isinstance(value, int | str):
        return json.dumps(value)
    message = f"a constant of {json.dumps(value)} has no Python literal"
    raise ArtefactRefusedError(message)

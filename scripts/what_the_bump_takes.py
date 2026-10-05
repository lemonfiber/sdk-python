# Copyright (c) 2026 NightWorksIO
"""Name the files a contract bump commits, refusing any change a bump does not make.

`contract-bump` commits with a token that can write to this repository, after a
build that runs the suite. So it commits only what syncing and generating write,
`contract/` and `src/lemonfiber/_generated/`, and refuses to commit at all when
anything else changed on disk: a test that rewrote a file, or a tool that
touched the lock, is a person's to read rather than the bot's to carry. A
deletion or a rename is refused too, since the commit it makes carries
additions only.

    git status --porcelain=v1 -z --untracked-files=all | uv run python -m scripts.what_the_bump_takes

Prints one path per line, the list the commit is built from.
"""

import sys

TAKEN = ("contract/", "src/lemonfiber/_generated/")
"""Where syncing and generating write, and so all a bump may change."""

ADDED_OR_CHANGED = frozenset({"M", "A", "?", " "})
"""The status letters of a file a commit of additions can carry."""

MOVED = frozenset({"R", "C"})
"""The status letters followed by a second entry naming where the file came from."""


def problems(status: str) -> tuple[list[str], list[str]]:
    """Read `git status --porcelain=v1 -z`: every path a bump takes, and everything that stops it."""
    entries = iter(status.split("\0"))
    taken: list[str] = []
    found: list[str] = []
    for entry in entries:
        if not entry:
            continue
        letters, name = set(entry[:2]), entry[3:]
        if letters & MOVED:
            found.append(
                f"moved {next(entries, '')} to {name}, and the commit a bump makes carries additions only",
            )
        elif "D" in letters:
            found.append(f"deleted {name}, and the commit a bump makes carries additions only")
        elif not letters <= ADDED_OR_CHANGED:
            found.append(
                f"{name} stands as {entry[:2]!r} in git's status, which syncing and generating never leave",
            )
        elif not name.isprintable():
            found.append(f"a name that is not one printable line: {name!r}".replace("'", '"'))
        elif not name.startswith(TAKEN):
            found.append(f"changed outside what a bump takes: {name}")
        else:
            taken.append(name)
    if not taken and not found:
        found.append("nothing changed on disk, so there is nothing to commit")
    return sorted(taken), found


def run(status: str) -> int:
    """Print what a bump commits, or refuse and say why."""
    taken, found = problems(status)
    if found:
        for line in found:
            sys.stderr.write(f"::error::{line}\n")
        return 1
    sys.stdout.write("".join(f"{name}\n" for name in taken))
    return 0


if __name__ == "__main__":
    raise SystemExit(run(sys.stdin.read()))

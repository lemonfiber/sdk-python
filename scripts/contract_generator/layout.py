# Copyright (c) 2026 NightWorksIO
"""Where each shape is written: one module per set of kinds and action routes carrying it, in parts where one would outgrow the cap.

A shape every carrier of which also carries what it names imports only from
modules carried by more kinds than its own, so the modules import one way. A
module over the cap becomes a package of parts, each part a run of shapes that
name one another, and each part importing only from parts before it.
"""

from typing import TYPE_CHECKING

from scripts.contract_generator.modules import Module, index
from scripts.contract_generator.refused import refuse
from scripts.contract_generator.shapes import declarations
from scripts.contract_generator.spelling import module_name
from scripts.contract_generator.tables import API, BODIES_PACKAGE, KINDS_PACKAGE, SHARED_PACKAGE
from scripts.line_cap import lines_in

if TYPE_CHECKING:
    from collections.abc import Collection, Mapping

    from scripts.contract_generator.formatting import Formatter
    from scripts.contract_generator.shapes import Shape

type Path = tuple[str, ...]

BOTH = 2
"""How many carriers a shape has where they `both` carry it, rather than `all`."""


def ticked(words: Collection[str]) -> str:
    """Write words as a list in prose, each in backticks: `a`, `b` and `c`."""
    quoted = [f"`{word}`" for word in sorted(words)]
    return quoted[0] if len(quoted) == 1 else f"{', '.join(quoted[:-1])} and {quoted[-1]}"


def carried(carriers: frozenset[str]) -> str:
    """Say which kinds carry a shape: only `a`, `a` and `b` both, or all of several."""
    if len(carriers) == 1:
        return f"only {ticked(carriers)} carries"
    return f"{ticked(carriers)} {'both' if len(carriers) == BOTH else 'all'} carry"


def is_route(carrier: str) -> bool:
    """Tell whether a carrier is the route an action is posted to, rather than a kind."""
    return carrier.startswith(f"{API}/")


def path_of(carriers: frozenset[str], first: str) -> Path:
    """Return the module the shapes some kinds or routes carry are written in, named after `first` where more than one does."""
    if len(carriers) == 1:
        carrier = next(iter(carriers))
        if is_route(carrier):
            return (*BODIES_PACKAGE, module_name(carrier.removeprefix(f"{API}/").replace("/", "-")))
        return (*KINDS_PACKAGE, module_name(carrier))
    return (*SHARED_PACKAGE, module_name(first))


def grouped(shapes: Mapping[str, Shape]) -> dict[Path, dict[str, Shape]]:
    """Return every shape by the module it is written in: one module per set of kinds.

    Where two sets' shared modules would take one name, the set later in the
    order of its sorted kinds takes that name followed by two underscores and the
    next number from 2. Two kinds never meet here under one name: their envelopes
    would already share one, which is refused before.
    """
    sets: dict[tuple[str, ...], dict[str, Shape]] = {}
    for name in sorted(shapes):
        sets.setdefault(tuple(sorted(shapes[name].carriers)), {})[name] = shapes[name]
    groups: dict[Path, dict[str, Shape]] = {}
    held: dict[Path, frozenset[str]] = {}
    for kinds in sorted(sets):
        members = sets[kinds]
        carriers = frozenset(kinds)
        named = path_of(carriers, next(iter(members)))
        path = named
        number = 2
        while path in held:
            path = (*named[:-1], f"{named[-1]}__{number}")
            number += 1
        held[path] = carriers
        groups[path] = members
    return groups


def check_carried(shapes: Mapping[str, Shape]) -> None:
    """Refuse a shape naming one that some of its own carriers do not carry."""
    for name in sorted(shapes):
        shape = shapes[name]
        for other in sorted(shape.refers_to(shapes)):
            missing = shape.carriers - shapes[other].carriers
            if missing:
                refuse(
                    f"`{name}`, which {carried(shape.carriers)}, names `{other}`, which {ticked(missing)} "
                    "does not define",
                )


def components(shapes: Mapping[str, Shape]) -> list[list[str]]:
    """Return the shapes as runs that name one another, each run after every run it names.

    Tarjan's algorithm over the names each shape gives, visited in name order,
    so the same shapes always come out in the same runs and the same order.
    """
    names = sorted(shapes)
    edges = {name: sorted(shapes[name].refers_to(shapes)) for name in names}
    order: dict[str, int] = {}
    low: dict[str, int] = {}
    stack: list[str] = []
    runs: list[list[str]] = []

    def visit(name: str) -> None:
        order[name] = low[name] = len(order)
        stack.append(name)
        for other in edges[name]:
            if other not in order:
                visit(other)
                low[name] = min(low[name], low[other])
            elif other in stack:
                low[name] = min(low[name], order[other])
        if low[name] == order[name]:
            run: list[str] = []
            while not run or run[-1] != name:
                run.append(stack.pop())
            runs.append(sorted(run))

    for name in names:
        if name not in order:
            visit(name)
    return runs


def uses_typing(shape: Shape) -> bool:
    """Tell whether a shape's declaration spells anything through the typing module."""
    return (
        shape.fields is not None
        or shape.lines[0].startswith("class ")
        or any("typing." in annotation for annotation in shape.annotations)
    )


def module_of(path: Path, summary: str, members: Mapping[str, Shape], where: Mapping[str, Path]) -> Module:
    """Return the module declaring `members`, importing what they name from where it is written."""
    imports: dict[Path, set[str]] = {}
    for shape in members.values():
        for other in shape.refers_to(where):
            if other not in members:
                imports.setdefault(where[other], set()).add(other)
    standard = {one for shape in members.values() for one in shape.standard}
    if any(uses_typing(shape) for shape in members.values()):
        standard.add("typing")
    return Module(path, summary, declarations(members), sorted(members), imports, tuple(sorted(standard)))


class Layout:
    """Lays every shape out in modules, each within the cap, asking the formatter how long each would be."""

    def __init__(
        self,
        shapes: Mapping[str, Shape],
        formatter: Formatter,
        cap: int,
        placed: Mapping[str, Path] | None = None,
    ) -> None:
        """Hold the shapes, the formatter and the cap, and where each name `placed` holds is written already."""
        check_carried(shapes)
        self._formatter = formatter
        self._cap = cap
        self.groups = grouped(shapes)
        self._where = {
            **(placed or {}),
            **{name: path for path, members in self.groups.items() for name in members},
        }

    def length(self, module: Module) -> int:
        """Return how many lines a module holds once formatted."""
        return lines_in(self._formatter.formatted({"one": module.source()})["one"])

    def modules(self) -> list[Module]:
        """Return every module the shapes are written in, splitting each that would outgrow the cap."""
        whole = {
            path: module_of(path, f"{self.holds(path)}.", members, self._where)
            for path, members in sorted(self.groups.items())
        }
        lengths = self._formatter.formatted(
            {".".join(path): module.source() for path, module in whole.items()},
        )
        written: list[Module] = []
        for path, module in whole.items():
            if lines_in(lengths[".".join(path)]) <= self._cap:
                written.append(module)
            else:
                written.extend(self.parts(path))
        return written

    def holds(self, path: Path) -> str:
        """Say what the module at `path` holds."""
        carriers = next(iter(self.groups[path].values())).carriers
        if len(carriers) == 1 and is_route(next(iter(carriers))):
            return f"The action posted to {ticked(carriers)}, and the shapes {carried(carriers)}"
        if len(carriers) == 1:
            return f"The {ticked(carriers)} envelope, and the shapes {carried(carriers)}"
        return f"The shapes {carried(carriers)}"

    def parts(self, path: Path) -> list[Module]:
        """Return the package `path` becomes, each part a run of shapes within the cap."""
        members = self.groups[path]
        carriers = next(iter(members.values())).carriers
        where = dict(self._where)
        done: list[Module] = []
        current: list[str] = []

        def part(names: list[str]) -> Module:
            summary = f"Some of the shapes {carried(carriers)}; `{'.'.join(path)}` gathers them all."
            return module_of((*path, module_name(names[0])), summary, {n: members[n] for n in names}, where)

        def close() -> None:
            finished = part(current)
            if any(one.path == finished.path for one in done):
                refuse(
                    f"two parts of `{'.'.join(path)}` would both be written as `{'.'.join(finished.path)}`",
                )
            done.append(finished)
            where.update(dict.fromkeys(current, finished.path))

        for run in components(members):
            if self.length(part([*current, *run])) <= self._cap:
                current.extend(run)
                continue
            if current:
                close()
            alone = self.length(part(run))
            if alone > self._cap:
                together = " name one another and" if len(run) > 1 else ""
                refuse(
                    f"{ticked(run)}, which {carried(carriers)},{together} would hold {alone} lines as one "
                    f"module, over the {self._cap} a module may hold",
                )
            current = list(run)
        close()
        gathered = index(
            path,
            f"{self.holds(path)}, gathered from its parts.",
            [one.path for one in done],
        )
        return [gathered, *done]

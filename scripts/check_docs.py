"""Docs gate: `施工纪律.md` §4.6「不做」栏三分制.

Gate (hard, exit code 1 on violation)
-------------------------------------
For every `docs/V1.0/<version>-*/01-计划/README.md`:

* ``D1`` the ``| **不做** | ... |`` row **must exist**;
* ``D2`` the row's cell **must start with** ``①`` / ``②`` / ``③``;
* ``D3`` every ``<br>``-separated block inside the cell **must start with**
  ``①`` / ``②`` / ``③`` (``<br>`` is the explicit hard separator, see V0.4.0 / V0.7.0).

Why D2/D3 and not "split on semicolons"
---------------------------------------
Inline ``；`` also occurs *inside* a single item's prose (V1.0.1 does this three
times), so splitting on it and demanding a marker on every fragment produces
false reds.  ``<br>`` and the cell start are the only machine-decidable item
boundaries, so those are what get gated.  Semicolon-separated fragments that lack
a marker are reported as **notes**, never as failures.

Backlog exemption (``施工纪律.md`` §4.6 存量处置)
------------------------------------------------
``V0.0.1``–``V1.0.0`` (13 versions, listed explicitly in :data:`EXEMPT_VERSIONS`)
are exempt: their 「不做」 rows are frozen and **must not be rewritten**.  Their
rows are still parsed and counted so the report shows what was skipped instead of
silently ignoring them.  ``V1.0.1`` onwards is gated.

Read-only
---------
``docs/`` is an independent git repository.  This script only reads; it never
writes, moves or normalises any file under it.

Exit codes: ``0`` pass, ``1`` violation, ``2`` usage error (e.g. docs root missing).
Standard library only.
"""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

__all__ = ["EXEMPT_VERSIONS", "RULE", "Violation", "VersionReport", "main"]

#: `施工纪律.md` §4.6 存量处置: V0.0.1–V1.0.0, 13 versions, frozen -- never rewritten.
EXEMPT_VERSIONS: tuple[str, ...] = (
    "V0.0.1",
    "V0.0.2",
    "V0.1.0",
    "V0.2.0",
    "V0.3.0",
    "V0.3.1",
    "V0.4.0",
    "V0.5.0",
    "V0.6.0",
    "V0.7.0",
    "V0.8.0",
    "V0.9.0",
    "V1.0.0",
)

#: Version directory pattern, e.g. ``V1.0.1-移动接入``.
VERSION_DIR_RE = re.compile(r"^(?P<version>V\d+\.\d+\.\d+)(?:[-_].*)?$")

#: The 「不做」 row.  Single-cell table row, e.g. ``| **不做** | ... |``.
NOT_DO_ROW_RE = re.compile(r"^\s*\|\s*\*\*不做\*\*\s*\|(?P<cell>.*)\|\s*$")

#: Hard block separator used inside the cell.
BR_RE = re.compile(r"<br\s*/?>", re.IGNORECASE)

#: Fragment separator used for advisory notes only (never gated).
SOFT_SEP_RE = re.compile(r"[；;]")

#: The three-way markers from §4.6.
MARKERS: tuple[str, ...] = ("①", "②", "③")

#: Leading markdown noise stripped before looking for a marker.
_STRIP_PREFIX_RE = re.compile(r"^[\s*_`\"'「『（(]+")

RULE = "施工纪律.md §4.6"


@dataclass
class Violation:
    """One gate failure."""

    code: str
    relative_path: str
    line: int
    reason: str

    def render(self) -> str:
        """Render as ``file:line: [code] reason``."""
        return f"{self.relative_path}:{self.line}: [{self.code}] {self.reason}"


@dataclass
class VersionReport:
    """Per-version scan result."""

    version: str
    relative_path: str
    exempt: bool
    has_row: bool = False
    row_line: int = 0
    blocks: int = 0
    marked_blocks: int = 0
    notes: list[str] = field(default_factory=list)
    violations: list[Violation] = field(default_factory=list)


def _leading_marker(text: str) -> str | None:
    """Return the first ①/②/③ of ``text`` if it is the first meaningful character."""
    cleaned = _STRIP_PREFIX_RE.sub("", text)
    if cleaned and cleaned[0] in MARKERS:
        return cleaned[0]
    return None


def _iter_version_dirs(docs_root: Path) -> list[tuple[str, Path]]:
    """List ``(version, README path)`` pairs under ``<docs_root>/V1.0/<version>-*/01-计划``.

    Args:
        docs_root: The ``docs`` directory.

    Returns:
        Pairs sorted by version directory name.
    """
    plan_root = docs_root / "V1.0"
    if not plan_root.is_dir():
        return []
    pairs: list[tuple[str, Path]] = []
    for entry in sorted(plan_root.iterdir(), key=lambda item: item.name):
        if not entry.is_dir():
            continue
        matched = VERSION_DIR_RE.match(entry.name)
        if not matched:
            continue
        readme = entry / "01-计划" / "README.md"
        if readme.is_file():
            pairs.append((matched.group("version"), readme))
    return pairs


def scan_readme(docs_root: Path, version: str, readme: Path) -> VersionReport:
    """Scan a single plan README for the 「不做」 row.

    Args:
        docs_root: The ``docs`` directory (used for relative paths in messages).
        version: Version string parsed from the directory name, e.g. ``V1.0.1``.
        readme: Absolute path to ``01-计划/README.md``.

    Returns:
        A populated :class:`VersionReport`.
    """
    try:
        relative = readme.relative_to(docs_root).as_posix()
    except ValueError:  # pragma: no cover - defensive
        relative = readme.as_posix()

    exempt = version in EXEMPT_VERSIONS
    report = VersionReport(version=version, relative_path=relative, exempt=exempt)

    lines = readme.read_text(encoding="utf-8").splitlines()
    cell = ""
    for lineno, line in enumerate(lines, start=1):
        matched = NOT_DO_ROW_RE.match(line)
        if matched:
            report.has_row = True
            report.row_line = lineno
            cell = matched.group("cell")
            break

    if not report.has_row:
        report.violations.append(
            Violation("D1", relative, 0, f"缺「不做」栏（表格行 `| **不做** | ... |`，{RULE}）")
        )
        return report

    blocks = [block.strip() for block in BR_RE.split(cell) if block.strip()]
    report.blocks = len(blocks)
    report.marked_blocks = sum(1 for block in blocks if _leading_marker(block))

    if exempt:
        # Frozen backlog: counted, never gated (§4.6 存量处置 1).
        return report

    if not blocks:
        report.violations.append(
            Violation("D2", relative, report.row_line, "「不做」栏为空")
        )
        return report

    first_marker = _leading_marker(blocks[0])
    if first_marker is None:
        head = blocks[0][:40].replace("|", "\\|")
        report.violations.append(
            Violation(
                "D2",
                relative,
                report.row_line,
                f"「不做」栏未以 ①/②/③ 开头（实为 {head!r}…，{RULE} 三问裁定 §4）",
            )
        )

    for index, block in enumerate(blocks, start=1):
        if _leading_marker(block) is None:
            head = block[:40].replace("|", "\\|")
            report.violations.append(
                Violation(
                    "D3",
                    relative,
                    report.row_line,
                    f"第 {index}/{len(blocks)} 个 <br> 块未以 ①/②/③ 开头（实为 {head!r}…）",
                )
            )

    # Advisory only: inline-; fragments without a marker.  Legal prose, not a gate.
    for fragment in SOFT_SEP_RE.split(cell):
        text = fragment.strip()
        if len(text) < 8 or _leading_marker(text):
            continue
        if text.startswith(("|", "-")):
            continue
        report.notes.append(f"{relative}:{report.row_line}: 无标记片段（仅提示，不判红）：{text[:48]}")

    return report


def main(argv: list[str] | None = None) -> int:
    """CLI entry point.

    Args:
        argv: Arguments without program name.

    Returns:
        ``0`` pass, ``1`` violation, ``2`` usage error.
    """
    parser = argparse.ArgumentParser(
        prog="check_docs",
        description=f"Docs gate for {RULE}（「不做」栏 ①/②/③ 三分制）",
    )
    parser.add_argument(
        "--docs-root",
        default=None,
        help="docs 目录（默认：<repo>/docs）",
    )
    parser.add_argument(
        "--show-notes",
        action="store_true",
        help="打印无标记片段提示（默认不打印，只计数）",
    )
    parser.add_argument(
        "--list",
        action="store_true",
        help="打印逐个版本的扫描明细",
    )
    args = parser.parse_args(argv)

    repo_root = Path(__file__).resolve().parents[1]
    docs_root = Path(args.docs_root).resolve() if args.docs_root else repo_root / "docs"

    if not docs_root.is_dir():
        sys.stderr.write(f"[check_docs] ERROR: docs 目录不存在: {docs_root}\n")
        return 2

    pairs = _iter_version_dirs(docs_root)
    if not pairs:
        sys.stderr.write(f"[check_docs] ERROR: 未找到任何 01-计划/README.md（{docs_root}/V1.0/*）\n")
        return 2

    reports = [scan_readme(docs_root, version, readme) for version, readme in pairs]
    violations = [violation for report in reports for violation in report.violations]
    notes = [note for report in reports for note in report.notes]
    exempt_count = sum(1 for report in reports if report.exempt)

    if args.list:
        for report in reports:
            flag = "EXEMPT" if report.exempt else "GATED "
            state = "FAIL" if report.violations else "ok  "
            sys.stdout.write(
                f"  [{flag}] {state} {report.version:<7} "
                f"row@{report.row_line or '-':<3} blocks={report.blocks} "
                f"marked={report.marked_blocks} {report.relative_path}\n"
            )

    if args.show_notes:
        for note in notes:
            sys.stdout.write(f"  note: {note}\n")

    scanned = len(reports)
    gated = scanned - exempt_count
    sys.stdout.write(
        f"[check_docs] 规则={RULE} scanned={scanned} exempt={exempt_count} "
        f"gated={gated} violations={len(violations)} notes={len(notes)}\n"
    )

    if violations:
        for violation in violations:
            sys.stdout.write(f"  {violation.render()}\n")
        sys.stdout.write("[check_docs] FAIL\n")
        return 1

    sys.stdout.write("[check_docs] PASS\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

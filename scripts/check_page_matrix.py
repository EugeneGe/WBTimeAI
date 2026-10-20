#!/usr/bin/env python3
"""T1-08 — keep the page-lighting matrix honest against the real router.

Why this gate exists
--------------------
``docs/V1.0/V0.1.0-基座与契约层/03-台账/页面点亮矩阵.md`` is the **zero baseline**
that every later "x/24" / "n/19" claim (roadmap D4) is measured against.  A
baseline that drifts away from the router it claims to describe is worse than no
baseline at all: later versions would report progress against a fiction.

So this gate does **not** trust the markdown.  It re-derives the numbers from the
one artefact that cannot lie about them — ``apps/web/src/router.tsx`` — and then
checks that the matrix agrees:

* ``page(<X />)`` elements        -> rendered pages (**19**, per the router's own comment)
* ``<Navigate ... />`` elements   -> redirects (**5**, not lazy-loaded)
* rendered + redirect             -> route entries (**24**, the D4 denominator)

The vacuity trap (project defect K-11)
--------------------------------------
An empty parse (0 pages) is **INVALID(EMPTY)**, never PASS.  If ``apps/web`` has
not been migrated yet, this gate must go red rather than silently report "0/0
lit" — that is exactly the "empty glob is vacuously true" failure this repo has
already been burned by.

Exit codes
----------
* ``0`` — router and matrix agree
* ``1`` — disagreement, or INVALID(EMPTY), or the matrix/router files are missing
* ``2`` — usage error
* ``9`` — ``--self-test`` failed

Python: standard library only.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
ROUTER = REPO_ROOT / "apps" / "web" / "src" / "router.tsx"
MATRIX = (
    REPO_ROOT
    / "docs"
    / "V1.0"
    / "V0.1.0-基座与契约层"
    / "03-台账"
    / "页面点亮矩阵.md"
)

# Structural floor: the router is a 200-line file with a known shape.  Anything
# at or under this is "we did not actually parse a router" (K-11).
MIN_RENDERED = 10
MIN_REDIRECTS = 1

EXPECTED_RENDERED = 19
EXPECTED_REDIRECTS = 5
EXPECTED_TOTAL = EXPECTED_RENDERED + EXPECTED_REDIRECTS  # 24

RE_PAGE_CALL = re.compile(r"page\(<")
RE_NAVIGATE = re.compile(r"<Navigate")


def _code_lines(text: str) -> list[str]:
    """Drop comment lines before counting.

    Measured on ``apps/web/src/router.tsx`` (2026-10-21): a naive count of
    ``element: page(`` yields **20**, not 19 — two of those hits live in comments
    (the ``[U-9]`` enterprise slot at :154 and its activation note at :37), and a
    third real page (``/settings``' ``page(<SettingsWindow />)`` at :179) is
    nested inside ``<RequireAuth>`` so it does *not* match ``element: page(`` at
    all.  20 − 2 + 1 = 19.  Counting without stripping comments is how a gate
    reports a number that no human can reconcile with the source.
    """
    out = []
    for line in text.splitlines():
        stripped = line.lstrip()
        if stripped.startswith("//"):
            continue
        if stripped.startswith("*") or stripped.startswith("/*"):
            continue
        out.append(line)
    return out


def parse_router(text: str) -> tuple[int, int]:
    """Return ``(rendered_pages, redirects)`` derived from the router source."""
    code = "\n".join(_code_lines(text))
    return len(RE_PAGE_CALL.findall(code)), len(RE_NAVIGATE.findall(code))


def parse_matrix(text: str) -> tuple[int, int]:
    """Return ``(unlit_rows, redirect_rows)`` counted from the matrix table."""
    unlit = len(re.findall(r"\|\s*⚫\s*\|", text))
    redirects = len(re.findall(r"\|\s*➡️\s*\|", text))
    return unlit, redirects


def check(router_text: str, matrix_text: str) -> tuple[bool, list[str]]:
    """Return ``(ok, report_lines)``.  Never folds distinct failures together."""
    rendered, redirects = parse_router(router_text)
    m_unlit, m_redirects = parse_matrix(matrix_text)
    total = rendered + redirects
    m_total = m_unlit + m_redirects

    problems: list[str] = []

    # -- vacuity first: an empty surface fails before anything else is judged ----
    if rendered < MIN_RENDERED:
        problems.append(
            f"INVALID(EMPTY): router rendered pages = {rendered} < {MIN_RENDERED} "
            f"— either apps/web is not migrated or the parse regex broke"
        )
    if redirects < MIN_REDIRECTS:
        problems.append(
            f"INVALID(EMPTY): router redirects = {redirects} < {MIN_REDIRECTS}"
        )
    if m_total == 0:
        problems.append("INVALID(EMPTY): matrix has 0 counted rows")

    # -- router vs its own documented expectation -------------------------------
    if rendered != EXPECTED_RENDERED:
        problems.append(
            f"rendered pages = {rendered}, expected {EXPECTED_RENDERED} "
            f"(router.tsx documents '19 个渲染页')"
        )
    if redirects != EXPECTED_REDIRECTS:
        problems.append(
            f"redirects = {redirects}, expected {EXPECTED_REDIRECTS}"
        )
    if total != EXPECTED_TOTAL:
        problems.append(f"total route entries = {total}, expected {EXPECTED_TOTAL}")

    # -- matrix vs router (the drift this gate exists to catch) -----------------
    if m_unlit != rendered:
        problems.append(
            f"matrix '⚫ 未点亮' rows = {m_unlit} but router rendered pages = {rendered}"
        )
    if m_redirects != redirects:
        problems.append(
            f"matrix '➡️ 重定向' rows = {m_redirects} but router redirects = {redirects}"
        )

    report = [
        f"router   rendered={rendered} redirects={redirects} total={total}",
        f"matrix   unlit={m_unlit} redirects={m_redirects} total={m_total}",
    ]
    report += [f"  PROBLEM: {p}" for p in problems]
    return (not problems), report


def self_test() -> bool:
    """Five cases: baseline green + each single failure mode must go red."""
    good_router = "".join(
        f"  {{ path: 'p{i}', element: page(<P{i} />) }},\n" for i in range(EXPECTED_RENDERED)
    ) + "".join(
        f"  {{ path: 'r{i}', element: <Navigate to='/x' replace /> }},\n"
        for i in range(EXPECTED_REDIRECTS)
    )
    # A commented-out slot must NOT be counted — otherwise the gate silently
    # agrees with a number that includes dead routes (see _code_lines).
    good_router += "  // { path: 'enterprise', element: page(<Enterprise />) },\n"
    good_matrix = "".join(
        f"| {i} | /p{i} | X | Y | Z | ⚫ |\n" for i in range(EXPECTED_RENDERED)
    ) + "".join(f"| {i} | /r{i} | — | — | — | ➡️ |\n" for i in range(EXPECTED_REDIRECTS))

    cases = [
        ("baseline", good_router, good_matrix, True),
        ("empty router", "", good_matrix, False),
        ("empty matrix", good_router, "", False),
        ("one page lost", good_router.replace("element: page(<P0 />)", ""), good_matrix, False),
        (
            "matrix row lost",
            good_router,
            good_matrix.replace("| 0 | /p0 | X | Y | Z | ⚫ |\n", ""),
            False,
        ),
    ]
    ok = True
    for name, router, matrix, expect_pass in cases:
        passed, _ = check(router, matrix)
        status = "OK" if passed == expect_pass else "FAIL"
        if status == "FAIL":
            ok = False
        print(f"  [{status}] self-test {name!r}: passed={passed} expected={expect_pass}")
    return ok


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--self-test", action="store_true", help="run built-in cases")
    args = parser.parse_args(argv)

    if args.self_test:
        print("[check_page_matrix] self-test")
        ok = self_test()
        print(f"[check_page_matrix] {'PASS' if ok else 'FAIL'}")
        return 0 if ok else 9

    for label, path in (("router", ROUTER), ("matrix", MATRIX)):
        if not path.is_file():
            print(f"[check_page_matrix] FAIL missing {label}: {path}")
            return 1

    ok, report = check(
        ROUTER.read_text(encoding="utf-8"), MATRIX.read_text(encoding="utf-8")
    )
    for line in report:
        print(f"[check_page_matrix] {line}")
    print(f"[check_page_matrix] {'PASS' if ok else 'FAIL'}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())

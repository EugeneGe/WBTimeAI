"""M-4 — i18n key-parity gate: `en` and `zh-CN` must carry *the same* key set.

Why this gate exists (audit finding M-4)
----------------------------------------
`apps/web/src/i18n/locales/en.ts` says in its own header comment:

    ⚠️ 本文件与 `zh-CN.ts` 必须保持 key 集合一致（对等性由 `i18n.test.ts` 守卫）。

and `apps/web/src/i18n/__tests__/i18n.test.ts` does guard it — but that guard lives
inside the frontend test suite, i.e. it only fires when someone runs `vitest`.
A locale file is a *data* artifact: it is edited by whoever adds a string, often in
a commit that touches nothing else.  This gate makes the same claim checkable from
the repo root, without node, without a frontend build, in the same `gates` job that
already guards contracts.

What is measured (four independent claims)
-----------------------------------------
============================================  ==============================
claim                                          failure tag
============================================  ==============================
both files parse to a **non-empty** key set    ``empty-set``
neither file repeats a key                     ``duplicate-key``
``en`` ⊆ ``zh-CN`` (every key translated)      ``missing-key``
``zh-CN`` ⊆ ``en`` (no invented key)           ``extra-key``
same key ⇒ same ``{placeholder}`` set          ``placeholder-mismatch``
============================================  ==============================

An empty parse result is ``INVALID``, never PASS: if the extraction regex ever
stops matching (someone switches to single quotes, or a generator rewrites the
file), both sides become *equally empty* and a naive "sets are equal" check goes
green while proving nothing.  That is the K-11 哑真 failure mode.

Why a regex and not a TS parser: this gate must run on a bare Python, in the
``gates`` job, without ``pnpm install`` and without compiling the frontend.  Keys
are therefore read with ``^\\s*"([^"]+)"\\s*:`` — deliberately matching only the
*key* part, so a value that spans several lines cannot hide an entry.

Exit codes (same convention as the sibling gates)::

    0   every claim above holds
    1   violation (drift, duplicate, placeholder mismatch, empty parse)
    2   usage / environment error (missing arg, unreadable locale file)

``--self-test`` re-runs the detector against four in-memory counter-examples
(missing key / extra key / placeholder drift / duplicate key) plus one well-formed
control.  The self-test passes only if **all four** are caught *and* the control
stays green — otherwise the detector is not a detector.

Python: standard library only.
"""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Final, Mapping

sys.dont_write_bytecode = True

TAG: Final[str] = "check_i18n_keys"

ROOT: Final[Path] = Path(__file__).resolve().parent.parent

#: Locale label → path relative to the repo root (order matters only for output).
LOCALES: Final[Mapping[str, str]] = {
    "en": "apps/web/src/i18n/locales/en.ts",
    "zh-CN": "apps/web/src/i18n/locales/zh-CN.ts",
}

#: A key line: `<indent>"<key>":`.  Only the key part is matched on purpose —
#: values may wrap onto the following lines, so a full-line value regex would
#: silently drop those entries.
KEY_RE: Final[re.Pattern[str]] = re.compile(r'^\s*"([^"]+)"\s*:', re.MULTILINE)

#: Interpolation placeholder (`{name}`).  Nested braces are not supported by the
#: i18n runtime either, so `[^{}]+` is the honest class here.
PLACEHOLDER_RE: Final[re.Pattern[str]] = re.compile(r"\{([^{}]+)\}")

#: End of the exported dictionary literal (`};` at column 0).  Used to clip the
#: last entry's slice so trailing module code cannot contribute placeholders.
DICT_END_RE: Final[re.Pattern[str]] = re.compile(r"^\};", re.MULTILINE)

#: Floor for "the parse actually found something".  Empty ⇒ INVALID, never PASS.
MIN_KEYS: Final[int] = 1


@dataclass(frozen=True)
class Violation:
    """One detected problem, tagged so the self-test can assert *what* was caught."""

    tag: str
    detail: str

    def render(self) -> str:
        """Render as ``[FAIL] tag: detail``."""
        return f"  [FAIL] {self.tag}: {self.detail}"


@dataclass(frozen=True)
class Locale:
    """A parsed locale dictionary: key order, per-key placeholders, duplicates."""

    label: str
    keys: tuple[str, ...]
    placeholders: Mapping[str, frozenset[str]]
    duplicates: tuple[str, ...]

    @property
    def key_set(self) -> frozenset[str]:
        """The key set, ignoring order and duplicates."""
        return frozenset(self.keys)


def parse_locale(label: str, text: str) -> Locale:
    """Extract keys and their placeholder sets from a locale source file.

    Args:
        label: Human label used in messages (``en`` / ``zh-CN``).
        text: Raw file content.

    Returns:
        Parsed :class:`Locale`.  Duplicate keys are recorded but the *first*
        occurrence wins for placeholder comparison (a repeat is already a
        violation on its own, its value cannot be trusted either way).
    """
    matches = list(KEY_RE.finditer(text))
    dict_end_match = DICT_END_RE.search(text)
    body_end = dict_end_match.start() if dict_end_match is not None else len(text)

    keys: list[str] = []
    placeholders: dict[str, frozenset[str]] = {}
    duplicates: list[str] = []

    for index, match in enumerate(matches):
        key = match.group(1)
        next_start = matches[index + 1].start() if index + 1 < len(matches) else body_end
        end = min(next_start, body_end)
        segment = text[match.start() : max(end, match.end())]
        keys.append(key)
        if key in placeholders:
            duplicates.append(key)
            continue
        placeholders[key] = frozenset(PLACEHOLDER_RE.findall(segment))

    return Locale(label=label, keys=tuple(keys), placeholders=placeholders, duplicates=tuple(duplicates))


def compare_pair(base: Locale, other: Locale) -> list[Violation]:
    """Compare two locales; ``base`` (``en``) is the reference set.

    Args:
        base: Reference locale (``en``).
        other: Target locale (``zh-CN``).

    Returns:
        All violations, in a stable order: empty → duplicate → missing → extra →
        placeholder.  A well-formed pair returns an empty list.
    """
    violations: list[Violation] = []

    for locale in (base, other):
        if len(locale.key_set) < MIN_KEYS:
            violations.append(
                Violation(
                    "empty-set",
                    f"{locale.label}: 解析出 {len(locale.key_set)} 个键 —— 空集合必须红，不得当作 PASS",
                )
            )
        if locale.duplicates:
            unique_dupes = sorted(set(locale.duplicates))
            violations.append(
                Violation(
                    "duplicate-key",
                    f"{locale.label}: 重复键 {len(locale.duplicates)} 处 → {unique_dupes}",
                )
            )

    missing_in_other = sorted(base.key_set - other.key_set)
    if missing_in_other:
        violations.append(
            Violation(
                "missing-key",
                f"{other.label} 缺 {len(missing_in_other)} 个 {base.label} 的键 → {missing_in_other[:20]}"
                + ("（仅列前 20）" if len(missing_in_other) > 20 else ""),
            )
        )

    extra_in_other = sorted(other.key_set - base.key_set)
    if extra_in_other:
        violations.append(
            Violation(
                "extra-key",
                f"{other.label} 多出 {len(extra_in_other)} 个 {base.label} 没有的键 → "
                f"{extra_in_other[:20]}" + ("（仅列前 20）" if len(extra_in_other) > 20 else ""),
            )
        )

    placeholder_drift: list[str] = []
    for key in sorted(base.key_set & other.key_set):
        base_ph = base.placeholders.get(key, frozenset())
        other_ph = other.placeholders.get(key, frozenset())
        if base_ph != other_ph:
            placeholder_drift.append(
                f"{key}: {base.label}{sorted(base_ph)} vs {other.label}{sorted(other_ph)}"
            )
    if placeholder_drift:
        violations.append(
            Violation(
                "placeholder-mismatch",
                f"{len(placeholder_drift)} 个键的 {{placeholder}} 集合不一致 → "
                f"{placeholder_drift[:10]}" + ("（仅列前 10）" if len(placeholder_drift) > 10 else ""),
            )
        )

    return violations


def _load_locales(repo_root: Path) -> tuple[dict[str, Locale], str | None]:
    """Read and parse every locale file.

    Args:
        repo_root: Repository root.

    Returns:
        ``(locales, error)``: on success ``error`` is ``None``; on a missing or
        unreadable file the returned mapping holds whatever parsed so far and
        ``error`` describes the failure (the caller maps it to exit code 2).
    """
    locales: dict[str, Locale] = {}
    for label, rel_path in LOCALES.items():
        path = repo_root / rel_path
        try:
            text = path.read_text(encoding="utf-8")
        except OSError as error:
            return locales, f"无法读取 {rel_path}: {error}"
        locales[label] = parse_locale(label, text)
    return locales, None


def run_self_test() -> int:
    """Prove the detector turns red on four counter-examples (and green on control).

    Returns:
        ``0`` when all four are caught and the control stays green, else ``1``.
    """
    base_ok = parse_locale("en", '"a.one": "One",\n"a.two": "Hi {name}",\n')
    other_ok = parse_locale("zh-CN", '"a.one": "一",\n"a.two": "你好 {name}",\n')

    cases: list[tuple[str, str, Locale, Locale]] = [
        (
            "missing-key",
            "zh-CN 少一个键",
            base_ok,
            parse_locale("zh-CN", '"a.one": "一",\n'),
        ),
        (
            "extra-key",
            "zh-CN 多一个 en 没有的键",
            base_ok,
            parse_locale("zh-CN", '"a.one": "一",\n"a.two": "你好 {name}",\n"a.three": "三",\n'),
        ),
        (
            "placeholder-mismatch",
            "同一键的占位符不同名",
            base_ok,
            parse_locale("zh-CN", '"a.one": "一",\n"a.two": "你好 {nom}",\n'),
        ),
        (
            "duplicate-key",
            "en 内部重复键",
            parse_locale("en", '"a.one": "One",\n"a.one": "One again",\n"a.two": "Hi {name}",\n'),
            other_ok,
        ),
    ]

    failures: list[str] = []

    control = compare_pair(base_ok, other_ok)
    if control:
        failures.append(
            "对照组（键集与占位符都正确）不该红，实测: " + "; ".join(v.render().strip() for v in control)
        )
    else:
        sys.stdout.write("  [ok  ] control: 键集 + 占位符正确 ⇒ 绿\n")

    for expected_tag, description, base, other in cases:
        found = compare_pair(base, other)
        tags = {violation.tag for violation in found}
        if expected_tag in tags:
            sys.stdout.write(f"  [ok  ] {expected_tag}: 已捕获 '{description}'\n")
        else:
            failures.append(
                f"反例 '{description}' 未被捕获（期望 tag={expected_tag}，实测 tags={sorted(tags)}）"
            )

    if failures:
        for failure in failures:
            sys.stdout.write(f"  [FAIL] {failure}\n")
        return 1
    return 0


def main(argv: list[str] | None = None) -> int:
    """CLI entry point.

    Args:
        argv: Arguments without program name.

    Returns:
        ``0`` pass, ``1`` violation, ``2`` usage / environment error.
    """
    parser = argparse.ArgumentParser(
        prog="check_i18n_keys.py",
        description="M-4 · en / zh-CN i18n key-set parity (no node, no frontend build)",
    )
    parser.add_argument("--self-test", action="store_true", help="用内存反例证明检测器会红")
    arguments = parser.parse_args(argv)

    sys.stdout.write(f"[{TAG}] repo={ROOT.as_posix()}\n")

    if arguments.self_test:
        sys.stdout.write(f"[{TAG}] self-test: 4 个反例 + 1 个对照组\n")
        code = run_self_test()
        if code == 0:
            sys.stdout.write(f"[{TAG}] PASS (self-test)\n")
        else:
            sys.stdout.write(f"[{TAG}] FAIL (self-test)\n")
        return code

    locales, error = _load_locales(ROOT)
    if error is not None:
        sys.stderr.write(f"[{TAG}] ERROR: {error}\n")
        return 2

    base_label = "en"
    other_label = "zh-CN"
    base = locales[base_label]
    other = locales[other_label]

    sys.stdout.write(
        f"  measured: {base_label} keys={len(base.key_set)}（行数 {len(base.keys)}）, "
        f"{other_label} keys={len(other.key_set)}（行数 {len(other.keys)}）\n"
    )

    violations = compare_pair(base, other)
    for violation in violations:
        sys.stdout.write(violation.render() + "\n")

    if violations:
        sys.stdout.write(f"[{TAG}] FAIL ({len(violations)} 项)\n")
        return 1

    sys.stdout.write(
        f"  [ok  ] 键集双向相等（{len(base.key_set)} 个键）、无重复、"
        f"{len(base.key_set & other.key_set)} 个同名键的占位符集合一致\n"
    )
    sys.stdout.write(f"[{TAG}] PASS\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

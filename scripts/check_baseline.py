"""Baseline invariants for the repo skeleton (C-08).

Everything this script asserts is a *hard* clause from docs, encoded so it cannot
silently drift:

============================  ================================================  ==============
Invariant                     Source                                            Enforcement
============================  ================================================  ==============
``version == "0.3.0"``        V0.3.0 版本回写（纪律 §4.2-1 迭代号=版本号，全栈同版）  exact
``version != "0.4.8"``        0.4.8 是旧线 ``create_app().openapi()`` 的代码串，   forbidden
                              **从未发布**，不得作为 TS 线版本号
``engines.node``              `施工纪律.md` §4.7-1 / roadmap §7.2-15            exact string
``^22.19.0 || >=24.0.0``      （不得写 ``>=22`` / ``>=24`` / ``22``）
``.nvmrc == 24.18.1``         桌面实际档 = 选定 Electron 内置 Node 精确值        exact
CI matrix node values          `施工纪律.md` §4.7-4                              exact set
``{22.19.0, 24.18.1, 26.x}``  （禁止浮点 major ``22`` / ``24``）
CI ``continue-on-error``      §4.7-4 「全部 required」                          forbidden
per-leg runtime assertion     `施工纪律.md` §4.7-5                              required
============================  ================================================  ==============

YAML is parsed with PyYAML when available, and with a narrow regex fallback
otherwise, so the gate runs on a bare Python too (the CI image does not
guarantee PyYAML); both paths assert the same invariants.

Exit codes: ``0`` pass, ``1`` violation, ``2`` usage error.
Standard library only (PyYAML optional).
"""

from __future__ import annotations

import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path

__all__ = [
    "EXPECTED_NAME",
    "EXPECTED_VERSION",
    "FORBIDDEN_VERSION",
    "EXPECTED_ENGINES_NODE",
    "EXPECTED_NVMRC",
    "EXPECTED_CI_NODE_VALUES",
    "Check",
    "main",
]

EXPECTED_NAME = "wbtime-ai"
EXPECTED_VERSION = "0.3.0"
FORBIDDEN_VERSION = "0.4.8"
EXPECTED_ENGINES_NODE = "^22.19.0 || >=24.0.0"
EXPECTED_NVMRC = "24.18.1"
EXPECTED_CI_NODE_VALUES = ("22.19.0", "24.18.1", "26.x")
EXPECTED_PNPM = "pnpm@9.15.0"

#: A floating major such as ``22`` or ``24`` is banned in the matrix (§4.7-4).
FLOATING_MAJOR_RE = re.compile(r"^\d+$")


@dataclass
class Check:
    """One assertion result."""

    ident: str
    ok: bool
    detail: str

    def render(self) -> str:
        """Render as ``[ok]/[FAIL] id: detail``."""
        flag = "ok  " if self.ok else "FAIL"
        return f"  [{flag}] {self.ident}: {self.detail}"


def _load_package_json(repo_root: Path, checks: list[Check]) -> dict:
    """Parse ``package.json``, recording a failure instead of raising."""
    path = repo_root / "package.json"
    if not path.is_file():
        checks.append(Check("package.json", False, f"missing: {path}"))
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        checks.append(Check("package.json", False, f"invalid JSON: {error}"))
        return {}


def _ci_node_values(workflow_text: str) -> list[str]:
    """Extract the matrix ``node:`` values from the workflow, preferring PyYAML."""
    try:
        import yaml  # noqa: PLC0415 - optional dependency
    except ImportError:
        return re.findall(r'^\s*-\s*node:\s*"?([0-9][0-9.]*(?:\.x)?)"?\s*$', workflow_text, re.MULTILINE)

    document = yaml.safe_load(workflow_text) or {}
    values: list[str] = []
    jobs = document.get("jobs") or {}
    for job in jobs.values():
        if not isinstance(job, dict):
            continue
        matrix = ((job.get("strategy") or {}).get("matrix") or {})
        include = matrix.get("include") or []
        if isinstance(include, list):
            for item in include:
                if isinstance(item, dict) and "node" in item:
                    values.append(str(item["node"]))
        single = matrix.get("node")
        if isinstance(single, list):
            values.extend(str(value) for value in single)
    return values


def _yaml_available() -> bool:
    """Return ``True`` when PyYAML can be imported."""
    try:
        import yaml  # noqa: F401,PLC0415 - probe only
    except ImportError:
        return False
    return True


def _strip_yaml_comments(text: str) -> str:
    """Drop YAML comment lines and trailing `` # ...`` comments.

    Needed because this workflow *documents* the banned constructs in comments
    (``# 禁止 continue-on-error``); a naive substring search would fire on the
    documentation instead of the configuration.

    Args:
        text: Raw workflow text.

    Returns:
        Text with comments removed; line structure preserved.
    """
    kept: list[str] = []
    for line in text.splitlines():
        stripped = line.lstrip()
        if stripped.startswith("#"):
            kept.append("")
            continue
        marker = line.find(" #")
        kept.append(line[:marker] if marker != -1 else line)
    return "\n".join(kept)


def run_checks(repo_root: Path) -> list[Check]:
    """Evaluate every invariant.

    Args:
        repo_root: Repository root.

    Returns:
        Ordered list of :class:`Check` results.
    """
    checks: list[Check] = []
    package = _load_package_json(repo_root, checks)

    name = package.get("name")
    checks.append(
        Check("package.json/name", name == EXPECTED_NAME, f"{name!r} (expected {EXPECTED_NAME!r})")
    )

    version = package.get("version")
    checks.append(
        Check(
            "package.json/version",
            version == EXPECTED_VERSION,
            f"{version!r} (expected {EXPECTED_VERSION!r})",
        )
    )
    checks.append(
        Check(
            "package.json/version!=0.4.8",
            str(version) != FORBIDDEN_VERSION,
            f"{version!r} (0.4.8 是旧线 OpenAPI 代码串，从未发布，禁止作为 TS 线版本号)",
        )
    )

    # 全栈版本串一致（路线图 D6）—— 所有 workspace 成员的 version 必须等于根 version。
    #
    # Why (2026-10-21): 出包前实测发现 `packages/e2e` 仍是 `0.0.2`，而其余 10 个成员
    # 已是 `0.1.0`。此前本脚本只读根 `package.json`，**成员漂移无人发现**，而 D6 明写
    # 「版本串全栈一致（所有 `package.json` + 契约 manifest）」。只查根等于只查了 1/11。
    mismatched: list[str] = []
    member_paths: list[Path] = []
    for pattern in ("apps/*/package.json", "packages/*/package.json"):
        member_paths.extend(sorted(repo_root.glob(pattern)))
    for member_path in member_paths:
        try:
            member = json.loads(member_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            mismatched.append(f"{member_path.parent.name}:<UNREADABLE>")
            continue
        member_version = member.get("version")
        if member_version != version:
            mismatched.append(f"{member.get('name')}:{member_version}")
    checks.append(
        Check(
            "workspace/version一致",
            bool(member_paths) and not mismatched,
            (
                f"{len(member_paths)} 个成员全部 = {version!r}"
                if member_paths and not mismatched
                else (
                    f"漂移 {len(mismatched)}/{len(member_paths)} 个: {mismatched}"
                    "（D6 要求全栈版本串一致）"
                )
            ),
        )
    )

    private = package.get("private")
    checks.append(Check("package.json/private", private is True, f"{private!r} (expected True)"))

    engines = package.get("engines") or {}
    engines_node = engines.get("node") if isinstance(engines, dict) else None
    checks.append(
        Check(
            "package.json/engines.node",
            engines_node == EXPECTED_ENGINES_NODE,
            f"{engines_node!r} (expected {EXPECTED_ENGINES_NODE!r}, 逐字符比对)",
        )
    )

    manager = package.get("packageManager")
    checks.append(
        Check("package.json/packageManager", manager == EXPECTED_PNPM, f"{manager!r} (expected {EXPECTED_PNPM!r})")
    )

    nvmrc_path = repo_root / ".nvmrc"
    nvmrc = nvmrc_path.read_text(encoding="utf-8").strip() if nvmrc_path.is_file() else None
    checks.append(Check(".nvmrc", nvmrc == EXPECTED_NVMRC, f"{nvmrc!r} (expected {EXPECTED_NVMRC!r})"))

    workspace_path = repo_root / "pnpm-workspace.yaml"
    workspace_ok = False
    workspace_detail = f"missing: {workspace_path}"
    if workspace_path.is_file():
        workspace_text = workspace_path.read_text(encoding="utf-8")
        has_key = re.search(r"^packages:\s*$", workspace_text, re.MULTILINE) is not None
        has_entries = re.search(r"^\s*-\s*[\"']?[^\s#]", workspace_text, re.MULTILINE) is not None
        workspace_ok = has_key and has_entries
        workspace_detail = f"packages: key={has_key} entries={has_entries}"
    checks.append(Check("pnpm-workspace.yaml", workspace_ok, workspace_detail))

    workflow_path = repo_root / ".github" / "workflows" / "ci.yml"
    if not workflow_path.is_file():
        checks.append(Check("ci.yml", False, f"missing: {workflow_path}"))
        checks.append(Check("ci.yml/node matrix", False, "workflow missing"))
        checks.append(Check("ci.yml/no continue-on-error", True, "workflow missing (vacuous)"))
        checks.append(Check("ci.yml/per-leg assertion", False, "workflow missing"))
        return checks

    text = workflow_path.read_text(encoding="utf-8")
    parser = "PyYAML" if _yaml_available() else "regex fallback"
    node_values = _ci_node_values(text)

    expected_set = set(EXPECTED_CI_NODE_VALUES)
    actual_set = set(node_values)
    checks.append(
        Check(
            "ci.yml/node matrix",
            actual_set == expected_set and len(node_values) == len(expected_set),
            f"{sorted(actual_set)} (expected {sorted(expected_set)}, parser={parser})",
        )
    )

    floating = [value for value in node_values if FLOATING_MAJOR_RE.match(value)]
    checks.append(
        Check(
            "ci.yml/no floating major",
            not floating,
            f"floating majors={floating or 'none'} (禁止写 22 / 24：会解析成该线最新值 ⇒ 测不到下界)",
        )
    )

    code_only = _strip_yaml_comments(text)
    checks.append(
        Check(
            "ci.yml/no continue-on-error",
            re.search(r"^\s*continue-on-error\s*:", code_only, re.MULTILINE) is None,
            "absent"
            if re.search(r"^\s*continue-on-error\s*:", code_only, re.MULTILINE) is None
            else "FOUND continue-on-error key (三档必须全部 required)",
        )
    )

    asserts_runtime = "process.versions.node" in code_only
    asserts_env = "DECLARED" in code_only and "matrix.node" in code_only
    checks.append(
        Check(
            "ci.yml/per-leg assertion",
            asserts_runtime and asserts_env,
            f"process.versions.node={asserts_runtime} env_from_matrix.node={asserts_env}",
        )
    )

    nvmrc_in_matrix = nvmrc in actual_set if nvmrc else False
    checks.append(
        Check(
            "ci.yml/desktop tier == .nvmrc",
            nvmrc_in_matrix,
            f".nvmrc={nvmrc!r} in matrix={sorted(actual_set)}",
        )
    )

    return checks


def main(argv: list[str] | None = None) -> int:
    """CLI entry point.

    Args:
        argv: Arguments without program name (all arguments are ignored; a
            ``--repo-root`` override exists for out-of-tree validation).

    Returns:
        ``0`` pass, ``1`` violation, ``2`` usage error.
    """
    arguments = list(argv) if argv is not None else sys.argv[1:]
    repo_root = Path(__file__).resolve().parents[1]
    if "--repo-root" in arguments:
        position = arguments.index("--repo-root")
        try:
            repo_root = Path(arguments[position + 1]).resolve()
        except IndexError:
            sys.stderr.write("[check_baseline] ERROR: --repo-root 缺少路径参数\n")
            return 2
    elif arguments:
        sys.stderr.write(f"[check_baseline] ERROR: 未知参数 {arguments}\n")
        return 2

    if not (repo_root / "package.json").is_file():
        sys.stderr.write(f"[check_baseline] ERROR: 找不到 {repo_root / 'package.json'}\n")
        return 2

    checks = run_checks(repo_root)
    failures = [check for check in checks if not check.ok]

    sys.stdout.write(f"[check_baseline] repo={repo_root.as_posix()} checks={len(checks)}\n")
    for check in checks:
        sys.stdout.write(check.render() + "\n")

    if failures:
        sys.stdout.write(f"[check_baseline] FAIL ({len(failures)}/{len(checks)})\n")
        return 1

    sys.stdout.write(f"[check_baseline] PASS ({len(checks)}/{len(checks)})\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

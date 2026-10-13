#!/usr/bin/env python3
"""manual 验收证据归档校验（V0.4.1 · J-2；设计 §13.1「无证据不得通过」/ 决策 1 / A-12）。

**定位**：G3 手动验收签署环节的**门禁脚本**——校验
``docs/设计/验收证据/manual-checklists/*.md`` 中「**声称通过**」的条目的证据**存在且非空**。
**空槽 / 引用缺失 / 指向不存在文件 / 0 字节 → 违规，退出码非 0**；
「**显式未留证标注**」（未留证 / 未执行 / 挂账 / ⛔ …）= **已披露状态**（输出「未验收清单」，
**不按违规计**）。长期资产：``V0.5+`` 直接继承（接口稳定：``--root`` 参数化 + 退出码语义）。

**解析口径（据仓库真实格式定义）**——逐文件按「单元」分析（跳过 ``` 围栏代码块）：

- **表格数据行**：若表头含含「证据」的列（如 ``证据（脱敏）`` / ``证据路径``），该列为「证据列」。
  行「声称通过」= 含 ``[x]`` / ``✅`` / ``☑`` / ``✔`` / ``通过`` / ``PASS``。
  - 证据列**非空** → 抽取其中**文件引用**并校验存在 + 非空（不存在的引用即违规）；
  - 证据列**为空** 且 行声称通过（或含 ``☐ 通过`` 结论框）且**未**显式披露 → **空槽违规**。
- **无证据列的表格行 / 列表项 / 段落**：仅当**声称通过**且未披露时，校验其中的文件引用。

**文件引用**语法 = 反引号代码段 / 链接目标 / 裸词 中匹配 ``含 / 且带证据类扩展名`` 的路径；
多基准解析（``repo_root`` / ``docs_root`` / ``manual_dir``），任一存在即通过（宽容解析，降误报）。

**退出码**：``0`` = 通过（含「素材未挂载」的**显式**跳过）；``1`` = 存在违规；
``2`` = 素材缺失且 ``--require-material``（强制）。

用法::

    python scripts/check_manual_evidence.py                 # 自动定位 manual-checklists
    python scripts/check_manual_evidence.py --root docs     # docs 仓布局
    python scripts/check_manual_evidence.py --root .        # 父仓布局（含 docs/）
    python scripts/check_manual_evidence.py --json          # JSON 输出
    python scripts/check_manual_evidence.py --require-material  # 素材缺失 → 退出码 2

🔴 **零第三方依赖**（仅标准库）；**只读**。
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections.abc import Iterator
from dataclasses import asdict, dataclass
from pathlib import Path

__all__ = ["Finding", "main", "scan", "scan_checklist"]

#: 验收证据根目录片段（相对 docs 仓 / 父仓的两种布局）。
_MANUAL_DIR_PARTS: tuple[str, ...] = ("设计", "验收证据", "manual-checklists")

#: 默认扫描根（本脚本位于 ``<repo>/scripts/`` 下）。
DEFAULT_ROOT = Path(__file__).resolve().parents[1]

#: 「声称通过」标记（勾选 / ✅ / ☑ / ✔ / 通过 / PASS）——**大小写不敏感**于 ``PASS``。
_PASS_RE = re.compile(r"\[[xX]\]|✅|☑|✔|通过|\bPASS(?:ED)?\b", re.IGNORECASE)

#: 「显式未留证 / 未执行」披露标记（= 已披露状态，非违规）。
_DISCLOSE_MARKS: tuple[str, ...] = (
    "未留证",
    "未执行",
    "挂账",
    "⛔",
    "N/A",
    "不适用",
    "not applicable",
)

#: 表格行「结论框」（``☐ 通过`` / ``☑ 通过``）——空槽判定辅助。
_CONCLUSION_BOX_RE = re.compile(r"[☐☑]\s*通过")

#: 反引号代码段。
_CODE_RE = re.compile(r"`([^`]+)`")
#: markdown 链接目标 ``[text](target)``。
_LINK_RE = re.compile(r"\[[^\]]*\]\(([^)]+)\)")
#: 文件引用：**含路径分隔符** 且 带证据类扩展名的 token。
_PATH_RE = re.compile(
    r"^[\w.\-/]+/[\w.\-/]+\.(?:md|txt|json|png|jpe?g|log|csv|pdf|ya?ml|gz|zip|tar)$",
    re.IGNORECASE,
)
#: 裸 token（用于从正文中提取路径）。
_TOKEN_RE = re.compile(r"[\w.\-/]+")


@dataclass(frozen=True)
class Finding:
    """一条违规发现项。"""

    rule: str
    file: str
    line: int
    message: str


# -- 解析辅助 ----------------------------------------------------------------


def _split_row(line: str) -> list[str]:
    """拆分 markdown 表格行 → 单元格列表（去首尾 ``|``；忽略转义 ``\\|`` 的边角情形）。"""
    stripped = line.strip()
    if stripped.startswith("|"):
        stripped = stripped[1:]
    if stripped.endswith("|"):
        stripped = stripped[:-1]
    return [cell.strip() for cell in stripped.split("|")]


def _is_separator(cells: list[str]) -> bool:
    """是否为表头分隔行（``---`` / ``:--:``）。"""
    return bool(cells) and all(re.fullmatch(r":?-{2,}:?", cell) for cell in cells)


def _iter_units(
    markdown: str,
) -> Iterator[tuple[str, int, list[str] | None, list[str] | None, str]]:
    """产出「单元」：``(kind, lineno, cells|None, header|None, text)``。

    ``kind`` ∈ ``row``（表格数据行）/ ``line``（列表项 / 段落）。跳过 ``` 围栏代码块；
    表格以「首个 ``|`` 行 = 表头」切分，遇非表格行重置；``row`` 单元保留其 ``header``
    （供「证据列」定位）。
    """
    header: list[str] | None = None
    in_fence = False
    for lineno, raw in enumerate(markdown.splitlines(), start=1):
        stripped = raw.strip()
        if stripped.startswith("```"):
            in_fence = not in_fence
            continue
        if in_fence or not stripped:
            header = None
            continue
        if stripped.startswith("|"):
            cells = _split_row(stripped)
            if header is None:
                header = cells  # 表头
                continue
            if _is_separator(cells):
                continue
            yield ("row", lineno, cells, header, stripped)
        else:
            header = None
            yield ("line", lineno, None, None, stripped)


def _extract_refs(text: str) -> list[str]:
    """从文本抽取**文件引用**（链接目标 + 反引号代码段 + 裸 token，均需匹配路径语法）。"""
    refs: list[str] = []
    for target in _LINK_RE.findall(text):
        candidate = target.split("#", 1)[0].strip()
        if _PATH_RE.match(candidate):
            refs.append(candidate)
    for span in _CODE_RE.findall(text):
        candidate = span.strip()
        if _PATH_RE.match(candidate):
            refs.append(candidate)
    for token in _TOKEN_RE.findall(text):
        if _PATH_RE.match(token):
            refs.append(token)
    # 去重，保序
    seen: set[str] = set()
    unique: list[str] = []
    for ref in refs:
        if ref not in seen:
            seen.add(ref)
            unique.append(ref)
    return unique


def _resolve_ref(ref: str, bases: tuple[Path, ...]) -> Path | None:
    """在多个基准下解析引用 → 首个存在路径（否则 ``None``）。"""
    normalized = ref.replace("\\", "/").lstrip("./")
    for base in bases:
        candidate = (base / normalized).resolve()
        if candidate.exists():
            return candidate
    return None


# -- 单文件扫描 --------------------------------------------------------------


def scan_checklist(path: Path, bases: tuple[Path, ...]) -> list[Finding]:
    """扫描单个 checklist 文件 → 违规列表。"""
    findings: list[Finding] = []
    rel = path.name
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return [Finding("manual_evidence.unreadable", rel, 0, f"清单不可读：{path}")]

    for kind, lineno, cells, header, raw in _iter_units(text):
        if kind == "row" and cells is not None and header is not None:
            row_text = " ".join(cells)
            claimed = bool(_PASS_RE.search(row_text))
            disclosed = any(mark in row_text for mark in _DISCLOSE_MARKS)
            ev_index = next((i for i, h in enumerate(header) if "证据" in h), None)
            ev_value = (
                cells[ev_index].strip() if ev_index is not None and ev_index < len(cells) else None
            )

            if disclosed:
                continue
            if ev_index is not None:
                if ev_value:  # 证据列非空 → 校验其中的文件引用
                    findings.extend(_check_refs(_extract_refs(ev_value), rel, lineno, bases))
                elif claimed or _CONCLUSION_BOX_RE.search(row_text):
                    # 空证据槽 + 声称通过 / 含结论框 → 空槽违规（对齐 R1–R4「每槽必填」）。
                    findings.append(
                        Finding(
                            "manual_evidence.empty_slot",
                            rel,
                            lineno,
                            "空槽：声称通过 / 待核但证据缺失（第 "
                            f"{lineno} 行，证据列 `{header[ev_index]}` 为空）",
                        )
                    )
            elif claimed:  # 无证据列的表格行（键值表）→ 校验行内引用
                findings.extend(_check_refs(_extract_refs(row_text), rel, lineno, bases))
        else:
            claimed = bool(_PASS_RE.search(raw))
            disclosed = any(mark in raw for mark in _DISCLOSE_MARKS)
            if claimed and not disclosed:
                findings.extend(_check_refs(_extract_refs(raw), rel, lineno, bases))

    return findings


def _check_refs(refs: list[str], rel: str, lineno: int, bases: tuple[Path, ...]) -> list[Finding]:
    """校验引用：不存在 → 违规；存在但 0 字节 → 违规。"""
    findings: list[Finding] = []
    for ref in refs:
        resolved = _resolve_ref(ref, bases)
        if resolved is None:
            findings.append(
                Finding(
                    "manual_evidence.reference_missing",
                    rel,
                    lineno,
                    f"引用的证据文件不存在：`{ref}`",
                )
            )
        elif resolved.is_file() and resolved.stat().st_size == 0:
            findings.append(
                Finding(
                    "manual_evidence.reference_empty",
                    rel,
                    lineno,
                    f"引用的证据文件为 0 字节：`{ref}`",
                )
            )
    return findings


# -- 目录扫描 ----------------------------------------------------------------


def _locate_manual_dir(root: Path) -> Path | None:
    """在 ``root``（docs 仓布局）或 ``root/docs``（父仓布局）下定位 manual-checklists。"""
    candidates = [root.joinpath(*_MANUAL_DIR_PARTS), root.joinpath("docs", *_MANUAL_DIR_PARTS)]
    for candidate in candidates:
        if candidate.is_dir():
            return candidate
    return None


def _resolution_bases(manual_dir: Path) -> tuple[Path, ...]:
    """引用解析基准：``repo_root`` / ``docs_root`` / ``manual_dir``（宽容多基准）。"""
    docs_root = manual_dir
    for _ in _MANUAL_DIR_PARTS:
        docs_root = docs_root.parent
    repo_root = docs_root.parent
    return (repo_root, docs_root, manual_dir)


def scan(root: Path) -> tuple[list[Finding], Path | None]:
    """扫描 ``root`` 下全部 checklist 文件 → ``(findings, manual_dir|None)``。"""
    manual_dir = _locate_manual_dir(root)
    if manual_dir is None:
        return ([], None)
    bases = _resolution_bases(manual_dir)
    findings: list[Finding] = []
    for path in sorted(manual_dir.glob("*.md")):
        findings.extend(scan_checklist(path, bases))
    return (findings, manual_dir)


def main(argv: list[str] | None = None) -> int:
    """脚本入口；返回退出码（``0`` 通过 / ``1`` 违规 / ``2`` 素材缺失且强制）。"""
    parser = argparse.ArgumentParser(description="Astra AI manual 验收证据归档校验（J-2）")
    parser.add_argument("--root", default=str(DEFAULT_ROOT), help="扫描根（默认仓库根）")
    parser.add_argument("--json", action="store_true", help="以 JSON 输出发现项")
    parser.add_argument(
        "--require-material",
        action="store_true",
        help="素材（manual-checklists）缺失时退出码 2（默认：显式提示并跳过 → 0）",
    )
    args = parser.parse_args(argv)

    root = Path(args.root).resolve()
    findings, manual_dir = scan(root)

    if manual_dir is None:
        # 「目录不存在（docs 未挂载）」→ 明确提示 + 定义可解释退出语义（**不** `|| true`）。
        suffix = (
            "按 --require-material 视为失败（退出码 2）。"
            if args.require_material
            else "明示跳过（退出码 0）。"
        )
        message = (
            f"manual-checklists 目录不存在（docs 未挂载 / 路径不符）：root={root}。"
            f"未执行证据校验——{suffix}"
        )
        print(f"[manual-evidence] {message}", file=sys.stderr)
        return 2 if args.require_material else 0

    if args.json:
        print(json.dumps([asdict(item) for item in findings], ensure_ascii=False, indent=2))
    elif findings:
        for item in findings:
            print(f"{item.file}:{item.line}: [{item.rule}] {item.message}", file=sys.stderr)
        print(f"manual 证据校验失败：{len(findings)} 项违规", file=sys.stderr)
    else:
        print(
            f"manual 证据校验通过（root={root}）："
            "无「声称通过但证据缺失 / 引用不存在 / 0 字节」条目"
        )

    return 1 if findings else 0


if __name__ == "__main__":  # pragma: no cover - CLI 直执行
    raise SystemExit(main())

#!/usr/bin/env python3
"""纪律扫描脚本（W10 / T2-51；设计 §2.17 / §3-#22 ``I-P2-22``）。

**定位**：与既有 ``tests/integration/test_layering.py`` **分工互补**（不重复造）——
本脚本为 **CI 可执行**的**单一入口**，覆盖四类纪律，**任一违规 → 退出码非 0**：

1. **分层（layering）** —— AST 级 import / 使用点扫描（非子串，规避 docstring 误报）：
   - ``packages/*/src/*/domain/**``（含 ``packages/domain`）**零** ``fastapi`` / ``starlette`` /
     ``sqlalchemy`` / ``alembic`` 导入；
   - ``apps/api/src/astra_api/routers/**`` **零** ``sqlalchemy`` / ``astra_database`` /
     ``astra_runtime`` 导入，且**零 MCP Client 直调**（``MCPClient`` / ``MCPClientInvoker`` /
     ``MCPStdioClient`` / ``MCPHttpClient`` 符号）。
2. **开源（open-source）** —— 全仓（排除 ``docs/`` / ``tests/`` / 隐藏目录 / 明确白名单）
   **无商业分流**（商业版 / 版本 gate 分支逻辑）。
3. **凭证（credential）** —— AST 级：**无明文密码 / 令牌写入日志或响应**——检测把敏感标识符
   （``password`` / ``secret`` / ``token`` / ``api_key`` / ``private_key``）经 ``logger.*`` /
   ``print`` 输出的调用点（f-string / 格式化 / 直接实参均覆盖）。
4. **出网判定唯一源（egress single-source）** —— 全仓**仅**规范原语（``astra_domain.ports.egress``）
   / 唯一入口（``astra_security.egress``）/ Phase 1 薄委托（``astra_tool.security``）**定义**出网判定
   符号；其它位置定义即「另建白名单判定源」违规（R1 / T2-56 · L-6）。

用法::

    python scripts/scan_discipline.py            # 扫描仓库根；违规退出码 1
    python scripts/scan_discipline.py --json     # 以 JSON 输出发现项
    python scripts/scan_discipline.py --root DIR # 扫描指定目录（供测试构造违规样本）

🔴 每条规则逐条注释其口径与依据；本脚本**零第三方依赖**（仅标准库）。
"""

from __future__ import annotations

import argparse
import ast
import json
import re
import sys
from collections.abc import Iterator
from dataclasses import asdict, dataclass
from pathlib import Path

__all__ = [
    "Finding",
    "main",
    "scan",
    "scan_credentials",
    "scan_egress_single_source",
    "scan_layering",
    "scan_open_source",
]

#: 默认扫描根（本脚本位于 ``<repo>/scripts/`` 下）。
DEFAULT_ROOT = Path(__file__).resolve().parents[1]

#: 显式排除的路径片段（docs / tests 与缓存 / 依赖目录 / VCS）。
EXCLUDED_PARTS: frozenset[str] = frozenset(
    {
        "docs",
        "tests",
        "plugins",
        "node_modules",
        ".venv",
        "venv",
        "__pycache__",
        ".git",
        "site-packages",
    }
)

#: ``domain/**`` 禁用的 Web / ORM 顶层模块根（分层 §2.2）。
DOMAIN_FORBIDDEN_ROOTS: frozenset[str] = frozenset(
    {"fastapi", "starlette", "sqlalchemy", "alembic"}
)

#: Router 禁用的基础设施顶层模块根（R-W10-10 / N-8）。
ROUTER_FORBIDDEN_ROOTS: frozenset[str] = frozenset(
    {"sqlalchemy", "astra_database", "astra_runtime"}
)

#: Router 禁用的 **MCP Client 直调**符号（应经 ``AppServices`` 注入的工厂取用）。
MCP_CLIENT_SYMBOLS: frozenset[str] = frozenset(
    {"MCPClient", "MCPClientInvoker", "MCPStdioClient", "MCPHttpClient"}
)

#: 敏感标识符片段（凭证不得经日志 / 打印输出）。
#: 说明：不含 ``credential``（过泛，易与 ``credential_id`` 等审计字段误撞）；
#: 聚焦「密码 / 令牌 / 密钥」。
SENSITIVE_TOKENS: tuple[str, ...] = (
    "password",
    "passwd",
    "secret",
    "api_key",
    "apikey",
    "private_key",
)

#: R1 / T2-56（L-6）：出网**判定**源（决策原语 / 白名单门）符号名——**唯一来源**。
#: 全仓**仅**下列文件允许**定义**这些符号；其它文件定义即视为「另建白名单判定源」违规。
EGRESS_DECISION_SYMBOLS: frozenset[str] = frozenset(
    {
        "SecurityEgressPolicy",
        "EgressPolicy",
        "EgressDecision",
        "host_matches",
        "is_blocked_ip",
        "is_metadata_ip",
        "resolve_all",
        "resolve_and_validate",
        "DENY_RANGES",
        "METADATA_IPS",
        "ALLOWED_SCHEMES",
    }
)

#: 允许**定义**出网判定符号的位置（相对仓库根的 posix 路径后缀）。
#: - ``astra_domain.ports.egress``：**规范原语**（唯一来源）；
#: - ``astra_security/egress/**``：**唯一入口实现**（策略 / DNS / 拒段再导出）；
#: - ``astra_tool/security.py``：Phase 1 **薄委托**兼容层（签名 / 语义不变，grandfathered）。
EGRESS_ALLOWED_DEFINITION_PATHS: tuple[str, ...] = (
    "packages/domain/src/astra_domain/ports/egress.py",
    "packages/security/src/astra_security/egress/policy.py",
    "packages/security/src/astra_security/egress/dns.py",
    "packages/security/src/astra_security/egress/deny_ranges.py",
    "packages/security/src/astra_security/egress/__init__.py",
    "packages/security/src/astra_security/egress/proxy.py",
    "packages/tool/src/astra_tool/security.py",
)

#: ``token`` 属**歧义**片段：命中它时，若标识符同时含下列「良性限定词」（用量 / 计数 /
#: 上限 / 窗口等**非凭证**语义）则**不视为敏感**（如 ``last_token_usage`` / ``token_count``）。
_TOKEN_BENIGN_QUALIFIERS: tuple[str, ...] = (
    "usage",
    "count",
    "limit",
    "budget",
    "total",
    "max",
    "length",
    "window",
    "num",
)

#: 视为「日志出口」的方法名（``logger.<m>`` / ``logging.<m>``）。
_LOG_METHODS: frozenset[str] = frozenset(
    {"info", "debug", "warning", "warn", "error", "critical", "exception", "log"}
)

#: 视为「打印出口」的函数名。
_LOG_FUNCS: frozenset[str] = frozenset({"print"})

#: 开源纪律：商业分流模式（保守：命中即违规；``\s+`` 转义规避扫描脚本自身误报）。
_COMMERCIAL_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\bif\s+commercial\b"),
    re.compile(r"\bedition\s*=="),
    re.compile(r"\bIS_COMMERCIAL\b"),
    re.compile(r"\bEDITION_GATE\b"),
    re.compile(r"\bis_commercial\b"),
    re.compile(r"\bcommercial_edition\b"),
)


@dataclass(frozen=True)
class Finding:
    """一条违规发现项。"""

    rule: str
    path: str
    line: int
    message: str


# -- 遍历 / 判定辅助 ---------------------------------------------------------


def _iter_py(root: Path) -> Iterator[Path]:
    """遍历 ``root`` 下的 ``.py``（显式排除白名单片段与**隐藏目录**）。

    排除判定一律基于 **相对 ``root`` 的路径**（非绝对路径）——这样既能过滤仓库内的
    ``.git`` / ``.venv`` / 各类缓存 / **pytest basetemp**（``.pytest_tmp*`` / ``.wt10_tmp`` 等，
    防把测试运行期落在仓库内的**临时构造样本**当真实源码扫的「自我污染」型假阳），
    又**不误伤**以隐藏临时目录为**扫描根**的合法调用（如测试以 ``tmp_path`` 构造违规样本时，
    其根之上的隐藏段不属于相对路径）。
    """
    resolved_root = root.resolve()
    for path in sorted(resolved_root.rglob("*.py")):
        try:
            rel_parts = path.relative_to(resolved_root).parts
        except ValueError:  # pragma: no cover - rglob 结果必在 root 之下
            rel_parts = path.parts
        if EXCLUDED_PARTS & set(rel_parts):
            continue
        # 仅对**目录段**（去掉文件名）做隐藏判定。
        if any(part.startswith(".") for part in rel_parts[:-1]):
            continue
        yield path


def _is_domain_module(path: Path, root: Path) -> bool:
    """是否为 ``domain/**`` 模块（规范化相对 ``root`` 后判断 ``domain`` 段）。"""
    try:
        parts = path.relative_to(root).parts
    except ValueError:
        parts = path.parts
    return "domain" in parts


def _is_router_module(path: Path) -> bool:
    """是否为 API Router 模块（``.../routers/**.py``）。"""
    return "routers" in path.parts and path.suffix == ".py"


def _rel(path: Path, root: Path) -> str:
    """相对 ``root`` 的路径字符串（越界时回退绝对路径）。"""
    try:
        return str(path.relative_to(root))
    except ValueError:
        return str(path)


def _parse(path: Path) -> ast.Module | None:
    """解析为 AST；语法错误时返回 ``None``（不因单文件失败而整体中断）。"""
    try:
        return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except SyntaxError:  # pragma: no cover - 正常仓库无语法错误
        return None


def _import_roots(tree: ast.AST) -> Iterator[tuple[str, int]]:
    """产出全部 import 的**顶层模块根**及其行号（含函数内 import）。"""
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                yield alias.name.split(".")[0], node.lineno
        elif isinstance(node, ast.ImportFrom) and node.module:
            yield node.module.split(".")[0], node.lineno


def _imported_and_used_names(tree: ast.AST) -> Iterator[tuple[str, int]]:
    """产出被 import 或作为 ``Name`` / ``Attribute`` 使用的符号名（MCP Client 直调检测用）。"""
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            for alias in node.names:
                yield alias.name, node.lineno
        elif isinstance(node, ast.Name):
            yield node.id, node.lineno
        elif isinstance(node, ast.Attribute):
            yield node.attr, getattr(node, "lineno", 0)


# -- 规则 1：分层 ------------------------------------------------------------


def scan_layering(root: Path) -> list[Finding]:
    """分层纪律：``domain/**`` 零 Web / ORM；Router 零 ORM / Runtime / MCP Client 直调。

    依据：设计 §2.2（包分层）/ §2.15（Router 只依赖 ``AppServices``）/ R-W10-10。
    与 ``test_layering.py`` 互补（此处为 **AST** 口径，规避 docstring 子串误报）。
    """
    findings: list[Finding] = []
    for path in _iter_py(root):
        tree = _parse(path)
        if tree is None:
            continue

        if _is_domain_module(path, root):
            for module_root, lineno in _import_roots(tree):
                if module_root in DOMAIN_FORBIDDEN_ROOTS:
                    findings.append(
                        Finding(
                            rule="layering.domain_no_web_orm",
                            path=_rel(path, root),
                            line=lineno,
                            message=f"domain 模块不得 import `{module_root}`（零 Web/ORM）",
                        )
                    )

        if _is_router_module(path):
            for module_root, lineno in _import_roots(tree):
                if module_root in ROUTER_FORBIDDEN_ROOTS:
                    findings.append(
                        Finding(
                            rule="layering.router_no_infra",
                            path=_rel(path, root),
                            line=lineno,
                            message=(
                                f"Router 不得 import `{module_root}`"
                                "（只依赖 AppServices/CurrentUser）"
                            ),
                        )
                    )
            for name, lineno in _imported_and_used_names(tree):
                if name in MCP_CLIENT_SYMBOLS:
                    findings.append(
                        Finding(
                            rule="layering.router_no_mcp_client",
                            path=_rel(path, root),
                            line=lineno,
                            message=f"Router 不得直调 MCP Client（`{name}` 应经 AppServices 取用）",
                        )
                    )
    return findings


# -- 规则 2：开源 ------------------------------------------------------------


def scan_open_source(root: Path) -> list[Finding]:
    """开源纪律：全仓（排除 ``docs/`` / ``tests/`` 与白名单）无商业版 / 版本分流。

    依据：设计 §3-#19 / 总纲 §13.3（核心 100% 开源，无 edition gate）。
    """
    findings: list[Finding] = []
    for path in _iter_py(root):
        text = path.read_text(encoding="utf-8", errors="ignore")
        for pattern in _COMMERCIAL_PATTERNS:
            for match in pattern.finditer(text):
                line = text.count("\n", 0, match.start()) + 1
                findings.append(
                    Finding(
                        rule="open_source.no_commercial_gate",
                        path=_rel(path, root),
                        line=line,
                        message=f"检测到商业分流（edition gate）：/{pattern.pattern}/",
                    )
                )
    return findings


# -- 规则 3：凭证不泄漏 ------------------------------------------------------


def _is_sensitive_name(name: str) -> bool:
    """判断标识符是否表示**敏感凭证**（密码 / 令牌 / 密钥）。

    ``token`` 为歧义片段：命中它但含「良性限定词」（用量 / 计数 / 上限等）时判**非敏感**
    （如 ``last_token_usage``），以规避过度误报。
    """
    lowered = name.lower()
    if any(token in lowered for token in SENSITIVE_TOKENS):
        return True
    if "token" in lowered:
        return not any(benign in lowered for benign in _TOKEN_BENIGN_QUALIFIERS)
    return False


def _sensitive_names(node: ast.AST) -> Iterator[tuple[str, int]]:
    """递归产出表达式子树中的**敏感标识符**引用（``Name`` / ``Attribute``）。

    仅看标识符（不看字符串常量），故 ``logger.info("password 字段")`` 不误报。
    """
    for child in ast.walk(node):
        name: str | None = None
        if isinstance(child, ast.Name):
            name = child.id
        elif isinstance(child, ast.Attribute):
            name = child.attr
        if name is None:
            continue
        if _is_sensitive_name(name):
            yield name, getattr(child, "lineno", 0)


def _is_log_call(func: ast.AST) -> bool:
    """判断调用是否为日志 / 打印出口（``logger.info`` / ``logging.error`` / ``print``）。"""
    if isinstance(func, ast.Attribute):
        return func.attr in _LOG_METHODS
    if isinstance(func, ast.Name):
        return func.id in _LOG_FUNCS
    return False


def scan_credentials(root: Path) -> list[Finding]:
    """凭证纪律：**无明文密码 / 令牌写入日志或响应**（AST 级调用点分析）。

    依据：C-07 / §3-#4（凭证明文不落库 / 不落日志 / 不回显）。
    """
    findings: list[Finding] = []
    for path in _iter_py(root):
        tree = _parse(path)
        if tree is None:
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or not _is_log_call(node.func):
                continue
            # 实参 + 关键字实参一并检查（覆盖 ``logger.info(msg, extra=...)`` 形态）。
            for arg in [*node.args, *(kw.value for kw in node.keywords)]:
                for name, lineno in _sensitive_names(arg):
                    findings.append(
                        Finding(
                            rule="credential.no_plaintext_in_log",
                            path=_rel(path, root),
                            line=lineno or node.lineno,
                            message=f"疑似把敏感标识符 `{name}` 写入日志 / 打印（明文禁止）",
                        )
                    )
    return findings


# -- 规则 4：出网判定唯一源（R1 / T2-56 · L-6） -------------------------------


def _module_defined_symbols(tree: ast.Module) -> Iterator[tuple[str, int]]:
    """产出**模块级**定义（``class`` / ``def`` / 赋值）的符号名与行号。

    仅看**顶层**定义（类 / 函数 / 赋值 / 带注解赋值），**不看** import（再导出不算“另建源”）。
    """
    for node in tree.body:
        if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            yield node.name, node.lineno
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    yield target.id, node.lineno
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            yield node.target.id, node.lineno


def scan_egress_single_source(root: Path) -> list[Finding]:
    """出网判定**唯一源**：全仓**仅**允许规范原语 / 唯一入口 / Phase 1 薄委托**定义**判定符号。

    依据：设计 §2.18 / R1 裁定 R-R1R5-15 **L-6** / §R-R1R5-07（``EgressPolicy`` 复用唯一判定源；
    **无第二白名单实现**）。检测「另建白名单判定源」——在允许位置**之外**定义
    ``SecurityEgressPolicy`` / ``EgressPolicy`` / ``EgressDecision`` / ``host_matches`` /
    ``is_blocked_ip`` / ``DENY_RANGES`` 等判定原语即违规。**仅新增（收紧）**。
    """
    findings: list[Finding] = []
    for path in _iter_py(root):
        rel = _rel(path, root).replace("\\", "/")
        if rel in EGRESS_ALLOWED_DEFINITION_PATHS:
            continue
        tree = _parse(path)
        if tree is None:
            continue
        for name, lineno in _module_defined_symbols(tree):
            if name in EGRESS_DECISION_SYMBOLS:
                findings.append(
                    Finding(
                        rule="egress.single_decision_source",
                        path=rel,
                        line=lineno,
                        message=(
                            f"检测到在允许位置之外定义出网判定符号 `{name}`"
                            "（唯一判定源＝astra_domain.ports.egress / "
                            "astra_security.egress.SecurityEgressPolicy）"
                        ),
                    )
                )
    return findings


# -- 汇总 / CLI --------------------------------------------------------------


def scan(root: Path) -> list[Finding]:
    """执行全部规则，返回聚合发现项（按路径 / 行号排序）。"""
    findings = [
        *scan_layering(root),
        *scan_open_source(root),
        *scan_credentials(root),
        *scan_egress_single_source(root),
    ]
    return sorted(findings, key=lambda item: (item.path, item.line, item.rule))


def main(argv: list[str] | None = None) -> int:
    """脚本入口；返回退出码（``0`` = 通过，``1`` = 存在违规）。"""
    parser = argparse.ArgumentParser(description="Astra AI 纪律扫描（分层 / 开源 / 凭证）")
    parser.add_argument("--root", default=str(DEFAULT_ROOT), help="扫描根目录（默认仓库根）")
    parser.add_argument("--json", action="store_true", help="以 JSON 输出发现项")
    args = parser.parse_args(argv)

    root = Path(args.root).resolve()
    findings = scan(root)

    if args.json:
        print(json.dumps([asdict(item) for item in findings], ensure_ascii=False, indent=2))
    elif findings:
        for item in findings:
            print(f"{item.path}:{item.line}: [{item.rule}] {item.message}", file=sys.stderr)
        print(f"纪律扫描失败：{len(findings)} 项违规", file=sys.stderr)
    else:
        print(f"纪律扫描通过（root={root}）：分层 / 开源 / 凭证均无违规")

    return 1 if findings else 0


if __name__ == "__main__":  # pragma: no cover - CLI 直执行
    raise SystemExit(main())

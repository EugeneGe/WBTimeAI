#!/usr/bin/env python3
"""装配可达性扫描脚本（V0.4.1 · J-1；施工口径见 ``00-本机轮开工前架构裁定`` §4 J-1）。

**定位**：与 ``scripts/scan_discipline.py`` **分工互补**（纪律 vs 接线），**不重复造**——
本脚本为 **CI 可执行**的「**定义存在 ≠ 被使用**」门禁，覆盖三个扫描维度，
**任一命中 → 退出码非 0**：

1. **注册点 / 实现类装配引用**（AST 级：import / 属性访问 / 实例化）——对各方 Provider /
   组件实现类断言存在**非定义模块**的引用 / 装配点（或**任意实例化点**，以覆盖组合根内
   **同模块**装配的适配器，如 ``apps/api`` 的 ``_StorageArtifactReader``）。
   防 **R5A-01**（读取 Provider 组合根未接线 → 产品恒降级、测试靠后门注入 fake）。
2. **``build_providers`` 槽位覆盖**——``Providers`` 数据类字段 与 ``_build_phase1_slots`` /
   ``_build_phase2_slots`` 装配键的**静态一致性**（无未知槽 / 无漏装配）。同防 R5A-01 型
   「槽位定义存在但组合根未装配」。
3. **无调用者的 ``recover_*`` / ``*_sweep`` 定义**——定义存在但全仓（非 ``tests/``）无**调用**。
   防 **FR5-1**（worker 恢复 sweep ``recover_on_startup`` 定义存在、全仓无调用者）。

**白名单机制**：确属「预留未接线」的符号必须**显式登记**在脚本内常量
:data:`RESERVED_UNWIRED`（符号级）/ :data:`RESERVED_SLOT_DEFAULTS`（槽位级）并注明出处
（总纲 §12 预留契约）；**禁止用白名单掩盖真实缺陷**——确发现真实接线缺口时应保持非 0 并
如实上报，而非登记掩盖。

用法::

    python scripts/scan_wiring.py             # 扫描仓库根；违规退出码 1
    python scripts/scan_wiring.py --json      # 以 JSON 输出发现项
    python scripts/scan_wiring.py --root DIR  # 扫描指定目录（供测试构造样本）

🔴 本脚本**只读**（不得修改源码）、**零第三方依赖**（仅标准库）。
"""

from __future__ import annotations

import argparse
import ast
import json
import sys
from collections.abc import Iterator
from dataclasses import asdict, dataclass
from pathlib import Path

__all__ = [
    "Finding",
    "main",
    "scan",
    "scan_build_providers_slots",
    "scan_orphan_sweeps",
    "scan_registry_implementations",
]

#: 默认扫描根（本脚本位于 ``<repo>/scripts/`` 下）。
DEFAULT_ROOT = Path(__file__).resolve().parents[1]

#: 显式排除的路径片段（与 ``scan_discipline.py`` 同口径：docs / tests / 依赖 / 缓存 / VCS）。
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

#: 维度①：**注册点 / 实现类**清单（以仓库实际结构为准摸底）。
#: 每条 = ``(符号名, 出处 / 说明)``。断言：该符号**存在定义** 且 存在
#: 「非定义模块引用 / 装配点」**或**「任意实例化点」；否则命中违规。
#: 🔴 新增 Provider / 组件实现类时必须登记于此（否则门禁不覆盖）。
REGISTRY_IMPLEMENTATIONS: tuple[tuple[str, str], ...] = (
    # -- Sandbox（R5A-01 同型：实现类必须被工厂/组合根引用） -------------------
    (
        "LocalProcessSandboxProvider",
        "packages/sandbox/src/astra_sandbox/local_process_provider.py（社区降级）",
    ),
    ("DockerSandboxProvider", "packages/sandbox/src/astra_sandbox/docker_provider.py"),
    # -- Storage / EventBus / TaskQueue / Scheduler / Executor 各实现 --------
    ("LocalFileStorage", "packages/storage/src/astra_storage/local.py"),
    ("UnsupportedStorage", "packages/storage/src/astra_storage/placeholder.py（占位）"),
    ("LocalEventBus", "packages/event/src/astra_event/bus.py"),
    ("UnsupportedEventBus", "packages/event/src/astra_event/placeholder.py（占位）"),
    ("InProcessTaskQueue", "packages/task/src/astra_task/queue/__init__.py"),
    ("RedisTaskQueue", "packages/task/src/astra_task/queue/redis.py"),
    ("UnsupportedTaskQueue", "packages/task/src/astra_task/placeholder.py（占位）"),
    ("LocalScheduler", "packages/task/src/astra_task/scheduler/__init__.py"),
    ("UnsupportedScheduler", "packages/task/src/astra_task/placeholder.py（占位）"),
    ("InProcessBackgroundExecutor", "packages/task/src/astra_task/executor/inprocess.py"),
    ("WorkerProcessExecutor", "packages/task/src/astra_task/executor/worker_process.py"),
    ("UnsupportedBackgroundExecutor", "packages/task/src/astra_task/placeholder.py（占位）"),
    # -- Model Provider 实现 + Resolver --------------------------------------
    ("StubModelProvider", "packages/model/src/astra_model/stub.py"),
    ("ProviderResolver", "packages/model/src/astra_model/services/provider_resolver.py（RP-15）"),
    ("OpenAIProvider", "packages/model/src/astra_model/providers/openai.py"),
    ("OpenAICompatibleProvider", "packages/model/src/astra_model/providers/openai_compatible.py"),
    ("AnthropicProvider", "packages/model/src/astra_model/providers/anthropic.py"),
    ("GeminiProvider", "packages/model/src/astra_model/providers/gemini.py"),
    ("DeepSeekProvider", "packages/model/src/astra_model/providers/deepseek.py"),
    ("QwenProvider", "packages/model/src/astra_model/providers/qwen.py"),
    ("OllamaProvider", "packages/model/src/astra_model/providers/ollama.py"),
    # -- Security ------------------------------------------------------------
    ("EnvSecretProvider", "packages/security/src/astra_security/secret_provider.py"),
    # -- Worker 恢复 / 执行记录 ----------------------------------------------
    ("LeaseManager", "apps/worker/src/astra_worker/recovery.py（FR5-1）"),
    ("ExecutionRecorder", "packages/task/src/astra_task/execution_record.py"),
    # -- 组合根内**同模块**装配的读取侧适配器（R5A-01 a/b） -------------------
    (
        "_StorageArtifactReader",
        "apps/api/src/astra_api/dependencies/services.py（R5A-01a，组合根内实例化）",
    ),
    (
        "_SandboxGitRefsProvider",
        "apps/api/src/astra_api/dependencies/services.py（R5A-01b，组合根内实例化）",
    ),
    (
        "_ProjectGitCredentialProvider",
        "apps/api/src/astra_api/dependencies/services.py（T2-60 组合根内实例化）",
    ),
    # -- 总纲 §12.2 预留空实现（RP-01~RP-05；见 RESERVED_UNWIRED 白名单） ------
    ("NullSkillResolver", "packages/runtime/src/astra_runtime/reserved/skill_resolver.py（RP-01）"),
    (
        "NullKnowledgeRetriever",
        "packages/runtime/src/astra_runtime/reserved/knowledge_retriever.py（RP-02）",
    ),
    ("NullMemoryManager", "packages/runtime/src/astra_runtime/reserved/memory_manager.py（RP-03）"),
    ("NullMCPExecutor", "packages/runtime/src/astra_runtime/reserved/mcp_executor.py（RP-04）"),
    ("NullPlanner", "packages/runtime/src/astra_runtime/reserved/planner.py（RP-05）"),
)

#: **白名单**：确属「预留未接线」的符号 → 出处。命中白名单的符号**不**计为违规。
#: 🔴 依据 = 总纲 §12 预留契约；每条必须写明出处。**禁止**用白名单掩盖真实缺陷
#: （若某符号属真实接线缺口，应保持非 0 并上报，而非登记于此）。
RESERVED_UNWIRED: dict[str, str] = {
    "NullSkillResolver": "总纲 §12.2 RP-01 预留空实现（Phase 2 填充，签名不变）",
    "NullKnowledgeRetriever": "总纲 §12.2 RP-02 预留空实现（Phase 2 填充，签名不变）",
    "NullMemoryManager": "总纲 §12.2 RP-03 预留空实现（Phase 2 填充，签名不变）",
    "NullMCPExecutor": "总纲 §12.2 RP-04 预留空实现（组合根默认注入，非组合根装配面）",
    "NullPlanner": "总纲 §12.2 RP-05 预留空实现（Phase 2 起步 / Phase 3+ 增强）",
}

#: 维度②：**预留槽位**（``Providers`` 字段，恒由默认值 ``None`` 承载、不在 ``build_providers``
#: 显式赋值 / 不经 phase 槽）。登记出处；否则「漏装配」命中违规。
RESERVED_SLOT_DEFAULTS: dict[str, str] = {
    "scheduler_runner": (
        "packages/config ... Providers.scheduler_runner（W7 / T2-39）：调度轮询执行体由"
        "组合根（AppServices.scheduler）装配，Providers 槽位**保留且恒为 None**"
    ),
}

#: 维度③：无调用者检测的**函数名模式**（去前导下划线后判定）。
#: ``recover_*``（启动恢复编排）/ ``*_sweep`` / ``sweep_*``（过期扫描）。
_SWEEP_PREFIXES: tuple[str, ...] = ("recover_", "sweep_")
_SWEEP_SUBSTRINGS: tuple[str, ...] = ("_sweep",)


@dataclass(frozen=True)
class Finding:
    """一条违规发现项。"""

    rule: str
    path: str
    line: int
    message: str


# -- 遍历 / 解析辅助 ---------------------------------------------------------


def _iter_py(root: Path) -> Iterator[Path]:
    """遍历 ``root`` 下的 ``.py``（排除白名单片段与**隐藏目录**，口径同 ``scan_discipline``）。"""
    resolved_root = root.resolve()
    for path in sorted(resolved_root.rglob("*.py")):
        try:
            rel_parts = path.relative_to(resolved_root).parts
        except ValueError:  # pragma: no cover - rglob 结果必在 root 之下
            rel_parts = path.parts
        if EXCLUDED_PARTS & set(rel_parts):
            continue
        if any(part.startswith(".") for part in rel_parts[:-1]):
            continue
        yield path


def _rel(path: Path, root: Path) -> str:
    """相对 ``root`` 的路径字符串（越界时回退绝对路径）。"""
    try:
        return str(path.relative_to(root))
    except ValueError:
        return str(path)


def _parse(path: Path) -> ast.Module | None:
    """解析为 AST；语法错误 / 读取失败时返回 ``None``（不因单文件失败而整体中断）。"""
    try:
        return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except (SyntaxError, UnicodeDecodeError, OSError):  # pragma: no cover - 正常仓库无此情形
        return None


@dataclass(frozen=True)
class _Ref:
    """一条符号引用点（``kind`` ∈ ``import`` / ``name`` / ``attr`` / ``call``）。"""

    path: Path
    line: int
    kind: str


class _SymbolIndex:
    """全仓符号定义 / 引用索引（AST 级，规避 docstring / 字符串子串误报）。"""

    def __init__(self) -> None:
        self.defs: dict[str, list[tuple[Path, int, str]]] = {}
        self.refs: dict[str, list[_Ref]] = {}

    def add_def(self, name: str, path: Path, line: int, kind: str) -> None:
        self.defs.setdefault(name, []).append((path, line, kind))

    def add_ref(self, name: str, path: Path, line: int, kind: str) -> None:
        self.refs.setdefault(name, []).append(_Ref(path=path, line=line, kind=kind))

    def def_paths(self, name: str) -> set[Path]:
        return {path for path, _line, _kind in self.defs.get(name, [])}


def _build_index(root: Path) -> _SymbolIndex:
    """构建全仓符号索引（``class`` / ``def`` 定义 + import / Name / Attribute / Call 引用）。"""
    index = _SymbolIndex()
    for path in _iter_py(root):
        tree = _parse(path)
        if tree is None:
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                index.add_def(node.name, path, node.lineno, "class")
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                index.add_def(node.name, path, node.lineno, "function")
            elif isinstance(node, ast.ImportFrom):
                for alias in node.names:
                    index.add_ref(alias.name, path, node.lineno, "import")
            elif isinstance(node, ast.Name):
                index.add_ref(node.id, path, node.lineno, "name")
            elif isinstance(node, ast.Attribute):
                index.add_ref(node.attr, path, getattr(node, "lineno", 0), "attr")
            elif isinstance(node, ast.Call):
                target = node.func
                if isinstance(target, ast.Name):
                    index.add_ref(target.id, path, getattr(target, "lineno", node.lineno), "call")
                elif isinstance(target, ast.Attribute):
                    index.add_ref(target.attr, path, getattr(target, "lineno", node.lineno), "call")
    return index


# -- 维度①：注册点 / 实现类装配引用 -----------------------------------------


def _classify(symbol: str, index: _SymbolIndex) -> str:
    """判定符号的「接线状态」。

    Returns:
        - ``"missing"``：全仓无定义（注册项陈旧 / 符号被删）；
        - ``"wired"``：存在**非定义模块**引用（import / 属性 / 名字 / 调用）；
        - ``"wired_same_module"``：仅在定义模块内被**实例化**（组合根内装配适配器）；
        - ``"orphan"``：有定义、但无任何有效装配引用（「定义存在 ≠ 被使用」）。
    """
    def_paths = index.def_paths(symbol)
    if not def_paths:
        return "missing"
    refs = index.refs.get(symbol, [])
    if any(ref.path not in def_paths for ref in refs):
        return "wired"
    if any(ref.kind == "call" for ref in refs):
        return "wired_same_module"
    return "orphan"


def scan_registry_implementations(
    root: Path,
    *,
    index: _SymbolIndex | None = None,
    whitelist: dict[str, str] | None = None,
) -> list[Finding]:
    """维度①：断言各注册点 / 实现类存在有效装配引用（防 R5A-01）。

    Args:
        root: 扫描根。
        index: 复用索引（可空；空则自行构建）。
        whitelist: 白名单（默认 :data:`RESERVED_UNWIRED`）。

    Returns:
        违规发现项列表。
    """
    idx = index if index is not None else _build_index(root)
    allowed = RESERVED_UNWIRED if whitelist is None else whitelist
    findings: list[Finding] = []
    for symbol, source in REGISTRY_IMPLEMENTATIONS:
        if symbol in allowed:
            continue
        status = _classify(symbol, idx)
        if status == "missing":
            findings.append(
                Finding(
                    rule="wiring.registry_symbol_missing",
                    path=_rel(_providers_source_path(root, symbol), root),
                    line=0,
                    message=f"注册项 `{symbol}` 全仓无定义（登记陈旧 / 符号被删；出处：{source}）",
                )
            )
        elif status == "orphan":
            findings.append(
                Finding(
                    rule="wiring.registry_symbol_unwired",
                    path=_rel(_def_path(idx, symbol, root), root),
                    line=_def_line(idx, symbol),
                    message=(
                        f"实现类 `{symbol}` 有定义但无装配引用（定义存在 ≠ 被使用；"
                        f"出处：{source}）"
                    ),
                )
            )
    return findings


def _def_path(index: _SymbolIndex, symbol: str, root: Path) -> Path:
    """符号首个定义所在文件（无定义时回退 ``root``）。"""
    defs = index.defs.get(symbol)
    return defs[0][0] if defs else root


def _def_line(index: _SymbolIndex, symbol: str) -> int:
    """符号首个定义行号（无定义时回退 ``0``）。"""
    defs = index.defs.get(symbol)
    return defs[0][1] if defs else 0


def _providers_source_path(root: Path, symbol: str) -> Path:
    """定位 ``symbol`` 的期望定义文件（用于 ``missing`` 报告的可读路径；找不到回退 root）。"""
    for _sym, source in REGISTRY_IMPLEMENTATIONS:
        if _sym == symbol:
            candidate = root / source.split("（", 1)[0].strip()
            return candidate
    return root


# -- 维度②：build_providers 槽位覆盖 ----------------------------------------


def _find_providers_module(root: Path) -> Path | None:
    """定位 ``astra_config/providers.py``（组合根装配点）。"""
    for path in _iter_py(root):
        if path.as_posix().endswith("astra_config/providers.py"):
            return path
    return None


def _find_class(tree: ast.Module, name: str) -> ast.ClassDef | None:
    """按名查找顶层类定义。"""
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == name:
            return node
    return None


def _find_func(tree: ast.Module, name: str) -> ast.FunctionDef | None:
    """按名查找顶层函数定义（含 ``AsyncFunctionDef`` 归一为 ``FunctionDef``）。"""
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
            return node  # type: ignore[return-value]
    return None


def _class_field_names(cls: ast.ClassDef) -> set[str]:
    """收集数据类**注解字段名**（``AnnAssign`` + 简单 ``Name`` 目标）。"""
    fields: set[str] = set()
    for node in cls.body:
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            fields.add(node.target.id)
    return fields


def _dict_str_keys(node: ast.Dict) -> set[str]:
    """收集字典字面量的**字符串键**（``**`` 展开忽略）。"""
    keys: set[str] = set()
    for key in node.keys:
        if isinstance(key, ast.Constant) and isinstance(key.value, str):
            keys.add(key.value)
    return keys


def _return_dict_keys(func: ast.FunctionDef) -> set[str]:
    """收集函数内 ``return {..}`` 字典字面量的字符串键（取首个 return）。"""
    for node in ast.walk(func):
        if isinstance(node, ast.Return) and isinstance(node.value, ast.Dict):
            return _dict_str_keys(node.value)
    return set()


def _assigned_vars_for(tree: ast.Module, factory: str) -> dict[str, set[str]]:
    """查找 ``var = factory(...)`` 形态赋值 → ``{var: 该工厂返回字典键集合}``。"""
    mapping: dict[str, set[str]] = {}
    func = _find_func(tree, factory)
    if func is None:
        return mapping
    keys = _return_dict_keys(func)
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Assign)
            and isinstance(node.value, ast.Call)
            and isinstance(node.value.func, ast.Name)
            and node.value.func.id == factory
        ):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    mapping[target.id] = keys
    return mapping


def _find_providers_call(tree: ast.Module) -> ast.Call | None:
    """查找 ``build_providers`` 内构造 ``Providers(...)`` 的调用点。"""
    func = _find_func(tree, "build_providers")
    if func is None:
        return None
    for node in ast.walk(func):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "Providers"
        ):
            return node
    return None


def scan_build_providers_slots(root: Path) -> list[Finding]:
    """维度②：``Providers`` 字段 与 phase 槽装配键的静态一致性（防 R5A-01 型漏装配）。

    断言：
    - phase 槽键 ⊆ ``Providers`` 字段（无未知槽）；
    - ``Providers(...)`` 显式 kwargs ⊆ ``Providers`` 字段（无未知 kwarg）；
    - ``Providers`` 字段被「显式 kwargs ∪ ** 展开槽键」覆盖（漏装配 → 违规，
      预留槽见 :data:`RESERVED_SLOT_DEFAULTS`）。
    """
    path = _find_providers_module(root)
    if path is None:
        return []
    tree = _parse(path)
    if tree is None:  # pragma: no cover - 正常仓库 providers.py 必可解析
        return []

    findings: list[Finding] = []
    rel = _rel(path, root)

    cls = _find_class(tree, "Providers")
    fields = _class_field_names(cls) if cls is not None else None

    # 各 phase 槽工厂的键 + 其在 build_providers 内的**展开变量**映射。
    slot_keys: set[str] = set()
    var_to_keys: dict[str, set[str]] = {}
    for factory in ("_build_phase1_slots", "_build_phase2_slots"):
        func = _find_func(tree, factory)
        if func is None:
            continue
        keys = _return_dict_keys(func)
        slot_keys |= keys
        var_to_keys.update(_assigned_vars_for(tree, factory))

    call = _find_providers_call(tree)
    explicit: list[tuple[str, int]] = []
    unpacked: list[tuple[str, int]] = []
    if call is not None:
        for kw in call.keywords:
            if kw.arg is None:  # ``**name``
                if isinstance(kw.value, ast.Name):
                    unpacked.append((kw.value.id, getattr(kw.value, "lineno", call.lineno)))
            else:
                explicit.append((kw.arg, getattr(kw, "lineno", call.lineno)))

    if fields is not None:
        # (1) 未知槽键。
        for key in sorted(slot_keys - fields):
            findings.append(
                Finding(
                    rule="wiring.slot_unknown",
                    path=rel,
                    line=0,
                    message=f"phase 槽键 `{key}` 不是 `Providers` 字段（装配键与容器字段不一致）",
                )
            )
        # (2) 未知显式 kwarg。
        for name, line in explicit:
            if name not in fields:
                findings.append(
                    Finding(
                        rule="wiring.slot_unknown_kwarg",
                        path=rel,
                        line=line,
                        message=f"`Providers(...)` 传入未知关键字 `{name}`（非容器字段）",
                    )
                )
        # (3) 漏装配：字段未被覆盖。
        covered = {name for name, _line in explicit}
        for var, line in unpacked:
            if var in var_to_keys:
                covered |= var_to_keys[var]
            else:
                findings.append(
                    Finding(
                        rule="wiring.slot_unresolved_unpack",
                        path=rel,
                        line=line,
                        message=f"`Providers(...)` 的 `**{var}` 无法解析到已知 phase 槽工厂",
                    )
                )
        missing = fields - covered - set(RESERVED_SLOT_DEFAULTS)
        for name in sorted(missing):
            findings.append(
                Finding(
                    rule="wiring.slot_uncovered",
                    path=rel,
                    line=0,
                    message=(
                        f"`Providers` 字段 `{name}` 未被装配（既非显式 kwarg、"
                        "也非 phase 槽、亦非登记预留默认值）"
                    ),
                )
            )
    return findings


# -- 维度③：无调用者的 recover_* / *_sweep 定义 ------------------------------


def _is_sweep_like(name: str) -> bool:
    """函数名是否属「恢复 / 扫描」族（去前导下划线后判定）。"""
    normalized = name.lstrip("_")
    if normalized.startswith(_SWEEP_PREFIXES):
        return True
    return any(needle in normalized for needle in _SWEEP_SUBSTRINGS)


def scan_orphan_sweeps(
    root: Path,
    *,
    index: _SymbolIndex | None = None,
    whitelist: dict[str, str] | None = None,
) -> list[Finding]:
    """维度③：``recover_*`` / ``*_sweep`` 函数定义必须有**调用者**（防 FR5-1）。

    「有调用者」= 全仓（非 ``tests/``）存在 ``call`` 型引用（``f(...)`` / ``o.f(...)``）；
    仅 import / 名字提及 **不** 计为调用。命中白名单的符号不计违规。
    """
    idx = index if index is not None else _build_index(root)
    allowed = RESERVED_UNWIRED if whitelist is None else whitelist
    findings: list[Finding] = []
    for symbol, defs in sorted(idx.defs.items()):
        if not _is_sweep_like(symbol):
            continue
        if not any(kind == "function" for _p, _l, kind in defs):
            continue
        if symbol in allowed:
            continue
        has_caller = any(ref.kind == "call" for ref in idx.refs.get(symbol, []))
        if has_caller:
            continue
        path, line, _kind = defs[0]
        findings.append(
            Finding(
                rule="wiring.orphan_sweep_definition",
                path=_rel(path, root),
                line=line,
                message=(
                    f"`{symbol}` 定义存在但全仓无调用者（定义存在 ≠ 被使用；"
                    "排查 worker 启动接线 / 组合根调用点）"
                ),
            )
        )
    return findings


# -- 汇总 / CLI --------------------------------------------------------------


def scan(root: Path) -> list[Finding]:
    """执行全部维度，返回聚合发现项（按路径 / 行号 / 规则排序）。"""
    index = _build_index(root)
    findings = [
        *scan_registry_implementations(root, index=index),
        *scan_build_providers_slots(root),
        *scan_orphan_sweeps(root, index=index),
    ]
    return sorted(findings, key=lambda item: (item.path, item.line, item.rule))


def main(argv: list[str] | None = None) -> int:
    """脚本入口；返回退出码（``0`` = 通过，``1`` = 存在违规）。"""
    parser = argparse.ArgumentParser(
        description="Astra AI 装配可达性扫描（注册点 / 槽位覆盖 / 孤儿 sweep）"
    )
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
        print(f"装配可达性扫描失败：{len(findings)} 项违规", file=sys.stderr)
    else:
        print(f"装配可达性扫描通过（root={root}）：注册点 / 槽位覆盖 / sweep 调用者均无违规")

    return 1 if findings else 0


if __name__ == "__main__":  # pragma: no cover - CLI 直执行
    raise SystemExit(main())

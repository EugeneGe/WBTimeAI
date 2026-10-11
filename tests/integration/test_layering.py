"""分层纪律 import 断言（设计 §2.2 / §2.15）。

- ``common`` / ``core``：不得依赖 Web（fastapi/starlette）与 ORM（sqlalchemy/alembic）；
- ``database``：不得依赖 API 层（``astra_api``）与 Web 框架；
- ``domain``：**零框架依赖**（禁 fastapi/starlette/sqlalchemy/alembic/pydantic/sqlmodel）——§3-#6；
- ``event`` / ``storage`` / ``model``：不得依赖 Web 与 ORM；
- ``task``：不得依赖 Web（W2 亦不依赖 database）；
- ``identity`` / ``security`` / ``application``：不得依赖 Web 框架。
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
PACKAGES = REPO_ROOT / "packages"

_IMPORT_RE = re.compile(
    r"^\s*(?:from\s+([\w\.]+)\s+import|import\s+([\w\.]+))",
    re.MULTILINE,
)


def _iter_python_files(base: Path) -> Iterator[Path]:
    for path in base.rglob("*.py"):
        if "__pycache__" in path.parts or ".venv" in path.parts:
            continue
        yield path


def _top_level_modules(text: str) -> set[str]:
    modules: set[str] = set()
    for match in _IMPORT_RE.finditer(text):
        module = match.group(1) or match.group(2) or ""
        if module:
            modules.add(module.split(".")[0])
    return modules


def _assert_no_forbidden(package: str, forbidden: set[str]) -> None:
    for path in _iter_python_files(PACKAGES / package):
        bad = forbidden & _top_level_modules(path.read_text(encoding="utf-8"))
        assert not bad, f"{path.relative_to(REPO_ROOT)} 违规导入：{sorted(bad)}"


def test_common_and_core_have_no_framework_dependencies() -> None:
    forbidden = {"fastapi", "starlette", "sqlalchemy", "alembic", "astra_api", "pydantic"}
    for package in ("common", "core"):
        _assert_no_forbidden(package, forbidden)


def test_database_does_not_depend_on_api_layer() -> None:
    _assert_no_forbidden("database", {"fastapi", "starlette", "astra_api"})


def test_domain_has_no_framework_dependencies() -> None:
    """``astra_domain`` 零框架依赖（可纯单测）——§3-#6。"""
    _assert_no_forbidden(
        "domain",
        {"fastapi", "starlette", "sqlalchemy", "alembic", "pydantic", "sqlmodel"},
    )


def test_phase1_domain_submodules_exist_and_are_framework_free() -> None:
    """Phase 1 新 domain 子模块（agent/model/tool/conversation/sandbox/audit）同样零框架。

    §3-#13 / C-03：断言 Phase 1 新增实体 / 值对象 / 仓储接口文件存在且不引入
    fastapi / starlette / sqlalchemy / alembic / pydantic / sqlmodel。
    """
    domain_src = PACKAGES / "domain" / "src" / "astra_domain"
    phase1_relative = [
        "entities/agent.py",
        "entities/model.py",
        "entities/tool.py",
        "entities/conversation.py",
        "entities/sandbox.py",
        "entities/audit.py",
        "value_objects/agent.py",
        "value_objects/conversation.py",
        "value_objects/tool.py",
        "value_objects/sandbox.py",
        "repositories/agent_repository.py",
        "repositories/model_repository.py",
        "repositories/tool_repository.py",
        "repositories/conversation_repository.py",
        "repositories/sandbox_repository.py",
        "repositories/audit_repository.py",
    ]
    forbidden = {"fastapi", "starlette", "sqlalchemy", "alembic", "pydantic", "sqlmodel"}
    for relative in phase1_relative:
        path = domain_src / relative
        assert path.is_file(), f"Phase 1 domain 子模块缺失：{relative}"
        bad = forbidden & _top_level_modules(path.read_text(encoding="utf-8"))
        assert not bad, f"{path.relative_to(REPO_ROOT)} 违规导入：{sorted(bad)}"


def test_abstraction_packages_have_no_web_or_orm_dependencies() -> None:
    """``event`` / ``storage`` / ``model`` / ``tool`` / ``sandbox`` / ``runtime`` / ``plugin``
    / ``audit`` 零 Web / ORM。

    W4 架构裁定 Q1（方案 B）**收紧**：``tool`` / ``sandbox`` 亦属**抽象包**（与
    ``event`` / ``storage`` / ``model`` 同列），其 SQL 仓储下移 ``astra_database.repositories``。
    W5 架构裁定 Q1（方案 B）**再收紧**：``runtime`` 亦属**抽象包（零 ORM）**——持久化经
    DI 注入领域 Protocol，SQL 并发下沉 ``conversation/repositories``。
    W1（Phase 2）架构裁定 §2.3 **再追加**：``plugin`` / ``audit`` 属**抽象包（零 ORM）**
    ——ExtensionPoint 契约经注入仓储使用；本断言**仅新增 / 收紧**，**不放宽**任何既有断言。
    """
    forbidden = {"fastapi", "starlette", "sqlalchemy", "alembic"}
    for package in (
        "event",
        "storage",
        "model",
        "tool",
        "sandbox",
        "runtime",
        "plugin",
        "audit",
    ):
        _assert_no_forbidden(package, forbidden)


def test_workspace_package_has_no_web_dependency() -> None:
    """能力包 ``workspace`` / ``conversation`` / ``agent`` 零 fastapi / starlette 依赖。

    W5 架构裁定 Q1（方案 B）**收紧**：``conversation`` / ``agent`` 为**能力包**
    （SQL 仓储留本包 ``repositories/``），与 ``workspace`` 同列——**仅禁 Web**，不禁 ORM。
    """
    _assert_no_forbidden("workspace", {"fastapi", "starlette"})
    for package in ("conversation", "agent"):
        _assert_no_forbidden(package, {"fastapi", "starlette"})


def test_runtime_package_is_pure_abstraction() -> None:
    """``packages/runtime`` 为**抽象包（零 ORM）**——W5 架构裁定 Q1（方案 B）。

    断言 runtime **不得**顶层 import 任何基础设施 / 能力包 / Web 框架：
    ``sqlalchemy`` / ``alembic`` / ``astra_database`` / ``astra_conversation`` /
    ``astra_agent`` / ``astra_api`` / ``fastapi`` / ``starlette``。
    （**允许** ``astra_{common,core,domain,event,model,tool,sandbox}``。）

    本断言为 W5 **新增约束（收紧）**，零放宽。
    """
    forbidden = {
        "sqlalchemy",
        "alembic",
        "astra_database",
        "astra_conversation",
        "astra_agent",
        "astra_api",
        "fastapi",
        "starlette",
    }
    _assert_no_forbidden("runtime", forbidden)


def test_api_routers_have_no_orm_dependency() -> None:
    """``apps/api/routers/**`` **不得** import ``sqlalchemy`` / ``astra_database``（§2S.0.1）。

    Router 只依赖 ``dependencies/services.py``（``AppServices``）与 ``dependencies/auth.py``。

    W6 / T1-29（裁定 Q9 / A33）**收紧**（零放宽）：Router 亦**不得** import
    ``astra_runtime`` / ``astra_conversation`` / ``astra_agent`` / ``astra_model``——
    Router 只编排 Application（``astra_application``），Runtime 由 Application 调用（N-8）；
    事件订阅落 ``astra_api/sse/``（非 ``routers/``）。

    W8 / T1-37 **再收紧**（零放宽）：Router 亦**不得** import ``astra_sandbox`` /
    ``astra_task`` / ``astra_storage`` / ``astra_event`` / ``astra_config``——
    Provider / 能力包一律经 ``AppServices`` 取用（N-8）。
    """
    routers_dir = REPO_ROOT / "apps" / "api" / "src" / "astra_api" / "routers"
    forbidden = {
        "sqlalchemy",
        "astra_database",
        "astra_runtime",
        "astra_conversation",
        "astra_agent",
        "astra_model",
        "astra_sandbox",
        "astra_task",
        "astra_storage",
        "astra_event",
        "astra_config",
    }
    for path in _iter_python_files(routers_dir):
        bad = forbidden & _top_level_modules(path.read_text(encoding="utf-8"))
        assert not bad, f"{path.relative_to(REPO_ROOT)} 违规导入：{sorted(bad)}"


def test_sse_encoder_has_no_domain_event_import() -> None:
    """``astra_api/sse/encoder.py`` **不得** import 领域事件 / ORM（W6 裁定 Q9 / A33）。

    编码器对事件**仅按 ``type`` 字符串 + ``payload`` 值**处理（纯字符串映射），
    不绑定 ``astra_event`` 事件类；亦不直连 ORM。新增断言（收紧），零放宽。
    """
    encoder = REPO_ROOT / "apps" / "api" / "src" / "astra_api" / "sse" / "encoder.py"
    assert encoder.is_file(), "SSE 编码器缺失：apps/api/src/astra_api/sse/encoder.py"
    forbidden = {"astra_event", "sqlalchemy", "astra_database"}
    bad = forbidden & _top_level_modules(encoder.read_text(encoding="utf-8"))
    assert not bad, f"{encoder.relative_to(REPO_ROOT)} 违规导入：{sorted(bad)}"


def test_task_package_has_no_web_or_database_dependency() -> None:
    """``astra_task``（W2）不依赖 Web，且不依赖 ORM。"""
    _assert_no_forbidden("task", {"fastapi", "starlette", "sqlalchemy", "astra_database"})


def test_identity_security_application_have_no_web_dependency() -> None:
    """``identity`` / ``security`` / ``application`` 不依赖 Web 框架。"""
    for package in ("identity", "security", "application"):
        _assert_no_forbidden(package, {"fastapi", "starlette"})


# -- R1（Phase 2）· T2-56：出网判定**不**直连 ORM（仅新增 / 收紧，零放宽） ------


def test_security_egress_has_no_orm_dependency() -> None:
    """``astra_security/egress/**`` **不得** import ``sqlalchemy`` / ``alembic`` / ``astra_database``。

    R1 架构裁定 §R-R1R5-15 **L-5**（新增断言，收紧）：出网判定（``SecurityEgressPolicy`` /
    受控 Egress Proxy）**不直连 ORM**——审计经**注入** Protocol（``audit_repository``），
    判定**只**复用 ``astra_domain.ports.egress`` 原语。本断言**仅新增**，既有断言原样不动。
    """
    egress_dir = PACKAGES / "security" / "src" / "astra_security" / "egress"
    assert egress_dir.is_dir(), "出网策略目录缺失：astra_security/egress"
    forbidden = {"sqlalchemy", "alembic", "astra_database"}
    for path in _iter_python_files(egress_dir):
        bad = forbidden & _top_level_modules(path.read_text(encoding="utf-8"))
        assert not bad, f"{path.relative_to(REPO_ROOT)}（egress）违规导入：{sorted(bad)}"


def test_application_import_boundary() -> None:
    """``astra_application``（W3 扩展）只允许依赖
    ``{common, core, domain, identity, workspace, security}``。

    固化依赖边界（W3 显式放开 ``astra-workspace`` / ``astra-security``）：
    任何对 api/config/database/event/task/storage/model 或 Web/ORM/校验框架的顶层导入
    都视为越界。
    """
    forbidden = {
        "astra_api",
        "astra_config",
        "astra_database",
        "astra_event",
        "astra_task",
        "astra_storage",
        "astra_model",
        "fastapi",
        "starlette",
        "sqlalchemy",
        "alembic",
        "pydantic",
        "sqlmodel",
    }
    for path in _iter_python_files(PACKAGES / "application"):
        bad = forbidden & _top_level_modules(path.read_text(encoding="utf-8"))
        assert not bad, f"{path.relative_to(REPO_ROOT)} 越界导入：{sorted(bad)}"


# -- W8 / T1-37：Phase 1 新包与 SSE 包的分层收紧（仅新增 / 收紧，零放宽） -----


def test_phase1_abstract_packages_are_present_and_orm_free() -> None:
    """Phase 1 / Phase 2 抽象包 ``runtime`` / ``tool`` / ``sandbox`` / ``plugin`` / ``audit``
    必须存在且零 ORM / Web。

    正向断言（防「扫了但没包」的假绿）：先确认包目录存在，再断言**整包**不含
    ``fastapi`` / ``starlette`` / ``sqlalchemy`` / ``alembic`` / ``astra_database``。
    W1（Phase 2）架构裁定 §2.3 **追加** ``plugin`` / ``audit``（**零放宽**）。
    """
    for package in ("runtime", "tool", "sandbox", "plugin", "audit"):
        package_dir = PACKAGES / package
        assert package_dir.is_dir(), f"抽象包缺失：packages/{package}"
        forbidden = {"fastapi", "starlette", "sqlalchemy", "alembic", "astra_database"}
        for path in _iter_python_files(package_dir):
            bad = forbidden & _top_level_modules(path.read_text(encoding="utf-8"))
            assert not bad, f"{path.relative_to(REPO_ROOT)} 违规导入：{sorted(bad)}"


def test_phase1_domain_facing_modules_have_no_orm_or_web() -> None:
    """``agent`` / ``conversation`` 的 **domain 面向部分**（服务 / 映射）零 Web / ORM。

    W5 架构裁定 Q1（方案 B）：``conversation`` / ``agent`` 为**能力包**，SQL 仅允许落在本包
    ``repositories/`` 与组合工厂 ``factory.py``；其**面向领域**的部分（``services/`` /
    ``mappers.py`` / 包门面 ``__init__.py``）**不得**依赖 ``fastapi`` / ``starlette`` /
    ``sqlalchemy`` / ``alembic``（§2.2 / ``I-P1-13``）。
    """
    forbidden = {"fastapi", "starlette", "sqlalchemy", "alembic"}
    for package in ("agent", "conversation"):
        package_dir = PACKAGES / package
        assert package_dir.is_dir(), f"Phase 1 能力包缺失：packages/{package}"
        for path in _iter_python_files(package_dir):
            parts = path.parts
            if "repositories" in parts or path.name == "factory.py":
                continue  # SQL 仓储 / 组合工厂为**显式允许**的 ORM 落点
            bad = forbidden & _top_level_modules(path.read_text(encoding="utf-8"))
            assert not bad, f"{path.relative_to(REPO_ROOT)}（domain 面向）违规导入：{sorted(bad)}"


def test_sse_package_has_no_orm_dependency() -> None:
    """``apps/api/sse/**`` **不得** import ``sqlalchemy`` / ``astra_database``（W8 收紧）。

    事件订阅 / 编码落 ``astra_api/sse/``，仅消费领域 Protocol 回调（``StreamDeps``），
    不直连 ORM；本断言与 ``test_sse_encoder_has_no_domain_event_import`` 互补（覆盖整包）。
    """
    sse_dir = REPO_ROOT / "apps" / "api" / "src" / "astra_api" / "sse"
    assert sse_dir.is_dir(), "SSE 包缺失：apps/api/src/astra_api/sse"
    forbidden = {"sqlalchemy", "astra_database"}
    for path in _iter_python_files(sse_dir):
        bad = forbidden & _top_level_modules(path.read_text(encoding="utf-8"))
        assert not bad, f"{path.relative_to(REPO_ROOT)} 违规导入：{sorted(bad)}"


# -- W1（Phase 2）· T2-01：7 个新包分层收紧（仅新增 / 收紧，零放宽） ----------

#: Phase 2 新包（能力包 + 抽象包）。
PHASE2_CAPABILITY_PACKAGES = ("skill", "mcp", "workflow", "knowledge", "memory")
PHASE2_ABSTRACT_PACKAGES = ("plugin", "audit")
PHASE2_PACKAGES = (*PHASE2_CAPABILITY_PACKAGES, *PHASE2_ABSTRACT_PACKAGES)


def test_phase2_capability_packages_have_no_web_dependency() -> None:
    """Phase 2 能力包 ``skill`` / ``mcp`` / ``workflow`` / ``knowledge`` / ``memory`` 仅禁 Web。

    W1（Phase 2）架构裁定 §2.2 / §2.3：能力包承载业务聚合持久化（SQL 留本包
    ``repositories/``），故**仅禁** ``fastapi`` / ``starlette``（与 ``workspace`` /
    ``conversation`` / ``agent`` 同列），**不禁** ORM。新增断言（收紧），零放宽。
    """
    for package in PHASE2_CAPABILITY_PACKAGES:
        _assert_no_forbidden(package, {"fastapi", "starlette"})


def test_phase2_packages_are_present() -> None:
    """Phase 2 的 7 个新包目录必须存在（正向断言，防「扫了但没包」的假绿）。

    W1（Phase 2）架构裁定 §2.3：新增断言（收紧），零放宽。
    """
    for package in PHASE2_PACKAGES:
        package_dir = PACKAGES / package
        assert package_dir.is_dir(), f"Phase 2 新包缺失：packages/{package}"


def test_phase2_domain_submodules_have_no_orm_or_web() -> None:
    """Phase 2 新包的 ``domain/`` 子模块须**零 Web / ORM**（能力包 ``repositories/`` 除外）。

    W1（Phase 2）架构裁定 §2.2 / §2.3（承接 T2-01 验收③）：扫描
    ``packages/{skill,mcp,workflow,knowledge,memory,plugin,audit}/**/domain/**``，禁
    ``fastapi`` / ``starlette`` / ``sqlalchemy`` / ``alembic``；对齐
    ``test_phase1_domain_facing_modules_have_no_orm_or_web`` 口径（**能力包**
    ``repositories/`` 与 ``factory.py`` 为**显式允许**的 ORM 落点）。新增断言（收紧）。
    """
    forbidden = {"fastapi", "starlette", "sqlalchemy", "alembic"}
    for package in PHASE2_PACKAGES:
        package_dir = PACKAGES / package
        assert package_dir.is_dir(), f"Phase 2 新包缺失：packages/{package}"
        for path in _iter_python_files(package_dir):
            parts = path.parts
            if "domain" not in parts:
                continue
            if "repositories" in parts or path.name == "factory.py":
                continue  # 能力包 SQL 仓储 / 组合工厂为显式允许的 ORM 落点
            bad = forbidden & _top_level_modules(path.read_text(encoding="utf-8"))
            assert not bad, f"{path.relative_to(REPO_ROOT)}（domain 子模块）违规导入：{sorted(bad)}"


# -- W1b（Phase 2）· T2-05：plugin 单包定向收紧（仅新增 / 零放宽） ------------


def test_plugin_package_has_no_capability_or_security_dependency() -> None:
    """``packages/plugin/**`` **不得** import ``astra_security`` / ``astra_database`` /
    ``astra_application``（防 F7 型穿透）。

    W1b 架构裁定 §2.4：``plugin`` 为抽象包，经**注入**使用仓储；import
    ``astra_security`` 会经 ``astra_database`` 拉入 ORM（F7），破坏「零 ORM」不变量。
    本断言**仅新增**，既有断言原样不动（零放宽）。
    """
    _assert_no_forbidden("plugin", {"astra_security", "astra_database", "astra_application"})


# -- W2（Phase 2）· T2-12：MCP 适配器保持抽象包（仅新增 / 零放宽） --------------


def test_mcp_adapter_stays_abstraction() -> None:
    """``packages/tool/**/adapters/**`` **不得** import ``astra_mcp`` / ``astra_security`` /
    ``astra_database`` / ``sqlalchemy`` / ``alembic`` / ``fastapi`` / ``starlette``。

    W2 裁定 R1 / R11（§16-tighten）：MCP Tool 适配器落 ``astra_tool``（**抽象包**），必须经
    **注入**的 ``MCPToolInvoker`` 使用能力（真实实现落 ``astra_mcp``，组合根注入）；import
    ``astra_mcp`` 会反向击穿「抽象包不依赖能力包」，import ``astra_security`` 会经
    ``astra_database`` 拉入 ORM。本断言**仅新增**，既有断言原样不动（**零放宽**）。
    """
    adapters_dir = PACKAGES / "tool" / "src" / "astra_tool" / "adapters"
    assert adapters_dir.is_dir(), "MCP 适配器目录缺失：packages/tool/src/astra_tool/adapters"
    forbidden = {
        "astra_mcp",
        "astra_security",
        "astra_database",
        "sqlalchemy",
        "alembic",
        "fastapi",
        "starlette",
    }
    for path in _iter_python_files(adapters_dir):
        bad = forbidden & _top_level_modules(path.read_text(encoding="utf-8"))
        assert not bad, f"{path.relative_to(REPO_ROOT)}（MCP 适配器）违规导入：{sorted(bad)}"


# -- W7（Phase 2）· T2-40：workspace 能力包 domain/ 分层收紧（仅新增 / 零放宽） ----


def test_workspace_domain_submodules_have_no_orm_or_web() -> None:
    """``astra_workspace/domain/**`` 须**零 Web / ORM**（W7 裁定 R1 / §6.5）。

    W7 采纳能力包自含布局：``Project`` / ``WorkspaceEnvironment`` 实体与 Protocol 落
    ``astra_workspace/domain/``（仿 skill / mcp / knowledge / memory）。该目录**不得**依赖
    ``fastapi`` / ``starlette`` / ``sqlalchemy`` / ``alembic``——SQL 落
    ``astra_workspace/repositories/``（为**显式允许**的 ORM 落点）。

    本案将 ``test_phase2_domain_submodules_have_no_orm_or_web`` 的 domain/ 口径**扩到
    workspace**；新增断言（收紧），零放宽。
    """
    workspace_dir = PACKAGES / "workspace"
    assert workspace_dir.is_dir(), "能力包缺失：packages/workspace"
    domain_dir = workspace_dir / "src" / "astra_workspace" / "domain"
    assert domain_dir.is_dir(), "workspace 领域目录缺失：astra_workspace/domain"
    forbidden = {"fastapi", "starlette", "sqlalchemy", "alembic"}
    for path in _iter_python_files(domain_dir):
        bad = forbidden & _top_level_modules(path.read_text(encoding="utf-8"))
        assert not bad, f"{path.relative_to(REPO_ROOT)}（workspace domain）违规导入：{sorted(bad)}"


# -- W8（Phase 2）· T2-42：marketplace 子包自含分层收紧（仅新增 / 零放宽） ------


def test_marketplace_subpackage_is_self_contained() -> None:
    """``astra_plugin/marketplace/**`` 须**自含**（零 Web / ORM / 能力包依赖）。

    W8 裁定 R1 / §2.2：marketplace 落 ``plugin`` 抽象包内，资源 schema **自含**
    （**不 import** ``astra_skill`` / ``astra_agent`` / ``astra_workflow`` 等能力包）；
    仅可依赖 ``{标准库, pyyaml, astra_core, astra_domain}``。本断言**仅新增（收紧）**、
    **零放宽**任何既有断言（防 ``plugin → 能力包`` 反向边把 DB / Web 语义间接带入抽象包）。
    """
    marketplace_dir = PACKAGES / "plugin" / "src" / "astra_plugin" / "marketplace"
    assert marketplace_dir.is_dir(), "marketplace 子包缺失：astra_plugin/marketplace"
    forbidden = {
        "fastapi",
        "starlette",
        "sqlalchemy",
        "alembic",
        "pydantic",
        "sqlmodel",
        "astra_api",
        "astra_database",
        "astra_security",
        "astra_application",
        "astra_agent",
        "astra_skill",
        "astra_workflow",
        "astra_config",
    }
    for path in _iter_python_files(marketplace_dir):
        bad = forbidden & _top_level_modules(path.read_text(encoding="utf-8"))
        assert not bad, f"{path.relative_to(REPO_ROOT)}（marketplace）违规导入：{sorted(bad)}"


# -- W9（Phase 2）· T2-48：astra_task/maintenance 子包零 ORM（仅新增 / 零放宽） ----


def test_task_maintenance_subpackage_is_orm_free() -> None:
    """``astra_task/maintenance/**`` 须**零 ORM / Web**（W9 裁定 R2 / R14）。

    W9 采纳「拆分落点」：``maintenance.cleanup`` 的 **纯 VO（``RetentionPolicy``）+
    任务类型常量** 留 ``astra_task/maintenance/``；**SQL 清理实现**落
    ``astra_database/maintenance/``（``astra_task`` 硬禁 ``sqlalchemy`` / ``astra_database``）。
    本断言为**正向断言**（先确认子包存在，再断言整子包零 ORM / Web）——**仅新增（收紧）**，
    **零放宽**任何既有断言。
    """
    maintenance_dir = PACKAGES / "task" / "src" / "astra_task" / "maintenance"
    assert maintenance_dir.is_dir(), "astra_task/maintenance 子包缺失：packages/task"
    forbidden = {"fastapi", "starlette", "sqlalchemy", "alembic", "astra_database"}
    for path in _iter_python_files(maintenance_dir):
        bad = forbidden & _top_level_modules(path.read_text(encoding="utf-8"))
        assert not bad, f"{path.relative_to(REPO_ROOT)}（task maintenance）违规导入：{sorted(bad)}"


# -- W9（Phase 2）· T2-45 / T2-46：astra_evaluation domain/ 零 ORM/Web（仅新增 / 零放宽） ---


def test_evaluation_package_domain_has_no_orm_or_web() -> None:
    """``packages/evaluation/**/domain/**`` 须**零 Web / ORM**；整包**零 Web**（W9 裁定 R14）。

    W9 采纳能力包自含布局：``EvaluationDataset`` / ``EvaluationCase`` / ``EvaluationRun`` /
    ``EvaluationResult`` 实体、常量（``kinds``）与仓储 Protocol 落
    ``astra_evaluation/domain/``（仿 skill / mcp / workflow / knowledge / memory）。

    正向断言（先确认包 / 领域目录存在）：① ``domain/`` **零** ``fastapi`` / ``starlette`` /
    ``sqlalchemy`` / ``alembic``（SQL 落 ``astra_evaluation/repositories/``，为**显式允许**的 ORM
    落点）；② 整包**仅禁 Web**（能力包口径）。本断言为 W9 **新增（收紧）**，**零放宽**任何既有断言。
    """
    package_dir = PACKAGES / "evaluation"
    assert package_dir.is_dir(), "能力包缺失：packages/evaluation"
    domain_dir = package_dir / "src" / "astra_evaluation" / "domain"
    assert domain_dir.is_dir(), "evaluation 领域目录缺失：astra_evaluation/domain"
    domain_forbidden = {"fastapi", "starlette", "sqlalchemy", "alembic"}
    for path in _iter_python_files(domain_dir):
        bad = domain_forbidden & _top_level_modules(path.read_text(encoding="utf-8"))
        assert not bad, f"{path.relative_to(REPO_ROOT)}（evaluation domain）违规导入：{sorted(bad)}"
    # 整包仅禁 Web（能力包口径；SQL 仓储 / 组合工厂为显式允许的 ORM 落点）。
    _assert_no_forbidden("evaluation", {"fastapi", "starlette"})

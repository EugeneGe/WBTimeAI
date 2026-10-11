"""Capability 受控词汇表（设计 §2.10.2；W3 裁定 §4 / Erratum-C）。

Capability 是**细粒度动作**（如 ``git.commit`` / ``shell.rm_rf``），与
``resource_permission.action``（8 个粗粒度枚举）不同：粗粒度决定「这个 Tool 能不能用」，
细粒度决定「这个 Tool 的哪些动作能用」。词汇表**落代码常量**（**非独立表**），
per-tenant 差异走 ``resource_permission.scope``（``{capabilities, deny, ...}``）。

🔴 词汇表变更纪律：**走设计评审 + 迁移默认值**（设计 §2.10.2；W3 裁定 §4.1）。
🔴 ``mcp`` 族 capability 按发现结果**动态命名空间化**：``mcp:<server>.<tool>``。
🔴 零框架依赖（受 ``test_layering.py::test_domain_has_no_framework_dependencies`` 覆盖）。
"""

from __future__ import annotations

from collections.abc import Mapping

__all__ = [
    # git
    "CAPABILITY_GIT_COMMIT",
    "CAPABILITY_GIT_PUSH",
    "CAPABILITY_GIT_FORCE_PUSH",
    "CAPABILITY_GIT_BRANCH",
    "CAPABILITY_GIT_MERGE",
    # fs
    "CAPABILITY_FS_READ",
    "CAPABILITY_FS_WRITE",
    "CAPABILITY_FS_DELETE",
    "CAPABILITY_FS_WRITE_OUTSIDE",
    # shell
    "CAPABILITY_SHELL_EXEC",
    "CAPABILITY_SHELL_RM_RF",
    # http
    "CAPABILITY_HTTP_REQUEST",
    "CAPABILITY_HTTP_ANY_HOST",
    # db
    "CAPABILITY_DB_QUERY",
    "CAPABILITY_DB_WRITE",
    "CAPABILITY_DB_DROP",
    # mcp（动态命名空间）
    "MCP_CAPABILITY_PREFIX",
    # 族 / 集合 / 函数
    "CAPABILITY_FAMILIES",
    "DEFAULT_DENY_CAPABILITIES",
    "all_capabilities",
    "capability_family",
    "is_known_capability",
    "mcp_capability",
]

# -- git ----------------------------------------------------------------------
CAPABILITY_GIT_COMMIT = "git.commit"
CAPABILITY_GIT_PUSH = "git.push"
CAPABILITY_GIT_FORCE_PUSH = "git.force_push"
CAPABILITY_GIT_BRANCH = "git.branch"
CAPABILITY_GIT_MERGE = "git.merge"

# -- fs -----------------------------------------------------------------------
CAPABILITY_FS_READ = "fs.read"
CAPABILITY_FS_WRITE = "fs.write"
CAPABILITY_FS_DELETE = "fs.delete"
CAPABILITY_FS_WRITE_OUTSIDE = "fs.write_outside_workspace"

# -- shell --------------------------------------------------------------------
CAPABILITY_SHELL_EXEC = "shell.exec"
CAPABILITY_SHELL_RM_RF = "shell.rm_rf"

# -- http ---------------------------------------------------------------------
CAPABILITY_HTTP_REQUEST = "http.request"
CAPABILITY_HTTP_ANY_HOST = "http.request_any_host"

# -- db -----------------------------------------------------------------------
CAPABILITY_DB_QUERY = "db.query"
CAPABILITY_DB_WRITE = "db.write"
CAPABILITY_DB_DROP = "db.drop"

# -- mcp（动态命名空间 ``mcp:<server>.<tool>``） ------------------------------
MCP_CAPABILITY_PREFIX = "mcp:"

#: 族 → capability 元组（受控词汇表；``mcp`` 族动态命名空间化，不入本表）。
CAPABILITY_FAMILIES: Mapping[str, tuple[str, ...]] = {
    "git": (
        CAPABILITY_GIT_COMMIT,
        CAPABILITY_GIT_PUSH,
        CAPABILITY_GIT_FORCE_PUSH,
        CAPABILITY_GIT_BRANCH,
        CAPABILITY_GIT_MERGE,
    ),
    "fs": (
        CAPABILITY_FS_READ,
        CAPABILITY_FS_WRITE,
        CAPABILITY_FS_DELETE,
        CAPABILITY_FS_WRITE_OUTSIDE,
    ),
    "shell": (CAPABILITY_SHELL_EXEC, CAPABILITY_SHELL_RM_RF),
    "http": (CAPABILITY_HTTP_REQUEST, CAPABILITY_HTTP_ANY_HOST),
    "db": (CAPABILITY_DB_QUERY, CAPABILITY_DB_WRITE, CAPABILITY_DB_DROP),
}

#: **默认拒绝** capability 集：不显式 allow 即拒绝（须显式授予才放行，W3 裁定 §4.1）。
DEFAULT_DENY_CAPABILITIES: frozenset[str] = frozenset(
    {
        CAPABILITY_FS_WRITE_OUTSIDE,
        CAPABILITY_SHELL_RM_RF,
        CAPABILITY_HTTP_ANY_HOST,
        CAPABILITY_DB_DROP,
        CAPABILITY_GIT_FORCE_PUSH,
    }
)


def all_capabilities() -> frozenset[str]:
    """返回词汇表内全部**静态** capability（不含动态 ``mcp:`` 命名空间）。"""
    values: set[str] = set()
    for members in CAPABILITY_FAMILIES.values():
        values.update(members)
    return frozenset(values)


def capability_family(capability: str) -> str | None:
    """返回 capability 所属族（``git.commit`` → ``git``；``mcp:x.y`` → ``mcp``）。

    Args:
        capability: capability 字面值（可含族通配 ``git.*``）。

    Returns:
        族名；未知族返回 ``None``。
    """
    if capability.startswith(MCP_CAPABILITY_PREFIX):
        return "mcp"
    family = capability.split(".", 1)[0]
    return family if family in CAPABILITY_FAMILIES else None


def is_known_capability(capability: str) -> bool:
    """判断 capability 是否为**受控词汇表**内的已知项（含动态 ``mcp:`` 命名空间）。"""
    if capability.startswith(MCP_CAPABILITY_PREFIX):
        return len(capability) > len(MCP_CAPABILITY_PREFIX)
    if capability in all_capabilities():
        return True
    return capability_family(capability) is not None


def mcp_capability(server: str, tool: str) -> str:
    """按发现结果命名空间化 MCP capability（``mcp:<server>.<tool>``）。"""
    return f"{MCP_CAPABILITY_PREFIX}{server}.{tool}"

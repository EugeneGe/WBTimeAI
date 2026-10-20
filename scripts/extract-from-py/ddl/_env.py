"""DDL 抽取工具链的「环境解析 + 解释器守卫」私有模块（C-03 自用）。

本模块只做三件事，且**只服务** :mod:`export_ddl` / :mod:`gen_type_map`：

1. 解析旧仓（``_old``）根目录、``*/src`` 导入根、旧仓解释器路径、产物目录；
2. 在 SQLAlchemy 不可用的解释器下**自动重执行**自身到旧仓 ``.venv`` 解释器（单次，
   以 ``WBTIME_DDL_REEXEC=1`` 作循环哨兵）；
3. 把旧仓暴露为可 import 的 ``wbtime_ai_*`` 命名空间，并返回 ``Base.metadata``。

实现策略：**全部委托给 C-01 基座** ``scripts/extract-from-py/_bootstrap.py``
（``make_context`` / ``install_import_paths`` / ``run_python`` / ``child_env``）。
本文件**不再复制**路径规范化、``*/src`` 枚举、解释器定位等逻辑——两份实现迟早会分叉，
而路径规范化一旦错了，症状是 ``ModuleNotFoundError``（极难定位），不是报错信息。

> 历史：C-03 并行开发期曾内置一份等价回退实现（避免阻塞在 C-01 上）。C-01 收口且接口冻结后
> 已删除，改为**硬依赖基座**：基座缺失时直接给出可执行的修复提示，而不是悄悄走另一套逻辑。
"""

from __future__ import annotations

import dataclasses
import importlib
import os
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

__all__ = [
    "REEXEC_ENV_VAR",
    "Env",
    "EnvError",
    "ensure_legacy_runtime",
    "install_metadata",
    "resolve_env",
    "source_hint",
]

#: 重执行哨兵：置 ``1`` 表示「已在旧仓解释器内」，防止无限递归。
REEXEC_ENV_VAR = "WBTIME_DDL_REEXEC"

#: C-01 基座模块名（与 ``scripts/extract-from-py/_bootstrap.py`` 同名）。
_BOOTSTRAP_MODULE = "_bootstrap"


class EnvError(RuntimeError):
    """旧仓、解释器、基座或依赖不可用时抛出（消息内必须给出可执行的修复建议）。"""


def source_hint(argv: Sequence[str]) -> str | None:
    """从命令行参数里取 ``--source`` 的值（供**重执行前**解析环境用）。

    重执行必须发生在 ``import _extract``（进而 ``import sqlalchemy``）**之前**，此时
    ``argparse`` 还没跑起来，因此需要这个不含依赖的最小扫描。支持 ``--source X`` 与
    ``--source=X`` 两种写法。

    Args:
        argv: 去掉脚本名后的参数列表（通常是 ``sys.argv[1:]``）。

    Returns:
        ``--source`` 的值；未提供时返回 ``None``（由环境变量/默认值兜底）。
    """
    for index, token in enumerate(argv):
        if token == "--source" and index + 1 < len(argv):
            return argv[index + 1]
        if token.startswith("--source="):
            return token.split("=", 1)[1]
    return None


@dataclasses.dataclass(frozen=True)
class Env:
    """一次性解析好的运行环境（派生自 ``_bootstrap.ExtractContext``）。

    Attributes:
        source: 旧仓根目录，已规范化为**盘符 + 正斜杠**形式（Windows Python 可直接打开）。
        pythonpath: ``os.pathsep`` 连接的全部导入根（30 个 ``packages/*/src`` + 3 个 ``apps/*/src``）。
        python_executable: 旧仓 ``.venv`` 解释器路径（缺失 Python 依赖时用于重执行）。
        repo_root: 新仓根目录（``D:/WBT/WBTimeAI``）。
        contracts_dir: 契约产物目录（``<repo_root>/contracts``）。
        script_dir: 本目录（``scripts/extract-from-py/ddl``）。
    """

    source: str
    pythonpath: str
    python_executable: str
    repo_root: Path
    contracts_dir: Path
    script_dir: Path


# ---------------------------------------------------------------------------
# C-01 基座（唯一实现来源，硬依赖）
# ---------------------------------------------------------------------------


def _require_bootstrap() -> Any:
    """导入并返回 C-01 基座模块 ``_bootstrap``。

    Returns:
        ``_bootstrap`` 模块对象（接口已冻结：``make_context`` / ``install_import_paths`` /
        ``run_python`` / ``child_env``）。

    Raises:
        EnvError: 基座缺失或导入失败（说明 toolkit 不完整，而不是「回退到另一套逻辑」）。
    """
    parent = Path(__file__).resolve().parent.parent
    if str(parent) not in sys.path:
        sys.path.insert(0, str(parent))
    try:
        return importlib.import_module(_BOOTSTRAP_MODULE)
    except Exception as exc:  # 任何失败都必须变成一条可执行的提示
        raise EnvError(
            f"无法导入 C-01 基座 {parent / '_bootstrap.py'}：{exc}；"
            "本目录不再内置回退实现（避免路径规范化逻辑分叉），"
            "请确认 scripts/extract-from-py/_bootstrap.py 存在且可导入"
        ) from exc


# ---------------------------------------------------------------------------
# 对外：解析环境
# ---------------------------------------------------------------------------


def resolve_env(source: str | None = None) -> Env:
    """解析旧仓 / 解释器 / 导入根 / 产物目录（委托 ``_bootstrap.make_context``）。

    Args:
        source: ``--source`` 传入的旧仓根目录；``None`` 时由基座按
            ``$WBTIME_SOURCE`` > 默认值 解析。

    Returns:
        冻结的 :class:`Env`。

    Raises:
        EnvError: 基座缺失、旧仓不存在或解释器缺失。
    """
    bootstrap = _require_bootstrap()
    try:
        context = bootstrap.make_context(source)
    except Exception as exc:  # 统一转成本模块的错误类型
        raise EnvError(f"解析旧仓环境失败：{exc}") from exc
    return Env(
        source=context.source,
        pythonpath=context.pythonpath,
        python_executable=context.python_executable,
        repo_root=Path(context.repo_root).resolve(),
        contracts_dir=Path(context.contracts_dir).resolve(),
        script_dir=Path(__file__).resolve().parent,
    )


# ---------------------------------------------------------------------------
# 对外：解释器守卫
# ---------------------------------------------------------------------------


def _sqlalchemy_available() -> bool:
    """当前解释器能否 ``import sqlalchemy``（旧仓 ``.venv`` 才有）。"""
    try:
        importlib.import_module("sqlalchemy")
    except Exception:  # noqa: BLE001 - 任何失败都等价于「不可用」
        return False
    return True


def ensure_legacy_runtime(env: Env) -> None:
    """确保当前进程运行在**能 import SQLAlchemy** 的解释器下。

    若不是（例如被系统 Python 启动），用旧仓 ``.venv`` 解释器**重执行本脚本一次**并原样
    透传 ``sys.argv``；哨兵 ``$WBTIME_DDL_REEXEC`` 防止递归。子进程环境由基座
    ``child_env`` 构建（``PYTHONPATH`` + UTF-8 stdio），不在本文件另拼一份。

    Args:
        env: 已解析的环境。

    Raises:
        EnvError: 已在旧仓解释器内仍缺 SQLAlchemy（依赖未安装）。
    """
    if _sqlalchemy_available():
        return
    if os.environ.get(REEXEC_ENV_VAR) == "1":
        raise EnvError(
            f"旧仓解释器 {env.python_executable!r} 内仍无法 import sqlalchemy；"
            "请在 _old 内检查 .venv 依赖（不要在本仓安装 Python 依赖）"
        )
    bootstrap = _require_bootstrap()
    # 哨兵先落进 os.environ：基座 child_env() 会 copy os.environ，子进程因此能看见它。
    os.environ[REEXEC_ENV_VAR] = "1"
    completed = bootstrap.run_python(env.source, sys.argv)
    sys.exit(completed.returncode)


# ---------------------------------------------------------------------------
# 对外：装载 ORM metadata
# ---------------------------------------------------------------------------


def install_metadata(env: Env) -> Any:
    """装载 ``wbtime_ai_database`` 并返回 ``Base.metadata``。

    🔴 ``pgvector`` 缺失时**硬失败**：此时 ``VectorType`` 会静默降级为 ``JSON``，
    冻结快照里的 ``VECTOR(1536)`` 会消失而无人察觉（路线图 §3.3 入口条件 ④）。

    Args:
        env: 已解析的环境。

    Returns:
        ``sqlalchemy.MetaData``（61 张表已注册）。

    Raises:
        EnvError: 包不可导入，或 ``pgvector`` 缺失。
    """
    bootstrap = _require_bootstrap()
    try:
        import_dirs = bootstrap.install_import_paths(env.source)
    except Exception as exc:  # 基座错误统一转成本模块类型
        raise EnvError(f"装载旧仓导入根失败：{exc}") from exc
    try:
        importlib.import_module("wbtime_ai_database.models")  # 触发全部模型注册
        base_module = importlib.import_module("wbtime_ai_database.base")
    except ModuleNotFoundError as exc:
        raise EnvError(
            "无法 import wbtime_ai_database（显式 PYTHONPATH 未生效？）："
            f"{exc}；已装载的导入根数量={len(import_dirs)}"
        ) from exc
    try:
        importlib.import_module("pgvector.sqlalchemy")
    except ImportError as exc:
        raise EnvError(
            "pgvector 不可用：VectorType 会静默退化为 JSON，"
            "VECTOR(1536) 将从冻结面消失（路线图 §3.3 入口条件 ④）"
        ) from exc
    return base_module.Base.metadata

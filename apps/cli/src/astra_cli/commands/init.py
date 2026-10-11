"""``astra init``——初始化本地数据目录与默认身份（决策 D5）。

步骤（**幂等**）：
1. 建立 ``{data_dir}/{data,workspace,storage,logs,secrets}/``；
2. 写 ``{data_dir}/config.yaml``（已存在则不覆盖，仅非敏感项）；
3. 确保数据库 schema（优先 ``alembic upgrade head``，回退 ``metadata.create_all``）；
4. 触发 :class:`~astra_identity.IdentityBootstrap` 默认身份引导（Tenant-ready）。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

__all__ = ["InitReport", "run_init"]


@dataclass
class InitReport:
    """``astra init`` 结果。

    Attributes:
        data_dir: 数据根目录。
        created_dirs: 本次新建的子目录。
        existing_dirs: 已存在的子目录。
        config_path: ``config.yaml`` 路径。
        config_written: 是否新写入 ``config.yaml``。
        schema_backend: 建表方式（``alembic`` / ``metadata``）。
        bootstrap_tenant_slug: 引导得到的默认租户 slug。
    """

    data_dir: Path
    created_dirs: list[Path] = field(default_factory=list)
    existing_dirs: list[Path] = field(default_factory=list)
    config_path: Path | None = None
    config_written: bool = False
    schema_backend: str = ""
    bootstrap_tenant_slug: str = ""


def _ensure_schema(settings) -> str:
    """确保数据库 schema 就位（**幂等**）。

    Returns:
        建表方式标识（``alembic`` 或 ``metadata``）。
    """
    from astra_cli.paths import locate_alembic_ini

    alembic_ini = locate_alembic_ini()
    if alembic_ini is not None:
        from alembic import command
        from alembic.config import Config

        config = Config(str(alembic_ini))
        config.set_main_option("script_location", str(alembic_ini.parent / "migrations"))
        command.upgrade(config, "head")
        return "alembic"

    import astra_database.models  # noqa: F401 - 注册全部 ORM 表
    from astra_database import Base, create_engine_from_settings

    engine = create_engine_from_settings(settings)
    try:
        Base.metadata.create_all(engine)
    finally:
        engine.dispose()
    return "metadata"


def run_init(data_dir: str | None = None) -> InitReport:
    """执行 ``astra init``。

    Args:
        data_dir: 显式数据目录；为 ``None`` 时取配置 ``ASTRA_DATA_DIR``。

    Returns:
        :class:`InitReport`。
    """
    from astra_api.dependencies import build_identity_services_from_providers
    from astra_config import build_providers, get_settings

    from astra_cli.paths import (
        bind_config_file,
        ensure_directories,
        resolve_data_dir,
        write_config_yaml,
    )

    base = resolve_data_dir(data_dir)
    created, existing = ensure_directories(base)
    config_path, written = write_config_yaml(base, data_dir=str(base))

    # 让本进程后续设置读取到生成的 config.yaml（ENV 仍优先）。
    bind_config_file(base)
    settings = get_settings()

    schema_backend = _ensure_schema(settings)

    providers = build_providers(settings)
    try:
        identity = build_identity_services_from_providers(providers)
        result = identity.bootstrap.ensure_default_identity()
        tenant_slug = result.tenant.slug
    finally:
        database = providers.database
        engine = getattr(database, "engine", None) if database is not None else None
        if engine is not None:
            engine.dispose()

    return InitReport(
        data_dir=base,
        created_dirs=created,
        existing_dirs=existing,
        config_path=config_path,
        config_written=written,
        schema_backend=schema_backend,
        bootstrap_tenant_slug=tenant_slug,
    )

"""CLI 集成测试（T0-19 / 决策 D5）。

使用 ``typer.testing.CliRunner``：``init`` 幂等、``run --help``、``doctor`` 退出码。
测试副作用隔离：全部落在 ``tmp_path``（``ASTRA_DATA_DIR`` / ``ASTRA_DATABASE_URL``）。
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from astra_cli.main import app
from typer.testing import CliRunner

_SUBDIRS = ("data", "workspace", "storage", "logs", "secrets")


@pytest.fixture()
def cli_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Iterator[Path]:
    """隔离的 CLI 环境：local 模式 + 临时 SQLite + ``tmp`` 数据目录。"""
    db_file = tmp_path / "cli.db"
    data_dir = tmp_path / "astra-data"
    monkeypatch.setenv("ASTRA_MODE", "local")
    monkeypatch.setenv("ASTRA_DATABASE_URL", f"sqlite:///{db_file.as_posix()}")
    monkeypatch.setenv("ASTRA_SECRET_KEY", "test-secret-key-0123456789abcdef-32bytes")
    monkeypatch.setenv("ASTRA_DATA_DIR", str(data_dir))
    monkeypatch.setenv("ASTRA_LOG_LEVEL", "WARNING")
    monkeypatch.setenv("ASTRA_LOG_FORMAT", "console")
    # 令 bind_config_file 的写入可被 monkeypatch 还原（避免跨用例泄漏）。
    monkeypatch.setenv("ASTRA_CONFIG_FILE", str(data_dir / "config.yaml"))

    from astra_config.loader import reset_settings_cache

    reset_settings_cache()
    yield data_dir
    reset_settings_cache()


def test_init_creates_directories_and_config(cli_env: Path) -> None:
    runner = CliRunner()
    result = runner.invoke(app, ["init"])
    assert result.exit_code == 0, result.output

    for name in _SUBDIRS:
        assert (cli_env / name).is_dir(), f"缺少子目录：{name}"
    assert (cli_env / "config.yaml").is_file()


def test_init_is_idempotent(cli_env: Path) -> None:
    runner = CliRunner()
    first = runner.invoke(app, ["init"])
    assert first.exit_code == 0, first.output
    snapshot = sorted(p.name for p in cli_env.iterdir())

    second = runner.invoke(app, ["init"])
    assert second.exit_code == 0, second.output
    assert sorted(p.name for p in cli_env.iterdir()) == snapshot

    # config.yaml 不被覆盖（幂等）。
    assert "config.yaml" in snapshot


def test_run_help_lists_options(cli_env: Path) -> None:
    """``run --help`` 列出 ``--host`` / ``--port`` / ``--reload``（三选项断言保留）。

    固定渲染宽度（``COLUMNS``）：Typer/Rich 在**非 tty** 下按终端宽度折行；CI 环境宽度偏窄
    （观测到 ``COLUMNS`` 缺失 / 极小时帮助被折行，``--host`` 不复现为子串）。注入足够宽的
    ``COLUMNS`` 使断言稳定——仅固定渲染宽度，不删 / 不弱化任何选项断言。
    """
    result = CliRunner().invoke(app, ["run", "--help"], env={"COLUMNS": "200", "LINES": "50"})
    assert result.exit_code == 0
    assert "--host" in result.output
    assert "--port" in result.output
    assert "--reload" in result.output


def test_doctor_passes_after_init(cli_env: Path) -> None:
    runner = CliRunner()
    assert runner.invoke(app, ["init"]).exit_code == 0
    result = runner.invoke(app, ["doctor"])
    assert result.exit_code == 0, result.output
    assert "doctor" in result.output.lower()


def test_doctor_fails_on_unreachable_database(
    cli_env: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from astra_config.loader import reset_settings_cache

    bad_db = cli_env.parent / "missing-subdir" / "astra.db"
    monkeypatch.setenv("ASTRA_DATABASE_URL", f"sqlite:///{bad_db.as_posix()}")
    reset_settings_cache()

    result = CliRunner().invoke(app, ["doctor"])
    assert result.exit_code == 1
    assert "FAIL" in result.output


def test_doctor_reports_docker_and_provider_checks(cli_env: Path) -> None:
    """T1-05：doctor 新增 Docker / Provider 自检项，社区模式仍退出 0。"""
    runner = CliRunner()
    assert runner.invoke(app, ["init"]).exit_code == 0
    result = runner.invoke(app, ["doctor"])
    assert result.exit_code == 0, result.output
    assert "docker" in result.output
    assert "provider" in result.output


def test_doctor_fails_on_short_secret_without_leaking(
    cli_env: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """T1-05：主密钥过短 → provider 自检失败（非零退出），且**不打印明文**。"""
    from astra_config.loader import reset_settings_cache

    leaked = "SHORT-SECRET-DO-NOT-LEAK"
    monkeypatch.setenv("ASTRA_SECRET_KEY", leaked)
    reset_settings_cache()

    result = CliRunner().invoke(app, ["doctor"])
    assert result.exit_code == 1
    assert "FAIL" in result.output
    assert "provider" in result.output
    # 明文不得出现在任何输出中（仅长度可见）。
    assert leaked not in result.output


def test_doctor_does_not_print_valid_secret(cli_env: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """T1-05：主密钥达标时亦不打印明文（掩码）。"""
    from astra_config.loader import reset_settings_cache

    secret = "VALID-SECRET-DO-NOT-PRINT-0123456789"
    monkeypatch.setenv("ASTRA_SECRET_KEY", secret)
    reset_settings_cache()

    runner = CliRunner()
    assert runner.invoke(app, ["init"]).exit_code == 0
    result = runner.invoke(app, ["doctor"])
    assert result.exit_code == 0, result.output
    assert secret not in result.output
    assert "****" in result.output


def test_register_command_group_supports_astra_group_cmd(cli_env: Path) -> None:
    """T1-05：扩展机制 `astra <group> <cmd>` 注册可用（不新增顶级核心命令）。"""
    import typer
    from astra_cli.main import register_command_group

    group = typer.Typer(help="测试用扩展分组")

    @group.command("ping")
    def _ping() -> None:  # noqa: ANN202 - typer 回调
        typer.echo("pong")

    register_command_group("exttest", group)

    result = CliRunner().invoke(app, ["exttest", "ping"])
    assert result.exit_code == 0, result.output
    assert "pong" in result.output


def test_core_commands_still_available(cli_env: Path) -> None:
    """T1-05：三核心命令兼容（init / run / doctor 均在帮助中）。"""
    result = CliRunner().invoke(app, ["--help"])
    assert result.exit_code == 0
    for command in ("init", "run", "doctor"):
        assert command in result.output

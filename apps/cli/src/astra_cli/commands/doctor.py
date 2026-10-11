"""``astra doctor``——本机自检（决策 D5 / P0-11 / T1-05）。

自检项（可扩展，见 :mod:`astra_cli.doctor_checks`）：配置 / DB 连通 / 迁移版本 /
目录可写 / 依赖版本（Phase 0 既有）+ **Docker 运行时可探测性** + **Model Provider
配置 / 凭证可达性（掩码）**（Phase 1 新增）。

每项返回 ``(name, status, detail)``，``status`` ∈ ``ok`` / ``fail`` / ``skip``；
退出码：``0``（无失败项）/ ``1``（存在失败项）。``skip`` 不影响退出码。

🔴 CLI 层**不判断 mode**（C-01）；**不打印任何密钥明文**。
"""

from __future__ import annotations

from dataclasses import dataclass

import typer

from astra_cli import doctor_checks

__all__ = ["CheckResult", "DoctorReport", "run_doctor"]


@dataclass
class CheckResult:
    """单项自检结果。

    Attributes:
        name: 检查名。
        status: ``ok`` / ``fail`` / ``skip``。
        detail: 详情（用于展示；**不含密钥明文**）。
    """

    name: str
    status: str
    detail: str = ""

    @property
    def ok(self) -> bool:
        """非 ``fail`` 即视为通过（``skip`` 计入通过）。"""
        return self.status != "fail"


@dataclass
class DoctorReport:
    """``astra doctor`` 汇总结果。

    Attributes:
        checks: 各检查项结果。
    """

    checks: list[CheckResult]

    @property
    def ok(self) -> bool:
        """无失败项返回 ``True``。"""
        return all(check.ok for check in self.checks)

    @property
    def failed(self) -> list[CheckResult]:
        """失败项列表。"""
        return [check for check in self.checks if not check.ok]


def _collect_checks() -> list[CheckResult]:
    """依序执行全部自检项，返回结果列表。"""
    config_outcome, settings = doctor_checks.load_settings()
    outcomes = [
        config_outcome,
        doctor_checks.check_database(settings),
        doctor_checks.check_migrations(settings),
        doctor_checks.check_directories(settings),
        doctor_checks.check_dependencies(),
        doctor_checks.check_docker(settings),
        doctor_checks.check_provider(settings),
        doctor_checks.check_worker(settings),
    ]
    return [
        CheckResult(name=name, status=status, detail=detail) for name, status, detail in outcomes
    ]


_MARKERS = {"ok": "OK  ", "fail": "FAIL", "skip": "SKIP"}


def run_doctor() -> int:
    """执行自检并返回退出码（``0`` 无失败项 / ``1`` 存在失败项）。"""
    report = DoctorReport(checks=_collect_checks())
    typer.echo("Astra AI doctor:")
    for check in report.checks:
        marker = _MARKERS.get(check.status, check.status.upper())
        typer.echo(f"  [{marker}] {check.name}: {check.detail}")
    typer.echo("结果：" + ("全部通过" if report.ok else "存在失败项"))
    return 0 if report.ok else 1

"""工具安全边界（纯逻辑，设计 §2.12 / §2.5.2 / `I-P1-19`）。

- **路径逃逸防护**：``resolve_within_workspace`` 以 ``pathlib`` 解析并强制限定在 Workspace
  根目录内（拒绝 ``..`` / 绝对路径越界 / 符号链接逃逸）；
- **scope 校验**：``validate_scope_paths`` 对 ``permission_scope`` 声明做注册期/校验期
  拦截（越界的 glob → ``VALIDATION_ERROR``，D-10）；
- **SSRF 防护**：``check_egress`` 解析域名（``socket.getaddrinfo``，**非 subprocess**），
  拒绝内网 IP / 环回 / 元数据端点，并以「二次解析」抵御 DNS rebinding（D-11 / D-12）；
  **出网默认拒绝全部**（仅显式 allowlist 放行，D-13）；W1 / T2-03 起本函数为
  ``astra_domain.ports.egress`` 原语的**薄委托**（签名/语义不变），唯一出网**入口**＝
  ``astra_security.egress.SecurityEgressPolicy``；
- **危险命令**：``check_command`` / ``check_git_command`` / ``check_python_code`` 对
  《首批危险动作清单》做模式拦截（D-01~D-05 / D-14 / D-15）。

🔴 本模块为**纯逻辑**，仅用标准库（``ipaddress`` / ``socket`` / ``urllib.parse`` / ``re`` /
   ``pathlib`` / ``fnmatch``）；**禁止** ``subprocess`` / ``os.system``（由扫描测试兜底）。
"""

from __future__ import annotations

import fnmatch
import ipaddress
import re
import socket
from collections.abc import Iterable, Sequence
from pathlib import Path
from urllib.parse import urlsplit

from astra_domain.ports.egress import ALLOWED_SCHEMES as _ALLOWED_SCHEMES
from astra_domain.ports.egress import METADATA_IPS as _METADATA_IPS
from astra_domain.ports.egress import host_matches as _host_matches
from astra_domain.ports.egress import is_blocked_ip as _is_blocked_ip
from astra_domain.ports.egress import resolve_all as _resolve_all

from .errors import permission_denied, validation_error

__all__ = [
    "resolve_within_workspace",
    "is_within_workspace",
    "validate_scope_paths",
    "resolve_host_ips",
    "is_blocked_ip",
    "check_egress",
    "check_command",
    "check_git_command",
    "check_python_code",
]

#: 云元数据端点（SSRF 重点）。**单一来源**＝``astra_domain.ports.egress.METADATA_IPS``。
METADATA_IPS: frozenset[str] = _METADATA_IPS

#: 允许的出网 scheme（**单一来源**＝``astra_domain.ports.egress.ALLOWED_SCHEMES``）。
_ALLOWED_SCHEMES: frozenset[str] = _ALLOWED_SCHEMES


# -- 路径逃逸防护 -----------------------------------------------------------


def is_within_workspace(path: Path | str, workspace_root: Path | str) -> bool:
    """判断 ``path`` 是否位于 ``workspace_root`` 之内（解析后）。"""
    root = Path(workspace_root).expanduser().resolve()
    try:
        resolved = Path(path).expanduser().resolve()
    except OSError:  # pragma: no cover - 极端路径
        return False
    return resolved.is_relative_to(root)


def _match_scope(relative: str, patterns: Iterable[str]) -> bool:
    """判断相对路径是否匹配 scope 白名单（支持 ``dir`` / ``dir/**`` / glob）。"""
    for raw in patterns:
        pattern = str(raw).replace("\\", "/").strip()
        if not pattern:
            continue
        if pattern.endswith("/**"):
            prefix = pattern[:-3].rstrip("/")
            if relative == prefix or relative.startswith(f"{prefix}/"):
                return True
        elif "*" in pattern or "?" in pattern:
            if fnmatch.fnmatch(relative, pattern):
                return True
        elif relative == pattern or relative.startswith(f"{pattern}/"):
            return True
    return False


def resolve_within_workspace(
    path: str,
    *,
    workspace_root: str | Path,
    allowed_paths: Sequence[str] | None = None,
    must_exist: bool = False,
) -> Path:
    """将 ``path`` 解析为 Workspace 内的绝对路径（拒绝一切越界）。

    Args:
        path: 目标路径（相对 / 绝对）。
        workspace_root: 工作区根目录。
        allowed_paths: 可选 scope 白名单（相对路径 / glob）。
        must_exist: 是否要求目标已存在。

    Returns:
        解析后的绝对路径（限定在 Workspace 内）。

    Raises:
        DomainError: 路径越界 / 不在 scope 内 / 不存在（``PERMISSION_DENIED`` /
            ``VALIDATION_ERROR``）。
    """
    root = Path(workspace_root).expanduser().resolve()
    candidate = Path(path)
    if not candidate.is_absolute():
        candidate = root / candidate
    try:
        resolved = candidate.resolve()
    except OSError as exc:  # pragma: no cover - 极端路径
        raise validation_error("路径解析失败", path=path) from exc

    if not resolved.is_relative_to(root):
        raise permission_denied("路径越出 Workspace 边界", path=path, workspace=str(root))

    if allowed_paths:
        relative = resolved.relative_to(root).as_posix()
        relative = "" if relative == "." else relative
        if not _match_scope(relative, allowed_paths):
            raise permission_denied(
                "路径不在 permission_scope 允许范围内",
                path=path,
                scope=[str(item) for item in allowed_paths],
            )

    if must_exist and not resolved.exists():
        raise validation_error("目标不存在", path=path)
    return resolved


def validate_scope_paths(
    paths: Iterable[str] | None, *, workspace_root: str | Path | None = None
) -> None:
    """校验 ``permission_scope.paths`` 声明（越界 → ``VALIDATION_ERROR``，D-10）。

    Raises:
        DomainError: 声明含绝对越界路径 / ``..`` 穿越（``VALIDATION_ERROR``）。
    """
    root = Path(workspace_root).expanduser().resolve() if workspace_root else None
    for raw in paths or ():
        text = str(raw).strip()
        if not text:
            continue
        normalized = text.replace("\\", "/")
        candidate = Path(normalized)
        looks_absolute = candidate.is_absolute() or normalized.startswith("/")
        if looks_absolute:
            if root is None:
                raise validation_error("permission_scope 不允许绝对路径", path=text)
            try:
                resolved = candidate.resolve()
            except OSError as exc:  # pragma: no cover - 极端路径
                raise validation_error("permission_scope 路径非法", path=text) from exc
            if not resolved.is_relative_to(root):
                raise validation_error(
                    "permission_scope 路径越出 Workspace",
                    path=text,
                    workspace=str(root),
                )
        if ".." in Path(normalized).parts:
            raise validation_error("permission_scope 不允许路径穿越 '..'", path=text)


# -- SSRF 防护（**薄委托** astra_domain 原语） ------------------------------
#
# 🔴 W1 / T2-03 收敛：本模块的 ``check_egress`` / ``is_blocked_ip`` / ``resolve_host_ips`` /
#    ``METADATA_IPS`` **签名与语义不变**，函数体改**薄委托** ``astra_domain.ports.egress``
#    原语（**单一来源**，**不** import ``astra_security``——其顶层 import 会拉入 ORM，
#    违「抽象包零 ORM」不变量；**不新增 tool→security 依赖边**）。
#    唯一出网判定**入口**＝``astra_security.egress.SecurityEgressPolicy``。


def resolve_host_ips(host: str, *, resolver: object | None = None) -> list[str]:
    """解析域名到 IP 列表（``resolver`` 可注入，测试用）。

    薄委托 :func:`astra_domain.ports.egress.resolve_all`。

    Raises:
        DomainError: 解析失败（``PERMISSION_DENIED``，解析不出即拒绝出网）。
    """
    try:
        return _resolve_all(host, resolver=resolver)  # type: ignore[arg-type]
    except (socket.gaierror, OSError, ValueError) as exc:
        raise permission_denied("域名解析失败，拒绝出网", host=host) from exc


def is_blocked_ip(ip: str) -> bool:
    """判断 IP 是否为**禁止**访问（内网 / 环回 / 链路本地 / 保留 / 元数据端点）。

    薄委托 :func:`astra_domain.ports.egress.is_blocked_ip`。
    """
    return _is_blocked_ip(ip)


def _host_allowed(host: str, allowlist: Sequence[str] | None) -> bool:
    """判断 host 是否命中出网白名单（默认拒绝全部）。

    薄委托 :func:`astra_domain.ports.egress.host_matches`。
    """
    return _host_matches(host, allowlist)


def check_egress(
    url: str,
    *,
    allowlist: Sequence[str] | None = None,
    resolver: object | None = None,
) -> str:
    """出网访问校验（默认**拒绝全部**；含内网 / 元数据 / DNS rebinding 防护）。

    **签名与语义不变**（Phase 1 冻结，``I-P1-19`` / D-11~D-13）；函数体**薄委托**
    ``astra_domain.ports.egress`` 原语。唯一出网**入口**＝
    ``astra_security.egress.SecurityEgressPolicy``（本函数为其在 tool 层的兼容委托）。

    Args:
        url: 目标 URL。
        allowlist: 显式出网白名单（host / glob）；为空则**拒绝全部**。
        resolver: 域名解析器（默认 ``socket.getaddrinfo``；测试可注入）。

    Returns:
        校验通过后**钉定**的 IP（供后续连接使用，抵御 rebinding）。

    Raises:
        DomainError: 命中任一拒绝条件（``PERMISSION_DENIED``）。
    """
    parsed = urlsplit(url)
    if parsed.scheme.lower() not in _ALLOWED_SCHEMES:
        raise permission_denied("非法的出网协议", url=url, scheme=parsed.scheme)
    host = parsed.hostname
    if not host:
        raise permission_denied("缺少目标 host", url=url)
    if not _host_allowed(host, allowlist):
        raise permission_denied("出网默认拒绝（未命中白名单）", url=url, host=host)

    # IP 直连：直接校验。
    try:
        ipaddress.ip_address(host)
        literal = True
    except ValueError:
        literal = False

    if literal:
        if is_blocked_ip(host):
            raise permission_denied("拒绝访问内网 / 元数据地址", url=url, ip=host)
        return host

    # 域名：解析两次，抵御 DNS rebinding（首解析公网、二次解析内网 → 拒绝）。
    first = resolve_host_ips(host, resolver=resolver)
    for ip in first:
        if is_blocked_ip(ip):
            raise permission_denied("域名解析到内网地址，拒绝出网", url=url, ip=ip)
    second = resolve_host_ips(host, resolver=resolver)
    for ip in second:
        if is_blocked_ip(ip):
            raise permission_denied("检测到 DNS rebinding，拒绝出网", url=url, ip=ip)
    return first[0]


# -- 危险命令拦截 -----------------------------------------------------------

_DANGEROUS_COMMAND_PATTERNS: tuple[tuple[str, str], ...] = (
    (r"\brm\s+-[a-z]*r[a-z]*f?\s+/(?:\s|$)", "禁止递归删除根目录"),
    (r"\brm\s+-[a-z]*f[a-z]*r?\s+/(?:\s|$)", "禁止递归删除根目录"),
    (r"\brm\s+-[a-z]*r[a-z]*f?\s+~(?:\s|$)", "禁止递归删除用户目录"),
    (r":\s*\(\s*\)\s*\{.*\};\s*:", "禁止 fork 炸弹"),
    (r"\bmkfs(\.\w+)?\b", "禁止格式化文件系统"),
    (r"\b(?:shutdown|reboot|halt|poweroff)\b", "禁止关机 / 重启"),
    (r"\bdd\b[^\n]*\bof=/dev/", "禁止裸写块设备"),
    (r"\bdrop\s+database\b", "禁止删除数据库"),
    (r"\btruncate\s+table\b", "禁止清空数据表"),
    (r"\bsudo\b", "禁止提权"),
    (r"\bnsenter\b", "禁止命名空间逃逸"),
    (r"--privileged\b", "禁止特权容器"),
    (r"docker\.sock", "禁止挂载宿主 docker.sock"),
    (r"`[^`]*`", "禁止反引号命令替换注入"),
    (r"\$\(", "禁止 $() 命令替换注入"),
)

_DANGEROUS_GIT_PATTERNS: tuple[tuple[str, str], ...] = (
    (r"\bpush\b.*(?:--force\b|-f\b)", "禁止强推（force push）"),
    (r"\breset\b.*--hard\b", "禁止 git reset --hard"),
    (r"\bremote\s+set-url\b.*@", "禁止在 remote 中内嵌凭证"),
    (r"\bconfig\b.*credential\.helper\b", "禁止写入凭证 helper"),
    (r"\bfilter-branch\b", "禁止重写历史"),
)

_DANGEROUS_PYTHON_PATTERNS: tuple[tuple[str, str], ...] = (
    (r"shutil\.rmtree\(\s*['\"]/(?:\s|['\"])", "禁止删除根目录"),
    (r"os\.remove\(\s*['\"]/(?:etc|root)/", "禁止删除系统目录文件"),
    (r"\bdrop\s+database\b", "禁止删除数据库"),
    (r"\btruncate\s+table\b", "禁止清空数据表"),
    (r"ASTRA_SECRET_KEY", "禁止读取 / 落盘宿主密钥（D-17）"),
    (r"subprocess|os\.system|os\.popen", "禁止在沙箱代码内直调宿主进程"),
)


def _scan(text: str, patterns: Iterable[tuple[str, str]], *, subject: str, payload: str) -> None:
    """按模式扫描文本，命中即抛 ``PERMISSION_DENIED``。"""
    for pattern, reason in patterns:
        if re.search(pattern, text, re.IGNORECASE):
            raise permission_denied(reason, subject=subject, payload=payload)


def check_command(command: str | Sequence[str]) -> None:
    """校验 shell 命令（危险动作清单 D-01 / D-02 / D-05 / D-14 / D-15）。

    Raises:
        DomainError: 命中危险模式（``PERMISSION_DENIED``）。
    """
    text = command if isinstance(command, str) else " ".join(str(part) for part in command)
    _scan(text, _DANGEROUS_COMMAND_PATTERNS, subject="shell", payload=text)


def check_git_command(args: Sequence[str]) -> None:
    """校验 git 子命令（危险动作清单 D-03 / D-04）。

    Raises:
        DomainError: 命中危险模式（``PERMISSION_DENIED``）。
    """
    text = " ".join(str(part) for part in args)
    _scan(text, _DANGEROUS_GIT_PATTERNS, subject="git", payload=text)


def check_python_code(code: str) -> None:
    """校验 Python 代码片段（危险动作清单 D-05 / D-17 / D-18）。

    Raises:
        DomainError: 命中危险模式（``PERMISSION_DENIED``）。
    """
    _scan(code, _DANGEROUS_PYTHON_PATTERNS, subject="python", payload=code)

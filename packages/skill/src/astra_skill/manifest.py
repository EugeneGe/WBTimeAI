"""``skill.yaml`` 包结构规范与 ``SkillManifest``（设计 §2.3；W2 裁定 R3）。

冻结的包结构（R3 §3.1）::

    <skill_pkg>/
    ├── skill.yaml          # 元数据（必填）
    ├── instructions.md     # 指令正文（默认入口；可被 skill.yaml.instructions 覆盖路径）
    ├── examples/           # 示例（可选目录，kind=example）
    ├── resources/          # 资源（可选目录，kind=file/template）
    └── scripts/            # 脚本资源（可选目录，kind=script；仅供 Tool/MCP 执行）

- :class:`SkillManifest`：``skill.yaml`` 的 `frozen` schema（R3 §3.2，**冻结字段**）；
- :class:`SkillResourceSpec`：包内资源规格（``kind`` / ``path``）；
- :class:`LoadedSkill`：装载结果（manifest + instructions + 资源清单）；
- :func:`parse_manifest` / :func:`load_skill_package`。

🔴 本模块**零 Web / ORM**（受 ``test_phase2_domain_submodules_have_no_orm_or_web`` 覆盖——
   本文件在 ``astra_skill`` 根，仍只依赖标准库 + ``astra_core`` + ``pyyaml``）。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from astra_core import DomainError, ErrorCode

__all__ = [
    "SKILL_NAME_PATTERN",
    "DEFAULT_INSTRUCTIONS_FILE",
    "DEFAULT_RESOURCES_DIR",
    "DEFAULT_EXAMPLES_DIR",
    "DEFAULT_SCRIPTS_DIR",
    "SkillManifest",
    "SkillResourceSpec",
    "LoadedSkill",
    "parse_manifest",
    "load_skill_package",
]

#: Skill 名合法模式（小型标识符；R3 §3.2）。
SKILL_NAME_PATTERN = re.compile(r"^[a-z0-9][a-z0-9._-]{1,63}$")

#: 语义化版本模式（``MAJOR.MINOR.PATCH``）。
_VERSION_PATTERN = re.compile(r"^(\d+)\.(\d+)\.(\d+)$")

#: 默认入口 / 资源目录名（R3 §3.1）。
DEFAULT_INSTRUCTIONS_FILE = "instructions.md"
DEFAULT_RESOURCES_DIR = "resources"
DEFAULT_EXAMPLES_DIR = "examples"
DEFAULT_SCRIPTS_DIR = "scripts"


@dataclass(frozen=True)
class SkillManifest:
    """``skill.yaml`` schema（R3 §3.2，**冻结字段**）。

    Attributes:
        name: 唯一键（``^[a-z0-9][a-z0-9._-]{1,63}$``）。
        version: 语义化版本（``MAJOR.MINOR.PATCH``）。
        display_name: 展示名（缺省 = ``name``）。
        description: 描述。
        category: 分类。
        entry: ``module:attr`` 或相对路径（``None`` = 纯指令包，无代码入口）。
        instructions: 指令文件相对路径（缺省 ``instructions.md``）。
        dependencies: 依赖声明（**字符串**，如 ``tool:filesystem``；**不 import**）。
        requires: 需要的 capability（对齐 §2.10.2 词汇表）。
        license: 许可标识（SPDX 或自定义）。
        resources: 资源根目录（缺省 ``resources/``）。
        examples: 示例根目录（缺省 ``examples/``）。
        scripts: 脚本根目录（缺省 ``scripts/``）。
        min_astra_version: 兼容下限（Marketplace 校验用）。
    """

    name: str
    version: str
    display_name: str = ""
    description: str = ""
    category: str = ""
    entry: str | None = None
    instructions: str = DEFAULT_INSTRUCTIONS_FILE
    dependencies: tuple[str, ...] = ()
    requires: tuple[str, ...] = ()
    license: str = ""
    resources: str = DEFAULT_RESOURCES_DIR
    examples: str = DEFAULT_EXAMPLES_DIR
    scripts: str = DEFAULT_SCRIPTS_DIR
    min_astra_version: str = ""


@dataclass(frozen=True)
class SkillResourceSpec:
    """包内资源规格（相对路径 + 种类 + 存储键）。

    Attributes:
        path: 包内相对路径（如 ``scripts/run.py``）。
        kind: 资源种类（``file`` / ``example`` / ``script`` / ``template``）。
        storage_key: ``Storage`` 对象键（``skills/{skill_id}/{version}/{path}``；装载期
            尚不知 ``skill_id``，故默认 ``None``，发布时补齐）。
    """

    path: str
    kind: str = "file"
    storage_key: str | None = None


@dataclass(frozen=True)
class LoadedSkill:
    """装载结果（manifest + 指令正文 + 资源清单 + 来源）。

    Attributes:
        manifest: 解析出的 :class:`SkillManifest`。
        instructions: 指令正文（``instructions.md`` 内容）。
        source: 来源（``builtin`` / ``plugin`` / ``workspace``，**字符串**；避免与
            ``registry.SkillSource`` 的循环依赖）。
        root: 包根目录（字符串，可空）。
        resources: 资源清单。
    """

    manifest: SkillManifest
    instructions: str = ""
    source: str = "builtin"
    root: str | None = None
    resources: tuple[SkillResourceSpec, ...] = field(default_factory=tuple)

    @property
    def name(self) -> str:
        """Skill 名（``manifest.name`` 便捷访问）。"""
        return self.manifest.name

    @property
    def version(self) -> str:
        """Skill 版本（``manifest.version`` 便捷访问）。"""
        return self.manifest.version


def _validation_error(message: str, **data: Any) -> DomainError:
    """构造统一 ``VALIDATION_ERROR``（复用既有错误码，不新增）。"""
    return DomainError(message, code=ErrorCode.VALIDATION_ERROR, data=dict(data))


def _validate_name(name: Any) -> str:
    if not isinstance(name, str) or not SKILL_NAME_PATTERN.match(name):
        raise _validation_error("skill.yaml: name 缺失或非法", field="name", value=name)
    return name


def _validate_version(version: Any) -> str:
    if not isinstance(version, str) or not _VERSION_PATTERN.match(version):
        raise _validation_error("skill.yaml: version 缺失或非语义化版本", field="version")
    return version


def version_key(version: str) -> tuple[int, int, int]:
    """把语义化版本解析为可比较的元组（非法版本回退 ``(0,0,0)``）。"""
    match = _VERSION_PATTERN.match(str(version))
    if not match:
        return (0, 0, 0)
    return (int(match.group(1)), int(match.group(2)), int(match.group(3)))


def _as_str_tuple(value: Any) -> tuple[str, ...]:
    """把 YAML 列表字段归一化为字符串元组。"""
    if not value:
        return ()
    if isinstance(value, str):
        return (value,)
    return tuple(str(item) for item in value)


def manifest_from_dict(data: dict[str, Any]) -> SkillManifest:
    """由 ``skill.yaml`` 解析出的字典构造并校验 :class:`SkillManifest`。

    Raises:
        DomainError: 缺 ``name`` / ``version`` 或取值非法（``VALIDATION_ERROR``）。
    """
    if not isinstance(data, dict):
        raise _validation_error("skill.yaml 顶层须为映射", field="skill")
    name = _validate_name(data.get("name"))
    version = _validate_version(data.get("version"))
    return SkillManifest(
        name=name,
        version=version,
        display_name=str(data.get("display_name") or name),
        description=str(data.get("description") or ""),
        category=str(data.get("category") or ""),
        entry=(str(data["entry"]) if data.get("entry") else None),
        instructions=str(data.get("instructions") or DEFAULT_INSTRUCTIONS_FILE),
        dependencies=_as_str_tuple(data.get("dependencies")),
        requires=_as_str_tuple(data.get("requires")),
        license=str(data.get("license") or ""),
        resources=str(data.get("resources") or DEFAULT_RESOURCES_DIR),
        examples=str(data.get("examples") or DEFAULT_EXAMPLES_DIR),
        scripts=str(data.get("scripts") or DEFAULT_SCRIPTS_DIR),
        min_astra_version=str(data.get("min_astra_version") or ""),
    )


def parse_manifest(path: Path) -> SkillManifest:
    """解析 ``skill.yaml``（``path`` 指向该文件）。

    Raises:
        DomainError: 文件不存在、YAML 非法或字段校验失败（``VALIDATION_ERROR``）。
    """
    import yaml  # 函数级延迟导入（保包可导入性）

    target = Path(path)
    if not target.is_file():
        raise _validation_error("skill.yaml 不存在", path=str(target))
    try:
        raw = yaml.safe_load(target.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:  # pragma: no cover - 非法 YAML
        raise _validation_error("skill.yaml 解析失败", path=str(target)) from exc
    return manifest_from_dict(raw or {})


def _scan_directory(root: Path, *, kind: str) -> tuple[SkillResourceSpec, ...]:
    """扫描目录下的全部文件为 :class:`SkillResourceSpec`（相对路径）。"""
    if not root.is_dir():
        return ()
    specs: list[SkillResourceSpec] = []
    for child in sorted(root.rglob("*")):
        if child.is_file():
            relative = child.relative_to(root.parent).as_posix()
            specs.append(SkillResourceSpec(path=relative, kind=kind))
    return tuple(specs)


def load_skill_package(directory: Path, *, source: str = "builtin") -> LoadedSkill:
    """从包目录装载一个 Skill（``skill.yaml`` + ``instructions`` + 资源清单）。

    Args:
        directory: Skill 包根目录。
        source: 来源（``builtin`` / ``plugin`` / ``workspace``）。

    Returns:
        :class:`LoadedSkill`。

    Raises:
        DomainError: 目录不存在 / ``skill.yaml`` 缺失或非法（``VALIDATION_ERROR``）。
    """
    root = Path(directory)
    if not root.is_dir():
        raise _validation_error("Skill 包目录不存在", path=str(root))
    manifest = parse_manifest(root / "skill.yaml")
    instructions_path = root / (manifest.instructions or DEFAULT_INSTRUCTIONS_FILE)
    instructions = (
        instructions_path.read_text(encoding="utf-8") if instructions_path.is_file() else ""
    )
    resources: list[SkillResourceSpec] = []
    resources.extend(_scan_directory(root / manifest.examples, kind="example"))
    resources.extend(_scan_directory(root / manifest.resources, kind="file"))
    resources.extend(_scan_directory(root / manifest.scripts, kind="script"))
    return LoadedSkill(
        manifest=manifest,
        instructions=instructions,
        source=source,
        root=str(root),
        resources=tuple(resources),
    )

"""``/agent-studio/marketplace`` API 集成测试（W8 / T2-44；设计 §2.12 / §2.13.1）。

覆盖：

- ``POST /import`` 预检（``confirm=false``）→ 元数据、**不落库**；
- ``POST /import`` 执行（``confirm=true``）→ 落库、返回 ``IMPORTED``；
- ``POST /import`` 拒绝路径：``expected_sha256`` 不匹配 / ``core_compat`` 越界 /
  敏感明文命中 → ``VALIDATION_ERROR``（HTTP 422），**无半成品**；
- ``POST /import`` 幂等（同包重复导入摘要一致，不重复建资源）/ 同名同版本异摘要
  → ``CONFLICT``（HTTP 409）；
- ``GET /export`` → **规范化 yaml 全文** + 摘要；
- **统一响应壳** ``{code, message, data, request_id}``；
- 权限拒绝 → ``PERMISSION_DENIED``（HTTP 403）。
"""

from __future__ import annotations

from typing import Any

from astra_plugin.marketplace import (
    DEFAULT_CORE_VERSION,
    build_manifest,
    canonical_dump,
    manifest_to_dict,
)

#: 测试用包名（满足 ``NAME_PATTERN``）。
_SKILL_NAME = "mp-skill"

#: 导入 / 导出端点前缀。
_IMPORT = "/api/v1/agent-studio/marketplace/import"
_EXPORT = "/api/v1/agent-studio/marketplace/export"


def _data(response: Any) -> Any:
    """从统一响应壳取 ``data``。"""
    body = response.json()
    assert "data" in body, response.text
    return body["data"]


def _skill_package_yaml(
    *,
    name: str = _SKILL_NAME,
    version: str = "1.0.0",
    instructions: str = "review the diff",
    core_compat: str | None = None,
) -> str:
    """构造一个合法的 skill 市场包 yaml（清单字段 + ``resource``）。"""
    resource = {
        "name": name,
        "version": version,
        "display_name": "Marketplace Skill",
        "description": "imported demo skill",
        "category": "quality",
        "instructions": instructions,
    }
    manifest = build_manifest(
        kind="skill",
        name=name,
        version=version,
        manifest_path="skill.yaml",
        core_compat=core_compat or f">={DEFAULT_CORE_VERSION}",
        author="alice",
        license="MIT",
        artifact_sha256="",
    )
    bundle = manifest_to_dict(manifest)
    bundle["resource"] = resource
    return canonical_dump(bundle)


def _import(
    client: Any,
    headers: dict[str, str],
    package_yaml: str,
    *,
    confirm: bool,
    expected_sha256: str | None = None,
) -> Any:
    """向 ``POST /import`` 发起一次请求（可选 ``expected_sha256``）。"""
    payload: dict[str, Any] = {"package_yaml": package_yaml, "confirm": confirm}
    if expected_sha256 is not None:
        payload["expected_sha256"] = expected_sha256
    return client.post(_IMPORT, headers=headers, json=payload)


def _skill_id(client: Any, headers: dict[str, str], name: str = _SKILL_NAME) -> str:
    """经 ``GET /skills`` 取某 Skill 的 id（供导出）。"""
    listed = _data(client.get("/api/v1/skills", headers=headers))
    match = next((item for item in listed if item["name"] == name), None)
    assert match is not None, f"Skill 未落库：{name}"
    return str(match["id"])


# -- 预检 / 执行 -------------------------------------------------------------


def test_import_preview_returns_metadata_without_persisting(
    client: Any, auth_headers: dict[str, str]
) -> None:
    """预检（``confirm=false``）返回元数据且**不落库**。"""
    response = _import(client, auth_headers, _skill_package_yaml(), confirm=False)
    assert response.status_code == 200, response.text
    data = _data(response)
    assert data["status"] == "PREVIEW"
    assert data["kind"] == "skill"
    assert data["name"] == _SKILL_NAME
    assert data["version"] == "1.0.0"
    assert data["core_compat"] == f">={DEFAULT_CORE_VERSION}"
    assert data["dependencies"] == []
    assert data["manifest_path"] == "skill.yaml"
    assert data["signature_present"] is False

    listed = _data(client.get("/api/v1/skills", headers=auth_headers))
    assert all(item["name"] != _SKILL_NAME for item in listed)


def test_import_execute_persists_resource(client: Any, auth_headers: dict[str, str]) -> None:
    """执行（``confirm=true``）返回 ``IMPORTED`` 并落库。"""
    response = _import(client, auth_headers, _skill_package_yaml(), confirm=True)
    assert response.status_code == 200, response.text
    data = _data(response)
    assert data["status"] == "IMPORTED"
    assert data["kind"] == "skill"
    assert data["name"] == _SKILL_NAME
    assert data["version"] == "1.0.0"
    assert data["digest"]

    listed = _data(client.get("/api/v1/skills", headers=auth_headers))
    assert any(item["name"] == _SKILL_NAME for item in listed)


def test_import_same_digest_is_idempotent(client: Any, auth_headers: dict[str, str]) -> None:
    """同包重复导入：摘要一致、**不重复建资源**（``existing_digest`` 幂等）。"""
    package = _skill_package_yaml()
    first = _import(client, auth_headers, package, confirm=True)
    second = _import(client, auth_headers, package, confirm=True)
    assert first.status_code == 200, first.text
    assert second.status_code == 200, second.text
    assert _data(first)["digest"] == _data(second)["digest"]

    names = [item["name"] for item in _data(client.get("/api/v1/skills", headers=auth_headers))]
    assert names.count(_SKILL_NAME) == 1


# -- 拒绝路径（无半成品） -----------------------------------------------------


def test_import_rejects_sha256_mismatch(client: Any, auth_headers: dict[str, str]) -> None:
    """``expected_sha256`` 不匹配 → ``VALIDATION_ERROR``（422）且**不落库**。"""
    response = _import(
        client, auth_headers, _skill_package_yaml(), confirm=True, expected_sha256="0" * 64
    )
    assert response.status_code == 422, response.text
    assert response.json()["code"] == "VALIDATION_ERROR"

    listed = _data(client.get("/api/v1/skills", headers=auth_headers))
    assert all(item["name"] != _SKILL_NAME for item in listed)


def test_import_rejects_incompatible_core_compat(client: Any, auth_headers: dict[str, str]) -> None:
    """``core_compat`` 越界 → ``VALIDATION_ERROR``（422）。"""
    response = _import(
        client, auth_headers, _skill_package_yaml(core_compat=">=9.9.9"), confirm=False
    )
    assert response.status_code == 422, response.text
    assert response.json()["code"] == "VALIDATION_ERROR"


def test_import_rejects_sensitive_plaintext(client: Any, auth_headers: dict[str, str]) -> None:
    """敏感明文命中 → ``VALIDATION_ERROR``（422）且**不泄漏明文**。"""
    response = _import(
        client,
        auth_headers,
        _skill_package_yaml(instructions="sk-ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"),
        confirm=True,
    )
    assert response.status_code == 422, response.text
    body = response.json()
    assert body["code"] == "VALIDATION_ERROR"
    assert "sk-ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789" not in response.text


def test_import_same_version_different_content_conflicts(
    client: Any, auth_headers: dict[str, str]
) -> None:
    """同名同版本异摘要 → ``CONFLICT``（409；R13）。"""
    first = _import(
        client,
        auth_headers,
        _skill_package_yaml(version="2.0.0", instructions="first"),
        confirm=True,
    )
    assert first.status_code == 200, first.text
    conflict = _import(
        client,
        auth_headers,
        _skill_package_yaml(version="2.0.0", instructions="second"),
        confirm=True,
    )
    assert conflict.status_code == 409, conflict.text
    assert conflict.json()["code"] == "CONFLICT"


# -- 导出 --------------------------------------------------------------------


def test_export_returns_normalized_yaml(client: Any, auth_headers: dict[str, str]) -> None:
    """导出已落地资源为**规范化 yaml 全文**（键序 / LF / 恰好一个尾换行）。"""
    assert _import(client, auth_headers, _skill_package_yaml(), confirm=True).status_code == 200
    skill_id = _skill_id(client, auth_headers)

    response = client.get(_EXPORT, headers=auth_headers, params={"kind": "skill", "id": skill_id})
    assert response.status_code == 200, response.text
    data = _data(response)
    assert data["kind"] == "skill"
    assert data["id"] == skill_id
    assert data["digest"]

    yaml_text = data["yaml"]
    assert yaml_text.endswith("\n")
    assert not yaml_text.endswith("\n\n")
    assert "kind: skill" in yaml_text
    assert f"name: {_SKILL_NAME}" in yaml_text


def test_export_unknown_kind_rejected(client: Any, auth_headers: dict[str, str]) -> None:
    """未知资源种类 → ``VALIDATION_ERROR``（422）。"""
    response = client.get(_EXPORT, headers=auth_headers, params={"kind": "bogus", "id": "x"})
    assert response.status_code == 422, response.text
    assert response.json()["code"] == "VALIDATION_ERROR"


# -- 统一响应壳 / 权限 -------------------------------------------------------


def test_response_shell_envelope(client: Any, auth_headers: dict[str, str]) -> None:
    """成功响应遵循统一响应壳 ``{code, message, data, request_id}``。"""
    response = _import(client, auth_headers, _skill_package_yaml(), confirm=False)
    assert response.status_code == 200, response.text
    body = response.json()
    assert {"code", "message", "data", "request_id"}.issubset(body.keys())
    assert body["code"] == 0
    assert body["message"] == "ok"
    assert body["request_id"]
    assert response.headers.get("X-Request-Id") == body["request_id"]


def test_import_requires_permission(client: Any, permissionless_headers: dict[str, str]) -> None:
    """无权限用户导入 → ``PERMISSION_DENIED``（403）。"""
    response = _import(client, permissionless_headers, _skill_package_yaml(), confirm=False)
    assert response.status_code == 403, response.text
    assert response.json()["code"] == "PERMISSION_DENIED"


def test_export_requires_permission(client: Any, permissionless_headers: dict[str, str]) -> None:
    """无权限用户导出 → ``PERMISSION_DENIED``（403）。"""
    response = client.get(
        _EXPORT, headers=permissionless_headers, params={"kind": "skill", "id": "x"}
    )
    assert response.status_code == 403, response.text
    assert response.json()["code"] == "PERMISSION_DENIED"

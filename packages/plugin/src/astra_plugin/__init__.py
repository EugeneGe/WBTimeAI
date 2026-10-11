"""Astra AI Plugin 抽象包（``astra_plugin``）——**骨架占位**。

设计 §2.14 / §2.14.1：承载 **8 个 ExtensionPoint 契约**（``auth_provider`` /
``policy_engine`` / ``audit_sink`` / ``secret_provider`` / ``model_gateway`` /
``model_provider`` / ``connector`` / ``ui_extension``）+ ``loader`` / ``registry``。

🔴 W1（T2-01）**仅建骨架**：本文件**只做占位导出**；契约实现归 **T2-04 起**。

- 包性质：**抽象包（零 ORM）**——不得 import ``sqlalchemy`` / ``alembic`` /
  ``astra_database``（W1 裁定 §2.2 / §2.3）；``plugin`` 表落 ``astra_database``，
  经**注入**仓储使用；
- 骨架期 deps：``astra-common`` / ``astra-core`` / ``astra-domain``。
"""

from __future__ import annotations

__all__: list[str] = []

"""Astra AI 配置层（``astra_config``）。

- :class:`~astra_config.settings.Settings`：统一配置模型（``ASTRA_*``）
- :func:`~astra_config.loader.get_settings`：进程级配置单例（ENV → config.yaml → 默认）
- :func:`~astra_config.providers.build_providers`：**Provider 自动装配（决策 D4）**
"""

from __future__ import annotations

from .defaults import (
    DEFAULT_DATABASE_URL,
    DEFAULT_FEATURE_FLAGS,
    DEFAULT_MODE,
)
from .feature_flags import (
    FEATURE_FLAGS,
    FeatureFlagDefinition,
    FeatureFlagService,
    FeatureFlagStore,
    feature_flag_defaults,
    feature_flag_names,
    is_known_feature_flag,
)
from .loader import (
    get_settings,
    load_yaml_config,
    reset_settings_cache,
    resolve_config_file,
)
from .providers import DatabaseProvider, Providers, build_providers
from .settings import (
    AuditSettings,
    CapabilitySettings,
    EgressSettings,
    MemorySettings,
    ObservabilitySettings,
    RetentionSettings,
    Settings,
)

__all__ = [
    "Settings",
    "ObservabilitySettings",
    "EgressSettings",
    "AuditSettings",
    "CapabilitySettings",
    "MemorySettings",
    "RetentionSettings",
    "get_settings",
    "reset_settings_cache",
    "load_yaml_config",
    "resolve_config_file",
    "Providers",
    "DatabaseProvider",
    "build_providers",
    "DEFAULT_MODE",
    "DEFAULT_DATABASE_URL",
    # Feature Flag（T0-21 / D7）
    "FEATURE_FLAGS",
    "DEFAULT_FEATURE_FLAGS",
    "FeatureFlagDefinition",
    "FeatureFlagService",
    "FeatureFlagStore",
    "feature_flag_defaults",
    "feature_flag_names",
    "is_known_feature_flag",
]

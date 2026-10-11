"""Astra AI HTTP API（``astra_api``）。"""

from __future__ import annotations

__version__ = "0.4.0"

from astra_api.main import create_app  # noqa: E402

__all__ = ["create_app", "__version__"]

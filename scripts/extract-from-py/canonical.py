"""Canonical serialisation shared by the C-04 / C-05 exporters.

The frozen baseline is written in **one** canonical form, identical to the one
pinned by :mod:`export_openapi` (C-02):

``json.dumps(document, ensure_ascii=False, indent=2, sort_keys=True) + "\\n"``

That is: object keys sorted, two-space indent, CJK text kept verbatim (never
``\\uXXXX``), UTF-8 on disk, exactly one trailing newline.

``sort_keys`` only affects **object** members -- array order (for example the
19-entry SSE channel list) is preserved, which is what the channel order
contract relies on.

This module is deliberately *not* named ``export_*.py`` so that ``run.py`` never
treats it as an exporter.  It exists so the three new exporters share one
serialisation implementation instead of re-deriving it.

Only the Python standard library is used here.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

import hashes

__all__ = [
    "INDENT",
    "dumps",
    "digest_text",
    "write_text",
    "write_document",
]

#: Indent width of the canonical form.
INDENT = 2


def dumps(document: Any) -> str:
    """Serialise ``document`` in the pinned canonical form.

    Args:
        document: Any JSON-serialisable object (dict / list / scalar).

    Returns:
        UTF-8 encodable text with exactly one trailing ``\\n``.
    """
    return json.dumps(document, ensure_ascii=False, indent=INDENT, sort_keys=True) + "\n"


def digest_text(text: str) -> str:
    """Return the hex SHA-256 of ``text`` encoded as UTF-8."""
    return hashes.sha256_bytes(text.encode("utf-8"))


def write_text(path: str | Path, text: str) -> Path:
    """Write ``text`` verbatim as UTF-8 bytes (newlines untouched).

    Parent directories are created when missing.  ``write_bytes`` is used on
    purpose: ``Path.write_text`` would translate ``\\n`` on Windows.

    Args:
        path: Target file path.
        text: Exact file content.

    Returns:
        The path that was written.
    """
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(text.encode("utf-8"))
    return target


def write_document(path: str | Path, document: Mapping[str, Any] | list[Any]) -> tuple[Path, str]:
    """Serialise ``document`` canonically and write it.

    Args:
        path: Target file path.
        document: JSON document to freeze.

    Returns:
        ``(path, text)`` so callers can report a digest without re-reading.
    """
    text = dumps(document)
    return write_text(path, text), text

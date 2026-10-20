"""``contracts/manifest.sha256`` generation and verification.

The manifest is the integrity ledger of the frozen contract baseline: one line
per artifact, ``<sha256><two spaces><relative/posix/path>``, sorted by path so
the file itself is byte-stable.

Verification (:func:`verify_manifest`) compares the recorded digest against the
bytes currently on disk and additionally reports unrecorded files, so a stray or
forgotten artifact cannot slip in unnoticed.  Neither generation nor
verification touches the legacy tree: ``check`` must keep working after
``D:/WBT/WBTimeAI_old`` is gone.

Only the Python standard library is used here.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Iterable, NamedTuple

__all__ = [
    "MANIFEST_NAME",
    "ManifestEntry",
    "ManifestVerification",
    "sha256_bytes",
    "sha256_file",
    "iter_artifact_files",
    "build_manifest_text",
    "write_manifest",
    "parse_manifest",
    "verify_manifest",
]

#: File name of the ledger, relative to the contracts directory.
MANIFEST_NAME = "manifest.sha256"

#: Separator used by ``sha256sum``: exactly two spaces.
_SEPARATOR = "  "


class ManifestEntry(NamedTuple):
    """One manifest line."""

    digest: str
    relative_path: str


class ManifestVerification(NamedTuple):
    """Outcome of :func:`verify_manifest`."""

    ok: bool
    checked: int
    problems: list[str]
    unrecorded: list[str]


def sha256_bytes(payload: bytes) -> str:
    """Return the hex SHA-256 digest of ``payload``."""
    return hashlib.sha256(payload).hexdigest()


def sha256_file(path: str | Path) -> str:
    """Return the hex SHA-256 digest of the file at ``path``.

    Raises:
        FileNotFoundError: If ``path`` is not an existing regular file.
    """
    target = Path(path)
    digest = hashlib.sha256()
    with target.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 128), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _is_ignorable(path: Path) -> bool:
    """Return ``True`` for entries that must never enter the ledger."""
    name = path.name
    if name == MANIFEST_NAME:
        return True
    if name.endswith((".pyc", ".pyo", ".tmp", ".bak")):
        return True
    if "__pycache__" in path.parts:
        return True
    return False


def iter_artifact_files(directory: str | Path) -> list[Path]:
    """List contract artifacts under ``directory`` in deterministic order.

    Args:
        directory: Contract output directory.

    Returns:
        Files sorted by POSIX relative path; the manifest and caches excluded.
    """
    root = Path(directory)
    if not root.is_dir():
        return []
    files = [path for path in root.rglob("*") if path.is_file() and not _is_ignorable(path)]
    return sorted(files, key=lambda path: path.relative_to(root).as_posix())


def build_manifest_text(directory: str | Path) -> str:
    """Render manifest content for ``directory`` (trailing newline included)."""
    root = Path(directory)
    lines: list[str] = []
    for path in iter_artifact_files(root):
        relative = path.relative_to(root).as_posix()
        lines.append(f"{sha256_file(path)}{_SEPARATOR}{relative}")
    if not lines:
        return ""
    return "\n".join(lines) + "\n"


def write_manifest(directory: str | Path, name: str = MANIFEST_NAME) -> Path:
    """Regenerate the ledger file and return its path.

    Args:
        directory: Contract output directory (created when missing).
        name: Manifest file name, defaults to :data:`MANIFEST_NAME`.
    """
    root = Path(directory)
    root.mkdir(parents=True, exist_ok=True)
    target = root / name
    target.write_text(build_manifest_text(root), encoding="utf-8", newline="\n")
    return target


def parse_manifest(text: str) -> list[ManifestEntry]:
    """Parse manifest text, ignoring blank lines and ``#`` comments.

    Args:
        text: Raw manifest content.

    Returns:
        Parsed entries in file order.

    Raises:
        ValueError: If a non-comment line is malformed.
    """
    entries: list[ManifestEntry] = []
    for lineno, raw in enumerate(text.splitlines(), start=1):
        line = raw.rstrip()
        if not line or line.lstrip().startswith("#"):
            continue
        parts = line.split(None, 1)
        if len(parts) != 2 or len(parts[0]) != 64:
            raise ValueError(f"malformed manifest line {lineno}: {raw!r}")
        entries.append(ManifestEntry(parts[0].lower(), parts[1].strip()))
    return entries


def verify_manifest(directory: str | Path, name: str = MANIFEST_NAME) -> ManifestVerification:
    """Verify every recorded artifact byte-for-byte.

    Args:
        directory: Contract output directory.
        name: Manifest file name.

    Returns:
        A :class:`ManifestVerification`; ``ok`` is true only when the manifest
        exists, no recorded file is missing or modified, and no file on disk is
        missing from the ledger.
    """
    root = Path(directory)
    manifest_path = root / name
    if not manifest_path.is_file():
        return ManifestVerification(
            ok=False,
            checked=0,
            problems=[f"manifest not found: {manifest_path.as_posix()}"],
            unrecorded=[],
        )

    try:
        entries = parse_manifest(manifest_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        return ManifestVerification(ok=False, checked=0, problems=[str(error)], unrecorded=[])

    problems: list[str] = []
    recorded: set[str] = set()
    for entry in entries:
        recorded.add(entry.relative_path)
        target = root / entry.relative_path
        if not target.is_file():
            problems.append(f"missing: {entry.relative_path}")
            continue
        actual = sha256_file(target)
        if actual != entry.digest:
            problems.append(f"modified: {entry.relative_path} expected {entry.digest[:12]} got {actual[:12]}")

    unrecorded = [
        path.relative_to(root).as_posix()
        for path in iter_artifact_files(root)
        if path.relative_to(root).as_posix() not in recorded
    ]
    for relative in unrecorded:
        problems.append(f"unrecorded: {relative}")

    return ManifestVerification(
        ok=not problems,
        checked=len(entries),
        problems=problems,
        unrecorded=unrecorded,
    )

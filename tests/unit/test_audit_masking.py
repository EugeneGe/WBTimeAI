"""审计 ``metadata`` 掩码单测（设计 §2.18.1：敏感值一律掩码，无明文）。"""

from __future__ import annotations

from astra_application.services import mask_sensitive_metadata

_PLAINTEXT_KEY = "sk-abcdefghijklmnop1234567890"


def _contains_plaintext(value: object) -> bool:
    return _PLAINTEXT_KEY in repr(value)


def test_masks_sensitive_key_value() -> None:
    masked = mask_sensitive_metadata({"api_key": _PLAINTEXT_KEY})
    assert not _contains_plaintext(masked)
    assert masked["api_key"] != _PLAINTEXT_KEY


def test_masks_nested_sensitive_keys() -> None:
    masked = mask_sensitive_metadata(
        {"auth": {"password": "hunter2", "authorization": "Bearer " + _PLAINTEXT_KEY}}
    )
    assert not _contains_plaintext(masked)
    assert masked["auth"]["password"] != "hunter2"


def test_masks_secret_pattern_in_benign_key() -> None:
    masked = mask_sensitive_metadata({"note": f"leaked {_PLAINTEXT_KEY} here"})
    assert not _contains_plaintext(masked)
    assert "leaked" in masked["note"]  # 非敏感内容保留


def test_preserves_benign_fields_and_scalars() -> None:
    source = {"path": "/workspace/a.txt", "count": 3, "ok": True, "items": ["a", "b"]}
    masked = mask_sensitive_metadata(source)
    assert masked == source


def test_masks_within_lists() -> None:
    masked = mask_sensitive_metadata({"creds": [{"token": _PLAINTEXT_KEY}]})
    assert not _contains_plaintext(masked)

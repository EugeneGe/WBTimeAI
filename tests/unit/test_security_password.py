"""密码哈希单测（argon2id；明文不落库）。"""

from __future__ import annotations

from astra_security import PasswordHasher


def test_hash_and_verify() -> None:
    hasher = PasswordHasher()
    hashed = hasher.hash("s3cret-pass")
    assert hashed != "s3cret-pass"
    assert hasher.verify("s3cret-pass", hashed) is True
    assert hasher.verify("wrong-pass", hashed) is False


def test_plaintext_not_present_in_hash() -> None:
    hasher = PasswordHasher()
    hashed = hasher.hash("plain-text-would-leak")
    assert "plain-text-would-leak" not in hashed
    assert hashed.startswith("$argon2id$")


def test_salt_randomized() -> None:
    hasher = PasswordHasher()
    assert hasher.hash("same") != hasher.hash("same")


def test_verify_invalid_hash_returns_false() -> None:
    assert PasswordHasher().verify("x", "not-a-hash") is False

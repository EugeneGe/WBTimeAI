"""领域值对象纯单测（无框架依赖）。"""

from __future__ import annotations

import pytest
from astra_core import ValidationError
from astra_domain import Email, OrgSlug, PermissionCode, TenantSlug, Username


def test_email_normalizes_and_validates() -> None:
    email = Email("  Alice@Example.COM  ")
    assert email.value == "alice@example.com"
    assert str(email) == "alice@example.com"


def test_email_rejects_invalid() -> None:
    with pytest.raises(ValidationError):
        Email("not-an-email")
    with pytest.raises(ValidationError):
        Email("")
    with pytest.raises(ValidationError):
        Email("a@" + "x" * 400 + ".com")


def test_username_valid() -> None:
    assert str(Username("  bob_01  ")) == "bob_01"


def test_username_rejects_short_and_bad_chars() -> None:
    with pytest.raises(ValidationError):
        Username("ab")
    with pytest.raises(ValidationError):
        Username("bad name")


def test_slug_normalizes_and_validates() -> None:
    assert str(TenantSlug("  DEFAULT ")) == "default"
    assert str(OrgSlug("my-org")) == "my-org"


def test_slug_rejects_invalid() -> None:
    with pytest.raises(ValidationError):
        TenantSlug("-bad")
    with pytest.raises(ValidationError):
        OrgSlug("")


def test_permission_code_valid() -> None:
    assert str(PermissionCode("workspace:update")) == "workspace:update"
    assert str(PermissionCode("*")) == "*"


def test_permission_code_rejects_invalid() -> None:
    with pytest.raises(ValidationError):
        PermissionCode("workspace")
    with pytest.raises(ValidationError):
        PermissionCode("Workspace:Update")

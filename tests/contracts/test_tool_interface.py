"""首批 5 Tool 统一接口契约套件（``C-P1-02`` 同类口径）。

参数化 :data:`astra_tool.BUILTIN_TOOL_CLASSES`，断言：满足 ``Tool`` Protocol、``spec`` 结构完整、
入参 Schema 校验生效、``requires_sandbox`` 标注符合设计 §2.5.2。
"""

from __future__ import annotations

import pytest
from astra_core import ValidationError
from astra_tool import BUILTIN_TOOL_CLASSES, TOOL_RESOURCE, Tool, ToolContext

pytestmark = pytest.mark.contracts

_TOOL_CLASSES = list(BUILTIN_TOOL_CLASSES)


@pytest.mark.parametrize("tool_class", _TOOL_CLASSES, ids=lambda c: c.__name__)
def test_tool_satisfies_protocol(tool_class: type) -> None:
    tool = tool_class()
    assert isinstance(tool, Tool)
    assert callable(tool.execute)


@pytest.mark.parametrize("tool_class", _TOOL_CLASSES, ids=lambda c: c.__name__)
def test_spec_shape(tool_class: type) -> None:
    spec = tool_class().spec
    assert spec.metadata.name
    assert spec.metadata.display_name
    assert spec.input_schema.get("type") == "object"
    assert spec.permission.resource == TOOL_RESOURCE
    assert spec.tool_type == "builtin"


@pytest.mark.parametrize("tool_class", _TOOL_CLASSES, ids=lambda c: c.__name__)
def test_invalid_args_rejected(tool_class: type) -> None:
    tool = tool_class()
    with pytest.raises(ValidationError):
        tool.execute({"__unknown_field__": 1}, ToolContext())


def test_requires_sandbox_flags_match_design() -> None:
    flags = {
        tool_class().spec.metadata.name: tool_class().spec.requires_sandbox
        for tool_class in _TOOL_CLASSES
    }
    assert flags == {
        "filesystem": False,  # read/list 不过沙箱（write/delete 动作级过沙箱）
        "shell": True,
        "git": True,
        "http": False,
        "python": True,
    }

# -*- coding: utf-8 -*-
"""
模板池（agent_template_pool）+ @template_agent 装饰器的单测。

覆盖：
- register_template：类 / dict / 缺 name / 缺 cls / 覆盖
- activate_template：单实例、双键写入、KeyError
- deactivate_template / remove_template
- list_templates / get_template / is_active
- @template_agent 装饰器：name 缺省、uuid 缺省、overwrite=False
- BaseAgent 上的 4 个 builtin_tool：list_templates / activate_template / deactivate_template
  （register_template 留给代码侧，测试只验证占位返回）
"""
import pytest
from tangyuanAI.Agent_list import (
    activate_template,
    agent_list,
    agent_template_pool,
    deactivate_template,
    get_template,
    is_active,
    list_templates,
    register_template,
    remove_template,
    template_agent,
)


@pytest.fixture(autouse=True)
def _clean_pool():
    """每个用例前后清空池与 agent_list，避免互相污染。"""
    agent_template_pool.clear()
    agent_list.clear()
    yield
    agent_template_pool.clear()
    agent_list.clear()


# ---------------------------------------------------------------------------
# 工具类：只实现模板/Agent 必需的标记，绕过 __init__ 的网络探测
# ---------------------------------------------------------------------------
class _Tpl:
    """最朴素的"模板类"——不是 BaseAgent 子类，因此没有 __init__ 副作用。"""

    def __init__(self, name="tpl"):
        self.tag = f"{name}-instance"

    def hi(self) -> str:
        return f"hi {self.tag}"


def _register_basic(tpl_cls=None, name="tpl", uuid=None, description=None):
    """注册一个最小模板；不显式给 uuid 时，池内默认 uuid = name。"""
    cls = tpl_cls or _Tpl
    return register_template(
        cls,
        name=name,
        uuid=uuid,
        description=description,
    )


# ===========================================================================
# register_template
# ===========================================================================
def test_register_template_class_only_stores_class_no_instance():
    """仅入池：池里有 dict，agent_list 必须为空。"""
    _register_basic(name="tpl")
    assert "tpl" in agent_template_pool
    assert "tpl" not in agent_list
    tpl = agent_template_pool["tpl"]
    assert tpl["name"] == "tpl"
    assert tpl["cls"] is _Tpl
    assert tpl["uuid"] == "tpl"  # 缺省 uuid 用 name 顶替
    assert tpl["description"] is None


def test_register_template_with_explicit_uuid_and_description():
    tpl = _register_basic(
        name="writer", uuid="writer-uuid", description="写文章"
    )
    assert tpl["uuid"] == "writer-uuid"
    assert tpl["description"] == "写文章"


def test_register_template_accepts_dict():
    """dict 入参：cls 必须显式给出。"""
    tpl = register_template({
        "name": "from_dict",
        "cls": _Tpl,
        "uuid": "d-uuid",
    })
    assert tpl["name"] == "from_dict"
    assert tpl["cls"] is _Tpl
    assert tpl["uuid"] == "d-uuid"


def test_register_template_explicit_name_overrides_class_attribute():
    class WithName:
        name = "class_name"

        def __init__(self):
            pass

    tpl = register_template(WithName, name="override_name")
    # 池内模板名应被覆盖
    assert tpl["name"] == "override_name"
    # 注意：函数式 register_template 不会回写类属性 name（避免污染用户类）


def test_register_template_missing_name_raises():
    with pytest.raises(ValueError, match="必须提供 name"):
        register_template({"cls": _Tpl})


def test_register_template_missing_cls_raises():
    with pytest.raises(ValueError, match="没有提供 cls"):
        register_template({"name": "no_cls"})


def test_register_template_overwrite_true_by_default():
    _register_basic(name="tpl")
    # 默认 overwrite=True，重复注册应成功
    tpl = _register_basic(name="tpl", description="覆盖")
    assert tpl["description"] == "覆盖"


def test_register_template_overwrite_false_raises():
    _register_basic(name="tpl")
    with pytest.raises(ValueError, match="overwrite=False"):
        register_template(_Tpl, name="tpl", overwrite=False)


def test_register_template_keeps_original_class_attribute_name():
    """不带显式 name 时，模板名取 cls.name 或类名。"""
    class Coder:
        name = "coder"

        def __init__(self):
            pass

    register_template(Coder)
    assert "coder" in agent_template_pool
    tpl = agent_template_pool["coder"]
    assert tpl["cls"] is Coder


def test_register_template_uses_class_qualname_when_no_name_attr():
    class AnonAgent:
        def __init__(self):
            pass

    register_template(AnonAgent)
    assert "AnonAgent" in agent_template_pool


# ===========================================================================
# activate_template
# ===========================================================================
def test_activate_writes_dual_keys_to_agent_list():
    _register_basic(name="tpl", uuid="tpl-uuid")
    activate_template("tpl")
    inst = agent_list["tpl"]
    assert agent_list["tpl-uuid"] is inst  # 双键指向同一实例
    assert inst.tag == "tpl-instance"


def test_activate_returns_new_instance_each_time():
    _register_basic(name="tpl")
    a = activate_template("tpl")
    deactivate_template("tpl")
    b = activate_template("tpl")
    assert a is not b  # 重新激活应生成新实例


def test_activate_unknown_name_raises_keyerror():
    with pytest.raises(KeyError, match="不在 agent_template_pool"):
        activate_template("missing")


def test_activate_does_not_require_class_to_subclass_baseagent():
    """只要模板有 cls，激活时 cls() 即可，不强制要求是 BaseAgent 子类。"""
    _register_basic(name="tpl")
    inst = activate_template("tpl")
    assert isinstance(inst, _Tpl)
    assert inst.hi() == "hi tpl-instance"


# ===========================================================================
# deactivate_template / remove_template
# ===========================================================================
def test_deactivate_removes_instance_but_keeps_template():
    _register_basic(name="tpl")
    activate_template("tpl")
    assert is_active("tpl")
    assert deactivate_template("tpl") is True
    assert not is_active("tpl")
    assert "tpl" in agent_template_pool  # 模板仍保留


def test_deactivate_unknown_returns_false():
    assert deactivate_template("nope") is False


def test_remove_template_drops_both_pool_and_agent_list():
    _register_basic(name="tpl")
    activate_template("tpl")
    assert remove_template("tpl") is True
    assert "tpl" not in agent_template_pool
    assert "tpl" not in agent_list


def test_remove_template_unknown_returns_false():
    assert remove_template("nope") is False


# ===========================================================================
# list_templates / get_template / is_active
# ===========================================================================
def test_list_templates_reflects_active_state():
    _register_basic(name="a")
    _register_basic(name="b", uuid="b-uuid")
    activate_template("a")

    items = list_templates()
    by_name = {it["name"]: it for it in items}
    assert set(by_name) == {"a", "b"}
    assert by_name["a"]["active"] is True
    assert by_name["b"]["active"] is False
    assert by_name["a"]["uuid"] == "a"
    assert by_name["b"]["uuid"] == "b-uuid"


def test_list_templates_empty():
    assert list_templates() == []


def test_get_template_returns_dict_or_none():
    _register_basic(name="tpl")
    assert get_template("tpl") is not None
    assert get_template("tpl")["name"] == "tpl"
    assert get_template("missing") is None


def test_is_active_reflects_agent_list():
    _register_basic(name="tpl")
    assert is_active("tpl") is False
    activate_template("tpl")
    assert is_active("tpl") is True


# ===========================================================================
# @template_agent 装饰器
# ===========================================================================
def test_decorator_only_registers_no_instance():
    @template_agent("writer", uuid="writer-uuid", description="写文章")
    class Writer:
        def __init__(self):
            self.tag = "writer-instance"

    assert "writer" in agent_template_pool
    assert "writer" not in agent_list
    tpl = agent_template_pool["writer"]
    assert tpl["cls"] is Writer
    assert tpl["uuid"] == "writer-uuid"
    assert tpl["description"] == "写文章"


def test_decorator_uses_default_name_when_omitted():
    @template_agent()
    class NamedAgent:
        name = "named_via_class_attr"

        def __init__(self):
            pass

    assert "named_via_class_attr" in agent_template_pool


def test_decorator_uses_class_qualname_when_no_name_attr_and_no_arg():
    @template_agent()
    class AnonDecoratedAgent:
        def __init__(self):
            pass

    assert "AnonDecoratedAgent" in agent_template_pool


def test_decorator_activated_after_definition():
    @template_agent("tpl")
    class Tpl:
        def __init__(self):
            self.tag = "t-inst"

    inst = activate_template("tpl")
    assert isinstance(inst, Tpl)
    assert agent_list["tpl"] is inst


def test_decorator_overwrite_false_raises():
    @template_agent("dup")
    class First:
        def __init__(self):
            pass

    with pytest.raises(ValueError, match="overwrite=False"):
        @template_agent("dup", overwrite=False)
        class Second:
            def __init__(self):
                pass


# ===========================================================================
# BaseAgent 上的 4 个 builtin_tool
# ===========================================================================
def _make_baseagent_stub_cls():
    """动态构造 BaseAgent 子类，绕开 __init__ 的网络连通性测试等副作用。

    与 test_placeholder.py:test_collect_builtin_tools_picks_up_base_methods 同款做法：
    BaseAgent.__init_subclass__ 会自动把父类 @builtin_tool 的 meta 提升到子类，
    所以 collect_builtin_tools 能找到 4 个模板池工具。
    """
    from tangyuanAI.Agent_Base_ import Agent as BaseAgent

    class _Stub(BaseAgent):
        def __init__(self):  # noqa: D401 - 故意跳过 BaseAgent.__init__
            self.uuid = "stub-uuid"
            self.name = "stub"

    return _Stub


def test_baseagent_builtin_tool_schemas_are_collected():
    """BaseAgent 上的 4 个模板池 builtin_tool 应被自动收集到 schema。"""
    from tangyuanAI import tool_registry

    inst = _make_baseagent_stub_cls()()
    schemas = tool_registry.collect_builtin_tools(inst)
    names = {s["function"]["name"] for s in schemas}
    assert "list_templates" in names
    assert "activate_template" in names
    assert "deactivate_template" in names
    assert "register_template" in names


def test_baseagent_builtin_list_templates_returns_pool():
    inst = _make_baseagent_stub_cls()()

    # 空池
    assert "（暂无）" in inst.list_templates()

    # 放入一个并激活
    _register_basic(name="tpl", description="desc")
    activate_template("tpl")

    text = inst.list_templates()
    assert "tpl" in text
    assert "active=True" in text
    assert "desc" in text


def test_baseagent_builtin_list_templates_by_name():
    inst = _make_baseagent_stub_cls()()
    _register_basic(name="tpl", uuid="t-uuid", description="hi")

    text = inst.list_templates(name="tpl")
    assert "tpl" in text
    assert "t-uuid" in text
    assert "active=False" in text

    text_missing = inst.list_templates(name="nope")
    assert "不在 agent_template_pool" in text_missing


def test_baseagent_builtin_activate_template_writes_to_agent_list():
    inst = _make_baseagent_stub_cls()()
    _register_basic(name="tpl")

    msg = inst.activate_template("tpl")
    assert "已激活" in msg
    assert "tpl" in agent_list

    msg_missing = inst.activate_template("nope")
    assert "激活失败" in msg_missing


def test_baseagent_builtin_deactivate_template():
    inst = _make_baseagent_stub_cls()()
    _register_basic(name="tpl")
    activate_template("tpl")

    msg = inst.deactivate_template("tpl")
    assert "已反激活" in msg
    assert "tpl" not in agent_list
    assert "tpl" in agent_template_pool  # 模板仍在

    msg_missing = inst.deactivate_template("nope")
    assert "不在池中" in msg_missing


def test_baseagent_builtin_register_template_is_placeholder():
    """builtin_tool 没法传 Python 类，所以 register_template 是占位说明。"""
    inst = _make_baseagent_stub_cls()()
    text = inst.register_template("any_name", description="d")
    assert "Python 代码侧" in text
    # 必须**没有副作用**：池里不应多出 "any_name"
    assert "any_name" not in agent_template_pool

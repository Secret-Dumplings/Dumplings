"""reload_hooks 总线测试。"""
from __future__ import annotations

import pytest
from tangyuanAI import reload_hooks
from tangyuanAI.reload_hooks import (
    clear_reload_hooks,
    fire_reload,
    get_reload_hooks,
    register_reload_hook,
    unregister_reload_hook,
)


@pytest.fixture(autouse=True)
def _isolate_hooks():
    """每个测试前后隔离 _hooks，避免污染其它测试。"""
    saved = list(reload_hooks._hooks)
    reload_hooks._hooks.clear()
    yield
    reload_hooks._hooks.clear()
    reload_hooks._hooks.extend(saved)


def test_register_appends_to_hooks():
    def fn():
        pass

    register_reload_hook(fn)
    assert reload_hooks._hooks == [fn]


def test_register_returns_fn_for_decorator_use():
    @register_reload_hook
    def my_hook():
        return 42

    assert my_hook in reload_hooks._hooks
    assert my_hook() == 42


def test_unregister_existing_returns_true():
    def fn():
        pass

    register_reload_hook(fn)
    assert unregister_reload_hook(fn) is True
    assert fn not in reload_hooks._hooks


def test_unregister_missing_returns_false():
    def fn():
        pass

    assert unregister_reload_hook(fn) is False


def test_fire_reload_calls_all_hooks_in_order():
    calls: list[str] = []

    def append_a():
        calls.append("a")

    def append_b():
        calls.append("b")

    def append_c():
        calls.append("c")

    register_reload_hook(append_a)
    register_reload_hook(append_b)
    register_reload_hook(append_c)

    ok = fire_reload()

    assert calls == ["a", "b", "c"]
    assert ok == 3


def test_fire_reload_returns_success_count():
    def noop():
        pass

    register_reload_hook(noop)
    register_reload_hook(noop)
    assert fire_reload() == 2


def test_fire_reload_isolates_failing_hooks():
    calls: list[str] = []

    def append_a():
        calls.append("a")

    def boom():
        raise RuntimeError("boom")

    def append_c():
        calls.append("c")

    register_reload_hook(append_a)
    register_reload_hook(boom)
    register_reload_hook(append_c)

    ok = fire_reload()

    assert calls == ["a", "c"]
    assert ok == 2


def test_fire_reload_safe_against_concurrent_unregister():
    """某钩子内部 unregister 另一个钩子，snapshot 机制保证迭代不爆。"""
    victim_hits: list[str] = []

    def victim():
        victim_hits.append("hit")

    register_reload_hook(victim)

    def attacker():
        unregister_reload_hook(victim)

    register_reload_hook(attacker)

    ok = fire_reload()

    assert ok == 2
    assert victim_hits == ["hit"]
    assert victim not in reload_hooks._hooks


def test_clear_reload_hooks_empties_list():
    def noop():
        pass

    register_reload_hook(noop)
    register_reload_hook(noop)
    assert len(reload_hooks._hooks) == 2

    clear_reload_hooks()

    assert reload_hooks._hooks == []


def test_get_reload_hooks_returns_snapshot():
    def fn():
        pass

    register_reload_hook(fn)

    snap = get_reload_hooks()

    assert snap == [fn]
    snap.clear()
    assert reload_hooks._hooks == [fn]


def test_skill_module_exposes_reload_hook():
    """skill 模块应暴露 _on_reload_skill 函数（用作 reload 钩子注册项）。"""
    from tangyuanAI.skill import _on_reload_skill

    assert callable(_on_reload_skill)


def test_mcp_module_exposes_reload_hook():
    """mcp_bridge 模块应暴露 _on_reload_mcp 函数。"""
    from tangyuanAI.mcp_bridge import _on_reload_mcp

    assert callable(_on_reload_mcp)

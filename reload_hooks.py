# -*- coding: utf-8 -*-
"""系统级 reload 钩子总线。

任何外置依赖（skill / MCP / plugin / A2A / KB 等）都可以在模块加载时
调用 :func:`register_reload_hook` 注册自己的刷新逻辑；``agent.reload()``
会调用 :func:`fire_reload` 通知所有监听者各自刷新。

钩子失败互不影响：单个钩子抛错会被记录并跳过，其它钩子继续执行。

使用示例：

.. code-block:: python

    # 在子模块加载时注册
    from tangyuanAI.reload_hooks import register_reload_hook

    @register_reload_hook
    def _on_reload():
        my_module.refresh_state()

    # 用户也可以注册自己的钩子
    register_reload_hook(lambda: print("reload fired"))

    # 注销
    from tangyuanAI.reload_hooks import unregister_reload_hook
    unregister_reload_hook(_on_reload)
"""
from __future__ import annotations

from typing import Callable, List

from .logging_config import get_logger

logger = get_logger(__name__)

ReloadHook = Callable[[], None]

_hooks: List[ReloadHook] = []


def register_reload_hook(fn: ReloadHook) -> ReloadHook:
    """注册 reload 钩子；返回 ``fn`` 本身，可作装饰器使用。"""
    _hooks.append(fn)
    return fn


def unregister_reload_hook(fn: ReloadHook) -> bool:
    """注销 reload 钩子；返回是否成功（``False`` 表示 fn 未注册）。"""
    try:
        _hooks.remove(fn)
        return True
    except ValueError:
        return False


def fire_reload() -> int:
    """触发所有 reload 钩子；返回成功执行的钩子数。

    遍历 ``_hooks`` 的**快照**——避免某钩子在执行过程中调用
    :func:`unregister_reload_hook` 导致 ``RuntimeError: list changed size``。
    """
    snapshot = list(_hooks)
    ok = 0
    for fn in snapshot:
        try:
            fn()
            ok += 1
        except Exception as e:  # noqa: BLE001 — 故意吞所有异常，保证 reload 不被任何一个坏钩子阻断
            logger.warning(
                f"reload hook {getattr(fn, '__qualname__', repr(fn))} 失败：{e}"
            )
    return ok


def clear_reload_hooks() -> None:
    """清空所有钩子（仅测试用）。"""
    _hooks.clear()


def get_reload_hooks() -> List[ReloadHook]:
    """返回当前所有钩子的快照（仅测试 / 调试用）。"""
    return list(_hooks)

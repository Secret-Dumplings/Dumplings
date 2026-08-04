# -*- coding: utf-8 -*-
"""子模块测试 conftest：把 tests/ 加入 sys.path 以便 import _llm_mock。

全局状态隔离（v0.4.1+）：
测试运行过程中很多模块共享进程级单例（agent_queue / skill_registry /
persistence），如果不清理，跨测试的污染会导致间歇失败。autouse fixture 在每个
测试前后清理这些全局状态。
"""
import sys
from pathlib import Path

import pytest

_TESTS_DIR = Path(__file__).resolve().parent
if str(_TESTS_DIR) not in sys.path:
    sys.path.insert(0, str(_TESTS_DIR))


# ---------------------------------------------------------------------------
# 全局状态清理（autouse，每个测试前后都跑）
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _clean_global_state():
    """每个测试前后清理跨测试的全局可变状态。

    涉及：
    - agent_queue._default_queue：单例 AgentQueue（ask_for_help 用）
    - skill_registry._skills / _skill_dirs / _watchers
    - persistence.backends / enabled / key_strategy

    各测试文件可以叠加更细粒度的清理（agent_list / tool_registry）。
    """
    # ===== 清理前 =====
    try:
        from dumplingsAI.agent_queue import _default_queue
    except ImportError:
        _default_queue = None
    try:
        from dumplingsAI.skill import skill_registry
    except ImportError:
        skill_registry = None
    try:
        from dumplingsAI.persistence import backends
    except ImportError:
        backends = None
    try:
        from dumplingsAI.mcp_bridge import _global_session_pool
    except ImportError:
        _global_session_pool = None

    # 备份
    if _default_queue is not None:
        try:
            _default_queue.shutdown(timeout=2.0)
        except Exception:
            pass
    default_queue_backup = _default_queue
    skill_backup = (
        dict(skill_registry._skills),
        dict(skill_registry._skill_dirs),
        dict(skill_registry._watchers),
    ) if skill_registry is not None else ({}, {}, {})
    if backends is not None:
        backends_backup = (
            backends.enabled,
            backends.default_name,
            backends.key_strategy,
        )
    else:
        backends_backup = None

    # ===== 测试运行 =====
    yield

    # ===== 清理后（恢复原状 + 关闭队列） =====
    # 关掉默认队列（防止 worker 线程泄漏到下一个测试）
    if default_queue_backup is not None and _default_queue is not default_queue_backup:
        try:
            _default_queue.shutdown(timeout=2.0)
        except Exception:
            pass
    if _default_queue is not None and default_queue_backup is None:
        try:
            _default_queue.shutdown(timeout=2.0)
        except Exception:
            pass

    # 重置模块级单例
    import dumplingsAI.agent_queue as _aq
    _aq._default_queue = default_queue_backup

    if skill_registry is not None:
        skill_registry._skills.clear()
        skill_registry._skill_dirs.clear()
        skill_registry._watchers.clear()
        skill_registry._skills.update(skill_backup[0])
        skill_registry._skill_dirs.update(skill_backup[1])
        skill_registry._watchers.update(skill_backup[2])

    if backends is not None and backends_backup is not None:
        backends.enabled, backends.default_name, backends.key_strategy = backends_backup

    # 关掉 MCP 全局 session 池（防止 spawn 的 stdio 进程泄漏到下一个测试）
    if _global_session_pool is not None:
        import asyncio
        try:
            loop = asyncio.new_event_loop()
            loop.run_until_complete(_global_session_pool.close_all())
            loop.close()
        except Exception:
            pass

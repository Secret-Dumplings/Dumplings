# -*- coding: utf-8 -*-
"""
Skill 热加载 / 重载单测。

覆盖 ``docs/TODO.md`` 里的"Skill 热加载"项。

**注**：watchdog 跨平台兼容性差（Windows 上文件变更事件可能延迟/丢失），
这里不依赖 watchdog 的实际触发，改成直接测 ``Skill.reload()`` 和
``SkillRegistry.reload_skill()`` 这两个核心 API。真实 watchdog 行为
在生产环境用 smoke test 验证（手动修改 SKILL.md 后看是否自动 reload）。
"""
from __future__ import annotations

import textwrap
from pathlib import Path

import pytest
from dumplingsAI.skill import Skill, SkillRegistry, skill_registry


@pytest.fixture(autouse=True)
def _clean_registry():
    """清 registry 状态"""
    skill_registry._skills.clear()
    skill_registry._skill_dirs.clear()
    skill_registry._watchers.clear()
    yield
    skill_registry._skills.clear()
    skill_registry._skill_dirs.clear()
    skill_registry._watchers.clear()


# ===========================================================================
# Skill.reload 直接调用
# ===========================================================================

def test_user_edits_skill_md_calls_reload_picks_up_changes(tmp_path: Path):
    """场景：用户修改了 .claude/skills/weather_query/SKILL.md → 调 reload → 新内容生效。
    真实任务：先看 v1，调 reload，再看 v2。
    """
    skill_dir = tmp_path / "weather_query"
    skill_dir.mkdir()
    skill_md = skill_dir / "SKILL.md"
    skill_md.write_text(textwrap.dedent("""\
        ---
        name: weather_query
        description: v1 老描述
        ---

        v1 body
        """), encoding="utf-8")

    skill = Skill(skill_dir)
    assert skill.description == "v1 老描述"

    # 用户修改文件
    skill_md.write_text(textwrap.dedent("""\
        ---
        name: weather_query
        description: v2 新描述
        ---

        v2 body
        """), encoding="utf-8")

    # 调 reload
    skill.reload()
    assert skill.description == "v2 新描述"
    assert "v2 body" in skill.content


def test_user_removes_skill_md_reload_fails_gracefully(tmp_path: Path, caplog):
    """场景：用户误删了 SKILL.md → reload 应报错但不崩"""
    import logging
    skill_dir = tmp_path / "broken_skill"
    skill_dir.mkdir()
    skill_md = skill_dir / "SKILL.md"
    skill_md.write_text("---\nname: x\ndescription: y\n---\nbody", encoding="utf-8")

    skill = Skill(skill_dir)
    skill_md.unlink()

    with caplog.at_level(logging.ERROR, logger="dumplingsAI"):
        skill.reload()  # 不应崩，只 log error
    # 旧内容还在（reload 失败时不动原状态）
    assert skill.name == "x"


# ===========================================================================
# SkillRegistry.reload_skill
# ===========================================================================

def test_user_reloads_skill_via_registry_picks_up_new_arguments(tmp_path: Path):
    """场景：用户给 skill 加了新参数 → reload → 新参数 schema 生效。
    真实任务：原本 skill 有 1 个参数，添加 1 个 → 重新注册 → schema 反映新参数。
    """
    skill_dir = tmp_path / "updatable"
    skill_dir.mkdir()
    skill_md = skill_dir / "SKILL.md"
    skill_md.write_text(textwrap.dedent("""\
        ---
        name: updatable
        description: v1
        arguments:
          - name: old_arg
            description: 老参数
        ---

        body
        """), encoding="utf-8")

    reg = SkillRegistry()
    skill = reg.register_skill(skill_dir)
    assert "old_arg" in skill.parameters["properties"]
    assert "new_arg" not in skill.parameters["properties"]

    # 用户修改 SKILL.md，加新参数
    skill_md.write_text(textwrap.dedent("""\
        ---
        name: updatable
        description: v2
        arguments:
          - name: old_arg
            description: 老参数
          - name: new_arg
            description: 新参数
        ---

        body
        """), encoding="utf-8")

    reg.reload_skill("updatable")
    updated = reg.get_skill("updatable")
    assert "new_arg" in updated.parameters["properties"]
    assert updated.parameters["properties"]["new_arg"]["description"] == "新参数"
    assert updated.description == "v2"


def test_user_unregisters_skill_then_reload_fails_gracefully(tmp_path: Path):
    """场景：用户先 unregister，然后调 reload → 静默 no-op，不抛"""
    reg = SkillRegistry()
    skill_dir = tmp_path / "to_unreg"
    skill_dir.mkdir()
    (skill_dir / "SKILL.md").write_text("---\nname: to_unreg\ndescription: x\n---\nbody", encoding="utf-8")
    reg.register_skill(skill_dir)
    reg.unregister_skill("to_unreg")

    # reload 不存在的 skill → no-op
    reg.reload_skill("to_unreg")  # 不应崩
    assert reg.get_skill("to_unreg") is None


# ===========================================================================
# Skill 错误恢复
# ===========================================================================

def test_user_corrupts_skill_md_scan_does_not_break_registry(tmp_path: Path):
    """场景：用户写了个格式错误的 SKILL.md → scan_and_register 不崩，只是跳过"""
    reg = SkillRegistry()
    # scan_and_register 要找 .claude/skills/ 子目录
    skills_dir = tmp_path / ".claude" / "skills"
    skills_dir.mkdir(parents=True)

    # 一个正常的
    good = skills_dir / "good"
    good.mkdir()
    (good / "SKILL.md").write_text("---\nname: good\ndescription: x\n---\nbody", encoding="utf-8")

    # 一个格式错的（不是 YAML frontmatter）
    bad = skills_dir / "bad"
    bad.mkdir()
    (bad / "SKILL.md").write_text("not a frontmatter", encoding="utf-8")

    # 一个没 SKILL.md 的目录
    (skills_dir / "no_skill_md").mkdir()

    # scan_and_register 不应崩
    reg.scan_and_register([tmp_path], auto_watch=False)
    # 至少 good 被注册了
    assert reg.get_skill("good") is not None

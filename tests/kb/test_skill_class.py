# -*- coding: utf-8 -*-
"""
Skill 类化测试（tests/kb/test_skill_class.py）
=============================================

验证 #4：Skill 类 + 自动发现 SKILL.md。
- subclass + 类属性 path（User 例子：class time(Skill): path=...）
- 自动从 SKILL.md frontmatter 解析 name/description/parameters
- 自动注册到 skill_registry 池（共享，不隔离）
- AI 可直接持有 Skill 实例调用
"""
from __future__ import annotations

from pathlib import Path

import pytest
from tangyuanAI.skill import Skill, skill_registry


@pytest.fixture(autouse=True)
def _clean_skill_registry():
    """清空 skill_registry + 对应的 tool_registry（避免跨测试污染）。"""
    from tangyuanAI.agent_tool import tool_registry
    saved = dict(skill_registry._skills), dict(skill_registry._skill_dirs)
    saved_tools = {k: v for k, v in tool_registry._tools.items()}
    skill_registry._skills.clear()
    skill_registry._skill_dirs.clear()
    yield
    skill_registry._skills.clear()
    skill_registry._skill_dirs.clear()
    skill_registry._skills.update(saved[0])
    skill_registry._skill_dirs.update(saved[1])
    tool_registry._tools.clear()
    tool_registry._tools.update(saved_tools)


def _write_skill(path: Path, name: str = "weather", description: str = "查询天气"):
    """写一个最小 SKILL.md。"""
    path.mkdir(parents=True, exist_ok=True)
    (path / "SKILL.md").write_text(
        f"""---
name: {name}
description: {description}
arguments:
  - city
---

查询 $city 的天气。
""",
        encoding="utf-8",
    )
    return path


class TestSkillClass:
    def test_subclass_with_path(self, tmp_path):
        """User 例子：class time(Skill): path=... → 实例化自动加载。"""
        sk_dir = _write_skill(tmp_path / "time", name="time", description="时间助手")

        class TimeSkill(Skill):
            path = str(sk_dir)  # 类属性

        t = TimeSkill()  # 无参数，自动读类属性 path
        assert t.name == "time"
        assert t.description == "时间助手"
        assert t.skill_dir == sk_dir

    def test_auto_register_to_pool(self, tmp_path):
        """实例化自动注册到 skill_registry（User 要求：自动进 skill 池）。"""
        sk_dir = _write_skill(tmp_path / "weather")
        s = Skill(sk_dir)  # 自动注册
        assert "weather" in skill_registry._skills
        assert skill_registry.get_skill("weather") is s

    def test_parameters_from_arguments(self, tmp_path):
        """SKILL.md arguments → parameters schema（city → required）。"""
        sk_dir = _write_skill(tmp_path / "w2")
        s = Skill(sk_dir)
        assert s.parameters["required"] == ["city"]
        assert "city" in s.parameters["properties"]

    def test_from_dir(self, tmp_path):
        """from_dir 便捷方法。"""
        sk_dir = _write_skill(tmp_path / "w3")
        s = Skill.from_dir(sk_dir)
        assert s.name == "weather"

    def test_render(self, tmp_path):
        """AI 可直接调 render。"""
        sk_dir = _write_skill(tmp_path / "w4")
        s = Skill(sk_dir)
        rendered = s.render({"city": "北京"})
        assert "北京" in rendered

    def test_no_dir_raises(self):
        """无目录且无类属性 path → 报错。"""
        with pytest.raises(ValueError, match="skill_dir"):
            Skill()

    def test_missing_skill_md(self, tmp_path):
        """目录无 SKILL.md → 报错。"""
        empty = tmp_path / "empty"
        empty.mkdir()
        with pytest.raises(FileNotFoundError, match="SKILL.md"):
            Skill(empty)

    def test_explicit_dir_overrides_class_attr(self, tmp_path):
        """显式 skill_dir 优先于类属性 path。"""
        sk_a = _write_skill(tmp_path / "a", name="a")
        sk_b = _write_skill(tmp_path / "b", name="b")

        class AB(Skill):
            path = str(sk_a)

        s = AB(sk_b)  # 显式传 b
        assert s.name == "b"

    def test_no_isolation_shared_pool(self, tmp_path):
        """Skill 不隔离：多个实例进同一池，AI 可遍历。"""
        sk1 = _write_skill(tmp_path / "s1", name="s1")
        sk2 = _write_skill(tmp_path / "s2", name="s2")
        Skill(sk1)
        Skill(sk2)
        names = [d["name"] for d in skill_registry.list_skills()]
        assert "s1" in names and "s2" in names

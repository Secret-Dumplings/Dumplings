# -*- coding: utf-8 -*-
"""
Skill 模块单测 —— 覆盖 `tests/test_skill.py` 缺失的协议层单测。

测试覆盖：

- Skill 解析：YAML frontmatter + body
- parameters schema 从 arguments 字段推导
- 模板变量替换（``$name``，Anthropic Skill 规范）
- SkillRegistry：register / unregister / get / list / scan
- get_skills_prompt_text 输出
- 边界：缺 SKILL.md / 无 frontmatter / 非法 YAML
"""
from __future__ import annotations

import textwrap
from pathlib import Path

import pytest
from tangyuanAI.skill import Skill, skill_registry

# ---------------------------------------------------------------------------
# fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def tmp_skill_dir(tmp_path: Path) -> Path:
    """建一个最小可用的 skill 目录。"""
    skill_dir = tmp_path / "weather_query"
    skill_dir.mkdir()
    (skill_dir / "SKILL.md").write_text(
        textwrap.dedent("""\
        ---
        name: weather_query
        description: 查询某城市当前天气
        arguments:
          - name: city
            description: 城市名
        ---

        # Weather Query

        查 $city 的天气。
        """),
        encoding="utf-8",
    )
    return skill_dir


@pytest.fixture
def clean_skill_registry():
    """每个用例前后清 skill_registry 状态。"""
    skill_registry._skills.clear()
    skill_registry._skill_dirs.clear()
    skill_registry._watchers.clear()
    yield skill_registry
    skill_registry._skills.clear()
    skill_registry._skill_dirs.clear()
    skill_registry._watchers.clear()


# ===========================================================================
# Skill 解析
# ===========================================================================

def test_skill_parses_frontmatter_and_body(tmp_skill_dir):
    skill = Skill(tmp_skill_dir)
    assert skill.name == "weather_query"
    assert skill.description == "查询某城市当前天气"
    assert "查 $city 的天气。" in skill.content


def test_skill_parameters_schema_from_arguments(tmp_skill_dir):
    """arguments 字段 → OpenAI parameters schema 推导"""
    skill = Skill(tmp_skill_dir)
    assert skill.parameters["type"] == "object"
    assert "city" in skill.parameters["properties"]
    assert skill.parameters["properties"]["city"]["type"] == "string"
    assert "city" in skill.parameters["required"]


def test_skill_render_substitutes_arguments(tmp_skill_dir):
    """render() 把 ``$name`` 占位符替换成 arguments 的值（Anthropic Skill 规范）"""
    skill = Skill(tmp_skill_dir)
    rendered = skill.render(arguments={"city": "北京"})
    assert "查 北京 的天气。" in rendered
    assert "$city" not in rendered


def test_skill_no_frontmatter_uses_dir_name(tmp_path: Path):
    """无 frontmatter 时，name 退化为目录名，description 退化为 content 第一段"""
    skill_dir = tmp_path / "my_skill"
    skill_dir.mkdir()
    (skill_dir / "SKILL.md").write_text("# Just content, no frontmatter", encoding="utf-8")
    skill = Skill(skill_dir)
    assert skill.name == "my_skill"
    # description 走 fallback：取 content 第一段（这里整段是一行，截到 200 字）
    assert skill.description.startswith("#")  # 走 fallback，含 markdown 标题


def test_skill_missing_skill_md_raises(tmp_path: Path):
    """目录里没 SKILL.md 应抛 FileNotFoundError"""
    skill_dir = tmp_path / "empty"
    skill_dir.mkdir()
    with pytest.raises(FileNotFoundError, match="SKILL.md 不存在"):
        Skill(skill_dir)


def test_skill_empty_arguments_means_no_required(tmp_path: Path):
    skill_dir = tmp_path / "noargs"
    skill_dir.mkdir()
    (skill_dir / "SKILL.md").write_text(
        textwrap.dedent("""\
        ---
        name: noargs
        description: no args
        ---

        body
        """),
        encoding="utf-8",
    )
    skill = Skill(skill_dir)
    assert skill.parameters["required"] == []
    assert skill.parameters["properties"] == {}


def test_skill_string_arguments_split_by_whitespace(tmp_path: Path):
    """arguments 字段可以是字符串（按空白拆）"""
    skill_dir = tmp_path / "strargs"
    skill_dir.mkdir()
    (skill_dir / "SKILL.md").write_text(
        textwrap.dedent("""\
        ---
        name: strargs
        description: str args
        arguments: "a b c"
        ---

        body
        """),
        encoding="utf-8",
    )
    skill = Skill(skill_dir)
    assert "a" in skill.parameters["properties"]
    assert "b" in skill.parameters["properties"]
    assert "c" in skill.parameters["properties"]


# ===========================================================================
# SkillRegistry
# ===========================================================================

def test_registry_register_get_unregister(tmp_skill_dir, clean_skill_registry):
    """register → get → list → unregister 闭环"""
    skill = clean_skill_registry.register_skill(tmp_skill_dir)
    assert skill is not None
    assert clean_skill_registry.get_skill("weather_query") is skill
    assert "weather_query" in [s["name"] for s in clean_skill_registry.list_skills()]

    clean_skill_registry.unregister_skill("weather_query")
    assert clean_skill_registry.get_skill("weather_query") is None
    assert clean_skill_registry.list_skills() == []


def test_registry_register_invalid_dir_returns_none(tmp_path, clean_skill_registry):
    """目录缺 SKILL.md 时返回 None（不抛）"""
    bad = tmp_path / "bad"
    bad.mkdir()
    result = clean_skill_registry.register_skill(bad)
    assert result is None
    assert clean_skill_registry.list_skills() == []


def test_registry_scan_and_register(tmp_path, clean_skill_registry):
    """scan_and_register 递归发现 .claude/skills/ 下的所有 SKILL.md"""
    # 建 monorepo 风格的嵌套结构
    base = tmp_path / "repo"
    base.mkdir()
    skills_dir = base / ".claude" / "skills"
    skills_dir.mkdir(parents=True)

    # 两个 skill
    for name in ("alpha", "beta"):
        sdir = skills_dir / name
        sdir.mkdir()
        (sdir / "SKILL.md").write_text(
            f"---\nname: {name}\ndescription: {name} skill\n---\nbody",
            encoding="utf-8",
        )
    # 一个不是目录的文件，应被忽略
    (skills_dir / "not_a_dir.txt").write_text("ignore me")

    clean_skill_registry.scan_and_register([base], auto_watch=False)
    names = {s["name"] for s in clean_skill_registry.list_skills()}
    assert names == {"alpha", "beta"}


def test_registry_scan_nonexistent_path_raises_warning_only(tmp_path, clean_skill_registry, caplog):
    """不存在的路径不抛，仅 logger.warning"""
    clean_skill_registry.scan_and_register([tmp_path / "no_such_path"], auto_watch=False)
    # 没注册任何 skill
    assert clean_skill_registry.list_skills() == []


def test_registry_get_skills_prompt_text(tmp_skill_dir, clean_skill_registry):
    """get_skills_prompt_text 输出可被注入到 system prompt"""
    clean_skill_registry.register_skill(tmp_skill_dir)
    text = clean_skill_registry.get_skills_prompt_text("any-uuid")
    assert "weather_query" in text
    assert "查询某城市当前天气" in text


def test_registry_get_skills_prompt_text_empty(clean_skill_registry):
    """空 registry → 空字符串（不抛）"""
    text = clean_skill_registry.get_skills_prompt_text("any-uuid")
    assert text == ""


def test_registry_search_skills_by_keyword(tmp_skill_dir, clean_skill_registry, tmp_path):
    """search_skills 按关键字过滤"""
    clean_skill_registry.register_skill(tmp_skill_dir)

    # 加一个无关 skill
    other = tmp_path / "translate"
    other.mkdir()
    (other / "SKILL.md").write_text(
        "---\nname: translate\ndescription: 翻译文本\n---\nbody",
        encoding="utf-8",
    )
    clean_skill_registry.register_skill(other)

    hits = clean_skill_registry.search_skills(keyword="天气")
    assert "weather_query" in [s["name"] for s in hits]
    assert "translate" not in [s["name"] for s in hits]


def test_registry_get_all_tool_schemas(tmp_skill_dir, clean_skill_registry):
    """get_all_tool_schemas 返回所有 skill 的 OpenAI tool schema"""
    clean_skill_registry.register_skill(tmp_skill_dir)
    schemas = clean_skill_registry.get_all_tool_schemas()
    assert len(schemas) >= 1
    weather = next(s for s in schemas if s.get("function", {}).get("name") == "weather_query")
    assert weather["type"] == "function"
    assert "city" in weather["function"]["parameters"]["properties"]

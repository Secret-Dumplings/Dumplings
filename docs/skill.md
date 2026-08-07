---
slug: skill
title: Skill（能力声明式）
order: 9
icon: SKILL_OUTLINED
---

# Skill（能力声明式）

> **v1.0.0+**。Skill = 一个目录 + `SKILL.md`（YAML frontmatter + Markdown body），声明式描述一个能力。tangyuanAI 遵循 Anthropic Agent Skills 开放标准。

## 快速上手（类化用法）

`Skill` 类是核心。**subclass + 类属性 `path`** → 实例化自动从 SKILL.md 解析 name/description/parameters：

```python
import tangyuanAI as t
from tangyuanAI.skill import Skill

# 1. 准备一个 skill 目录
# ./skills/time/SKILL.md:
#   ---
#   name: time
#   description: 查询世界各时区当前时间
#   arguments:
#     - tz
#   ---
#   查询 $tz 时区的当前时间。

class TimeSkill(Skill):
    path = "./skills/time"   # 类属性：指向含 SKILL.md 的目录

t_skill = TimeSkill()        # 自动加载 + 自动注册到 skill 池
print(t_skill.name, t_skill.description)
# → time 查询世界各时区当前时间

# 2. AI 直接调用
rendered = t_skill.render({"tz": "Asia/Shanghai"})
# → "查询 Asia/Shanghai 时区的当前时间。"
```

## 用法：直接构造

```python
from tangyuanAI.skill import Skill

# 从目录加载（自动解析 SKILL.md frontmatter）
s = Skill("./skills/weather")          # auto_register=True 默认进池
s = Skill.from_dir("./skills/weather") # 同 Skill(path)

# 禁用自动注册（如只想持有不共享）
s = Skill("./skills/code_review", auto_register=False)

# 或完全手动（无 SKILL.md）
s = Skill(name="my_skill", description="...", parameters={...})
```

## SKILL.md 格式

```markdown
---
name: weather_query          # 必填（缺省用目录名）
description: 查询某城市当前天气
arguments:                  # → 自动生成 parameters schema（required）
  - city
when_to_use: 用户问天气时
---

查询 {city} 的天气。

## Examples

- 北京今天天气怎么样？
- 上海会下雨吗？
```

实例化时自动解析 frontmatter → `name` / `description` / `arguments` → 生成 `parameters`（OpenAI schema），无需手写。

## 自动进池（共享，不隔离）

```python
# 每个 Skill 实例默认自动注册到全局 skill_registry（共享池，AI 可遍历）
from tangyuanAI.skill import skill_registry

s = Skill("./skills/weather")          # 已自动注册

skill_registry.get_skill("weather")    # → 同名 Skill 实例
skill_registry.list_skills()           # → [{"name", "description", ...}]
skill_registry.unregister_skill("weather")
```

Skill **不做隔离**（能力共享是设计目标）：所有实例进同一池，AI 可访问任意 Skill。

## 渲染与参数替换

```python
# render(arguments) 执行参数替换 + shell 预处理，返回最终 prompt
text = s.render({"city": "北京"})
# $city → 北京；$0-$9 位置参数；$ARGUMENTS 完整参数字符串；${CLAUDE_SKILL_DIR} 目录路径
```

## 注册为工具（Agent Function Calling）

```python
# 桥接到 tool_registry，Agent 可通过 Function Calling 调用
s.register_as_tool()        # 或 skill_bridge.register_skill_as_tool(s)

# 顶层：skill_registry.register_skill(dir) 也会自动桥接
```

## 编程式注册

```python
skill_registry.scan_and_register(base_paths=[".claude/skills/"], auto_watch=True)  # 目录扫描 + 热加载
skill_registry.register_skill("./skills/weather")   # 单个目录
```
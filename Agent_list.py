from typing import Optional

# 1. 已"激活"的 Agent 实例池（与 tangyuanAI.agent_list 兼容）
#    语义：只有调用 activate_template() 之后，模板才会作为实例进入这里。
agent_list = {}          # {key1: instance, key2: instance}

# 2. 用户自定义模板池 —— **只存类（cls），不实例化**
#    key 为模板名（str），value 为 dict：
#        {"name", "uuid", "description", "cls", ...可选元数据}
agent_template_pool: dict = {}

# 全库统一 logger
try:
    from .logging_config import logger
except ImportError:
    try:
        from tangyuanAI.logging_config import logger
    except ImportError:
        import logging as _logging
        logger = _logging.getLogger("tangyuanAI.Agent_list")


# ---------------------------------------------------------------------------
# 内部工具
# ---------------------------------------------------------------------------
def _normalize(template, *, name=None, uuid=None, description=None) -> dict:
    """把"模板对象"统一转成 dict，存进池里。

    支持三种入参：
    - Agent 类（type）：从类属性提取 uuid/name/description
    - dict：原样返回（拷贝一次，避免外部修改污染池内数据）
    - 其它对象：必须有 ``__tangyuan_template__()`` 返回 dict
    """
    if isinstance(template, dict):
        tpl = dict(template)
    elif isinstance(template, type):
        tpl = {
            "name": getattr(template, "name", None) or template.__name__,
            "uuid": getattr(template, "uuid", None),
            "description": getattr(template, "description", None),
            "cls": template,
        }
    else:
        factory = getattr(template, "__tangyuan_template__", None)
        if callable(factory):
            tpl = dict(factory())
        else:
            raise TypeError(
                f"无法识别的 template 类型：{type(template)!r}。"
                " 请传 Agent 类、dict，或提供 __tangyuan_template__() 方法。"
            )

    # 显式传入的参数覆盖类属性
    if name is not None:
        tpl["name"] = name
    if uuid is not None:
        tpl["uuid"] = uuid
    if description is not None:
        tpl["description"] = description

    if not tpl.get("name"):
        raise ValueError("模板必须提供 name 字段")
    if tpl.get("cls") is None:
        raise ValueError(f"模板 {tpl['name']!r} 没有提供 cls，无法激活时实例化")
    return tpl


def _ensure_meta(tpl: dict) -> dict:
    """补全 uuid / description 缺省值。"""
    if not tpl.get("uuid"):
        tpl["uuid"] = tpl["name"]
    tpl.setdefault("description", None)
    return tpl


# ---------------------------------------------------------------------------
# 模板池：只入池、不实例化、不写 agent_list
# ---------------------------------------------------------------------------
def register_template(template, *, name=None, uuid=None,
                      description=None, overwrite: bool = True) -> dict:
    """
    把一个"模板"（本质是 Agent 类）存进 ``agent_template_pool``，**不实例化**。
    模板的实例化时机完全由 ``activate_template`` 控制。

    参数:
        template: Agent 类 / dict / 实现了 ``__tangyuan_template__()`` 的对象
        name: 显式指定模板名（覆盖类属性）
        uuid: 显式指定模板 uuid（默认 = name）
        description: 显式指定描述
        overwrite: 同名模板已存在时是否覆盖（默认 True；False 时抛 ValueError）

    返回:
        写入池中的模板 dict（含 "cls" 键，指向 Agent 类对象）。
    """
    tpl = _normalize(template, name=name, uuid=uuid, description=description)
    _ensure_meta(tpl)

    if tpl["name"] in agent_template_pool and not overwrite:
        raise ValueError(f"模板 {tpl['name']!r} 已存在，且 overwrite=False")

    agent_template_pool[tpl["name"]] = tpl
    return tpl


# ---------------------------------------------------------------------------
# 装饰器形态：@template_agent(...)
#   行为等价于 register_template(cls)，**不实例化、不写 agent_list**。
# ---------------------------------------------------------------------------
def template_agent(name=None, *, uuid=None, description=None, overwrite: bool = True):
    """
    类装饰器：把被装饰的 Agent 类注册到 ``agent_template_pool``，**不实例化**。

    行为对标::

        @template_agent("my_agent")
        class MyAgent(Agent):
            ...

        # 等价于：
        register_template(MyAgent, name="my_agent")

    参数:
        name:    模板名；缺省时取 ``cls.name`` 或类名
        uuid:    模板 uuid（默认 = name）
        description: 模板描述
        overwrite: 同名模板已存在时是否覆盖（默认 True）

    注意：
    - **不会实例化类**，也**不会写入 agent_list**。
      需要使用 Agent 时请显式调用 ``activate_template("name")``。
    - 与旧版 ``@register_agent`` 的区别：旧版在 import 阶段就实例化并写入 agent_list；
      本装饰器只是把"模板"入池，按需激活。
    """
    def _decorator(cls):
        # 缺省 name 时的兜底：类属性 name -> 类名
        effective_name = name or getattr(cls, "name", None) or cls.__name__
        # 把 uuid / name / description 写回类属性，__init__ 内部 self.__class__.uuid
        # / self.__class__.name 才能拿到；这与旧版 @register_agent 行为一致
        # （v0.3.0 之前依赖 @register_agent 隐式设置；template_agent 也要做）。
        cls.uuid = uuid if uuid is not None else effective_name
        cls.name = effective_name
        cls.description = description
        register_template(
            cls,
            name=effective_name,
            uuid=cls.uuid,
            description=description,
            overwrite=overwrite,
        )
        return cls              # 原样返回，不影响类本身
    return _decorator


# ---------------------------------------------------------------------------
# 激活：模板 -> 实例 -> agent_list
# ---------------------------------------------------------------------------
def activate_template(name: str, *, uuid: Optional[str] = None):
    """
    把模板从池中"激活"到 ``agent_list``。

    步骤：
        1. 从 ``agent_template_pool`` 取出模板 dict（含 cls）
        2. 实例化（``cls()``）
        3. 按 ``uuid`` 和（首次时）``name`` 两个 key 写入 ``agent_list``

    Args:
        name: 模板名
        uuid: 可选；强制覆盖默认 uuid。多次激活同名模板时**必须传不同的 uuid**，
              否则抛 ``ValueError``（避免静默覆盖已有实例）。

    Raises:
        KeyError: 模板不在池中
        ValueError: agent_list 中已有同名 uuid 的实例

    Returns:
        新实例化的 Agent。
    """
    tpl = agent_template_pool.get(name)
    if tpl is None:
        raise KeyError(f"模板 {name!r} 不在 agent_template_pool 中")

    cls = tpl["cls"]
    inst = cls()  # **唯一实例化点**

    effective_uuid = uuid if uuid is not None else (tpl.get("uuid") or name)
    if effective_uuid in agent_list:
        raise ValueError(
            f"agent_list 已有 uuid={effective_uuid!r}。"
            f"多次激活同名模板请传不同 uuid，或先 deactivate_template。"
        )

    agent_list[effective_uuid] = inst
    # 第一次激活时才用 name 做 key；后续同名 name 不覆盖（避免冲掉）
    if name not in agent_list:
        agent_list[name] = inst

    return inst


def deactivate_template(name: str) -> bool:
    """从 ``agent_list`` 中移除该模板的实例，模板本身仍保留在池中。"""
    tpl = agent_template_pool.get(name)
    if tpl is None:
        return False
    uid = tpl.get("uuid") or name
    agent_list.pop(uid, None)
    agent_list.pop(name, None)
    return True


def remove_template(name: str) -> bool:
    """彻底从池中删除模板，并连带从 agent_list 移除实例。"""
    deactivate_template(name)
    return agent_template_pool.pop(name, None) is not None


# ---------------------------------------------------------------------------
# 查询
# ---------------------------------------------------------------------------
def list_templates() -> list:
    """列出所有已注册模板的元信息（不包含 cls，避免循环引用）"""
    items = []
    for name, tpl in agent_template_pool.items():
        items.append({
            "name": name,
            "uuid": tpl.get("uuid"),
            "description": tpl.get("description"),
            "active": name in agent_list,
        })
    return items


def get_template(name: str):
    return agent_template_pool.get(name)


def is_active(name: str) -> bool:
    return name in agent_list


# ---------------------------------------------------------------------------
# 注册表 API 包装（v0.4.2+）—— 替代直接 mutate agent_list dict
# ---------------------------------------------------------------------------

def register_agent(name: str, instance) -> None:
    """把 instance 注册到 agent_list（用 name 作 key）。

    不像 ``@register_agent`` 装饰器（已弃用），这是手动注册 API。
    多次注册同名会覆盖。
    """
    agent_list[name] = instance


def unregister_agent(name: str) -> bool:
    """从 agent_list 注销。name 不存在不抛，返回是否真的删了。"""
    return agent_list.pop(name, None) is not None


# ---------------------------------------------------------------------------
# 用法示例（直接 python Agent_list.py 跑通）
# ---------------------------------------------------------------------------
if __name__ == '__main__':
    # ---- 装饰器形态：@template_agent(...) ----
    @template_agent("writer", uuid="writer-uuid", description="模板：写文章")
    class Writer:
        uuid = None  # 装饰器参数会覆盖
        def __init__(self):
            self.tag = "writer-instance"
        def hi(self):
            return f"hi from {self.tag}"

    print("装饰器入池后:", list_templates())        # active=False
    print("writer 在 agent_list 中吗?", is_active("writer"))  # False

    # ---- 模板池：先入池（不实例化）----
    class Coder:
        name = "coder"
        uuid = "coder-uuid"
        description = "模板：写代码"

        def __init__(self):
            self.tag = "coder-instance"

        def hello(self):
            return f"hi from {self.tag}"

    register_template(Coder)

    print("池中模板:", list_templates())                    # active=False
    print("coder 在 agent_list 中吗?", is_active("coder"))  # False

    # ---- 显式激活 ----
    activate_template("coder")
    print("激活后:", list_templates())                      # active=True
    print(agent_list["coder"].hello())

    # ---- 反激活 ----
    deactivate_template("coder")
    print("反激活后:", is_active("coder"))                  # False

    # ---- 重新激活会生成新实例 ----
    inst = activate_template("coder")
    print("新实例 tag:", inst.tag)

    # ---- 通过装饰器入池的模板同样可激活 ----
    inst_w = activate_template("writer")
    print("writer 激活后 hi:", inst_w.hi())

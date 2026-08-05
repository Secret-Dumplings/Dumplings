# -*- coding: utf-8 -*-
"""
Tangyuan 启动 banner
====================

import tangyuanAI 时打一行提示，告知：
- 当前版本
- 文档 / issue 链接
- 三个常用入口：help() / --doctor / --demo

关闭方式：设置环境变量 ``TANGYUAN_QUIET=1`` 或在 ``__init__.py`` 入口之前
设置 ``_SILENCE_BANNER = True``。
"""
from __future__ import annotations

import os
import sys

_RESET = "\x1b[0m"
_BOLD = "\x1b[1m"
_DIM = "\x1b[2m"
_CYAN = "\x1b[36m"
_YELLOW = "\x1b[33m"
_GREEN = "\x1b[32m"


def _supports_color() -> bool:
    """判断 stderr/stdout 是否支持 ANSI 颜色"""
    if os.environ.get("NO_COLOR"):
        return False
    if os.environ.get("TANGYUAN_FORCE_COLOR"):
        return True
    return hasattr(sys.stderr, "isatty") and sys.stderr.isatty()


def print_banner(stream=None) -> None:
    """在指定 stream（默认 stderr）打一行 banner"""
    if os.environ.get("TANGYUAN_QUIET") in ("1", "true", "TRUE", "yes"):
        return

    # 延迟 import 避免循环
    from tangyuanAI import __version__

    s = stream or sys.stderr
    color = _supports_color()
    if color:
        c_ver, c_dim, c_link, c_tip = _BOLD + _CYAN, _DIM, _CYAN, _YELLOW
        rst = _RESET
    else:
        c_ver = c_dim = c_link = c_tip = rst = ""

    s.write(
        f"{c_ver}tangyuanAI v{__version__}{rst}  "
        f"{c_dim}— multi-agent LLM framework{rst}\n"
        f"  {c_link}https://github.com/secret-tangyuan/tangyuanAI{rst}\n"
        f"  {c_tip}→ help() / --doctor / --demo{rst}\n"
    )


def silence() -> None:
    """程序化关闭 banner（在测试 / 嵌入式场景用）"""
    os.environ["TANGYUAN_QUIET"] = "1"

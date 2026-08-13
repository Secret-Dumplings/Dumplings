# -*- coding: utf-8 -*-
"""tangyuanai.imaging —— 图片生成命名空间桥（实现由 Image 插件提供）。

- 安装了图片插件（``tangyuanai-image-plus``，entry point ``image``，type=image_generation）时：
  本包整体别名到插件 API。``from tangyuanAI.imaging import ImageGenerator`` 等价于
  ``from tangyuanAI_image_plus import ImageGenerator``。
- 未安装时：``import tangyuanAI.imaging`` 本身可导入，但取任何 API 会得到清晰的安装提示。

安装：
    pip install "tangyuanAI[all]"            # 安装全部插件
    pip install tangyuanai-image-plus        # 只装图片插件

接口文档：docs/plugin-dev.md
"""
from __future__ import annotations

from ..plugin_api import PLUGIN_TYPE_IMAGE
from ..plugin_loader import install_module_alias, resolve_plugin_for_namespace

_impl = resolve_plugin_for_namespace(PLUGIN_TYPE_IMAGE)
if _impl is not None:
    install_module_alias(__name__, _impl)
    _SELF = _impl
else:
    _SELF = None


def __getattr__(name):
    if _SELF is None:
        raise ImportError(
            "图片插件未安装，无法访问 tangyuanAI.imaging API。"
            "安装方式：pip install 'tangyuanAI[all]' 或 pip install tangyuanai-image-plus"
        )
    return getattr(_SELF, name)


def __dir__():
    if _SELF is not None:
        return sorted(set(globals()) | set(dir(_SELF)))
    return sorted(globals())


__all__ = [
    "ImageProvider",
    "ImageError",
    "ImageGenerator",
    "HttpJsonImageProvider",
    "download_urls",
    "render_template",
    "resolve_json_path",
    "resolve_url_template",
]

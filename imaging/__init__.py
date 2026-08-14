# -*- coding: utf-8 -*-
"""tangyuanai.imaging —— 图片生成子系统。

**两种使用模式**：

1. **默认（vendored）**：``pip install tangyuanai`` 自带完整图片生成实现，开箱即用。
2. **第三方替换**：安装替代图片包（通过 ``tangyuanai plugin install <git-url>`` 或
   ``pip install`` 任意含 ``tangyuanai.plugins`` entry point 的包）后，本包会
   自动优先使用第三方实现，vendored 代码作为 fallback。
"""
from __future__ import annotations

from ..plugin_api import PLUGIN_TYPE_IMAGE
from ..plugin_loader import install_module_alias, resolve_plugin_for_namespace

# ---------------------------------------------------------------------------
# 1) 第三方插件（如有）→ 通过 install_module_alias 接管 tangyuanAI.imaging 命名空间
# ---------------------------------------------------------------------------

_third_party = resolve_plugin_for_namespace(PLUGIN_TYPE_IMAGE)
if _third_party is not None:
    install_module_alias(__name__, _third_party)
    _SELF = _third_party
else:
    _SELF = None


# ---------------------------------------------------------------------------
# 2) Fallback：本地 vendored 实现
# ---------------------------------------------------------------------------

if _SELF is None:
    from .generator import ImageGenerator  # noqa: E402
    from .provider import (  # noqa: E402
        HttpJsonImageProvider,
        ImageError,
        ImageProvider,
        download_urls,
        render_template,
        resolve_json_path,
        resolve_url_template,
    )


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

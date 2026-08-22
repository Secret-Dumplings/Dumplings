# -*- coding: utf-8 -*-
"""图片输入归一化（OpenAI / Anthropic / Responses 三协议）。

支持 3 种输入形态：

- ``str`` —— 以 ``http(s)://`` 起头 → URL；否则视为裸 base64（自动推断 media_type）
- ``dict`` —— 包含 ``url`` / ``data`` / ``file_id`` 之一 + 可选 ``media_type`` / ``detail``

返回对应协议的内容块（content block）：

- :func:`to_openai_block` —— OpenAI Chat Completions：
  ``{"type": "image_url", "image_url": {"url": "...", "detail": "..."}}``
  或 ``{"type": "file", "file_id": "..."}``
- :func:`to_anthropic_block` —— Anthropic Messages：
  ``{"type": "image", "source": {"type": "url"|"base64"|"file", ...}}``
- :func:`to_responses_block` —— OpenAI Responses API：
  ``{"type": "input_image", "image_url": "...", "detail": "auto"}``
  或 ``{"type": "input_file", "file_id": "..."}``

``media_type`` 缺省时从 base64 头字节推断 JPEG / PNG / GIF / WebP；
无法推断时回退 ``image/png``。兼容 ``data:image/jpeg;base64,xxx`` 前缀。
"""
from __future__ import annotations

import base64
from typing import Any, Dict, Union

# ---------------------------------------------------------------------------
# media_type 推断（按 base64 头几个字节的 magic number）
# ---------------------------------------------------------------------------

_MAGIC_NUMBERS: tuple[tuple[bytes, str], ...] = (
    (b"\xff\xd8\xff", "image/jpeg"),
    (b"\x89PNG\r\n\x1a\n", "image/png"),
    (b"GIF87a", "image/gif"),
    (b"GIF89a", "image/gif"),
)

# 限制最大探测长度（64 字符 base64 ≈ 48 字节，已足够覆盖所有 magic number）
_PROBE_LEN = 64


def infer_media_type(b64: str) -> str:
    """从 base64 头几个字节推断图片格式（JPEG / PNG / GIF / WebP）。

    兼容 ``data:image/jpeg;base64,xxx`` 前缀；推断失败回退 ``image/png``。
    """
    if not b64:
        return "image/png"

    # 1) data URI 前缀优先
    if b64.startswith("data:"):
        try:
            head, _, payload = b64.partition(",")
            mime = head.split(";", 1)[0].split(":", 1)[1]
            if mime.startswith("image/"):
                return mime
            b64 = payload
        except Exception:
            return "image/png"

    # 2) magic number
    try:
        pad = "=" * (-len(b64[:_PROBE_LEN]) % 4)
        raw = base64.b64decode(b64[:_PROBE_LEN] + pad, validate=False)
    except Exception:
        return "image/png"

    for magic, mime in _MAGIC_NUMBERS:
        if raw.startswith(magic):
            return mime

    # WEBP：RIFF header + "WEBP" 在偏移 8-12
    if raw[:4] == b"RIFF" and raw[8:12] == b"WEBP":
        return "image/webp"

    return "image/png"


# ---------------------------------------------------------------------------
# 输入标准化
# ---------------------------------------------------------------------------

ImageInput = Union[str, Dict[str, Any]]


def _is_url(s: str) -> bool:
    return s.startswith(("http://", "https://"))


def _parse_str(img: str) -> Dict[str, Any]:
    """``str`` 输入：URL 或 base64。"""
    if _is_url(img):
        return {"url": img}
    return {"data": img, "media_type": infer_media_type(img)}


def _parse_dict(img: Dict[str, Any]) -> Dict[str, Any]:
    """``dict`` 输入：校验 + 标准化。

    ``url`` / ``data`` / ``file_id`` 三选一；``file_id`` 不能与其它字段同用。
    ``detail`` 仅对 url / data 有意义。
    """
    keys = set(img.keys())
    if "file_id" in keys:
        if keys - {"file_id"}:
            raise ValueError(
                f"file_id 不能与其它字段同用：{sorted(keys)}"
            )
        return {"file_id": img["file_id"]}

    if "url" in keys:
        if "data" in keys or "file_id" in keys:
            raise ValueError(
                f"url / data / file_id 三选一：{sorted(keys)}"
            )
        out: Dict[str, Any] = {"url": img["url"]}
        if "detail" in img:
            out["detail"] = img["detail"]
        return out

    if "data" in keys:
        out = {
            "data": img["data"],
            "media_type": img.get("media_type") or infer_media_type(img["data"]),
        }
        if "detail" in img:
            out["detail"] = img["detail"]
        return out

    raise ValueError(
        f"image dict 必须包含 url / data / file_id 之一：{sorted(keys)}"
    )


def _to_data_url(parsed: Dict[str, Any]) -> str:
    if "url" in parsed:
        return parsed["url"]
    return f"data:{parsed['media_type']};base64,{parsed['data']}"


def _normalize(img: ImageInput) -> Dict[str, Any]:
    if isinstance(img, str):
        return _parse_str(img)
    if isinstance(img, dict):
        return _parse_dict(img)
    raise TypeError(
        f"image 必须是 str 或 dict，得到 {type(img).__name__}"
    )


# ---------------------------------------------------------------------------
# 协议特化：构造各协议的内容块
# ---------------------------------------------------------------------------


def to_openai_block(img: ImageInput) -> Dict[str, Any]:
    """OpenAI Chat Completions 内容块（``image_url`` 或 ``file``）。"""
    parsed = _normalize(img)
    if "file_id" in parsed:
        return {"type": "file", "file_id": parsed["file_id"]}
    block: Dict[str, Any] = {
        "type": "image_url",
        "image_url": {"url": _to_data_url(parsed)},
    }
    if "detail" in parsed:
        block["image_url"]["detail"] = parsed["detail"]
    return block


def to_anthropic_block(img: ImageInput) -> Dict[str, Any]:
    """Anthropic Messages 内容块（``image`` + ``source.{url,base64,file}``）。"""
    parsed = _normalize(img)
    if "file_id" in parsed:
        return {
            "type": "image",
            "source": {"type": "file", "file_id": parsed["file_id"]},
        }
    if "url" in parsed:
        return {
            "type": "image",
            "source": {"type": "url", "url": parsed["url"]},
        }
    return {
        "type": "image",
        "source": {
            "type": "base64",
            "media_type": parsed["media_type"],
            "data": parsed["data"],
        },
    }


def to_responses_block(img: ImageInput) -> Dict[str, Any]:
    """OpenAI Responses API 内容块（``input_image`` 或 ``input_file``）。

    ``detail`` 缺省值是 ``"auto"``（语义：当前等价于 ``original``，DeepSeek
    文档允许 ``low`` / ``high`` / ``original`` / ``auto``）。
    """
    parsed = _normalize(img)
    if "file_id" in parsed:
        return {"type": "input_file", "file_id": parsed["file_id"]}
    return {
        "type": "input_image",
        "image_url": _to_data_url(parsed),
        "detail": parsed.get("detail", "auto"),
    }


# ---------------------------------------------------------------------------
# 顶层 re-export
# ---------------------------------------------------------------------------

__all__ = [
    "ImageInput",
    "infer_media_type",
    "to_openai_block",
    "to_anthropic_block",
    "to_responses_block",
]

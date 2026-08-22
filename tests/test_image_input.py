"""image_input helper + agent._build_user_message 端到端测试。

覆盖：
- infer_media_type 正确识别 PNG / JPEG / GIF / WebP base64
- infer_media_type 兼容 data URI 前缀；失败回退 image/png
- to_openai_block / to_anthropic_block / to_responses_block：
  str URL / str base64 / dict url / dict data / dict file_id / detail 字段
- agent._build_user_message 在 OpenAI / Anthropic / Responses 三协议下端到端拼装
"""
from __future__ import annotations

import base64
import uuid as _uuid

import pytest
from tangyuanAI import activate_template, agent_list, template_agent
from tangyuanAI.agent import _AnthropicBase, _OpenAIBase, _OpenAIResponsesBase
from tangyuanAI.Agent_list import agent_template_pool
from tangyuanAI.image_input import (
    infer_media_type,
    to_anthropic_block,
    to_openai_block,
    to_responses_block,
)

# ---------------------------------------------------------------------------
# fixture：复用 _make_agent 模式，构造最小 Agent（不连真 LLM）
# ---------------------------------------------------------------------------


@pytest.fixture
def _isolate_agent_list():
    saved_list = dict(agent_list)
    saved_pool = dict(agent_template_pool)
    yield
    agent_list.clear()
    agent_template_pool.clear()
    agent_list.update(saved_list)
    agent_template_pool.update(saved_pool)


def _make_agent(cls, name: str, *, protocol: str, api_provider: str):
    uuid_str = _uuid.uuid4().hex

    @template_agent(name, uuid=uuid_str, description="test")
    class _A(cls):
        prompt = "x"
        model_name = "m"
        api_key = "k"
        stream = False

    _A.protocol = protocol
    _A.api_provider = api_provider

    activate_template(name)
    inst = agent_list[name]
    inst._connectivity = lambda: None  # noqa: SLF001
    return inst


# ---------------------------------------------------------------------------
# 真实 magic bytes（用 python 生小图片，转 base64）
# ---------------------------------------------------------------------------


def _b64_of(raw: bytes) -> str:
    return base64.b64encode(raw).decode("ascii")


# 1×1 透明 PNG
_PNG_1X1 = _b64_of(
    bytes.fromhex(
        "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4"
        "890000000d49444154789c6300010000000500010d0a2db40000000049454e44"
        "ae426082"
    )
)

# 最小 JPEG
_JPEG_MIN = _b64_of(b"\xff\xd8\xff\xe0" + b"\x00" * 20)  # JPEG SOI + APP0 magic
_GIF_MIN = _b64_of(b"GIF89a" + b"\x00" * 20)
_WEBP_MIN = _b64_of(b"RIFF" + b"\x00\x00\x00\x00" + b"WEBP" + b"\x00" * 20)


# ---------------------------------------------------------------------------
# infer_media_type 测试
# ---------------------------------------------------------------------------


def test_infer_media_type_png():
    assert infer_media_type(_PNG_1X1) == "image/png"


def test_infer_media_type_jpeg():
    assert infer_media_type(_JPEG_MIN) == "image/jpeg"


def test_infer_media_type_webp():
    assert infer_media_type(_WEBP_MIN) == "image/webp"


def test_infer_media_type_gif():
    assert infer_media_type(_GIF_MIN) == "image/gif"


def test_infer_media_type_data_uri_prefix():
    """data URI 前缀优先。"""
    b64_png = _PNG_1X1
    assert infer_media_type(f"data:image/png;base64,{b64_png}") == "image/png"
    assert infer_media_type(f"data:image/jpeg;base64,{b64_png}") == "image/jpeg"


def test_infer_media_type_fallback():
    assert infer_media_type("") == "image/png"
    assert infer_media_type("not_valid_base64!!!") == "image/png"
    # 全 ASCII 不构成任何 magic number
    assert infer_media_type(_b64_of(b"random bytes here")) == "image/png"


# ---------------------------------------------------------------------------
# str 输入：URL / base64
# ---------------------------------------------------------------------------


def test_openai_block_str_url():
    block = to_openai_block("https://example.com/x.jpg")
    assert block == {"type": "image_url", "image_url": {"url": "https://example.com/x.jpg"}}


def test_openai_block_str_base64_infers_png():
    block = to_openai_block(_PNG_1X1)
    assert block == {
        "type": "image_url",
        "image_url": {"url": f"data:image/png;base64,{_PNG_1X1}"},
    }


def test_openai_block_str_base64_infers_jpeg():
    block = to_openai_block(_JPEG_MIN)
    assert "data:image/jpeg;base64," in block["image_url"]["url"]


def test_anthropic_block_str_url():
    block = to_anthropic_block("https://example.com/x.jpg")
    assert block == {
        "type": "image",
        "source": {"type": "url", "url": "https://example.com/x.jpg"},
    }


def test_anthropic_block_str_base64_infers_media_type():
    block = to_anthropic_block(_PNG_1X1)
    assert block == {
        "type": "image",
        "source": {"type": "base64", "media_type": "image/png", "data": _PNG_1X1},
    }


def test_responses_block_str_url_has_auto_detail():
    block = to_responses_block("https://example.com/x.jpg")
    assert block == {
        "type": "input_image",
        "image_url": "https://example.com/x.jpg",
        "detail": "auto",
    }


# ---------------------------------------------------------------------------
# dict 输入：url / data / file_id / detail
# ---------------------------------------------------------------------------


def test_openai_block_dict_url_with_detail():
    block = to_openai_block({"url": "https://example.com/x.jpg", "detail": "low"})
    assert block == {
        "type": "image_url",
        "image_url": {"url": "https://example.com/x.jpg", "detail": "low"},
    }


def test_openai_block_dict_data_explicit_media_type():
    block = to_openai_block({"data": _PNG_1X1, "media_type": "image/gif"})
    # 显式 media_type 覆盖推断
    assert "data:image/gif;base64," in block["image_url"]["url"]


def test_openai_block_dict_data_inferred_when_no_media_type():
    block = to_openai_block({"data": _JPEG_MIN})
    assert "data:image/jpeg;base64," in block["image_url"]["url"]


def test_openai_block_dict_file_id():
    block = to_openai_block({"file_id": "file-api-xxxxx"})
    assert block == {"type": "file", "file_id": "file-api-xxxxx"}


def test_openai_block_dict_file_id_mutually_exclusive():
    with pytest.raises(ValueError, match="file_id"):
        to_openai_block({"file_id": "x", "data": "y"})
    with pytest.raises(ValueError, match="file_id"):
        to_openai_block({"file_id": "x", "url": "https://x"})


def test_anthropic_block_dict_file_id():
    block = to_anthropic_block({"file_id": "file-api-xxxxx"})
    assert block == {
        "type": "image",
        "source": {"type": "file", "file_id": "file-api-xxxxx"},
    }


def test_anthropic_block_dict_url():
    block = to_anthropic_block({"url": "https://example.com/x.jpg"})
    assert block == {
        "type": "image",
        "source": {"type": "url", "url": "https://example.com/x.jpg"},
    }


def test_anthropic_block_dict_data_with_media_type():
    block = to_anthropic_block({"data": _PNG_1X1, "media_type": "image/webp"})
    assert block["source"]["media_type"] == "image/webp"
    assert block["source"]["type"] == "base64"


def test_responses_block_dict_file_id():
    block = to_responses_block({"file_id": "file-api-xxxxx"})
    assert block == {"type": "input_file", "file_id": "file-api-xxxxx"}


def test_responses_block_dict_url_with_detail_low():
    block = to_responses_block({"url": "https://example.com/x.jpg", "detail": "low"})
    assert block == {
        "type": "input_image",
        "image_url": "https://example.com/x.jpg",
        "detail": "low",
    }


def test_responses_block_dict_data_inferred():
    block = to_responses_block({"data": _JPEG_MIN})
    assert block["type"] == "input_image"
    assert "data:image/jpeg;base64," in block["image_url"]
    assert block["detail"] == "auto"


def test_block_rejects_unsupported_type():
    with pytest.raises(TypeError):
        to_openai_block(123)  # type: ignore[arg-type]


def test_block_rejects_dict_without_required_keys():
    with pytest.raises(ValueError, match="url / data / file_id"):
        to_openai_block({"foo": "bar"})


# ---------------------------------------------------------------------------
# agent._build_user_message 端到端测试
# ---------------------------------------------------------------------------


def test_openai_build_user_message_with_images(_isolate_agent_list):
    inst = _make_agent(
        _OpenAIBase,
        "img-oa",
        protocol="openai",
        api_provider="http://mock.invalid/v1/chat/completions",
    )
    msg = inst._build_user_message(
        "描述这张图",
        ["https://example.com/x.jpg", {"file_id": "file-api-y"}, {"data": _PNG_1X1}],
    )

    assert msg["role"] == "user"
    content = msg["content"]
    assert content[0] == {"type": "text", "text": "描述这张图"}
    assert content[1]["type"] == "image_url"
    assert content[1]["image_url"]["url"] == "https://example.com/x.jpg"
    assert content[2] == {"type": "file", "file_id": "file-api-y"}
    assert content[3]["type"] == "image_url"
    assert "data:image/png;base64," in content[3]["image_url"]["url"]


def test_anthropic_build_user_message_with_images(_isolate_agent_list):
    inst = _make_agent(
        _AnthropicBase,
        "img-anth",
        protocol="anthropic",
        api_provider="http://mock.invalid",
    )
    msg = inst._build_user_message(
        "描述这张图",
        ["https://example.com/x.jpg", {"file_id": "file-api-z"}],
    )

    assert msg["role"] == "user"
    content = msg["content"]
    # 新 path 的顺序：text 在前，image 块在后
    assert content[0] == {"type": "text", "text": "描述这张图"}
    assert content[1] == {
        "type": "image",
        "source": {"type": "url", "url": "https://example.com/x.jpg"},
    }
    assert content[2] == {
        "type": "image",
        "source": {"type": "file", "file_id": "file-api-z"},
    }


def test_responses_build_user_message_uses_input_blocks(_isolate_agent_list):
    inst = _make_agent(
        _OpenAIResponsesBase,
        "img-resp",
        protocol="openai-responses",
        api_provider="http://mock.invalid/v1/responses",
    )
    msg = inst._build_user_message(
        "描述这张图",
        ["https://example.com/x.jpg", {"file_id": "file-api-w"}],
    )

    content = msg["content"]
    assert content[0] == {"type": "input_text", "text": "描述这张图"}
    assert content[1] == {
        "type": "input_image",
        "image_url": "https://example.com/x.jpg",
        "detail": "auto",
    }
    assert content[2] == {"type": "input_file", "file_id": "file-api-w"}


def test_responses_build_user_message_no_images(_isolate_agent_list):
    """无 images 时保持纯字符串 content（兼容 Responses transport 的 str 分支）。"""
    inst = _make_agent(
        _OpenAIResponsesBase,
        "img-resp-noimg",
        protocol="openai-responses",
        api_provider="http://mock.invalid/v1/responses",
    )
    msg = inst._build_user_message("纯文本问题", None)
    assert msg == {"role": "user", "content": "纯文本问题"}

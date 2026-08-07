---
slug: image-generation
title: 图片生成（Image Generation）
order: 11
icon: IMAGE_OUTLINED
---

# 图片生成（Image Generation）

> **v1.0.0+**。config 驱动的图片生成 —— 每个 provider 自己的"方言"（请求体结构 / 字段名 / 嵌套层级）在 `tangyuanai.config.json` 描述，**不需要写 Python 代码新增 provider**。

## 快速开始（SiliconFlow）

### 1. 安装 plugin（从中央仓库）

```bash
# 从 https://github.com/secret-tangyuan/tangyuanAI_image_plus 下载并启用 image_generation
tangyuanai plugin install image_generation

# 设置 API key（config 只写 env 变量名，不写明文）
export TANGYUAN_IMAGE_API_KEY=sk-xxx
```

### 2. 生成图片

```bash
# 顶层 API（返回图片 URL；URL 1 小时过期）
python -c "
import asyncio, tangyuanAI as t
async def main():
    g = t.ImageGenerator()
    urls = await g.generate('image_generation', prompt='a cat on the moon', image_size='1024x1024')
    for u in urls: print(u)
    await g.close()
asyncio.run(main())
"

# CLI（自动下载到本地）
python -m tangyuanAI image-gen "a cat on the moon" --image-size 1024x1024 --download --download-dir ./imgs
# → 输出本地路径 ./imgs/<hash>.png

# CLI（只打印 URL）
python -m tangyuanAI image-gen "a cat on the moon" --image-size 1024x1024
```

## 原理：每家 provider 有自己的"方言"

以 SiliconFlow 和阿里百炼为例，**同一个功能**（文生图），请求体完全不同：

**SiliconFlow**（flat body，OpenAI images 风格）：
```json
{"model": "Qwen/Qwen-Image-Edit-2509", "prompt": "a cat on the moon", "image_size": "1024x1024"}
```

**阿里百炼 / DashScope**（nested OpenAI chat body）：
```json
{
  "model": "qwen-image-3.0-pro",
  "input": {"messages": [{"role": "user", "content": [{"text": "a cat on the moon"}]}]},
  "parameters": {"size": "1024x1024", "prompt_extend": true}
}
```

**转换对照字典 = config 里的 `request_template`**。框架把 canonical 参数（`prompt` / `image_size` / `seed` / ...）套进模板 → 得到 provider 方言 → 发送 → 用 `response_image_url_path` 从响应抽 URL。

## Config Schema

```json
{
  "features": [
    {
      "name": "image_generation",        // feature 唯一名
      "type": "image_generation",        // feature 类型
      "enabled": true,
      "config": {
        "provider": "siliconflow",       // provider 名
        "api_base": "https://api.siliconflow.cn/v1/images/generations",   // ★ 完整端点 URL（含路径）+ ${env:VAR} 占位
        "api_key_env": "TANGYUAN_IMAGE_API_KEY",       // env 变量名（key 从 env 读）
        "default_model": "Qwen/Qwen-Image-Edit-2509",
        "default_image_size": "1024x1024",
        "request_template": {            // ★ 转换对照字典
          "model": "${model}",
          "prompt": "${prompt}",
          "image_size": "${image_size}",
          "negative_prompt": "${negative_prompt}"
        },
        "request_static": {"stream": false},  // 每次请求都带的静态字段
        "response_image_url_path": "data.0.url"  // ★ 从响应抽 URL 的 JSON path
      }
    }
  ]
}
```

### 模板占位符规范

`request_template` 里 `${var}` 会被 `tangyuanAI.image_generate(prompt=..., model=..., image_size=..., ...)` 的对应参数替换：

| 占位符 | 来源 |
|---|---|
| `${prompt}` | 必填，文本提示词 |
| `${model}` | 覆盖 `default_model`；未传用 config 默认 |
| `${image_size}` / `${seed}` / `${negative_prompt}` / `${num_inference_steps}` / `${guidance_scale}` / `${cfg}` / `${image}` / `${batch_size}` / ... | `image_generate()` 同名 kwargs |

- **值为 null / 未传的字段会被剔除**（不发给 provider）
- 模板里写死的字面量（如 `"stream": false`、`"prompt_extend": true`）原样保留

### JSON path 语法（`response_image_url_path`）

点分隔 + 数字索引：`data.0.url` → `data[0]["url"]`；`output.choices.0.message.content.0.image` 同理。

## 阿里百炼 / DashScope

```bash
# 安装（默认禁用，需手动 enabled）
tangyuanai plugin install image_generation_dashscope

# 设 env
export DASHSCOPE_WORKSPACE_ID=ws-xxxxx     # URL 占位符 ${env:DASHSCOPE_WORKSPACE_ID}
export DASHSCOPE_API_KEY=sk-xxx

# 编辑本地 tangyuanai.config.json：把 image_generation_dashscope 的 enabled 改 true
```

顶层 API 调用不变（provider 方言在 config 里翻译）：
```python
import asyncio, tangyuanAI as t
async def main():
    g = t.ImageGenerator()
    paths = await g.generate('image_generation_dashscope', prompt='纵向户外人像',
                              image_size='1024x1024', download=True, download_dir='./imgs')
    for p in paths: print(p)
    await g.close()
asyncio.run(main())
```

## MiniMax

```bash
# 安装（默认禁用，需手动 enabled）
tangyuanai plugin install image_generation_minimax

# 设 env
export MINIMAX_API_KEY=eyJhbGciOiJIUzI1NiJ9.xxx

# 编辑本地 tangyuanai.config.json：把 image_generation_minimax 的 enabled 改 true
```

MiniMax 方言要点（与 SiliconFlow / DashScope 都不同）：
- 端点：`POST /v1/image_generation`（base 无 `/v1`，路径自带）
- 尺寸用 `aspect_ratio`（`"16:9"` 等）不是像素 `image_size`；`width` / `height` 是像素（仅 `image-01`）
- 数量用 `n`（1-9）不是 `batch_size`
- 响应 `data.image_urls` 是 **URL 数组**；URL **24 小时**有效（比 SiliconFlow 长）

```python
import asyncio, tangyuanAI as t
async def main():
    g = t.ImageGenerator()
    urls = await g.generate('image_generation_minimax',
                             prompt='a man at venice beach, photorealistic',
                             aspect_ratio='16:9', n=3, prompt_optimizer=True)
    for u in urls: print(u)
    await g.close()
asyncio.run(main())
```

CLI（MiniMax 的 `aspect_ratio`/`n` 非 CLI 标准 flag → 用顶层 API 传 kwargs；CLI 只支持通用参数）：
```bash
python -m tangyuanAI image-gen "a man at venice beach" --feature image_generation_minimax --download
```

## 火山引擎豆包（Seedream）

```bash
# 安装（默认禁用，需手动 enabled）
tangyuanai plugin install image_generation_doubao

# 设 env（火山引擎方舟 API key）
export ARK_API_KEY=xxx

# 编辑本地 tangyuanai.config.json：把 image_generation_doubao 的 enabled 改 true
```

豆包方言要点：
- 端点：`POST https://ark.cn-beijing.volces.com/api/v3/images/generations`（OpenAI images 兼容）
- 尺寸用 `size`（`image_size` 映射）；组图用 `sequential_image_generation`（auto/disabled）
- 输入图 `image`（数组，URL 或 base64，编辑模式）
- `response_format` 支持 `url`（24h 有效）/ `b64_json`；`watermark` / `guidance_scale` / `output_format` 等
- 响应 `data[]`（含 `url` / `size`），`response_image_url_path: "data.0.url"`

```python
import asyncio, tangyuanAI as t
async def main():
    g = t.ImageGenerator()
    urls = await g.generate('image_generation_doubao',
                             prompt='夕阳下的雪山，胶片感',
                             image_size='2048x2048',
                             guidance_scale=5.0, watermark=False)
    for u in urls: print(u)
    await g.close()
asyncio.run(main())
```

## 添加新 provider（不需要写 Python）

1. 复制任一现有 `.json` 作为模板
2. 改 `name` / `provider` / `api_base` / `api_key_env` / `default_model`
3. 按目标 API 写 `request_template`（把 canonical 参数翻译成它的方言）
4. 按目标响应写 `response_image_url_path`
5. 放到 `tangyuanai.config.json` 的 `features`（或提交到中央仓库）
6. `enabled: true` 即可用

**示例**（Stability 风格，假设它的 API 是 `{text_prompts: [{text: ...}]}`）：
```json
{
  "name": "image_generation_stability",
  "type": "image_generation",
  "enabled": true,
  "config": {
    "provider": "stability",
    "api_base": "https://api.stability.ai/v2beta/stable-image/generate/core",
    "api_key_env": "STABILITY_API_KEY",
    "default_model": "core",
    "request_template": {
      "text_prompts": [{"text": "${prompt}"}],
      "negative_prompt": "${negative_prompt}",
      "width": "${image_size}"
    },
    "response_image_url_path": "image"
  }
}
```

### 通用传输配置项（一次加，对所有厂商生效）

这些不是"厂商专用 hack"，是 `HttpJsonImageProvider` 的通用旋钮：

| 字段 | 默认 | 说明 |
|---|---|---|
| `auth_scheme` | `"bearer"` | `"bearer"`（带鉴权头）\| `"none"`（公开端点不带） |
| `auth_header` | `"Authorization"` | 鉴权 header 名（厂商用 `X-API-Key` 等时改） |
| `auth_prefix` | `"Bearer "` | 鉴权 header 值前缀（厂商用 `Token ` 等时改） |
| `request_static` | `{}` | 每次请求都带的静态字段 |
| `timeout` | `60.0` | 请求超时秒 |

```json
{
  "config": {
    "provider": "vendor_x",
    "api_key_env": "VENDOR_X_KEY",
    "auth_header": "X-API-Key",      // 厂商 X 用这个 header
    "auth_prefix": "",               // 且没有前缀
    "request_template": {...},
    "response_image_url_path": "..."
  }
}
```

### 传输差异 → 插件机制（`provider_impl`）

少数厂商**传输层不同**（不是方言）——form-data 请求 / base64 响应 / 动态签名鉴权。这种**不需要改核心代码**，写一个自定义 provider 模块，config 里指过去：

```python
# my_plugins/vendor_z.py
class ZImageProvider:
    name = "z"
    def __init__(self, *, name, feature_cfg):
        self._cfg = feature_cfg
    async def generate(self, *, prompt, model=None, **kwargs) -> list[str]:
        # 自定义：multipart 请求 / base64 解码落盘 / 动态签名...
        return ["/local/path.png"]
    async def close(self):
        pass
```

```json
{
  "config": {
    "provider": "z",
    "provider_impl": "my_plugins.vendor_z:ZImageProvider",
    "api_key_env": "Z_KEY",
    "request_template": {...},   // 仍可给自定义 provider 用（feature_cfg）
    "response_image_url_path": "..."
  }
}
```

自定义 provider 实现 `ImageProvider` Protocol（`name` / `async generate(prompt, model, **kwargs) -> list[str]` / `async close()`），构造签名 `(name, feature_cfg)` 与内置一致。

## 注意事项

- **URL 1 小时过期**（SiliconFlow 提示）。用 `download=True` 或 CLI `--download` 自动落盘
- config 里只写 `api_key_env` 变量名，**不写明文 key**
- `api_base` 必须是**完整端点 URL（含路径）**，支持 `${env:VAR}` 占位符（如 DashScope 的 workspace_id 子域）

## 顶层 API

```python
import tangyuanAI as t

# ImageGenerator（每次生成前创建，用完 close）
g = t.ImageGenerator(config_path=None)  # None → cwd / $TANGYUAN_CONFIG / 默认
urls = await g.generate(
    "image_generation",           # config 里的 feature 名
    prompt="a cat on the moon",
    model=None,                   # 覆盖 default_model
    image_size="1024x1024",
    negative_prompt=None,
    seed=None,
    num_inference_steps=None,
    guidance_scale=None,
    cfg=None,
    image=None,                   # 编辑模式 base64 或 URL
    download=False,               # True → 下载到 download_dir
    download_dir="./images",
)
await g.close()

# 同步顶层辅助（asyncio.run 包装）
import asyncio
asyncio.run(g.generate("image_generation", prompt="hi"))
```

## 配置加载优先级

`tangyuanai.config.json` 路径查找：
1. 显式 `config_path=` 参数 / CLI `--config`
2. `$TANGYUAN_CONFIG` 环境变量
3. 当前目录 `./tangyuanai.config.json`

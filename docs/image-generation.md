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
        "api_base": "https://api.siliconflow.cn/v1",   // 支持 ${env:VAR} 占位
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

## 注意事项

- **URL 1 小时过期**（SiliconFlow 提示）。用 `download=True` 或 CLI `--download` 自动落盘
- config 里只写 `api_key_env` 变量名，**不写明文 key**
- `api_base` 支持 `${env:VAR}` 占位符（如 DashScope 的 workspace_id 子域）

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

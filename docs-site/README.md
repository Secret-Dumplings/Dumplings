# dumplingsAI 文档站

VitePress + FastAPI 实现，BBDDFF 浅蓝色主题。markdown 源在 `../docs/`（自动按 frontmatter 排序）。

## 启动

```bash
cd Dumplings/docs-site

# 前端（VitePress dev server）
pnpm install         # 首次
pnpm dev             # http://localhost:5173

# 后端（FastAPI，可选 — 演示用，dev 期热加载）
pnpm api             # http://localhost:8001
# 或
uv run uvicorn api.main:app --reload --port 8001
```

## 目录结构

```
docs-site/
├── .vitepress/
│   ├── config.ts            # 侧栏自动生成（读 ../docs/*.md frontmatter）
│   └── theme/
│       ├── index.ts         # 主题入口
│       └── style.css        # BBDDFF 浅蓝配色（CSS 变量）
├── api/                     # FastAPI 后端（dev 期演示）
│   ├── __init__.py
│   ├── docs_loader.py       # 读 ../docs/*.md + frontmatter
│   └── main.py              # /api/docs/list, /api/docs/{slug}, /api/search
├── package.json
└── README.md
```

## 新增文档

往 `../docs/` 加一个带 frontmatter 的 .md 即可，不用改任何代码：

```markdown
---
slug: my-new-doc
title: 我的新文档
order: 11
icon: STAR_OUTLINED
---

# 我的新文档
正文...
```

侧栏会自动按 `order` 排序，应用自动出现。

## 部署

```bash
pnpm build       # 出 dist/ 静态文件
pnpm preview     # 预览 build 产物
```

把 `docs-site/.vitepress/dist/` 丢到任意静态托管（GitHub Pages / Vercel / Nginx）。

## 关键设计

- **srcDir 指向 `../docs/`**：VitePress 直接读子模块原 markdown 源，零复制。
- **BBDDFF 浅蓝主题**：仅覆盖 CSS 变量（`--vp-c-brand-1` 等），不 fork 主题。
- **打包隔离**：`pyproject.toml` 用 `exclude-package-data` + `MANIFEST.in` 排除 `docs-site/**`，保证 wheel/sdist 干净。GA publish workflow 加了"检查 wheel 不含 docs-site"步骤做二次保险。
- **FastAPI 仅 dev 用**：VitePress 静态构建后不需要后端。后端保留为可选工具，方便未来加交互（评论、搜索增强等）。
- **图标**：frontmatter 的 `icon` 字段是 Material Icons 枚举名（`HOME_OUTLINED` / `EDIT_NOTE_OUTLINED` 等），VitePress 侧栏目前只显示文字（不显示图标）。如需图标扩展可用 `theme/components/SidebarItem.vue` 自定义。
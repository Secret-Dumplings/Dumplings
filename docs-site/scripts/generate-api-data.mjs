// scripts/generate-api-data.mjs
// 构建时从 docs-build/*.md 生成 api-data.json，供 Cloudflare Pages Functions 使用。
// 保证 /api/* 端点在 Pages 上与 FastAPI 后端行为一致。
import { readdirSync, readFileSync, writeFileSync } from 'node:fs'
import { resolve, dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'

const __dirname = dirname(fileURLToPath(import.meta.url))
const DOCS_DIR = resolve(__dirname, '../docs-build')
const OUT = resolve(__dirname, '../api-data.json')

// 极简 frontmatter 解析（与 config.ts 保持一致）
function parseFrontmatter(raw) {
  const m = raw.match(/^---\n([\s\S]*?)\n---/)
  if (!m) return {}
  const meta = {}
  for (const line of m[1].split('\n')) {
    const idx = line.indexOf(':')
    if (idx <= 0) continue
    const key = line.slice(0, idx).trim()
    const value = line.slice(idx + 1).trim().replace(/^['"]|['"]$/g, '')
    if (key in meta) continue
    meta[key] = /^\d+$/.test(value) ? Number(value) : value
  }
  return meta
}

function extractHeadings(body) {
  const out = []
  for (const line of body.split('\n')) {
    const m = line.match(/^(#{1,6})\s+(.+?)\s*$/)
    if (m) out.push({ level: m[1].length, text: m[2].trim() })
  }
  return out
}

const docs = []
for (const f of readdirSync(DOCS_DIR).filter((f) => f.endsWith('.md'))) {
  const raw = readFileSync(join(DOCS_DIR, f), 'utf-8')
  const meta = parseFrontmatter(raw)
  const body = raw.replace(/^---\n[\s\S]*?\n---\n?/, '')
  const h1 = body.match(/^#\s+(.+)$/m)
  docs.push({
    slug: String(meta.slug ?? f.replace(/\.md$/, '')),
    title: String(meta.title ?? h1?.[1]?.trim() ?? f.replace(/\.md$/, '')),
    order: Number(meta.order ?? 999),
    icon: String(meta.icon ?? 'DESCRIPTION_OUTLINED'),
    content: body.trim(),
    headings: extractHeadings(body),
  })
}
docs.sort((a, b) => a.order - b.order)
writeFileSync(OUT, JSON.stringify(docs))
console.log(`[api-data] ${docs.length} docs → api-data.json`)
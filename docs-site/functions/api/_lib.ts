// functions/api/_lib.ts
// 共享工具（_ 开头 = Pages Functions 共享文件，不生成路由）
import data from '../../api-data.json'

export interface Doc {
  slug: string
  title: string
  order: number
  icon: string
  content: string
  headings: { level: number; text: string }[]
}

export const docs = data as Doc[]

export function json(data: unknown, status = 200): Response {
  return new Response(JSON.stringify(data), {
    status,
    headers: { 'content-type': 'application/json; charset=utf-8' },
  })
}
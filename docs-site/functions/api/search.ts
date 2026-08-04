import { docs, json } from './_lib'

export const onRequestGet = ({ request }: { request: Request }) => {
  const url = new URL(request.url)
  const q = (url.searchParams.get('q') ?? '').trim().toLowerCase()
  if (!q) return json([])
  const hits = docs
    .filter((d) => d.title.toLowerCase().includes(q) || d.content.toLowerCase().includes(q))
    .map(({ slug, title }) => ({ slug, title }))
  return json(hits)
}
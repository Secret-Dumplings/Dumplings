import { docs, json } from '../_lib'

interface Params {
  slug: string
}

export const onRequestGet = ({ params }: { params: Params }) => {
  const doc = docs.find((d) => d.slug === params.slug)
  if (!doc) return json({ detail: `doc not found: ${params.slug}` }, 404)
  return json(doc)
}
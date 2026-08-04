import { json } from './_lib'

export const onRequestGet = () =>
  json({ status: 'ok', source: 'Cloudflare Pages' })
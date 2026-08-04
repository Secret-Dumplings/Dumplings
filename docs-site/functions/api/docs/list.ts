import { docs, json } from '../_lib'

export const onRequestGet = () =>
  json(docs.map(({ slug, title, order, icon }) => ({ slug, title, order, icon })))
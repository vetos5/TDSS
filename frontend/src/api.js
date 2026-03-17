import axios from 'axios'

const api = axios.create({ baseURL: '/api' })

export async function fetchContexts() {
  const { data } = await api.get('/contexts')
  return data.contexts
}

export async function evaluate(context, weights, params) {
  const { data } = await api.post('/evaluate', { context, weights, params })
  return data
}

export async function fetchInterchangeDetail(name) {
  const { data } = await api.get(`/interchange/${encodeURIComponent(name)}`, {
    params: { _t: Date.now() },
  })
  return data
}

export function blueprintUrl(name) {
  const map = {
    'Cloverleaf': 'cloverleaf.png',
    'Turbine': 'turbine.png',
    'Stack (4-Level)': 'stack.png',
    'Diamond': 'diamond.png',
    'SPUI': 'spui.png',
    'DDI': 'ddi.png',
    'Trumpet': 'trumpet.png',
    'Directional T': 'directional_t.png',
  }
  const file = map[name]
  return file ? `/blueprints/${file}` : ''
}

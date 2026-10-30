import axios from 'axios'

const api = axios.create({ baseURL: '/api' })

export async function fetchContexts() {
  const { data } = await api.get('/contexts')
  return data.contexts
}

export async function evaluate(context, weights, params, lang = 'en', extra = {}) {
  const { data } = await api.post('/evaluate', { context, weights, params, ...extra }, { params: { lang } })
  return data
}

export async function robustness(body, lang = 'en') {
  const { data } = await api.post('/robustness', body, { params: { lang } })
  return data
}

export async function fetchInterchangeDetail(name, lang = 'en') {
  const { data } = await api.get(`/interchange/${encodeURIComponent(name)}`, {
    params: { lang, _t: Date.now() },
  })
  return data
}

export async function analyseSite(body, lang = 'en') {
  const { data } = await api.post('/site/analyse', body, { params: { lang } })
  return data
}

export async function getFootprint(body, lang = 'en') {
  const { data } = await api.post('/site/footprint', body, { params: { lang } })
  return data
}

// ── Prediction model (document-trained criterion values) ─────────────────────

export async function modelStatus() {
  const { data } = await api.get('/model/status')
  return data
}

export async function retrainModel() {
  const { data } = await api.post('/model/retrain')
  return data
}

export async function uploadDocument(file, overwrite = false) {
  const form = new FormData()
  form.append('file', file)
  const { data } = await api.post('/model/documents', form, { params: { overwrite } })
  return data
}

export async function deleteDocument(name) {
  const { data } = await api.delete(`/model/documents/${encodeURIComponent(name)}`)
  return data
}

export async function predictValues(body, lang = 'en') {
  const { data } = await api.post('/model/predict', body, { params: { lang } })
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

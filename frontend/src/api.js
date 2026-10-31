import axios from 'axios'
import { i18n } from './i18n.js'
import { backendErrorKeyMap } from './locales/backendKeys.js'

const api = axios.create({ baseURL: '/api' })

// ── Errors ───────────────────────────────────────────────────────────────────
// FastAPI answers with { detail: string }, or for 422 with { detail: [{ type, loc, msg }, …] }.
// The statuses with a fixed meaning get our own wording in the current UI language.
const BUSY = 'The server is busy'

function messages() {
  const g = i18n.global
  return (g.messages.value[g.locale.value] ?? g.messages.value.en).apiErrors
}

export function errorText(e) {
  const m = messages()
  const res = e?.response
  const detail = res?.data?.detail
  if (!res) return m.network
  if (res.status === 401) return m.unauthorized
  if (res.status === 403) return m.editingDisabled
  // 503 from the concurrency caps (or a proxy's rate limit); other 503s explain themselves.
  if (res.status === 429 || (res.status === 503 && (typeof detail !== 'string' || detail.startsWith(BUSY)))) {
    return m.busy
  }
  if (Array.isArray(detail)) {
    const items = detail.map(d => {
      const loc = (d?.loc ?? []).filter(p => p !== 'body' && p !== 'query' && p !== 'path').join(' → ')
      return loc ? `${loc}: ${d?.msg}` : String(d?.msg)
    })
    return `${m.invalid} ${items.join('; ')}`
  }
  if (typeof detail === 'string' && backendErrorKeyMap[detail]) return m[backendErrorKeyMap[detail]]
  if (typeof detail === 'string' && detail) return detail
  if (res.status >= 502 && res.status <= 504) return m.unavailable
  return m.http.replace('{status}', res.status)
}

// The admin token for the corpus-editing endpoints, sent only on those requests.
const auth = token => ({ headers: token ? { Authorization: `Bearer ${token}` } : {} })

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

// Resolves if *token* is the server's admin token; 401 if not, 403 if editing is off.
export async function checkAdminToken(token) {
  await api.get('/model/auth', auth(token))
}

export async function retrainModel(token) {
  const { data } = await api.post('/model/retrain', null, auth(token))
  return data
}

export async function uploadDocument(file, overwrite = false, token = '') {
  const form = new FormData()
  form.append('file', file)
  const { data } = await api.post('/model/documents', form, { params: { overwrite }, ...auth(token) })
  return data
}

export async function deleteDocument(name, token = '') {
  const { data } = await api.delete(`/model/documents/${encodeURIComponent(name)}`, auth(token))
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

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

// Professional analyses (backend/analysis_routes.py).
export async function engineering(body, lang = 'en') {
  const { data } = await api.post('/engineering', body, { params: { lang } })
  return data
}

export async function economics(body, lang = 'en') {
  const { data } = await api.post('/economics', body, { params: { lang } })
  return data
}

export async function breakeven(body, lang = 'en') {
  const { data } = await api.post('/breakeven', body, { params: { lang } })
  return data
}

export async function group(body, lang = 'en') {
  const { data } = await api.post('/group', body, { params: { lang } })
  return data
}

export async function fetchInterchangeDetail(name, lang = 'en') {
  const { data } = await api.get(`/interchange/${encodeURIComponent(name)}`, {
    params: { lang, _t: Date.now() },
  })
  return data
}

// Procedural 3D model of an interchange (heights and piers are computed by the backend).
export async function getModel3d(name) {
  // `v` only makes the URL new: browsers hold the copy that was once served as cacheable for an hour.
  const { data } = await api.get(`/interchange/${encodeURIComponent(name)}/model3d`, { params: { v: 2 } })
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

// ── Map data fetched by the browser ──────────────────────────────────────────
// The public Overpass servers are often at capacity for this server's address. They are meant for
// browser-based tools, and each visitor has their own address and query slots, so when the server
// answers a map-data 503 the browser asks Overpass itself and sends the ways along with the
// analysis request (backend/site_routes.py, `osm`).

// The tags the server classifies ways by (OsmTagKey in backend/schemas.py).
const OSM_TAG_KEYS = ['highway', 'building', 'natural', 'waterway', 'leisure', 'boundary', 'landuse']
const MAX_OSM_WAYS = 20000 // the request's limit
const MAX_WAY_NODES = 2000
const HEDGE_AFTER_MS = 4000 // a silent server gets the next one started alongside it
const OVERPASS_TIMEOUT_MS = 35000

// 503 texts that a browser-side fetch cannot help with: the analysis slots themselves are taken
// (the request needs one either way), or the area is too dense for any server.
const NOT_MAP_DATA = ['The server is busy with other analyses', 'There is too much map data']

export function isMapDataUnavailable(e) {
  const detail = e?.response?.data?.detail
  return e?.response?.status === 503 && !(typeof detail === 'string' && NOT_MAP_DATA.some(p => detail.startsWith(p)))
}

export async function fetchOsmInBrowser({ lat, lon, radius_m }) {
  const { data } = await api.get('/site/overpass-query', { params: { lat, lon, radius_m } })
  return compactWays(await raceOverpass(data.query, data.endpoints))
}

// The servers in order, each failure starting the next at once, and a server still silent after
// HEDGE_AFTER_MS getting the next one started alongside it. The first good answer wins and the
// others are aborted.
function raceOverpass(query, endpoints) {
  return new Promise((resolve, reject) => {
    const controllers = []
    let next = 0
    let running = 0
    let settled = false
    let hedge = null
    const finish = (settle, value) => {
      if (settled) return
      settled = true
      clearTimeout(hedge)
      clearTimeout(overall)
      controllers.forEach(c => c.abort())
      settle(value)
    }
    const overall = setTimeout(() => finish(reject, new Error('Overpass timed out')), OVERPASS_TIMEOUT_MS)
    const start = () => {
      clearTimeout(hedge)
      if (settled || next >= endpoints.length) return
      const controller = new AbortController()
      controllers.push(controller)
      running++
      fetch(endpoints[next++], { method: 'POST', body: new URLSearchParams({ data: query }), signal: controller.signal })
        .then(async res => {
          if (!res.ok) throw new Error(`HTTP ${res.status}`)
          const raw = await res.json()
          // A query that hit the server's time or memory limit comes back as 200 with a remark.
          if (typeof raw?.remark === 'string' && /error/i.test(raw.remark)) throw new Error(raw.remark)
          finish(resolve, raw)
        })
        .catch(() => {
          running--
          if (next < endpoints.length) start()
          else if (running === 0) finish(reject, new Error('Every Overpass server failed'))
        })
      hedge = setTimeout(start, HEDGE_AFTER_MS)
    }
    start()
  })
}

// Ways only, with the classifying tags only, coordinates to 6 decimals (about 0.1 m): a dense
// cell's answer shrinks to a fraction of Overpass's. Buildings give way first at the way limit.
function compactWays(raw) {
  const ways = []
  for (const el of raw?.elements ?? []) {
    if (el.type !== 'way' || !Array.isArray(el.geometry)) continue
    const coords = el.geometry.filter(Boolean).slice(0, MAX_WAY_NODES)
      .map(p => [Number(p.lat.toFixed(6)), Number(p.lon.toFixed(6))])
    if (!coords.length) continue
    const tags = {}
    for (const key of OSM_TAG_KEYS) {
      if (el.tags?.[key] !== undefined) tags[key] = String(el.tags[key]).slice(0, 64)
    }
    ways.push({ id: el.id, tags, coords })
  }
  if (ways.length <= MAX_OSM_WAYS) return ways
  const others = ways.filter(w => !('building' in w.tags))
  return [...others, ...ways.filter(w => 'building' in w.tags)].slice(0, MAX_OSM_WAYS)
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

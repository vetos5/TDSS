import { ref, watch } from 'vue'

// Named snapshots of every evaluation input (useDSS().snapshotState), kept in this browser's
// localStorage, plus share links that carry one snapshot in the URL hash (#s=…), so nothing is
// stored on the server.

const STORAGE_KEY = 'tdss:scenarios'
const HASH_PREFIX = '#s='
const FORMAT = 1

function readStored() {
  try {
    const list = JSON.parse(localStorage.getItem(STORAGE_KEY) ?? '[]')
    return Array.isArray(list) ? list.filter(s => s?.id && s?.name && s?.state) : []
  } catch {
    return []
  }
}

const scenarios = ref(readStored())
// Ids of the saved scenarios shown in the comparison next to the current inputs.
const compared = ref(scenarios.value.slice(-2).map(s => s.id))

watch(scenarios, list => localStorage.setItem(STORAGE_KEY, JSON.stringify(list)), { deep: true })

function save(name, state) {
  const trimmed = name.trim()
  const existing = scenarios.value.find(s => s.name === trimmed)
  // Not crypto.randomUUID: it is missing over plain http, e.g. a phone opening the dev server.
  const id = existing?.id ?? `${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 8)}`
  const entry = { id, name: trimmed, savedAt: new Date().toISOString(), state }
  if (existing) Object.assign(existing, entry)
  else scenarios.value.push(entry)
  if (!compared.value.includes(entry.id)) compared.value.push(entry.id)
  return entry
}

function remove(id) {
  scenarios.value = scenarios.value.filter(s => s.id !== id)
  compared.value = compared.value.filter(c => c !== id)
}

function toggleCompared(id) {
  compared.value = compared.value.includes(id)
    ? compared.value.filter(c => c !== id)
    : [...compared.value, id]
}

// base64url of the UTF-8 JSON, so Ukrainian scenario names survive the round trip.
function encode(payload) {
  const bytes = new TextEncoder().encode(JSON.stringify(payload))
  let binary = ''
  bytes.forEach(b => { binary += String.fromCharCode(b) })
  return btoa(binary).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '')
}

function decode(text) {
  const binary = atob(text.replace(/-/g, '+').replace(/_/g, '/'))
  return JSON.parse(new TextDecoder().decode(Uint8Array.from(binary, c => c.charCodeAt(0))))
}

function shareUrl(state, name = '') {
  const url = new URL(window.location.href)
  url.hash = HASH_PREFIX.slice(1) + encode({ v: FORMAT, name, state })
  return url.toString()
}

// The snapshot in the current URL, or null. The hash is cleared so that a reload or later
// edits are not silently overwritten by the link again.
function takeSharedState() {
  if (!window.location.hash.startsWith(HASH_PREFIX)) return null
  let shared = null
  try {
    const payload = decode(window.location.hash.slice(HASH_PREFIX.length))
    if (payload?.v === FORMAT && payload.state) shared = payload
  } catch {
    shared = null
  }
  history.replaceState(null, '', window.location.pathname + window.location.search)
  return shared
}

export function useScenarios() {
  return { scenarios, compared, save, remove, toggleCompared, shareUrl, takeSharedState }
}

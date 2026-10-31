import { ref, reactive, computed } from 'vue'
import {
  modelStatus, retrainModel, uploadDocument, deleteDocument, predictValues, checkAdminToken, errorText,
} from '../api.js'

// Shared (module-level) state of the document-trained prediction model, like useRobustness.js:
// the Model tab, the robustness tab and App.vue all see the same status.

export const ALLOWED_EXTENSIONS = ['.csv', '.json', '.jsonl', '.txt', '.md', '.pdf']
export const MAX_UPLOAD_BYTES = 5 * 1024 * 1024 // mirrors the backend limit (413 above it)

const status = ref(null)       // last ModelStatus from /api/model/*
const prediction = ref(null)   // last /api/model/predict response
const error = ref('')          // status / document actions
const predictError = ref('')

// In-flight counters, so overlapping requests never clear a spinner that is still needed.
const pending = reactive({ status: 0, upload: 0, predict: 0, auth: 0 })
const loading = computed(() => pending.status > 0)
const uploading = computed(() => pending.upload > 0)
const predicting = computed(() => pending.predict > 0)
const unlocking = computed(() => pending.auth > 0)

// ── Admin token ──────────────────────────────────────────────────────────────
// Uploads, deletes and retrains need the server's admin token. It lives in sessionStorage (this
// tab only, gone when it closes), never in the URL or localStorage: share links copy the URL.
const TOKEN_KEY = 'tdss:adminToken'
const token = ref(readToken())
const authError = ref('')     // the unlock form's own message
const editingEnabled = computed(() => status.value?.editing_enabled === true)
const unlocked = computed(() => token.value !== '')

function readToken() {
  try {
    return sessionStorage.getItem(TOKEN_KEY) ?? ''
  } catch {
    return ''
  }
}

function setToken(value) {
  token.value = value
  try {
    if (value) sessionStorage.setItem(TOKEN_KEY, value)
    else sessionStorage.removeItem(TOKEN_KEY)
  } catch { /* storage blocked: the token then lasts until reload */ }
}

// Verifies *candidate* with GET /api/model/auth before keeping it. Returns true when unlocked.
async function unlock(candidate) {
  const value = candidate.trim()
  authError.value = ''
  // A header can only carry visible ASCII; anything else cannot be the token.
  if (!/^[\x21-\x7e]+$/.test(value)) {
    authError.value = errorText({ response: { status: 401 } })
    return false
  }
  pending.auth++
  try {
    await checkAdminToken(value)
    setToken(value)
    error.value = ''
    return true
  } catch (e) {
    authError.value = errorText(e)
    if (e?.response?.status === 403) load() // editing was switched off: show the read-only view
    return false
  } finally {
    pending.auth--
  }
}

function lock() {
  setToken('')
  authError.value = ''
}

// Status responses are ordered by the server's model revision, not by request order: a GET that
// was answered before a slower upload finished must never hide that upload's newer model.
let predictSeq = 0

function apply(result) {
  if (!status.value || result.revision >= status.value.revision) status.value = result
}

// *label* (a file name) marks one step of a batch: its error is appended, not replacing earlier
// ones, and the batch clears errors once at its start (clearError).
async function track(kind, call, label = '') {
  pending[kind]++
  if (!label) error.value = ''
  try {
    apply(await call())
    return 'ok'
  } catch (e) {
    const code = e?.response?.status
    if (kind === 'upload' && code === 409) return 'conflict'
    // A rejected token is forgotten: the view goes back to the unlock form, which says why.
    if (code === 401) {
      lock()
      authError.value = errorText(e)
      return 'error'
    }
    if (code === 403) load() // editing was switched off since the last status
    const msg = label ? `${label}: ${errorText(e)}` : errorText(e)
    error.value = label && error.value ? `${error.value}\n${msg}` : msg
    return 'error'
  } finally {
    pending[kind]--
  }
}

function clearError() {
  error.value = ''
}

function load() {
  return track('status', modelStatus)
}

function retrain() {
  return track('status', () => retrainModel(token.value))
}

// Returns 'ok' | 'conflict' (name exists and overwrite is false) | 'error'.
function upload(file, overwrite = false) {
  return track('upload', () => uploadDocument(file, overwrite, token.value), file.name)
}

function remove(name) {
  return track('status', () => deleteDocument(name, token.value))
}

async function predict(dss, lang = 'en') {
  if (!dss.selectedContext.value) return
  const id = ++predictSeq
  pending.predict++
  try {
    const result = await predictValues({ context: dss.selectedContext.value, params: { ...dss.params } }, lang)
    if (id === predictSeq) {
      prediction.value = result
      predictError.value = ''
    }
  } catch (e) {
    if (id === predictSeq) {
      predictError.value = errorText(e)
      prediction.value = null
    }
  } finally {
    pending.predict--
  }
}

export function useModel() {
  return {
    status, prediction, loading, uploading, predicting, error, predictError,
    editingEnabled, unlocked, unlocking, authError,
    load, retrain, upload, remove, predict, clearError, unlock, lock,
  }
}

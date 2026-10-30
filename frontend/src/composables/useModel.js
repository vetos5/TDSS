import { ref, reactive, computed } from 'vue'
import { modelStatus, retrainModel, uploadDocument, deleteDocument, predictValues } from '../api.js'

// Shared (module-level) state of the document-trained prediction model, like useRobustness.js:
// the Model tab, the robustness tab and App.vue all see the same status.

export const ALLOWED_EXTENSIONS = ['.csv', '.json', '.jsonl', '.txt', '.md', '.pdf']
export const MAX_UPLOAD_BYTES = 5 * 1024 * 1024 // mirrors the backend limit (413 above it)

const status = ref(null)       // last ModelStatus from /api/model/*
const prediction = ref(null)   // last /api/model/predict response
const error = ref('')          // status / document actions
const predictError = ref('')

// In-flight counters, so overlapping requests never clear a spinner that is still needed.
const pending = reactive({ status: 0, upload: 0, predict: 0 })
const loading = computed(() => pending.status > 0)
const uploading = computed(() => pending.upload > 0)
const predicting = computed(() => pending.predict > 0)

// Status responses are ordered by the server's model revision, not by request order: a GET that
// was answered before a slower upload finished must never hide that upload's newer model.
let predictSeq = 0

function errorText(e) {
  const detail = e?.response?.data?.detail
  if (detail) return typeof detail === 'string' ? detail : JSON.stringify(detail)
  return String(e?.message ?? e)
}

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
    if (kind === 'upload' && e?.response?.status === 409) return 'conflict'
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
  return track('status', retrainModel)
}

// Returns 'ok' | 'conflict' (name exists and overwrite is false) | 'error'.
function upload(file, overwrite = false) {
  return track('upload', () => uploadDocument(file, overwrite), file.name)
}

function remove(name) {
  return track('status', () => deleteDocument(name))
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
    load, retrain, upload, remove, predict, clearError,
  }
}

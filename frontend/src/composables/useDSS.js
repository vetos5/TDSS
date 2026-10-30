import { ref, reactive } from 'vue'
import { fetchContexts, evaluate } from '../api.js'

const contexts = ref([])
const selectedContext = ref('')
const loading = ref(false)
const evalData = ref(null)
const evalError = ref('')

export const ALL_METHODS = ['wsm', 'topsis', 'ahp', 'promethee', 'vikor']
export const CRITERION_KEYS = ['construction_cost_mln', 'land_area_hectares', 'throughput_vph', 'safety_index']
// Upper-triangle cells of the 4×4 AHP matrix, in criteria order.
export const AHP_PAIRS = [[0, 1], [0, 2], [0, 3], [1, 2], [1, 3], [2, 3]]

const methods = ref([...ALL_METHODS])

// Where criterion values come from: the fixed expert constants, or the document-trained
// prediction model (the backend then applies the same site rules and feasibility filter).
export const VALUE_SOURCES = ['expert', 'model']
const valueSource = ref('expert')

const weighting = reactive({
  mode: 'manual',          // manual | entropy | critic | ahp | combined
  subjective: 'manual',    // combined mode: manual | ahp
  objective: 'entropy',    // combined mode: entropy | critic
  alpha: 0.5,
})

// Saaty judgements a_ij for AHP_PAIRS (> 1: row criterion more important).
const ahpJudgements = reactive(AHP_PAIRS.map(() => 1))

const weights = reactive({
  construction_cost_mln: 30,
  land_area_hectares: 20,
  throughput_vph: 25,
  safety_index: 25,
})

const params = reactive({
  design_speed: 100,
  aadt: 45000,
  peak_factor: 10,
  num_lanes: 2,
  budget: 100,
  land_limit: 30,
  terrain: 'Flat',
  env_sensitivity: 'Medium',
})

function normalizedWeights() {
  return weightsOf(weights)
}

function ahpMatrix() {
  return ahpMatrixOf(ahpJudgements)
}

function usesAhp() {
  return weighting.mode === 'ahp' || (weighting.mode === 'combined' && weighting.subjective === 'ahp')
}

function weightingPayload() {
  return { ...weighting, ahp_matrix: usesAhp() ? ahpMatrix() : null }
}

async function loadContexts() {
  contexts.value = await fetchContexts()
  if (contexts.value.length && !selectedContext.value) {
    selectedContext.value = contexts.value[0]
  }
}

// Every input of an evaluation as plain data: what a saved scenario or a shared link holds.
function snapshotState() {
  return {
    context: selectedContext.value,
    params: { ...params },
    weights: { ...weights },
    methods: [...methods.value],
    weighting: { ...weighting },
    ahpJudgements: [...ahpJudgements],
    valueSource: valueSource.value,
  }
}

// Load a snapshot into the inputs. Unknown or missing fields keep their current value, so a
// link from an older version still opens.
function applyState(state) {
  if (!state || typeof state !== 'object') return
  if (contexts.value.includes(state.context)) selectedContext.value = state.context
  for (const [target, source] of [[params, state.params], [weights, state.weights], [weighting, state.weighting]]) {
    for (const key of Object.keys(target)) {
      if (source && typeof source[key] === typeof target[key]) target[key] = source[key]
    }
  }
  if (Array.isArray(state.methods)) {
    const known = state.methods.filter(m => ALL_METHODS.includes(m))
    if (known.length) methods.value = known
  }
  if (Array.isArray(state.ahpJudgements) && state.ahpJudgements.length === AHP_PAIRS.length &&
      state.ahpJudgements.every(v => typeof v === 'number' && v > 0)) {
    ahpJudgements.splice(0, AHP_PAIRS.length, ...state.ahpJudgements)
  }
  if (VALUE_SOURCES.includes(state.valueSource)) valueSource.value = state.valueSource
}

function weightsOf(w) {
  const total = CRITERION_KEYS.reduce((sum, k) => sum + w[k], 0)
  return Object.fromEntries(CRITERION_KEYS.map(k => [k, total === 0 ? 0.25 : w[k] / total]))
}

function ahpMatrixOf(judgements) {
  const n = CRITERION_KEYS.length
  const a = Array.from({ length: n }, () => Array(n).fill(1))
  AHP_PAIRS.forEach(([i, j], k) => {
    a[i][j] = judgements[k]
    a[j][i] = 1 / judgements[k]
  })
  return a
}

// POST /api/evaluate for a snapshot, without touching the shared state.
function evaluateState(state, lang = 'en') {
  const w = state.weighting
  const ahp = w.mode === 'ahp' || (w.mode === 'combined' && w.subjective === 'ahp')
  return evaluate(state.context, weightsOf(state.weights), { ...state.params }, lang, {
    methods: state.methods.length ? state.methods : ['wsm'],
    weighting: { ...w, ahp_matrix: ahp ? ahpMatrixOf(state.ahpJudgements) : null },
    value_source: state.valueSource,
  })
}

async function runEvaluation(lang = 'en') {
  if (!selectedContext.value) return
  loading.value = true
  try {
    evalData.value = await evaluateState(snapshotState(), lang)
    evalError.value = ''
  } catch (e) {
    // The shown ranking no longer matches the inputs; say so instead of failing silently.
    const detail = e?.response?.data?.detail
    evalError.value = detail ? (typeof detail === 'string' ? detail : JSON.stringify(detail)) : String(e)
  } finally {
    loading.value = false
  }
}

export function useDSS() {
  return {
    contexts,
    selectedContext,
    loading,
    evalData,
    evalError,
    weights,
    params,
    methods,
    weighting,
    ahpJudgements,
    valueSource,
    usesAhp,
    weightingPayload,
    normalizedWeights,
    loadContexts,
    runEvaluation,
    snapshotState,
    applyState,
    evaluateState,
  }
}

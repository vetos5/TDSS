import { ref, reactive } from 'vue'
import { fetchContexts, evaluate, errorText } from '../api.js'

const contexts = ref([])
const selectedContext = ref('')
const loading = ref(false)
const evalData = ref(null)
const evalError = ref('')

export const ALL_METHODS = ['wsm', 'topsis', 'ahp', 'promethee', 'vikor']
export const CRITERION_KEYS = ['construction_cost_mln', 'land_area_hectares', 'throughput_vph', 'safety_index']
// Upper-triangle cells of the 4×4 AHP matrix, in criteria order.
export const AHP_PAIRS = [[0, 1], [0, 2], [0, 3], [1, 2], [1, 3], [2, 3]]
// Saaty scale values offered for each AHP judgement.
export const SAATY = [9, 7, 5, 3, 1, 1 / 3, 1 / 5, 1 / 7, 1 / 9]

// The choices the input panel offers (Sidebar.vue, WeightingControls.vue).
export const DESIGN_SPEEDS = [60, 80, 100, 120, 140]
export const LANE_COUNTS = [1, 2, 3, 4, 5]
export const TERRAINS = ['Flat', 'Rolling', 'Mountainous']
export const ENV_LEVELS = ['Low', 'Medium', 'High', 'Critical']
export const WEIGHTING_MODES = ['manual', 'entropy', 'critic', 'ahp', 'combined']

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

// What a snapshot may put into each input. Pop-up menus and sliders accept only what they offer;
// the typed number fields accept any finite number within the API's bounds (backend/schemas.py),
// so a value someone typed and saved or shared comes back unchanged. Integers are rounded.
const PARAM_RULES = {
  design_speed: { oneOf: DESIGN_SPEEDS },
  aadt: { min: 0, max: 1_000_000, int: true },
  peak_factor: { min: 0, max: 100, int: true },
  num_lanes: { oneOf: LANE_COUNTS },
  budget: { min: 0, max: 1e9 },
  land_limit: { min: 0, max: 1e9 },
  terrain: { oneOf: TERRAINS },
  env_sensitivity: { oneOf: ENV_LEVELS },
}
const WEIGHT_RULES = Object.fromEntries(CRITERION_KEYS.map(k => [k, { min: 0, max: 100 }]))
const WEIGHTING_RULES = {
  mode: { oneOf: WEIGHTING_MODES },
  subjective: { oneOf: ['manual', 'ahp'] },
  objective: { oneOf: ['entropy', 'critic'] },
  alpha: { min: 0, max: 1 },
}

// *value* as the input would hold it under *rule*, or undefined if it is not acceptable.
function sanitize(value, rule) {
  if (rule.oneOf) return rule.oneOf.includes(value) ? value : undefined
  if (typeof value !== 'number' || !Number.isFinite(value)) return undefined
  const v = Math.min(rule.max, Math.max(rule.min, value))
  return rule.int ? Math.round(v) : v
}

function pick(source, rules, base) {
  const ok = source && typeof source === 'object'
  return Object.fromEntries(Object.keys(base).map(k => {
    const value = ok ? sanitize(source[k], rules[k]) : undefined
    return [k, value === undefined ? base[k] : value]
  }))
}

// A snapshot (a saved scenario or a shared link, so untrusted) as a complete, valid one: unknown,
// missing or invalid fields take their value from *base* (the current inputs), so a link from an
// older version still opens. Loading a scenario and evaluating it both go through here.
function normalizeState(state, base = snapshotState()) {
  const s = state && typeof state === 'object' ? state : {}
  const known = Array.isArray(s.methods) ? [...new Set(s.methods.filter(m => ALL_METHODS.includes(m)))] : []
  // Each judgement must be a value of the Saaty scale (as JSON may round it, compare loosely).
  const judgements = Array.isArray(s.ahpJudgements) && s.ahpJudgements.length === AHP_PAIRS.length
    ? s.ahpJudgements.map(v => SAATY.find(x => Math.abs(x - v) < 1e-9))
    : []
  return {
    context: contexts.value.includes(s.context) ? s.context : base.context,
    params: pick(s.params, PARAM_RULES, base.params),
    weights: pick(s.weights, WEIGHT_RULES, base.weights),
    methods: known.length ? known : [...base.methods],
    weighting: pick(s.weighting, WEIGHTING_RULES, base.weighting),
    ahpJudgements: judgements.length && judgements.every(v => v !== undefined) ? judgements : [...base.ahpJudgements],
    valueSource: VALUE_SOURCES.includes(s.valueSource) ? s.valueSource : base.valueSource,
  }
}

// Load a snapshot into the inputs.
function applyState(state) {
  if (!state || typeof state !== 'object') return
  const next = normalizeState(state)
  selectedContext.value = next.context
  Object.assign(params, next.params)
  Object.assign(weights, next.weights)
  Object.assign(weighting, next.weighting)
  methods.value = next.methods
  ahpJudgements.splice(0, AHP_PAIRS.length, ...next.ahpJudgements)
  valueSource.value = next.valueSource
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

// POST /api/evaluate for a snapshot as given.
function requestEvaluation(state, lang) {
  const w = state.weighting
  const ahp = w.mode === 'ahp' || (w.mode === 'combined' && w.subjective === 'ahp')
  return evaluate(state.context, weightsOf(state.weights), { ...state.params }, lang, {
    methods: state.methods.length ? state.methods : ['wsm'],
    weighting: { ...w, ahp_matrix: ahp ? ahpMatrixOf(state.ahpJudgements) : null },
    value_source: state.valueSource,
  })
}

// POST /api/evaluate for a saved or shared snapshot, read exactly as applyState would load it,
// without touching the shared state.
function evaluateState(state, lang = 'en') {
  return requestEvaluation(normalizeState(state), lang)
}

async function runEvaluation(lang = 'en') {
  if (!selectedContext.value) return
  loading.value = true
  try {
    // The live inputs go as they are: the backend validates them and the error is shown.
    evalData.value = await requestEvaluation(snapshotState(), lang)
    evalError.value = ''
  } catch (e) {
    // The shown ranking no longer matches the inputs; say so instead of failing silently.
    evalError.value = errorText(e)
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
    normalizeState,
    evaluateState,
  }
}

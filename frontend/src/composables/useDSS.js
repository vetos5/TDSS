import { ref, reactive } from 'vue'
import { fetchContexts, evaluate } from '../api.js'

const contexts = ref([])
const selectedContext = ref('')
const loading = ref(false)
const evalData = ref(null)

export const ALL_METHODS = ['wsm', 'topsis', 'ahp', 'promethee', 'vikor']
export const CRITERION_KEYS = ['construction_cost_mln', 'land_area_hectares', 'throughput_vph', 'safety_index']
// Upper-triangle cells of the 4×4 AHP matrix, in criteria order.
export const AHP_PAIRS = [[0, 1], [0, 2], [0, 3], [1, 2], [1, 3], [2, 3]]

const methods = ref([...ALL_METHODS])

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
  const total = weights.construction_cost_mln + weights.land_area_hectares +
    weights.throughput_vph + weights.safety_index
  if (total === 0) return { construction_cost_mln: 0.25, land_area_hectares: 0.25, throughput_vph: 0.25, safety_index: 0.25 }
  return {
    construction_cost_mln: weights.construction_cost_mln / total,
    land_area_hectares: weights.land_area_hectares / total,
    throughput_vph: weights.throughput_vph / total,
    safety_index: weights.safety_index / total,
  }
}

function ahpMatrix() {
  const n = CRITERION_KEYS.length
  const a = Array.from({ length: n }, () => Array(n).fill(1))
  AHP_PAIRS.forEach(([i, j], k) => {
    a[i][j] = ahpJudgements[k]
    a[j][i] = 1 / ahpJudgements[k]
  })
  return a
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

async function runEvaluation(lang = 'en') {
  if (!selectedContext.value) return
  loading.value = true
  try {
    const nw = normalizedWeights()
    evalData.value = await evaluate(selectedContext.value, nw, { ...params }, lang, {
      methods: methods.value.length ? methods.value : ['wsm'],
      weighting: weightingPayload(),
    })
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
    weights,
    params,
    methods,
    weighting,
    ahpJudgements,
    usesAhp,
    weightingPayload,
    normalizedWeights,
    loadContexts,
    runEvaluation,
  }
}

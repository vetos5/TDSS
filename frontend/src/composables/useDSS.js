import { ref, reactive } from 'vue'
import { fetchContexts, evaluate } from '../api.js'

const contexts = ref([])
const selectedContext = ref('')
const loading = ref(false)
const evalData = ref(null)

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

async function loadContexts() {
  contexts.value = await fetchContexts()
  if (contexts.value.length && !selectedContext.value) {
    selectedContext.value = contexts.value[0]
  }
}

async function runEvaluation() {
  if (!selectedContext.value) return
  loading.value = true
  try {
    const nw = normalizedWeights()
    evalData.value = await evaluate(selectedContext.value, nw, { ...params })
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
    normalizedWeights,
    loadContexts,
    runEvaluation,
  }
}

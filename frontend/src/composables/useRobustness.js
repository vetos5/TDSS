import { ref, reactive } from 'vue'
import { robustness, errorText } from '../api.js'
import { CRITERION_KEYS } from './useDSS.js'

// Defaults mirror app/data/uncertainty_defaults.py (the backend fills any criterion left out).
const DEFAULT_RANGES = {
  construction_cost_mln: { low: 0.9, high: 1.5, distribution: 'triangular' },
  land_area_hectares:    { low: 0.9, high: 1.2, distribution: 'triangular' },
  throughput_vph:        { low: 0.85, high: 1.15, distribution: 'triangular' },
  safety_index:          { low: 0.85, high: 1.15, distribution: 'triangular' },
}

const settings = reactive({
  iterations: 1000,
  seed: 42,
  weight_model: 'perturbed',   // fixed | perturbed | uniform
  concentration: 100,
  values: Object.fromEntries(CRITERION_KEYS.map(k => [k, { ...DEFAULT_RANGES[k] }])),
})

const data = ref(null)
const loading = ref(false)
const error = ref('')
let requestId = 0

function resetRanges() {
  for (const k of CRITERION_KEYS) Object.assign(settings.values[k], DEFAULT_RANGES[k])
}

// With the prediction model as the value source, send no per-criterion ranges: the backend
// then derives each range from the model's prediction intervals.
function uncertaintyPayload(valueSource) {
  const body = JSON.parse(JSON.stringify(settings))
  if (valueSource === 'model') body.values = {}
  return body
}

async function run(dss, lang = 'en') {
  if (!dss.selectedContext.value) return
  const id = ++requestId
  loading.value = true
  error.value = ''
  try {
    const result = await robustness({
      context: dss.selectedContext.value,
      weights: dss.normalizedWeights(),
      params: { ...dss.params },
      methods: dss.methods.value.length ? dss.methods.value : ['wsm'],
      weighting: dss.weightingPayload(),
      value_source: dss.valueSource.value,
      uncertainty: uncertaintyPayload(dss.valueSource.value),
    }, lang)
    if (id === requestId) data.value = result
  } catch (e) {
    if (id === requestId) {
      error.value = errorText(e)
      data.value = null
    }
  } finally {
    if (id === requestId) loading.value = false
  }
}

export function useRobustness() {
  return { settings, data, loading, error, run, resetRanges }
}

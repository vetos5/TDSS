import { reactive, watch } from 'vue'

// The stakeholders of a group decision, kept in this browser. Weights are in % as on the sliders.
const KEY = 'tdss:stakeholders'
export const MAX_STAKEHOLDERS = 8

const DEFAULTS = [
  { name: 'Road agency', influence: 2, weights: { construction_cost_mln: 45, land_area_hectares: 10, throughput_vph: 25, safety_index: 20 } },
  { name: 'City', influence: 1, weights: { construction_cost_mln: 15, land_area_hectares: 35, throughput_vph: 30, safety_index: 20 } },
  { name: 'Environmental reviewer', influence: 1, weights: { construction_cost_mln: 5, land_area_hectares: 50, throughput_vph: 5, safety_index: 40 } },
]

function load() {
  try {
    const saved = JSON.parse(localStorage.getItem(KEY))
    if (Array.isArray(saved) && saved.length >= 2) return saved.slice(0, MAX_STAKEHOLDERS)
  } catch { /* fall back to the defaults */ }
  return JSON.parse(JSON.stringify(DEFAULTS))
}

const stakeholders = reactive(load())
watch(stakeholders, v => localStorage.setItem(KEY, JSON.stringify(v)), { deep: true })

function add() {
  if (stakeholders.length >= MAX_STAKEHOLDERS) return
  stakeholders.push({ name: `Stakeholder ${stakeholders.length + 1}`, influence: 1,
    weights: { construction_cost_mln: 25, land_area_hectares: 25, throughput_vph: 25, safety_index: 25 } })
}

function remove(i) {
  if (stakeholders.length > 2) stakeholders.splice(i, 1)
}

function reset() {
  stakeholders.splice(0, stakeholders.length, ...JSON.parse(JSON.stringify(DEFAULTS)))
}

export function useGroup() {
  return { stakeholders, add, remove, reset }
}

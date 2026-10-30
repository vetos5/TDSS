<script setup>
import { computed, ref, watch } from 'vue'
import { useLocale } from '../composables/useLocale.js'
import { useScenarios } from '../composables/useScenarios.js'
import { CRITERION_KEYS } from '../composables/useDSS.js'

// The current inputs side by side with the saved scenarios ticked in the inputs panel. Each
// column is evaluated live by the backend, so a comparison never shows stale scores; rows whose
// inputs differ are highlighted.
const props = defineProps({ dss: Object, active: Boolean, dark: Boolean })

const { t, locale } = useLocale()
const { scenarios, compared } = useScenarios()

const results = ref({})   // scenario id → evaluate response | { error }
let requestId = 0

const columns = computed(() => [
  { id: 'current', name: t.value.scenarioCurrent, state: props.dss.snapshotState(), data: props.dss.evalData.value },
  ...compared.value
    .map(id => scenarios.value.find(s => s.id === id))
    .filter(Boolean)
    .map(s => ({ id: s.id, name: s.name, state: s.state, data: results.value[s.id] })),
])

async function refresh() {
  const id = ++requestId
  const saved = columns.value.filter(c => c.id !== 'current')
  const settled = await Promise.allSettled(saved.map(c => props.dss.evaluateState(c.state, locale.value)))
  if (id !== requestId) return
  results.value = Object.fromEntries(saved.map((c, i) => [c.id,
    settled[i].status === 'fulfilled' ? settled[i].value : { error: settled[i].reason?.response?.data?.detail ?? String(settled[i].reason) }]))
}

// Saved scenarios only change when one is saved, ticked or deleted; the current column follows
// the evaluation the rest of the app already runs.
watch(() => [props.active, locale.value, JSON.stringify(columns.value.slice(1).map(c => [c.id, c.state]))],
  () => { if (props.active) refresh() }, { immediate: true })

const terrainLabel = computed(() => ({ Flat: t.value.terrainFlat, Rolling: t.value.terrainRolling, Mountainous: t.value.terrainMountainous }))
const envLabel = computed(() => ({ Low: t.value.envLow, Medium: t.value.envMedium, High: t.value.envHigh, Critical: t.value.envCritical }))
const criterionLabel = computed(() => ({
  construction_cost_mln: t.value.constructionCost,
  land_area_hectares: t.value.landArea,
  throughput_vph: t.value.throughput,
  safety_index: t.value.safetyIndex,
}))

// Input rows: label and how to show the value of one column.
const inputRows = computed(() => [
  { label: t.value.taskContext, value: c => c.state.context },
  { label: t.value.designSpeed, value: c => c.state.params.design_speed },
  { label: t.value.aadt, value: c => c.state.params.aadt.toLocaleString() },
  { label: t.value.peakFactor, value: c => c.state.params.peak_factor },
  { label: t.value.numLanes, value: c => c.state.params.num_lanes },
  { label: t.value.budget, value: c => c.state.params.budget },
  { label: t.value.landLimit, value: c => c.state.params.land_limit },
  { label: t.value.terrainType, value: c => terrainLabel.value[c.state.params.terrain] },
  { label: t.value.envSensitivity, value: c => envLabel.value[c.state.params.env_sensitivity] },
  { label: t.value.methodsTitle, value: c => c.state.methods.map(m => t.value.methodLabels[m]).join(', ') },
  { label: t.value.criteriaWeights, value: c => t.value.weightingModes[c.state.weighting.mode] },
  // Weights the backend used, so objective and AHP modes show real numbers too.
  ...CRITERION_KEYS.map(k => ({
    label: `${t.value.scenarioWeightOf} ${criterionLabel.value[k]}`,
    value: c => c.data?.normalised_weights?.[k]?.toFixed(2) ?? '…',
  })),
  { label: t.value.valueSourceTitle, value: c => t.value.valueSources[c.state.valueSource] },
])

function differs(row) {
  return new Set(columns.value.map(c => String(row.value(c)))).size > 1
}

function topOf(data, method) {
  return data?.method_results?.[method]?.scores?.find(s => s.rank === 1)?.alternative_name ?? '—'
}

const methodsShown = computed(() => [...new Set(columns.value.flatMap(c => c.state.methods))])

// Every alternative that appears in any column, best first by its best rank.
const alternatives = computed(() => {
  const best = new Map()
  for (const c of columns.value) {
    (c.data?.results ?? []).forEach((r, i) => {
      best.set(r.alternative_name, Math.min(best.get(r.alternative_name) ?? Infinity, i))
    })
  }
  return [...best.keys()].sort((a, b) => best.get(a) - best.get(b))
})

function rankCell(data, name) {
  const i = (data?.results ?? []).findIndex(r => r.alternative_name === name)
  return i < 0 ? null : { rank: i + 1, score: data.results[i].total_score }
}
</script>

<template>
  <div class="space-y-4">
    <div v-if="columns.length < 2" class="card p-6 text-center">
      <p class="card-title">{{ t.scenarioCompareEmptyTitle }}</p>
      <p class="card-desc mx-auto mt-1 max-w-md">{{ t.scenarioCompareEmpty }}</p>
    </div>

    <template v-else>
      <div class="card overflow-hidden">
        <div class="table-scroll">
          <table class="table w-full text-[13px]">
            <thead>
              <tr>
                <th class="sticky left-0 z-10 bg-surface text-left">{{ t.scenarioInput }}</th>
                <th v-for="c in columns" :key="c.id" class="min-w-36 text-left">
                  {{ c.name }}
                </th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="row in inputRows" :key="row.label">
                <td class="sticky left-0 z-10 bg-surface text-muted">
                  <span class="inline-flex items-center gap-1.5">
                    <span class="h-1.5 w-1.5 shrink-0 rounded-full transition-colors"
                          :class="differs(row) ? 'bg-warn' : 'bg-transparent'"></span>
                    {{ row.label }}
                  </span>
                </td>
                <td v-for="c in columns" :key="c.id" class="num" :class="differs(row) ? 'font-medium' : 'text-muted'">
                  {{ row.value(c) }}
                </td>
              </tr>
            </tbody>
          </table>
        </div>
        <p class="border-t border-line px-4 py-2 text-xs text-subtle">
          <span class="mr-1 inline-block h-1.5 w-1.5 rounded-full bg-warn align-middle"></span>{{ t.scenarioDiffers }}
        </p>
      </div>

      <div class="card overflow-hidden">
        <div class="table-scroll">
          <table class="table w-full text-[13px]">
            <thead>
              <tr>
                <th class="sticky left-0 z-10 bg-surface text-left">{{ t.scenarioOutcome }}</th>
                <th v-for="c in columns" :key="c.id" class="min-w-36 text-left">{{ c.name }}</th>
              </tr>
            </thead>
            <tbody>
              <tr>
                <td class="sticky left-0 z-10 bg-surface text-muted">{{ t.recommended }}</td>
                <td v-for="c in columns" :key="c.id" class="font-semibold">
                  <span v-if="c.data?.error" class="font-normal text-bad">{{ c.data.error }}</span>
                  <template v-else>{{ c.data?.results?.[0]?.alternative_name ?? (c.data ? t.scenarioNoneFeasible : '…') }}</template>
                </td>
              </tr>
              <tr v-for="m in methodsShown" :key="m">
                <td class="sticky left-0 z-10 bg-surface text-muted">{{ t.scenarioTopBy }} {{ t.methodLabels[m] }}</td>
                <td v-for="c in columns" :key="c.id">{{ c.state.methods.includes(m) ? topOf(c.data, m) : '—' }}</td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>

      <div class="card overflow-hidden">
        <div class="px-4 pt-3 pb-2">
          <p class="card-title">{{ t.scenarioRanking }}</p>
          <p class="card-desc">{{ t.scenarioRankingDesc }}</p>
        </div>
        <div class="table-scroll">
          <table class="table w-full text-[13px]">
            <thead>
              <tr>
                <th class="sticky left-0 z-10 bg-surface text-left">{{ t.scenarioAlternative }}</th>
                <th v-for="c in columns" :key="c.id" class="min-w-36 text-left">{{ c.name }}</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="name in alternatives" :key="name">
                <td class="sticky left-0 z-10 bg-surface">{{ name }}</td>
                <td v-for="c in columns" :key="c.id" class="num">
                  <template v-if="rankCell(c.data, name)">
                    <span class="font-medium" :class="rankCell(c.data, name).rank === 1 ? 'text-accent-ink' : ''">
                      #{{ rankCell(c.data, name).rank }}
                    </span>
                    <span class="text-subtle"> · {{ rankCell(c.data, name).score.toFixed(3) }}</span>
                  </template>
                  <span v-else class="text-subtle">—</span>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>
    </template>
  </div>
</template>

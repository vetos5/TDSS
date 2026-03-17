<script setup>
import { computed } from 'vue'
import { blueprintUrl } from '../api.js'

const props = defineProps({
  data: Object,
  params: Object,
  dark: Boolean,
})

const winner = computed(() => props.data?.results?.[0])
const maxScore = computed(() => winner.value?.total_score || 1)

const RANK_BADGES = { 1: { bg: '#fbbf24', fg: '#78350f', icon: '🏆' }, 2: { bg: '#cbd5e1', fg: '#1e293b', icon: '🥈' }, 3: { bg: '#d6a06c', fg: '#422006', icon: '🥉' } }
const ORDINALS = ['1st', '2nd', '3rd', '4th', '5th', '6th', '7th', '8th']

const CRITERION_LABELS = {
  construction_cost_mln: 'Construction Cost',
  land_area_hectares: 'Land Area',
  throughput_vph: 'Throughput (vph)',
  safety_index: 'Safety Index',
}

function altColor(name) {
  const r = props.data?.results?.find(r => r.alternative_name === name)
  return props.dark ? (r?.color_dark || '#2dd4bf') : (r?.color || '#0f766e')
}

function isFeasible(rv) {
  return rv.construction_cost_mln <= props.params.budget && rv.land_area_hectares <= props.params.land_limit
}
</script>

<template>
  <div v-if="data">
    <h2 class="text-lg font-bold mb-4" :class="dark ? 'text-slate-100' : 'text-slate-900'">Interchange Schematic Blueprints</h2>

    <!-- Project parameters summary -->
    <div class="rounded-xl border p-4 mb-6"
         :class="dark ? 'bg-slate-800 border-slate-700' : 'bg-white border-slate-200'">
      <p class="text-[0.65rem] font-semibold uppercase tracking-wider mb-2"
         :class="dark ? 'text-slate-400' : 'text-slate-500'">Project Parameters</p>
      <div class="flex flex-wrap gap-4 text-sm" :class="dark ? 'text-slate-300' : 'text-slate-600'">
        <span>Design Speed: <strong :class="dark ? 'text-slate-100' : 'text-slate-900'">{{ params.design_speed }} km/h</strong></span>
        <span>AADT: <strong :class="dark ? 'text-slate-100' : 'text-slate-900'">{{ params.aadt.toLocaleString() }}</strong></span>
        <span>Peak Factor: <strong :class="dark ? 'text-slate-100' : 'text-slate-900'">{{ params.peak_factor }}%</strong></span>
        <span>Lanes: <strong :class="dark ? 'text-slate-100' : 'text-slate-900'">{{ params.num_lanes }}/dir</strong></span>
        <span>Budget: <strong :class="dark ? 'text-slate-100' : 'text-slate-900'">${{ params.budget }}M</strong></span>
        <span>Land: <strong :class="dark ? 'text-slate-100' : 'text-slate-900'">{{ params.land_limit }} ha</strong></span>
        <span>Terrain: <strong :class="dark ? 'text-slate-100' : 'text-slate-900'">{{ params.terrain }}</strong></span>
        <span>Env: <strong :class="dark ? 'text-slate-100' : 'text-slate-900'">{{ params.env_sensitivity }}</strong></span>
      </div>
    </div>

    <!-- Winner spotlight -->
    <div class="grid grid-cols-7 gap-6 mb-6">
      <div class="col-span-2">
        <div class="rounded-2xl border-2 p-5 text-center"
             :class="dark ? 'bg-teal-900/20 border-teal-600' : 'bg-teal-50 border-teal-600'">
          <p class="text-[0.65rem] font-semibold uppercase tracking-wider mb-1"
             :class="dark ? 'text-slate-400' : 'text-slate-500'">Recommended</p>
          <p class="text-lg font-extrabold mb-0.5" :style="{ color: altColor(winner.alternative_name) }">
            {{ winner.alternative_name }}
          </p>
          <p class="text-2xl font-bold mb-3" :class="dark ? 'text-slate-100' : 'text-slate-900'">
            WSM {{ winner.total_score.toFixed(4) }}
          </p>
          <img :src="blueprintUrl(winner.alternative_name)" :alt="winner.alternative_name"
               class="mx-auto max-h-64 object-contain mb-3" />
          <p class="text-xs font-semibold"
             :class="isFeasible(winner.raw_values) ? (dark ? 'text-teal-400' : 'text-teal-700') : 'text-red-500'">
            {{ isFeasible(winner.raw_values) ? 'Feasible' : 'Exceeds constraints' }}
          </p>
        </div>
      </div>

      <div class="col-span-5">
        <p class="font-semibold mb-1" :style="{ color: altColor(winner.alternative_name) }">
          {{ winner.alternative_name }} — Criterion Detail
        </p>
        <p class="text-sm mb-3" :class="dark ? 'text-slate-300' : 'text-slate-600'">
          {{ winner.description }}
        </p>
        <div class="overflow-x-auto rounded-xl border"
             :class="dark ? 'border-slate-700' : 'border-slate-200'">
          <table class="w-full text-sm">
            <thead>
              <tr :class="dark ? 'bg-slate-800' : 'bg-slate-50'">
                <th class="px-4 py-2 text-left font-semibold" :class="dark ? 'text-slate-300' : 'text-slate-600'">Criterion</th>
                <th class="px-4 py-2 text-left font-semibold" :class="dark ? 'text-slate-300' : 'text-slate-600'">Direction</th>
                <th class="px-4 py-2 text-left font-semibold" :class="dark ? 'text-slate-300' : 'text-slate-600'">Raw Value</th>
                <th class="px-4 py-2 text-left font-semibold" :class="dark ? 'text-slate-300' : 'text-slate-600'">Normalised</th>
                <th class="px-4 py-2 text-left font-semibold" :class="dark ? 'text-slate-300' : 'text-slate-600'">Weight</th>
                <th class="px-4 py-2 text-left font-semibold" :class="dark ? 'text-slate-300' : 'text-slate-600'">Contribution</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="crit in data.criteria" :key="crit.name"
                  class="border-t" :class="dark ? 'border-slate-700' : 'border-slate-100'">
                <td class="px-4 py-2 font-medium">{{ data.criterion_labels[crit.name] }}</td>
                <td class="px-4 py-2">{{ crit.direction === 'maximize' ? 'Maximize' : 'Minimize' }}</td>
                <td class="px-4 py-2">{{ winner.raw_values[crit.name] }} {{ crit.unit }}</td>
                <td class="px-4 py-2">{{ winner.normalised_values[crit.name]?.toFixed(3) }}</td>
                <td class="px-4 py-2">{{ data.normalised_weights[crit.name]?.toFixed(2) }}</td>
                <td class="px-4 py-2 font-semibold">{{ winner.weighted_scores[crit.name]?.toFixed(4) }}</td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>
    </div>

    <hr class="mb-6" :class="dark ? 'border-slate-700' : 'border-slate-200'" />

    <!-- All alternatives grid -->
    <p class="font-semibold text-sm mb-3" :class="dark ? 'text-slate-200' : 'text-slate-700'">All Alternatives</p>
    <div class="grid gap-4" :style="{ gridTemplateColumns: `repeat(${Math.min(data.results.length, 4)}, 1fr)` }">
      <div v-for="res in data.results" :key="res.alternative_name"
           class="rounded-xl border p-4 text-center transition-all hover:shadow-lg hover:-translate-y-0.5"
           :class="dark ? 'bg-slate-800 border-slate-700 hover:border-teal-500' : 'bg-white border-slate-200 hover:border-teal-600'">
        <span class="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[0.65rem] font-bold mb-2"
              :style="{
                background: RANK_BADGES[res.rank]?.bg || (dark ? '#334155' : '#e2e8f0'),
                color: RANK_BADGES[res.rank]?.fg || (dark ? '#94a3b8' : '#334155'),
              }">
          {{ RANK_BADGES[res.rank]?.icon }} {{ ORDINALS[res.rank - 1] }}
        </span>

        <p class="font-bold text-sm mb-0.5" :style="{ color: altColor(res.alternative_name) }">{{ res.alternative_name }}</p>
        <p class="text-xs mb-2" :class="dark ? 'text-slate-300' : 'text-slate-600'">
          WSM: <strong :class="dark ? 'text-slate-100' : 'text-slate-900'">{{ res.total_score.toFixed(4) }}</strong>
        </p>

        <img :src="blueprintUrl(res.alternative_name)" :alt="res.alternative_name"
             class="mx-auto max-h-52 object-contain mb-2" />

        <div class="w-4/5 mx-auto h-1 rounded-full overflow-hidden mt-2 mb-2"
             :class="dark ? 'bg-slate-700' : 'bg-slate-200'">
          <div class="h-full rounded-full transition-all"
               :style="{ width: Math.round((res.total_score / maxScore) * 100) + '%', background: altColor(res.alternative_name) }"></div>
        </div>

        <p class="text-[0.65rem]"
           :class="isFeasible(res.raw_values) ? (dark ? 'text-teal-400' : 'text-teal-700') : 'text-red-500'">
          {{ isFeasible(res.raw_values) ? '✓ Feasible' : '✗ Exceeds limits' }}
        </p>
        <p class="text-[0.65rem] mt-1 line-clamp-2" :class="dark ? 'text-slate-400' : 'text-slate-500'">
          {{ res.description?.slice(0, 90) }}…
        </p>
      </div>
    </div>
  </div>
</template>

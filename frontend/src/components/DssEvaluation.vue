<script setup>
import { ref, computed, watch, nextTick } from 'vue'
import { blueprintUrl, fetchInterchangeDetail } from '../api.js'
import PlotlyChart from './PlotlyChart.vue'
import LeafletMap from './LeafletMap.vue'

const props = defineProps({
  data: Object,
  params: Object,
  dark: Boolean,
})

const selectedDetail = ref(null)
const detailInfo = ref(null)

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

function barPct(score) {
  return maxScore.value > 0 ? Math.round((score / maxScore.value) * 100) : 0
}

function isFeasible(rv) {
  return rv.construction_cost_mln <= props.params.budget && rv.land_area_hectares <= props.params.land_limit
}

async function toggleDetail(name) {
  if (selectedDetail.value === name) {
    selectedDetail.value = null
    detailInfo.value = null
    return
  }
  selectedDetail.value = name
  try {
    detailInfo.value = await fetchInterchangeDetail(name)
  } catch { detailInfo.value = null }
}

watch(() => props.data?.context, () => {
  selectedDetail.value = null
  detailInfo.value = null
})

function radarData() {
  const results = props.data.results.slice(0, 2)
  const keys = Object.keys(results[0].normalised_values)
  const labels = keys.map(k => CRITERION_LABELS[k] || k)
  const traces = results.map((r, i) => ({
    type: 'scatterpolar',
    r: [...keys.map(k => r.normalised_values[k]), r.normalised_values[keys[0]]],
    theta: [...labels, labels[0]],
    fill: 'toself',
    name: `#${r.rank} ${r.alternative_name}`,
    line: { color: props.dark ? r.color_dark : r.color, width: 2.5 },
    fillcolor: `${props.dark ? r.color_dark : r.color}22`,
  }))
  const p = props.dark
  return {
    data: traces,
    layout: {
      polar: {
        bgcolor: p ? '#1e293b' : '#ffffff',
        radialaxis: { visible: true, range: [0, 1], tickvals: [0.25, 0.5, 0.75, 1], tickfont: { size: 10, color: p ? '#94a3b8' : '#334155' }, gridcolor: p ? '#334155' : '#cbd5e1' },
        angularaxis: { tickfont: { size: 11, color: p ? '#e2e8f0' : '#0f172a' }, gridcolor: p ? '#334155' : '#cbd5e1', rotation: 90, direction: 'clockwise' },
      },
      paper_bgcolor: p ? '#1e293b' : '#f8fafc', plot_bgcolor: p ? '#1e293b' : '#f8fafc',
      font: { family: 'Inter, system-ui, sans-serif', color: p ? '#e2e8f0' : '#0f172a', size: 12 },
      legend: { orientation: 'h', y: -0.15, x: 0.5, xanchor: 'center', font: { size: 11 }, bgcolor: 'rgba(0,0,0,0)' },
      margin: { l: 16, r: 16, t: 48, b: 16 },
      title: { text: `Normalised Criterion Profile — Top ${results.length}`, font: { size: 15 }, x: 0.02 },
      height: 420,
    },
  }
}

function barChartData() {
  const ordered = [...props.data.results].sort((a, b) => a.total_score - b.total_score)
  const p = props.dark
  return {
    data: [{
      type: 'bar', orientation: 'h',
      x: ordered.map(r => r.total_score),
      y: ordered.map(r => r.alternative_name),
      marker: { color: ordered.map(r => p ? r.color_dark : r.color), opacity: 0.92 },
      text: ordered.map(r => `  #${r.rank}  ${r.total_score.toFixed(4)}`),
      textposition: 'outside', textfont: { size: 11, color: p ? '#e2e8f0' : '#0f172a' },
      hovertemplate: '<b>%{y}</b><br>WSM Score: <b>%{x:.4f}</b><extra></extra>',
    }],
    layout: {
      paper_bgcolor: p ? '#1e293b' : '#f8fafc', plot_bgcolor: p ? '#1e293b' : '#f8fafc',
      font: { family: 'Inter, system-ui, sans-serif', color: p ? '#e2e8f0' : '#0f172a', size: 12 },
      xaxis: { title: 'WSM Composite Score', range: [0, 1.22], gridcolor: p ? '#334155' : '#cbd5e1', tickfont: { color: p ? '#94a3b8' : '#334155' } },
      yaxis: { gridcolor: p ? '#334155' : '#cbd5e1', tickfont: { size: 12, color: p ? '#e2e8f0' : '#0f172a' } },
      margin: { l: 16, r: 16, t: 48, b: 16 },
      title: { text: 'WSM Score Ranking', font: { size: 15 }, x: 0.02 },
      showlegend: false, height: 300,
    },
  }
}

function stackedBarData() {
  const ordered = [...props.data.results].sort((a, b) => a.total_score - b.total_score)
  const keys = Object.keys(props.data.results[0].weighted_scores)
  const COLORS = props.dark ? ['#2dd4bf', '#fb923c', '#a78bfa', '#60a5fa'] : ['#0f766e', '#ea580c', '#7c3aed', '#1d4ed8']
  const p = props.dark
  return {
    data: keys.map((k, i) => ({
      type: 'bar', orientation: 'h',
      name: CRITERION_LABELS[k] || k,
      x: ordered.map(r => r.weighted_scores[k]),
      y: ordered.map(r => r.alternative_name),
      marker: { color: COLORS[i % COLORS.length], opacity: 0.88 },
      hovertemplate: `<b>${CRITERION_LABELS[k] || k}</b><br>Contribution: <b>%{x:.4f}</b><extra></extra>`,
    })),
    layout: {
      barmode: 'stack',
      paper_bgcolor: p ? '#1e293b' : '#f8fafc', plot_bgcolor: p ? '#1e293b' : '#f8fafc',
      font: { family: 'Inter, system-ui, sans-serif', color: p ? '#e2e8f0' : '#0f172a', size: 12 },
      xaxis: { title: 'Summed Weighted Contribution', range: [0, 1.08], gridcolor: p ? '#334155' : '#cbd5e1', tickfont: { color: p ? '#94a3b8' : '#334155' } },
      yaxis: { gridcolor: p ? '#334155' : '#cbd5e1', tickfont: { size: 12, color: p ? '#e2e8f0' : '#0f172a' } },
      legend: { orientation: 'h', y: 1.02, x: 0.5, xanchor: 'center', font: { size: 11 }, bgcolor: 'rgba(0,0,0,0)' },
      margin: { l: 16, r: 16, t: 88, b: 32 },
      title: { text: 'Weighted Contribution Breakdown', font: { size: 15 }, x: 0.02 },
      height: 340,
    },
  }
}

const selResult = computed(() => props.data?.results?.find(r => r.alternative_name === selectedDetail.value))
</script>

<template>
  <div v-if="data">
    <!-- Context badge + winner banner -->
    <div class="flex items-center gap-3 mb-3">
      <span class="inline-block px-3 py-1 rounded-lg text-xs font-semibold border"
            :class="dark ? 'bg-teal-900/30 border-teal-700 text-teal-400' : 'bg-teal-50 border-teal-200 text-teal-700'">
        Context: {{ data.context }}
      </span>
    </div>

    <div class="rounded-lg border px-4 py-3 mb-6 flex items-center gap-2"
         :class="dark ? 'bg-emerald-900/20 border-emerald-700 text-emerald-300' : 'bg-emerald-50 border-emerald-200 text-emerald-800'">
      <span class="text-lg">✅</span>
      <span class="text-sm font-medium">
        Recommended: <strong>{{ winner?.alternative_name }}</strong> —
        WSM Score {{ winner?.total_score?.toFixed(4) }}
        (rank #1 of {{ data.results.length }} alternatives in "{{ data.context }}")
      </span>
    </div>

    <!-- Project params summary -->
    <div class="grid grid-cols-4 gap-3 mb-4">
      <div v-for="m in [
        { label: 'Design Speed', val: params.design_speed + ' km/h' },
        { label: 'AADT', val: params.aadt.toLocaleString() },
        { label: 'Budget Limit', val: '$' + params.budget + 'M' },
        { label: 'Land Limit', val: params.land_limit + ' ha' },
      ]" :key="m.label"
           class="rounded-xl border p-3"
           :class="dark ? 'bg-slate-800 border-slate-700' : 'bg-white border-slate-200'">
        <p class="text-[0.7rem] font-medium uppercase tracking-wide" :class="dark ? 'text-slate-400' : 'text-slate-500'">{{ m.label }}</p>
        <p class="text-lg font-bold" :class="dark ? 'text-slate-100' : 'text-slate-900'">{{ m.val }}</p>
      </div>
    </div>
    <div class="grid grid-cols-4 gap-3 mb-6">
      <div v-for="m in [
        { label: 'Peak Hour Factor', val: params.peak_factor + '%' },
        { label: 'Lanes / Direction', val: String(params.num_lanes) },
        { label: 'Terrain', val: params.terrain },
        { label: 'Env. Sensitivity', val: params.env_sensitivity },
      ]" :key="m.label"
           class="rounded-xl border p-3"
           :class="dark ? 'bg-slate-800 border-slate-700' : 'bg-white border-slate-200'">
        <p class="text-[0.7rem] font-medium uppercase tracking-wide" :class="dark ? 'text-slate-400' : 'text-slate-500'">{{ m.label }}</p>
        <p class="text-lg font-bold" :class="dark ? 'text-slate-100' : 'text-slate-900'">{{ m.val }}</p>
      </div>
    </div>

    <!-- Ranking cards -->
    <h2 class="text-lg font-bold mb-1" :class="dark ? 'text-slate-100' : 'text-slate-900'">WSM Score Ranking</h2>
    <p class="text-xs mb-4" :class="dark ? 'text-slate-400' : 'text-slate-500'">
      Click any card to view its detailed engineering profile, metrics, and real-world map.
    </p>

    <div class="grid gap-3 mb-4" :style="{ gridTemplateColumns: `repeat(${data.results.length}, 1fr)` }">
      <div v-for="(res, idx) in data.results" :key="res.alternative_name"
           class="rounded-t-2xl border p-4 text-center transition-all duration-200 cursor-pointer relative"
           :class="[
             dark ? 'bg-slate-800 border-slate-700' : 'bg-white border-slate-200',
             res.rank === 1 ? (dark ? 'border-teal-500 border-2 scale-[1.02] shadow-lg shadow-teal-500/20' : 'border-teal-600 border-2 scale-[1.02] shadow-lg shadow-teal-600/10') : '',
             selectedDetail === res.alternative_name ? (dark ? 'border-teal-400 border-2 shadow-xl shadow-teal-400/30 scale-[1.02]' : 'border-teal-600 border-2 shadow-xl shadow-teal-600/20 scale-[1.02]') : '',
             selectedDetail && selectedDetail !== res.alternative_name ? 'opacity-50 grayscale-[30%] hover:opacity-85 hover:grayscale-0' : '',
             'hover:shadow-lg hover:-translate-y-1',
           ]"
           @click="toggleDetail(res.alternative_name)">
        <!-- Rank badge -->
        <span class="inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full text-[0.7rem] font-bold uppercase tracking-wider mb-2"
              :style="{
                background: RANK_BADGES[res.rank]?.bg || (dark ? '#334155' : '#e2e8f0'),
                color: RANK_BADGES[res.rank]?.fg || (dark ? '#94a3b8' : '#334155'),
              }">
          {{ RANK_BADGES[res.rank]?.icon }} {{ ORDINALS[res.rank - 1] }}
        </span>

        <p class="font-bold text-sm mb-2" :style="{ color: altColor(res.alternative_name) }">
          {{ res.alternative_name }}
        </p>

        <img :src="blueprintUrl(res.alternative_name)" :alt="res.alternative_name + ' schematic'"
             class="mx-auto max-h-36 object-contain mb-2" />

        <p class="text-2xl font-extrabold" :class="dark ? 'text-slate-100' : 'text-slate-900'">
          {{ res.total_score.toFixed(4) }}
        </p>
        <p class="text-[0.65rem]" :class="dark ? 'text-slate-400' : 'text-slate-500'">WSM Score</p>

        <!-- Score bar -->
        <div class="w-4/5 mx-auto h-1 rounded-full overflow-hidden mt-2"
             :class="dark ? 'bg-slate-700' : 'bg-slate-200'">
          <div class="h-full rounded-full transition-all duration-500"
               :style="{ width: barPct(res.total_score) + '%', background: altColor(res.alternative_name) }"></div>
        </div>
      </div>
    </div>

    <!-- Detail buttons row -->
    <div class="grid gap-3 -mt-4 mb-6" :style="{ gridTemplateColumns: `repeat(${data.results.length}, 1fr)` }">
      <button v-for="res in data.results" :key="'btn-'+res.alternative_name"
              @click="toggleDetail(res.alternative_name)"
              class="rounded-b-xl border border-t-0 py-2 text-[0.72rem] font-semibold tracking-wide transition-colors"
              :class="selectedDetail === res.alternative_name
                ? (dark ? 'bg-teal-500 text-slate-900 border-teal-500' : 'bg-teal-600 text-white border-teal-600')
                : (dark ? 'bg-slate-800 border-slate-700 text-teal-400 hover:bg-teal-500 hover:text-slate-900' : 'bg-white border-slate-200 text-teal-700 hover:bg-teal-600 hover:text-white')">
        {{ selectedDetail === res.alternative_name ? '✖ Close Details' : '→ Detailed Analysis' }}
      </button>
    </div>

    <!-- Detailed view -->
    <div v-if="selResult" class="rounded-2xl border-2 p-6 mb-6 transition-all"
         :class="dark ? 'bg-slate-800 border-teal-500' : 'bg-white border-teal-600'">
      <div class="flex items-center gap-3 pb-4 border-b mb-4" :class="dark ? 'border-slate-700' : 'border-slate-200'">
        <span class="inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full text-[0.7rem] font-bold"
              :style="{
                background: RANK_BADGES[selResult.rank]?.bg || '#e2e8f0',
                color: RANK_BADGES[selResult.rank]?.fg || '#334155',
              }">
          {{ RANK_BADGES[selResult.rank]?.icon }} {{ ORDINALS[selResult.rank - 1] }}
        </span>
        <span class="text-lg font-bold" :style="{ color: altColor(selResult.alternative_name) }">
          Detailed Analysis: {{ selResult.alternative_name }}
        </span>
      </div>

      <!-- Criterion breakdown -->
      <div class="grid gap-3 mb-4" :style="{ gridTemplateColumns: `repeat(${data.criteria.length}, 1fr)` }">
        <div v-for="crit in data.criteria" :key="crit.name"
             class="rounded-xl border p-3"
             :class="dark ? 'bg-slate-900 border-slate-700' : 'bg-slate-50 border-slate-200'">
          <p class="text-[0.65rem] font-semibold uppercase tracking-wider mb-1"
             :class="dark ? 'text-slate-400' : 'text-slate-500'">
            {{ data.criterion_labels[crit.name] }}
          </p>
          <p class="text-base font-bold" :class="dark ? 'text-slate-100' : 'text-slate-900'">
            {{ selResult.raw_values[crit.name] }} {{ crit.unit }}
          </p>
          <div class="w-full h-1 rounded-full overflow-hidden mt-2 mb-1"
               :class="dark ? 'bg-slate-700' : 'bg-slate-200'">
            <div class="h-full rounded-full"
                 :style="{ width: (selResult.normalised_values[crit.name] * 100) + '%', background: altColor(selResult.alternative_name) }"></div>
          </div>
          <div class="flex justify-between text-[0.6rem]" :class="dark ? 'text-slate-500' : 'text-slate-400'">
            <span>norm {{ selResult.normalised_values[crit.name]?.toFixed(3) }}</span>
            <span>w·x̄ = {{ selResult.weighted_scores[crit.name]?.toFixed(4) }}</span>
          </div>
        </div>
      </div>

      <!-- Key metrics row -->
      <div class="grid grid-cols-6 gap-3 mb-4">
        <div v-for="m in [
          { l: 'WSM Score', v: selResult.total_score.toFixed(4) },
          { l: 'Cost', v: '$' + selResult.raw_values.construction_cost_mln.toFixed(1) + 'M' },
          { l: 'Throughput', v: Math.round(selResult.raw_values.throughput_vph).toLocaleString() + ' vph' },
          { l: 'Safety', v: selResult.raw_values.safety_index.toFixed(1) + ' / 10' },
          { l: 'Land Area', v: selResult.raw_values.land_area_hectares.toFixed(1) + ' ha' },
          { l: 'Feasibility', v: isFeasible(selResult.raw_values) ? 'Feasible' : 'Over limit' },
        ]" :key="m.l"
             class="rounded-xl border p-3"
             :class="dark ? 'bg-slate-800 border-slate-700' : 'bg-white border-slate-200'">
          <p class="text-[0.65rem] font-medium" :class="dark ? 'text-slate-400' : 'text-slate-500'">{{ m.l }}</p>
          <p class="text-lg font-bold" :class="dark ? 'text-slate-100' : 'text-slate-900'">{{ m.v }}</p>
        </div>
      </div>

      <!-- Description + Map row -->
      <div class="grid grid-cols-5 gap-6" v-if="detailInfo">
        <div class="col-span-3">
          <p class="text-[0.65rem] font-semibold uppercase tracking-wider mb-2"
             :class="dark ? 'text-slate-400' : 'text-slate-500'">Engineering Description</p>
          <div class="text-sm leading-relaxed mb-4" :class="dark ? 'text-slate-200' : 'text-slate-700'"
               v-html="detailInfo.engineering_desc?.replace(/\*\*(.*?)\*\*/g, '<strong class=\'text-teal-500\'>$1</strong>').replace(/\n\n/g, '<br/><br/>')">
          </div>

          <div v-if="detailInfo.pros?.length || detailInfo.cons?.length" class="grid grid-cols-2 gap-3">
            <div class="rounded-xl border p-4"
                 :class="dark ? 'bg-slate-900 border-slate-700' : 'bg-slate-50 border-slate-200'">
              <h4 class="text-xs font-bold uppercase tracking-wider mb-2"
                  :class="dark ? 'text-teal-400' : 'text-teal-700'">Advantages</h4>
              <ul class="list-disc pl-4 space-y-1 text-sm" :class="dark ? 'text-slate-200' : 'text-slate-700'">
                <li v-for="p in detailInfo.pros" :key="p">{{ p }}</li>
              </ul>
            </div>
            <div class="rounded-xl border p-4"
                 :class="dark ? 'bg-slate-900 border-slate-700' : 'bg-slate-50 border-slate-200'">
              <h4 class="text-xs font-bold uppercase tracking-wider mb-2 text-red-500">Limitations</h4>
              <ul class="list-disc pl-4 space-y-1 text-sm" :class="dark ? 'text-slate-200' : 'text-slate-700'">
                <li v-for="c in detailInfo.cons" :key="c">{{ c }}</li>
              </ul>
            </div>
          </div>
        </div>

        <div class="col-span-2">
          <LeafletMap
            :lat="detailInfo.lat"
            :lon="detailInfo.lon"
            :name="selectedDetail"
            :example="detailInfo.example_name"
            :dark="dark"
          />
          <p class="text-sm mt-2" :class="dark ? 'text-slate-200' : 'text-slate-700'">
            <strong>Real-world example:</strong> {{ detailInfo.example_name }}
          </p>
          <p class="text-xs" :class="dark ? 'text-slate-400' : 'text-slate-500'">
            Coordinates: {{ detailInfo.lat?.toFixed(4) }}°N,
            {{ Math.abs(detailInfo.lon)?.toFixed(4) }}°{{ detailInfo.lon < 0 ? 'W' : 'E' }}
            · Satellite imagery (Esri)
          </p>
        </div>
      </div>
    </div>

    <!-- Charts -->
    <div class="grid grid-cols-2 gap-6 mb-6">
      <PlotlyChart :chart="radarData()" :dark="dark" />
      <PlotlyChart :chart="barChartData()" :dark="dark" />
    </div>

    <PlotlyChart :chart="stackedBarData()" :dark="dark" class="mb-6" />

    <hr class="mb-6" :class="dark ? 'border-slate-700' : 'border-slate-200'" />

    <!-- Raw data table -->
    <h2 class="text-lg font-bold mb-3" :class="dark ? 'text-slate-100' : 'text-slate-900'">Criterion Values</h2>
    <div class="overflow-x-auto rounded-xl border mb-6"
         :class="dark ? 'border-slate-700' : 'border-slate-200'">
      <table class="w-full text-sm">
        <thead>
          <tr :class="dark ? 'bg-slate-800' : 'bg-slate-50'">
            <th class="px-4 py-2 text-left font-semibold" :class="dark ? 'text-slate-300' : 'text-slate-600'">Rank</th>
            <th class="px-4 py-2 text-left font-semibold" :class="dark ? 'text-slate-300' : 'text-slate-600'">Alternative</th>
            <th class="px-4 py-2 text-left font-semibold" :class="dark ? 'text-slate-300' : 'text-slate-600'">Cost (M USD)</th>
            <th class="px-4 py-2 text-left font-semibold" :class="dark ? 'text-slate-300' : 'text-slate-600'">Land Area (ha)</th>
            <th class="px-4 py-2 text-left font-semibold" :class="dark ? 'text-slate-300' : 'text-slate-600'">Throughput (vph)</th>
            <th class="px-4 py-2 text-left font-semibold" :class="dark ? 'text-slate-300' : 'text-slate-600'">Safety Index</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="res in data.results" :key="res.alternative_name"
              class="border-t" :class="dark ? 'border-slate-700 hover:bg-slate-800' : 'border-slate-100 hover:bg-slate-50'">
            <td class="px-4 py-2 font-medium">#{{ res.rank }}</td>
            <td class="px-4 py-2 font-semibold" :style="{ color: altColor(res.alternative_name) }">{{ res.alternative_name }}</td>
            <td class="px-4 py-2">${{ res.raw_values.construction_cost_mln.toFixed(1) }} M</td>
            <td class="px-4 py-2">{{ res.raw_values.land_area_hectares.toFixed(1) }} ha</td>
            <td class="px-4 py-2">{{ Math.round(res.raw_values.throughput_vph).toLocaleString() }}</td>
            <td class="px-4 py-2">{{ res.raw_values.safety_index.toFixed(1) }} / 10</td>
          </tr>
        </tbody>
      </table>
    </div>

    <hr class="mb-6" :class="dark ? 'border-slate-700' : 'border-slate-200'" />

    <!-- Normalised scores table -->
    <h2 class="text-lg font-bold mb-1" :class="dark ? 'text-slate-100' : 'text-slate-900'">Normalised Scores and Weighted Contributions</h2>
    <p class="text-xs mb-3" :class="dark ? 'text-slate-400' : 'text-slate-500'">
      Min-Max normalisation maps each raw value to [0, 1]. Minimize criteria are inverted so 1.0 denotes the best performer.
      Cell format: normalised x̄ᵢⱼ → weighted contribution wⱼ · x̄ᵢⱼ.
    </p>
    <div class="overflow-x-auto rounded-xl border"
         :class="dark ? 'border-slate-700' : 'border-slate-200'">
      <table class="w-full text-sm">
        <thead>
          <tr :class="dark ? 'bg-slate-800' : 'bg-slate-50'">
            <th class="px-4 py-2 text-left font-semibold" :class="dark ? 'text-slate-300' : 'text-slate-600'">Rank</th>
            <th class="px-4 py-2 text-left font-semibold" :class="dark ? 'text-slate-300' : 'text-slate-600'">Alternative</th>
            <th v-for="crit in data.criteria" :key="crit.name"
                class="px-4 py-2 text-left font-semibold" :class="dark ? 'text-slate-300' : 'text-slate-600'">
              {{ data.criterion_labels[crit.name] }}
              [{{ crit.direction === 'maximize' ? 'Max' : 'Min' }}, w={{ data.normalised_weights[crit.name]?.toFixed(2) }}]
            </th>
            <th class="px-4 py-2 text-left font-semibold" :class="dark ? 'text-slate-300' : 'text-slate-600'">WSM Score</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="res in data.results" :key="res.alternative_name"
              class="border-t" :class="dark ? 'border-slate-700 hover:bg-slate-800' : 'border-slate-100 hover:bg-slate-50'">
            <td class="px-4 py-2 font-medium">#{{ res.rank }}</td>
            <td class="px-4 py-2 font-semibold" :style="{ color: altColor(res.alternative_name) }">{{ res.alternative_name }}</td>
            <td v-for="crit in data.criteria" :key="crit.name" class="px-4 py-2">
              {{ res.normalised_values[crit.name]?.toFixed(3) }} → {{ res.weighted_scores[crit.name]?.toFixed(3) }}
            </td>
            <td class="px-4 py-2 font-bold">{{ res.total_score.toFixed(4) }}</td>
          </tr>
        </tbody>
      </table>
    </div>
  </div>
</template>

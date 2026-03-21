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
        bgcolor: 'rgba(0,0,0,0)',
        radialaxis: { visible: true, range: [0, 1], tickvals: [0.25, 0.5, 0.75, 1], tickfont: { size: 10, color: p ? '#94a3b8' : '#334155' }, gridcolor: p ? '#334155' : '#cbd5e1' },
        angularaxis: { tickfont: { size: 12, color: p ? '#e2e8f0' : '#0f172a' }, gridcolor: p ? '#334155' : '#cbd5e1', rotation: 90, direction: 'clockwise' },
      },
      paper_bgcolor: 'rgba(0,0,0,0)', plot_bgcolor: 'rgba(0,0,0,0)',
      font: { family: 'Inter, system-ui, sans-serif', color: p ? '#e2e8f0' : '#0f172a', size: 12 },
      legend: { orientation: 'h', y: -0.18, x: 0.5, xanchor: 'center', font: { size: 11 }, bgcolor: 'rgba(0,0,0,0)' },
      margin: { l: 56, r: 56, t: 56, b: 56 },
      title: { text: `Normalised Criterion Profile — Top ${results.length}`, font: { size: 15 }, x: 0.02 },
      height: 420,
    },
  }
}

function barChartData() {
  const ordered = [...props.data.results].sort((a, b) => a.total_score - b.total_score)
  const p = props.dark
  const maxLabelLen = Math.max(...ordered.map(r => r.alternative_name.length))
  const leftMargin = Math.max(160, maxLabelLen * 11)
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
      paper_bgcolor: 'rgba(0,0,0,0)', plot_bgcolor: 'rgba(0,0,0,0)',
      font: { family: 'Inter, system-ui, sans-serif', color: p ? '#e2e8f0' : '#0f172a', size: 12 },
      xaxis: { title: 'WSM Composite Score', range: [0, 1.22], gridcolor: p ? '#334155' : '#cbd5e1', tickfont: { color: p ? '#94a3b8' : '#334155' } },
      yaxis: { gridcolor: p ? '#334155' : '#cbd5e1', tickfont: { size: 12, color: p ? '#e2e8f0' : '#0f172a' }, automargin: true, ticksuffix: '  ' },
      margin: { l: leftMargin, r: 80, t: 48, b: 48 },
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
  const maxLabelLen = Math.max(...ordered.map(r => r.alternative_name.length))
  const leftMargin = Math.max(160, maxLabelLen * 11)
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
      paper_bgcolor: 'rgba(0,0,0,0)', plot_bgcolor: 'rgba(0,0,0,0)',
      font: { family: 'Inter, system-ui, sans-serif', color: p ? '#e2e8f0' : '#0f172a', size: 12 },
      xaxis: { title: 'Summed Weighted Contribution', range: [0, 1.08], gridcolor: p ? '#334155' : '#cbd5e1', tickfont: { color: p ? '#94a3b8' : '#334155' } },
      yaxis: { gridcolor: p ? '#334155' : '#cbd5e1', tickfont: { size: 12, color: p ? '#e2e8f0' : '#0f172a' }, automargin: true, ticksuffix: '  ' },
      legend: { orientation: 'h', y: 1.08, x: 0.5, xanchor: 'center', font: { size: 11 }, bgcolor: 'rgba(0,0,0,0)' },
      margin: { l: leftMargin, r: 24, t: 72, b: 48 },
      title: { text: 'Weighted Contribution Breakdown', font: { size: 15 }, x: 0.02 },
      height: 340,
    },
  }
}

const selResult = computed(() => props.data?.results?.find(r => r.alternative_name === selectedDetail.value))
</script>

<template>
  <div v-if="data" class="dss-wrapper" :class="{ 'dss-main-container': !dark }">
    <!-- Context badge + winner banner -->
    <div class="flex items-center gap-3 mb-3">
      <span class="inline-block px-3 py-1 rounded-full text-xs font-semibold"
            :class="dark
              ? 'bg-teal-900/30 border border-teal-700 text-teal-400'
              : 'bg-blue-500/10 text-blue-600 border border-blue-200/60'">
        Context: {{ data.context }}
      </span>
    </div>

    <div class="rounded-2xl px-4 py-3 mb-6 flex items-center gap-2 backdrop-blur-xl"
         :class="dark
           ? 'bg-emerald-900/20 border border-emerald-700 text-emerald-300'
           : 'bg-white/60 border border-white/80 text-emerald-700 shadow-[0_8px_30px_rgb(0,0,0,0.04)]'">
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
           class="rounded-2xl p-3 backdrop-blur-xl"
           :class="dark
             ? 'bg-slate-800 border border-slate-700'
             : 'bg-white/60 border border-white/80 shadow-[0_8px_30px_rgb(0,0,0,0.04)]'">
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
           class="rounded-2xl p-3 backdrop-blur-xl"
           :class="dark
             ? 'bg-slate-800 border border-slate-700'
             : 'bg-white/60 border border-white/80 shadow-[0_8px_30px_rgb(0,0,0,0.04)]'">
        <p class="text-[0.7rem] font-medium uppercase tracking-wide" :class="dark ? 'text-slate-400' : 'text-slate-500'">{{ m.label }}</p>
        <p class="text-lg font-bold" :class="dark ? 'text-slate-100' : 'text-slate-900'">{{ m.val }}</p>
      </div>
    </div>

    <!-- ═══ Active Parameter Adjustments ═══ -->
    <div v-if="data.adjustments && data.adjustments.length" class="rounded-2xl px-4 py-3 mb-6"
         :class="dark
           ? 'bg-amber-900/20 border border-amber-700/50'
           : 'bg-amber-50/80 border border-amber-200/80 shadow-[0_4px_16px_rgb(0,0,0,0.04)]'">
      <p class="text-[0.7rem] font-bold uppercase tracking-widest mb-2"
         :class="dark ? 'text-amber-400' : 'text-amber-600'">
        ⚙ Parameter Adjustments Applied
      </p>
      <ul class="space-y-1">
        <li v-for="note in data.adjustments" :key="note.kind"
            class="flex items-start gap-2 text-xs leading-relaxed"
            :class="dark ? 'text-amber-200' : 'text-amber-800'">
          <span class="mt-0.5 shrink-0 font-bold uppercase tracking-wide text-[0.6rem] px-1.5 py-0.5 rounded"
                :class="dark ? 'bg-amber-700/40 text-amber-300' : 'bg-amber-200 text-amber-700'">
            {{ note.kind.replace('_', ' ') }}
          </span>
          <span>{{ note.message }}</span>
        </li>
      </ul>
    </div>

    <!-- ═══ WSM Score Ranking — iOS Light Glassmorphism ═══ -->
    <div class="relative overflow-hidden rounded-[32px] p-1 mb-6">

      <!-- Glass container -->
      <div class="relative rounded-[28px] backdrop-blur-2xl p-6 lg:p-8"
           :class="dark
             ? 'bg-white/[0.06] border border-white/10'
             : 'bg-white/60 border border-white/80 shadow-[0_8px_30px_rgb(0,0,0,0.04)]'">

        <!-- Section header -->
        <h2 class="text-xl font-semibold tracking-tight mb-1"
            :class="dark ? 'text-white/90' : 'text-slate-900'">
          WSM Score Ranking
        </h2>
        <p class="text-xs tracking-wide mb-6"
           :class="dark ? 'text-white/40' : 'text-slate-500'">
          Tap any card to explore its detailed engineering profile, metrics, and real-world map.
        </p>

        <!-- Ranking cards grid -->
        <div class="grid gap-4" :style="{ gridTemplateColumns: `repeat(${data.results.length}, 1fr)` }">
          <div v-for="(res, idx) in data.results" :key="res.alternative_name"
               class="group relative flex flex-col items-center rounded-3xl border p-6 text-center cursor-pointer
                      transition-all duration-300 ease-[cubic-bezier(0.25,0.8,0.25,1)]
                      active:scale-[0.97]"
               :class="[
                 dark
                   ? (selectedDetail === res.alternative_name
                       ? 'border-teal-400/60 bg-white/15 shadow-[0_0_30px_rgba(45,212,191,0.2)] scale-[1.02]'
                       : 'border-white/10 bg-white/[0.06] hover:-translate-y-1 hover:bg-white/12')
                   : (selectedDetail === res.alternative_name
                       ? 'border-blue-400/50 bg-white/90 shadow-[0_8px_40px_rgb(59,130,246,0.12)] scale-[1.02]'
                       : 'border-white/80 bg-white/60 shadow-[0_8px_30px_rgb(0,0,0,0.04)] hover:-translate-y-1 hover:bg-white/80 hover:shadow-[0_12px_40px_rgb(0,0,0,0.07)]'),
                 selectedDetail && selectedDetail !== res.alternative_name
                   ? 'opacity-45 grayscale-[40%] hover:opacity-80 hover:grayscale-0' : '',
                 !dark && res.rank === 1 && selectedDetail !== res.alternative_name
                   ? 'border-blue-300/60 shadow-[0_8px_30px_rgb(59,130,246,0.08)]' : '',
                 dark && res.rank === 1 && selectedDetail !== res.alternative_name
                   ? 'border-amber-400/40 shadow-lg shadow-amber-500/10' : '',
               ]"
               @click="toggleDetail(res.alternative_name)">

            <!-- Rank badge — vibrant iOS pill -->
            <span class="inline-flex items-center gap-1.5 px-3 py-1 rounded-full text-[0.68rem] font-bold uppercase tracking-widest mb-3"
                  :class="[
                    res.rank === 1
                      ? (dark ? 'bg-amber-500/20 text-amber-300 border border-amber-400/20' : 'bg-blue-500 text-white shadow-[0_2px_8px_rgb(59,130,246,0.3)]')
                      : '',
                    res.rank === 2
                      ? (dark ? 'bg-slate-400/15 text-slate-300 border border-white/10' : 'bg-emerald-500 text-white shadow-[0_2px_8px_rgb(16,185,129,0.3)]')
                      : '',
                    res.rank === 3
                      ? (dark ? 'bg-orange-500/15 text-orange-300 border border-orange-400/20' : 'bg-orange-500 text-white shadow-[0_2px_8px_rgb(249,115,22,0.3)]')
                      : '',
                    res.rank > 3
                      ? (dark ? 'bg-white/10 text-white/50 border border-white/10' : 'bg-slate-200/80 text-slate-500')
                      : '',
                  ]">
              <span class="text-sm">{{ RANK_BADGES[res.rank]?.icon || '•' }}</span>
              {{ ORDINALS[res.rank - 1] }}
            </span>

            <!-- Alternative name -->
            <p class="font-semibold text-sm mb-3 tracking-tight" :style="{ color: altColor(res.alternative_name) }">
              {{ res.alternative_name }}
            </p>

            <!-- Blueprint thumbnail -->
            <div class="relative mb-4 w-full flex justify-center">
              <img :src="blueprintUrl(res.alternative_name)" :alt="res.alternative_name + ' schematic'"
                   class="max-h-36 object-contain drop-shadow-lg transition-transform duration-300 ease-[cubic-bezier(0.25,0.8,0.25,1)]
                          group-hover:scale-105" />
            </div>

            <!-- WSM Score — hero number -->
            <p class="text-3xl font-semibold tracking-tight mb-0.5"
               :class="dark ? 'text-white/90' : 'text-slate-900'">
              {{ res.total_score.toFixed(4) }}
            </p>
            <p class="text-[0.6rem] font-medium uppercase tracking-widest mb-3"
               :class="dark ? 'text-white/35' : 'text-slate-400'">
              WSM Score
            </p>

            <!-- Score progress bar -->
            <div class="w-4/5 h-1 rounded-full overflow-hidden"
                 :class="dark ? 'bg-white/10' : 'bg-black/5'">
              <div class="h-full rounded-full transition-all duration-500 ease-[cubic-bezier(0.25,0.8,0.25,1)]"
                   :style="{ width: barPct(res.total_score) + '%', background: altColor(res.alternative_name) }"></div>
            </div>

            <!-- Detail action label -->
            <span class="mt-4 inline-flex items-center gap-1 text-[0.68rem] font-semibold tracking-wide
                         transition-colors duration-200"
                  :class="selectedDetail === res.alternative_name
                    ? (dark ? 'text-teal-300' : 'text-blue-500')
                    : (dark ? 'text-white/40 group-hover:text-white/70' : 'text-slate-400 group-hover:text-slate-600')">
              {{ selectedDetail === res.alternative_name ? '✕  Close' : '→  Details' }}
            </span>
          </div>
        </div>
      </div>
    </div>

    <!-- Detailed view -->
    <div v-if="selResult" class="rounded-[28px] border-2 p-6 mb-6 transition-all backdrop-blur-2xl"
         :class="dark
           ? 'bg-slate-800 border-teal-500'
           : 'bg-white/60 border-blue-400/40 shadow-[0_8px_30px_rgb(0,0,0,0.04)]'">
      <div class="flex items-center gap-3 pb-4 border-b mb-4"
           :class="dark ? 'border-slate-700' : 'border-black/5'">
        <span class="inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full text-[0.7rem] font-bold text-white"
              :class="[
                selResult.rank === 1 ? 'bg-blue-500' : '',
                selResult.rank === 2 ? 'bg-emerald-500' : '',
                selResult.rank === 3 ? 'bg-orange-500' : '',
                selResult.rank > 3 ? 'bg-slate-400' : '',
              ]">
          {{ RANK_BADGES[selResult.rank]?.icon }} {{ ORDINALS[selResult.rank - 1] }}
        </span>
        <span class="text-lg font-bold" :style="{ color: altColor(selResult.alternative_name) }">
          Detailed Analysis: {{ selResult.alternative_name }}
        </span>
      </div>

      <!-- Criterion breakdown -->
      <div class="grid gap-3 mb-4" :style="{ gridTemplateColumns: `repeat(${data.criteria.length}, 1fr)` }">
        <div v-for="crit in data.criteria" :key="crit.name"
             class="rounded-2xl p-3 backdrop-blur-xl"
             :class="dark
               ? 'bg-slate-900 border border-slate-700'
               : 'bg-white/70 border border-white/80 shadow-[0_4px_16px_rgb(0,0,0,0.03)]'">
          <p class="text-[0.65rem] font-semibold uppercase tracking-wider mb-1"
             :class="dark ? 'text-slate-400' : 'text-slate-500'">
            {{ data.criterion_labels[crit.name] }}
          </p>
          <p class="text-base font-bold" :class="dark ? 'text-slate-100' : 'text-slate-900'">
            {{ selResult.raw_values[crit.name] }} {{ crit.unit }}
          </p>
          <div class="w-full h-1 rounded-full overflow-hidden mt-2 mb-1"
               :class="dark ? 'bg-slate-700' : 'bg-black/5'">
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
          { l: 'Feasibility', v: isFeasible(selResult.raw_values) ? '✅ Feasible' : '⚠ Over limit' },
        ]" :key="m.l"
             class="rounded-2xl p-3 backdrop-blur-xl"
             :class="dark
               ? 'bg-slate-800 border border-slate-700'
               : 'bg-white/70 border border-white/80 shadow-[0_4px_16px_rgb(0,0,0,0.03)]'">
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
            <div class="rounded-2xl p-4 backdrop-blur-xl"
                 :class="dark
                   ? 'bg-slate-900 border border-slate-700'
                   : 'bg-white/70 border border-white/80 shadow-[0_4px_16px_rgb(0,0,0,0.03)]'">
              <h4 class="text-xs font-bold uppercase tracking-wider mb-2"
                  :class="dark ? 'text-teal-400' : 'text-emerald-600'">Advantages</h4>
              <ul class="list-disc pl-4 space-y-1 text-sm" :class="dark ? 'text-slate-200' : 'text-slate-700'">
                <li v-for="p in detailInfo.pros" :key="p">{{ p }}</li>
              </ul>
            </div>
            <div class="rounded-2xl p-4 backdrop-blur-xl"
                 :class="dark
                   ? 'bg-slate-900 border border-slate-700'
                   : 'bg-white/70 border border-white/80 shadow-[0_4px_16px_rgb(0,0,0,0.03)]'">
              <h4 class="text-xs font-bold uppercase tracking-wider mb-2 text-red-500">Limitations</h4>
              <ul class="list-disc pl-4 space-y-1 text-sm" :class="dark ? 'text-slate-200' : 'text-slate-700'">
                <li v-for="c in detailInfo.cons" :key="c">{{ c }}</li>
              </ul>
            </div>
          </div>
        </div>

        <div class="col-span-2">
          <LeafletMap
            :key="selectedDetail"
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
            Coordinates: {{ Math.abs(detailInfo.lat)?.toFixed(4) }}°{{ detailInfo.lat >= 0 ? 'N' : 'S' }},
            {{ Math.abs(detailInfo.lon)?.toFixed(4) }}°{{ detailInfo.lon < 0 ? 'W' : 'E' }}
            · Satellite imagery (Esri)
          </p>
        </div>
      </div>
    </div>

    <!-- Charts -->
    <div class="grid grid-cols-2 gap-6 mb-6">
      <div class="rounded-[28px] overflow-hidden backdrop-blur-2xl"
           :class="dark
             ? 'bg-white/[0.06] border border-white/10'
             : 'bg-white/60 border border-white/80 shadow-[0_8px_30px_rgb(0,0,0,0.04)]'">
        <PlotlyChart :chart="radarData()" :dark="dark" />
      </div>
      <div class="rounded-[28px] overflow-hidden backdrop-blur-2xl"
           :class="dark
             ? 'bg-white/[0.06] border border-white/10'
             : 'bg-white/60 border border-white/80 shadow-[0_8px_30px_rgb(0,0,0,0.04)]'">
        <PlotlyChart :chart="barChartData()" :dark="dark" />
      </div>
    </div>

    <div class="rounded-[28px] overflow-hidden backdrop-blur-2xl mb-6"
         :class="dark
           ? 'bg-white/[0.06] border border-white/10'
           : 'bg-white/60 border border-white/80 shadow-[0_8px_30px_rgb(0,0,0,0.04)]'">
      <PlotlyChart :chart="stackedBarData()" :dark="dark" />
    </div>

    <hr class="mb-6" :class="dark ? 'border-slate-700' : 'border-black/5'" />

    <!-- Raw data table -->
    <h2 class="text-lg font-bold mb-3" :class="dark ? 'text-slate-100' : 'text-slate-900'">Criterion Values</h2>
    <div class="overflow-x-auto rounded-2xl border mb-6 backdrop-blur-xl"
         :class="dark
           ? 'border-slate-700'
           : 'border-white/80 bg-white/60 shadow-[0_8px_30px_rgb(0,0,0,0.04)]'">
      <table class="w-full text-sm">
        <thead>
          <tr :class="dark ? 'bg-slate-800' : 'bg-white/50'">
            <th class="px-4 py-2 text-left font-semibold" :class="dark ? 'text-slate-300' : 'text-slate-500'">Rank</th>
            <th class="px-4 py-2 text-left font-semibold" :class="dark ? 'text-slate-300' : 'text-slate-500'">Alternative</th>
            <th class="px-4 py-2 text-left font-semibold" :class="dark ? 'text-slate-300' : 'text-slate-500'">Cost (M USD)</th>
            <th class="px-4 py-2 text-left font-semibold" :class="dark ? 'text-slate-300' : 'text-slate-500'">Land Area (ha)</th>
            <th class="px-4 py-2 text-left font-semibold" :class="dark ? 'text-slate-300' : 'text-slate-500'">Throughput (vph)</th>
            <th class="px-4 py-2 text-left font-semibold" :class="dark ? 'text-slate-300' : 'text-slate-500'">Safety Index</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="res in data.results" :key="res.alternative_name"
              class="border-t" :class="dark ? 'border-slate-700 hover:bg-slate-800' : 'border-black/5 hover:bg-white/60'">
            <td class="px-4 py-2 font-medium" :class="dark ? '' : 'text-slate-900'">#{{ res.rank }}</td>
            <td class="px-4 py-2 font-semibold" :style="{ color: altColor(res.alternative_name) }">{{ res.alternative_name }}</td>
            <td class="px-4 py-2" :class="dark ? '' : 'text-slate-700'">${{ res.raw_values.construction_cost_mln.toFixed(1) }} M</td>
            <td class="px-4 py-2" :class="dark ? '' : 'text-slate-700'">{{ res.raw_values.land_area_hectares.toFixed(1) }} ha</td>
            <td class="px-4 py-2" :class="dark ? '' : 'text-slate-700'">{{ Math.round(res.raw_values.throughput_vph).toLocaleString() }}</td>
            <td class="px-4 py-2" :class="dark ? '' : 'text-slate-700'">{{ res.raw_values.safety_index.toFixed(1) }} / 10</td>
          </tr>
        </tbody>
      </table>
    </div>

    <hr class="mb-6" :class="dark ? 'border-slate-700' : 'border-black/5'" />

    <!-- Normalised scores table -->
    <h2 class="text-lg font-bold mb-1" :class="dark ? 'text-slate-100' : 'text-slate-900'">Normalised Scores and Weighted Contributions</h2>
    <p class="text-xs mb-3" :class="dark ? 'text-slate-400' : 'text-slate-500'">
      Min-Max normalisation maps each raw value to [0, 1]. Minimize criteria are inverted so 1.0 denotes the best performer.
      Cell format: normalised x̄ᵢⱼ → weighted contribution wⱼ · x̄ᵢⱼ.
    </p>
    <div class="overflow-x-auto rounded-2xl border backdrop-blur-xl"
         :class="dark
           ? 'border-slate-700'
           : 'border-white/80 bg-white/60 shadow-[0_8px_30px_rgb(0,0,0,0.04)]'">
      <table class="w-full text-sm">
        <thead>
          <tr :class="dark ? 'bg-slate-800' : 'bg-white/50'">
            <th class="px-4 py-2 text-left font-semibold" :class="dark ? 'text-slate-300' : 'text-slate-500'">Rank</th>
            <th class="px-4 py-2 text-left font-semibold" :class="dark ? 'text-slate-300' : 'text-slate-500'">Alternative</th>
            <th v-for="crit in data.criteria" :key="crit.name"
                class="px-4 py-2 text-left font-semibold" :class="dark ? 'text-slate-300' : 'text-slate-500'">
              {{ data.criterion_labels[crit.name] }}
              [{{ crit.direction === 'maximize' ? 'Max' : 'Min' }}, w={{ data.normalised_weights[crit.name]?.toFixed(2) }}]
            </th>
            <th class="px-4 py-2 text-left font-semibold" :class="dark ? 'text-slate-300' : 'text-slate-500'">WSM Score</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="res in data.results" :key="res.alternative_name"
              class="border-t" :class="dark ? 'border-slate-700 hover:bg-slate-800' : 'border-black/5 hover:bg-white/60'">
            <td class="px-4 py-2 font-medium" :class="dark ? '' : 'text-slate-900'">#{{ res.rank }}</td>
            <td class="px-4 py-2 font-semibold" :style="{ color: altColor(res.alternative_name) }">{{ res.alternative_name }}</td>
            <td v-for="crit in data.criteria" :key="crit.name" class="px-4 py-2" :class="dark ? '' : 'text-slate-700'">
              {{ res.normalised_values[crit.name]?.toFixed(3) }} → {{ res.weighted_scores[crit.name]?.toFixed(3) }}
            </td>
            <td class="px-4 py-2 font-bold" :class="dark ? '' : 'text-slate-900'">{{ res.total_score.toFixed(4) }}</td>
          </tr>
        </tbody>
      </table>
    </div>
  </div>
</template>

<style scoped>
.dss-wrapper {
  border-radius: 1.5rem;
  padding: 1.75rem 2rem;
}

.dss-main-container {
  background:
    radial-gradient(ellipse at 18% 22%, #e0e5ec 0%, transparent 52%),
    radial-gradient(ellipse at 82% 70%, #dce3ee 0%, transparent 50%),
    radial-gradient(ellipse at 50% 50%, #f0f2f6 0%, #eaecf2 100%);
}
</style>

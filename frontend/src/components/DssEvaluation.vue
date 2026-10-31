<script setup>
import { ref, computed, watch, nextTick } from 'vue'
import { blueprintUrl, fetchInterchangeDetail } from '../api.js'
import PlotlyChart from './PlotlyChart.vue'
import LeafletMap from './LeafletMap.vue'
import MethodComparison from './MethodComparison.vue'
import Icon from './Icon.vue'
import { useLocale } from '../composables/useLocale.js'
import { chartInk } from '../chartPalette.js'
import { useViewport } from '../composables/useViewport.js'

const props = defineProps({
  data: Object,
  params: Object,
  dark: Boolean,
})

const { t, locale } = useLocale()
const { narrow } = useViewport()

const selectedDetail = ref(null)
const detailInfo = ref(null)

const winner = computed(() => props.data?.results?.[0])
const maxScore = computed(() => winner.value?.total_score || 1)

const criterionLabels = computed(() => ({
  construction_cost_mln: t.value.constructionCost,
  land_area_hectares:    t.value.landArea,
  throughput_vph:        t.value.throughput,
  safety_index:          t.value.safetyIndex,
}))

function displayTerrain(val) { return t.value.terrainDisplay?.[val] ?? val }
function displayEnv(val)     { return t.value.envDisplay?.[val] ?? val }

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
    detailInfo.value = await fetchInterchangeDetail(name, locale.value)
  } catch { detailInfo.value = null }
}

watch(() => props.data?.context, () => {
  selectedDetail.value = null
  detailInfo.value = null
})

watch(locale, async () => {
  if (selectedDetail.value) {
    try {
      detailInfo.value = await fetchInterchangeDetail(selectedDetail.value, locale.value)
    } catch { detailInfo.value = null }
  }
})

// Breaks a chart label into short lines so radar axis labels fit beside a phone-width plot.
function wrapLabel(text, max = 12) {
  const lines = []
  for (const word of String(text).split(' ')) {
    const last = lines[lines.length - 1]
    if (last && last.length + word.length < max) lines[lines.length - 1] = `${last} ${word}`
    else lines.push(word)
  }
  return lines.join('<br>')
}

const radarChart = computed(() => {
  const n = narrow.value
  const results = props.data.results.slice(0, 2)
  const keys = Object.keys(results[0].normalised_values)
  const labels = keys.map(k => criterionLabels.value[k] || k).map(l => (n ? wrapLabel(l) : l))
  const traces = results.map((r, i) => ({
    type: 'scatterpolar',
    r: [...keys.map(k => r.normalised_values[k]), r.normalised_values[keys[0]]],
    theta: [...labels, labels[0]],
    fill: 'toself',
    name: `#${r.rank} ${r.alternative_name}`,
    line: { color: props.dark ? r.color_dark : r.color, width: 2.5 },
    fillcolor: `${props.dark ? r.color_dark : r.color}22`,
  }))
  const ink = chartInk(props.dark)
  return {
    data: traces,
    layout: {
      polar: {
        bgcolor: 'rgba(0,0,0,0)',
        radialaxis: { visible: true, range: [0, 1], tickvals: n ? [0.5, 1] : [0.25, 0.5, 0.75, 1], tickfont: { size: 10, color: ink.muted }, gridcolor: ink.grid, linecolor: ink.grid },
        angularaxis: { tickfont: { size: n ? 10 : 11, color: ink.text }, gridcolor: ink.grid, linecolor: ink.grid, rotation: 90, direction: 'clockwise' },
      },
      paper_bgcolor: 'rgba(0,0,0,0)', plot_bgcolor: 'rgba(0,0,0,0)',
      font: { family: ink.font, color: ink.text, size: 11 },
      legend: { orientation: 'h', y: n ? -0.24 : -0.18, x: 0.5, xanchor: 'center', yanchor: 'top', font: { size: 11, color: ink.muted }, bgcolor: 'rgba(0,0,0,0)' },
      margin: n ? { l: 60, r: 60, t: 40, b: 56 } : { l: 56, r: 56, t: 32, b: 56 },
      height: n ? 330 : 396,
    },
  }
})

const barChart = computed(() => {
  const n = narrow.value
  const ordered = [...props.data.results].sort((a, b) => a.total_score - b.total_score)
  const p = props.dark
  const ink = chartInk(p)
  return {
    data: [{
      type: 'bar', orientation: 'h',
      x: ordered.map(r => r.total_score),
      y: ordered.map(r => r.alternative_name),
      marker: { color: ordered.map(r => p ? r.color_dark : r.color), opacity: 0.92 },
      text: ordered.map(r => `  #${r.rank}  ${r.total_score.toFixed(4)}`),
      textposition: 'outside', textfont: { size: 11, color: ink.muted },
      hovertemplate: `<b>%{y}</b><br>${t.value.wsmScore}: <b>%{x:.4f}</b><extra></extra>`,
    }],
    layout: {
      paper_bgcolor: 'rgba(0,0,0,0)', plot_bgcolor: 'rgba(0,0,0,0)',
      font: { family: ink.font, color: ink.text, size: 11 },
      xaxis: { title: { text: t.value.chartBarXAxis, font: { color: ink.muted, ...(n && { size: 11 }) } }, range: [0, n ? 1.32 : 1.22], gridcolor: ink.grid, zerolinecolor: ink.grid, tickfont: { color: ink.muted } },
      yaxis: { gridcolor: ink.grid, tickfont: { size: 11, color: ink.text }, automargin: true, ticksuffix: n ? ' ' : '  ' },
      margin: n ? { l: 4, r: 12, t: 8, b: 44, pad: 2 } : { l: 8, r: 80, t: 12, b: 48, pad: 4 },
      showlegend: false, height: n ? 260 : 300,
      autosize: true,
    },
  }
})

const stackedChart = computed(() => {
  const n = narrow.value
  const ordered = [...props.data.results].sort((a, b) => a.total_score - b.total_score)
  const keys = Object.keys(props.data.results[0].weighted_scores)
  const COLORS = props.dark ? ['#2dd4bf', '#fb923c', '#a78bfa', '#60a5fa'] : ['#0f766e', '#ea580c', '#7c3aed', '#1d4ed8']
  const ink = chartInk(props.dark)
  return {
    data: keys.map((k, i) => ({
      type: 'bar', orientation: 'h',
      name: criterionLabels.value[k] || k,
      x: ordered.map(r => r.weighted_scores[k]),
      y: ordered.map(r => r.alternative_name),
      marker: { color: COLORS[i % COLORS.length], opacity: 0.88 },
      hovertemplate: `<b>${criterionLabels.value[k] || k}</b><br>${t.value.chartContribution}: <b>%{x:.4f}</b><extra></extra>`,
    })),
    layout: {
      barmode: 'stack',
      paper_bgcolor: 'rgba(0,0,0,0)', plot_bgcolor: 'rgba(0,0,0,0)',
      font: { family: ink.font, color: ink.text, size: 11 },
      xaxis: { title: { text: t.value.chartStackXAxis, font: { color: ink.muted, ...(n && { size: 11 }) } }, range: [0, 1.08], gridcolor: ink.grid, zerolinecolor: ink.grid, tickfont: { color: ink.muted } },
      yaxis: { gridcolor: ink.grid, tickfont: { size: 11, color: ink.text }, automargin: true, ticksuffix: n ? ' ' : '  ' },
      legend: n
        ? { orientation: 'h', y: -0.3, x: 0, xanchor: 'left', yanchor: 'top', font: { size: 11, color: ink.muted }, bgcolor: 'rgba(0,0,0,0)' }
        : { orientation: 'h', y: -0.32, x: 0.5, xanchor: 'center', font: { size: 11, color: ink.muted }, bgcolor: 'rgba(0,0,0,0)' },
      margin: n ? { l: 4, r: 12, t: 8, b: 40, pad: 2 } : { l: 8, r: 24, t: 12, b: 120, pad: 4 },
      height: n ? 320 : 344,
      autosize: true,
    },
  }
})

const selResult = computed(() => props.data?.results?.find(r => r.alternative_name === selectedDetail.value))

// engineering_desc uses light markdown (**bold**, *italic*, blank-line breaks). It is escaped
// first, so the only HTML in the result is the markup added here.
const HTML_ESCAPES = { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }
const descHtml = computed(() => (detailInfo.value?.engineering_desc ?? '')
  .replace(/[&<>"']/g, c => HTML_ESCAPES[c])
  .replace(/\*\*(.*?)\*\*/g, '<strong class="font-semibold text-accent-ink">$1</strong>')
  .replace(/\*(.*?)\*/g, '<em>$1</em>')
  .replace(/\n\n/g, '<br/><br/>'))
</script>

<template>
  <div v-if="data" class="space-y-4">
    <!-- The toolbar already names the context; on phones it has no room for the value source. -->
    <div v-if="data.value_source === 'model'" class="md:hidden">
      <span class="badge-accent">{{ t.valueSourceTitle }}: {{ t.valueSources.model }}</span>
    </div>

    <div class="notice notice-ok flex items-start gap-2">
      <Icon name="check" class="mt-0.5 text-sm" />
      <span>
        {{ t.recommended }}: <strong class="font-semibold">{{ winner?.alternative_name }}</strong> —
        {{ t.wsmScore }} <span class="num">{{ winner?.total_score?.toFixed(4) }}</span>
        ({{ t.rankOf }} {{ data.results.length }} {{ t.alternatives }} "{{ data.context }}")
      </span>
    </div>

    <!-- Project params summary -->
    <div class="grid grid-cols-2 gap-px overflow-hidden rounded-xl border border-line bg-line sm:grid-cols-4">
      <div v-for="m in [
        { label: t.designSpeedLabel, val: params.design_speed + ' km/h', n: true },
        { label: t.aadtLabel,        val: params.aadt.toLocaleString(), n: true },
        { label: t.budgetLimit,      val: '$' + params.budget + 'M', n: true },
        { label: t.landLimitLabel,   val: params.land_limit + ' ha', n: true },
      ]" :key="m.label" class="bg-surface px-3 py-2.5">
        <p class="eyebrow">{{ m.label }}</p>
        <p class="mt-0.5 text-sm font-semibold" :class="{ num: m.n }">{{ m.val }}</p>
      </div>
      <div v-for="m in [
        { label: t.peakHourFactor, val: params.peak_factor + '%', n: true },
        { label: t.lanesPerDir,    val: String(params.num_lanes), n: true },
        { label: t.terrain,        val: displayTerrain(params.terrain) },
        { label: t.envSens,        val: displayEnv(params.env_sensitivity) },
      ]" :key="m.label" class="bg-surface px-3 py-2.5">
        <p class="eyebrow">{{ m.label }}</p>
        <p class="mt-0.5 text-sm font-semibold" :class="{ num: m.n }">{{ m.val }}</p>
      </div>
    </div>

    <!-- Active parameter adjustments -->
    <div v-if="data.adjustments && data.adjustments.length" class="notice notice-warn">
      <p class="mb-1.5 flex items-center gap-1.5 text-xs font-medium">
        <Icon name="sliders" />
        {{ t.paramAdjustments }}
      </p>
      <ul class="space-y-1">
        <li v-for="note in data.adjustments" :key="note.kind" class="flex flex-col items-start gap-1 text-xs leading-relaxed text-fg sm:flex-row sm:gap-2">
          <span class="mt-px shrink-0 rounded bg-warn-soft px-1.5 py-0.5 text-[0.6rem] font-medium uppercase tracking-wide text-warn">
            {{ note.kind.replace('_', ' ') }}
          </span>
          <span>{{ note.message }}</span>
        </li>
      </ul>
    </div>

    <!-- WSM score ranking -->
    <section class="card p-4">
      <h2 class="card-title">{{ t.wsmRanking }}</h2>
      <p class="card-desc">{{ t.tapToExplore }}</p>

      <!-- Phones: compact list rows (thumbnail · rank + name · score). From sm: cards with the full schematic. -->
      <div class="mt-3 grid grid-cols-1 gap-2 sm:mt-4 sm:grid-cols-2 sm:gap-3 lg:grid-cols-3 xl:grid-cols-4">
        <button v-for="res in data.results" :key="res.alternative_name" type="button"
                :aria-expanded="selectedDetail === res.alternative_name"
                class="group flex w-full min-w-0 cursor-pointer items-center gap-3 rounded-lg border bg-surface p-2.5 text-left transition-[border-color,opacity,box-shadow,background-color] duration-150
                       sm:flex-col sm:items-stretch sm:gap-0 sm:p-3"
                :class="[
                  selectedDetail === res.alternative_name
                    ? 'border-accent ring-2 ring-accent/30'
                    : 'border-line hover:border-line-strong active:bg-surface-2',
                  selectedDetail && selectedDetail !== res.alternative_name ? 'opacity-60 hover:opacity-100' : '',
                ]"
                @click="toggleDetail(res.alternative_name)">
          <!-- Phone row -->
          <img :src="blueprintUrl(res.alternative_name)" alt="" aria-hidden="true"
               class="h-14 w-14 shrink-0 rounded-md object-contain sm:hidden" />
          <span class="flex min-w-0 flex-1 flex-col gap-1 sm:hidden">
            <span class="flex min-w-0 items-center gap-1.5">
              <span class="shrink-0" :class="res.rank === 1 ? 'badge-accent' : 'badge'">
                <Icon v-if="res.rank === 1" name="trophy" />
                {{ t.ordinals[res.rank - 1] }}
              </span>
              <span class="h-2 w-2 shrink-0 rounded-full" :style="{ background: altColor(res.alternative_name) }" aria-hidden="true"></span>
              <span class="truncate text-[15px] font-medium">{{ res.alternative_name }}</span>
            </span>
            <span class="flex items-center gap-2.5">
              <span class="num text-[15px] font-semibold tracking-tight">{{ res.total_score.toFixed(4) }}</span>
              <span class="h-1 flex-1 overflow-hidden rounded-full bg-surface-3">
                <span class="block h-full rounded-full transition-all duration-500"
                      :style="{ width: barPct(res.total_score) + '%', background: altColor(res.alternative_name) }"></span>
              </span>
            </span>
          </span>
          <Icon :name="selectedDetail === res.alternative_name ? 'x' : 'chevron-right'"
                class="shrink-0 text-base sm:hidden"
                :class="selectedDetail === res.alternative_name ? 'text-accent-ink' : 'text-subtle'" />

          <!-- Card (sm and up) -->
          <span class="hidden items-center justify-between gap-2 sm:flex">
            <span :class="res.rank === 1 ? 'badge-accent' : 'badge'">
              <Icon v-if="res.rank === 1" name="trophy" />
              {{ t.ordinals[res.rank - 1] }}
            </span>
            <span class="inline-flex items-center gap-0.5 text-xs transition-colors"
                  :class="selectedDetail === res.alternative_name ? 'text-accent-ink' : 'text-subtle group-hover:text-fg'">
              {{ selectedDetail === res.alternative_name ? t.close : t.details }}
              <Icon :name="selectedDetail === res.alternative_name ? 'x' : 'chevron-right'" />
            </span>
          </span>

          <span class="mt-2.5 hidden min-w-0 items-center gap-1.5 text-[13px] font-medium sm:flex">
            <span class="h-2 w-2 shrink-0 rounded-full" :style="{ background: altColor(res.alternative_name) }" aria-hidden="true"></span>
            <span class="truncate">{{ res.alternative_name }}</span>
          </span>

          <span class="my-3 hidden justify-center sm:flex">
            <img :src="blueprintUrl(res.alternative_name)" :alt="res.alternative_name + ' schematic'"
                 class="max-h-32 object-contain" />
          </span>

          <span class="mt-auto hidden items-baseline justify-between gap-2 sm:flex">
            <span class="eyebrow">{{ t.wsmScore }}</span>
            <span class="num text-lg font-semibold tracking-tight">{{ res.total_score.toFixed(4) }}</span>
          </span>
          <span class="mt-1.5 hidden h-1 overflow-hidden rounded-full bg-surface-3 sm:block">
            <span class="block h-full rounded-full transition-all duration-500"
                  :style="{ width: barPct(res.total_score) + '%', background: altColor(res.alternative_name) }"></span>
          </span>
        </button>
      </div>
    </section>

    <!-- Detailed view -->
    <section v-if="selResult" class="card p-4">
      <div class="mb-4 flex items-start gap-2 border-b border-line pb-3 sm:items-center">
        <span :class="selResult.rank === 1 ? 'badge-accent' : 'badge'">
          <Icon v-if="selResult.rank === 1" name="trophy" />
          {{ t.ordinals[selResult.rank - 1] }}
        </span>
        <span class="mt-2 h-2 w-2 shrink-0 rounded-full sm:mt-0" :style="{ background: altColor(selResult.alternative_name) }" aria-hidden="true"></span>
        <h2 class="card-title min-w-0">{{ t.detailedAnalysis }}: {{ selResult.alternative_name }}</h2>
      </div>

      <!-- Criterion breakdown -->
      <div class="mb-3 grid grid-cols-2 gap-2 sm:grid-cols-4 sm:gap-3">
        <div v-for="crit in data.criteria" :key="crit.name" class="min-w-0 rounded-lg border border-line p-3">
          <p class="eyebrow">{{ criterionLabels[crit.name] }}</p>
          <p class="num mt-0.5 text-sm font-semibold">
            {{ selResult.raw_values[crit.name] }} <span class="font-normal text-muted">{{ crit.unit }}</span>
          </p>
          <div class="mt-2 mb-1 h-1 w-full overflow-hidden rounded-full bg-surface-3">
            <div class="h-full rounded-full"
                 :style="{ width: (selResult.normalised_values[crit.name] * 100) + '%', background: altColor(selResult.alternative_name) }"></div>
          </div>
          <div class="num flex flex-wrap justify-between gap-x-2 text-[0.65rem] text-subtle">
            <span>{{ t.norm }} {{ selResult.normalised_values[crit.name]?.toFixed(3) }}</span>
            <span>w·x̄ = {{ selResult.weighted_scores[crit.name]?.toFixed(4) }}</span>
          </div>
        </div>
      </div>

      <div class="mb-4 grid grid-cols-2 gap-px overflow-hidden rounded-lg border border-line bg-line sm:grid-cols-3 lg:grid-cols-6">
        <div v-for="m in [
          { l: t.wsmScore,    v: selResult.total_score.toFixed(4), n: true },
          { l: t.cost,        v: '$' + selResult.raw_values.construction_cost_mln.toFixed(1) + 'M', n: true },
          { l: t.throughput,  v: Math.round(selResult.raw_values.throughput_vph).toLocaleString() + ' vph', n: true },
          { l: t.safetyIndex, v: selResult.raw_values.safety_index.toFixed(1) + ' / 10', n: true },
          { l: t.landArea,    v: selResult.raw_values.land_area_hectares.toFixed(1) + ' ha', n: true },
          { l: t.feasibility, v: isFeasible(selResult.raw_values) ? t.feasible : t.overLimit,
            tone: isFeasible(selResult.raw_values) ? 'text-ok' : 'text-bad' },
        ]" :key="m.l" class="bg-surface px-3 py-2.5">
          <p class="text-xs text-muted">{{ m.l }}</p>
          <p class="mt-0.5 text-sm font-semibold" :class="[m.n ? 'num' : '', m.tone]">{{ m.v }}</p>
        </div>
      </div>

      <!-- Description + Map row -->
      <div class="grid grid-cols-1 gap-4 md:grid-cols-5" v-if="detailInfo">
        <div class="md:col-span-3">
          <p class="eyebrow mb-1.5">{{ t.engineeringDesc }}</p>
          <div class="mb-4 text-[13px] leading-relaxed break-words text-fg"
               v-html="descHtml">
          </div>

          <div v-if="detailInfo.pros?.length || detailInfo.cons?.length" class="grid grid-cols-1 gap-3 sm:grid-cols-2">
            <div class="rounded-lg border border-line p-3">
              <h4 class="mb-1.5 text-xs font-medium text-ok">{{ t.advantages }}</h4>
              <ul class="list-disc space-y-1 pl-4 text-[13px] text-fg marker:text-subtle">
                <li v-for="p in detailInfo.pros" :key="p">{{ p }}</li>
              </ul>
            </div>
            <div class="rounded-lg border border-line p-3">
              <h4 class="mb-1.5 text-xs font-medium text-bad">{{ t.limitations }}</h4>
              <ul class="list-disc space-y-1 pl-4 text-[13px] text-fg marker:text-subtle">
                <li v-for="c in detailInfo.cons" :key="c">{{ c }}</li>
              </ul>
            </div>
          </div>
        </div>

        <div class="md:col-span-2">
          <LeafletMap
            :key="selectedDetail"
            :lat="detailInfo.lat"
            :lon="detailInfo.lon"
            :name="selectedDetail"
            :example="detailInfo.example_name"
            :dark="dark"
          />
          <p class="mt-2 text-[13px]">
            <span class="font-medium">{{ t.realWorldExample }}:</span> {{ detailInfo.example_name }}
          </p>
          <p class="mt-0.5 text-xs text-muted">
            {{ t.coordinates }}: <span class="num">{{ Math.abs(detailInfo.lat)?.toFixed(4) }}°{{ detailInfo.lat >= 0 ? 'N' : 'S' }},
            {{ Math.abs(detailInfo.lon)?.toFixed(4) }}°{{ detailInfo.lon < 0 ? 'W' : 'E' }}</span>
            · {{ t.satellite }}
          </p>
        </div>
      </div>
    </section>

    <!-- Multi-method comparison -->
    <MethodComparison :data="data" :dark="dark" />

    <!-- Charts -->
    <div class="grid grid-cols-1 gap-4 md:grid-cols-2">
      <section class="card overflow-hidden">
        <h2 class="card-title px-4 pt-4">{{ t.chartRadarTitle }} {{ Math.min(data.results.length, 2) }}</h2>
        <PlotlyChart :chart="radarChart" :dark="dark" />
      </section>
      <section class="card overflow-hidden">
        <h2 class="card-title px-4 pt-4">{{ t.chartBarTitle }}</h2>
        <PlotlyChart :chart="barChart" :dark="dark" />
      </section>
    </div>

    <section class="card overflow-hidden">
      <h2 class="card-title px-4 pt-4">{{ t.chartStackTitle }}</h2>
      <PlotlyChart :chart="stackedChart" :dark="dark" />
    </section>

    <!-- Raw data table -->
    <section class="card overflow-hidden">
      <div class="border-b border-line px-4 py-3">
        <h2 class="card-title">{{ t.criterionValues }}</h2>
      </div>
      <div class="table-scroll">
        <table class="table border-separate border-spacing-0 [&_td]:whitespace-nowrap">
          <thead>
            <tr>
              <th>{{ t.rank }}</th>
              <th class="sticky-col">{{ t.alternative }}</th>
              <th class="text-right">{{ t.cost }}</th>
              <th class="text-right">{{ t.landAreaCol }}</th>
              <th class="text-right">{{ t.throughputCol }}</th>
              <th class="text-right">{{ t.safetyCol }}</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="res in data.results" :key="res.alternative_name">
              <td class="num text-muted">#{{ res.rank }}</td>
              <td class="sticky-col font-medium">
                <span class="mr-1.5 inline-block h-2 w-2 rounded-full align-middle" :style="{ background: altColor(res.alternative_name) }" aria-hidden="true"></span>{{ res.alternative_name }}
              </td>
              <td class="num text-right">${{ res.raw_values.construction_cost_mln.toFixed(1) }} M</td>
              <td class="num text-right">{{ res.raw_values.land_area_hectares.toFixed(1) }} ha</td>
              <td class="num text-right">{{ Math.round(res.raw_values.throughput_vph).toLocaleString() }}</td>
              <td class="num text-right">{{ res.raw_values.safety_index.toFixed(1) }} / 10</td>
            </tr>
          </tbody>
        </table>
      </div>
    </section>

    <!-- Normalised scores table -->
    <section class="card overflow-hidden">
      <div class="border-b border-line px-4 py-3">
        <h2 class="card-title">{{ t.normScores }}</h2>
        <p class="card-desc">{{ t.normDesc }}</p>
      </div>
      <div class="table-scroll">
        <table class="table border-separate border-spacing-0 [&_td]:whitespace-nowrap">
          <thead>
            <tr>
              <th>{{ t.rank }}</th>
              <th class="sticky-col">{{ t.alternative }}</th>
              <th v-for="crit in data.criteria" :key="crit.name" class="text-right">
                {{ criterionLabels[crit.name] }}
                <span class="num block text-subtle md:inline">[{{ crit.direction === 'maximize' ? 'Max' : 'Min' }}, w={{ data.normalised_weights[crit.name]?.toFixed(2) }}]</span>
              </th>
              <th class="text-right">{{ t.wsmScore }}</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="res in data.results" :key="res.alternative_name">
              <td class="num text-muted">#{{ res.rank }}</td>
              <td class="sticky-col font-medium">
                <span class="mr-1.5 inline-block h-2 w-2 rounded-full align-middle" :style="{ background: altColor(res.alternative_name) }" aria-hidden="true"></span>{{ res.alternative_name }}
              </td>
              <td v-for="crit in data.criteria" :key="crit.name" class="num text-right">
                {{ res.normalised_values[crit.name]?.toFixed(3) }} <span class="text-subtle">→</span> {{ res.weighted_scores[crit.name]?.toFixed(3) }}
              </td>
              <td class="num text-right font-semibold">{{ res.total_score.toFixed(4) }}</td>
            </tr>
          </tbody>
        </table>
      </div>
    </section>
  </div>
</template>

<style scoped>
/* The alternative column stays put while the numbers scroll sideways on phones. */
.sticky-col {
  position: sticky;
  left: 0;
  z-index: 1;
  background-color: var(--surface);
  box-shadow: inset -1px 0 var(--line);
}
tbody tr:nth-child(even) .sticky-col {
  background-image: linear-gradient(color-mix(in oklab, var(--surface-2) 40%, transparent), color-mix(in oklab, var(--surface-2) 40%, transparent));
}
</style>

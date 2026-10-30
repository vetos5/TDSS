<script setup>
import { computed, ref, watch, onMounted } from 'vue'
import PlotlyChart from './PlotlyChart.vue'
import Icon from './Icon.vue'
import { useLocale } from '../composables/useLocale.js'
import { useRobustness } from '../composables/useRobustness.js'
import { useModel } from '../composables/useModel.js'
import { useViewport } from '../composables/useViewport.js'
import { CRITERION_KEYS } from '../composables/useDSS.js'
import { METHOD_COLORS, SURFACE, chartInk, rankColors } from '../chartPalette.js'

const props = defineProps({
  dss: Object,
  active: Boolean,
  dark: Boolean,
})

const { t, locale } = useLocale()
const rob = useRobustness()
const { settings } = rob
const model = useModel()
const { narrow } = useViewport()

const selectedMethod = ref('wsm')
const sweepCriterion = ref(CRITERION_KEYS[0])
let stale = true
let timer = null

const modelMode = computed(() => props.dss.valueSource.value === 'model')
const intervalPct = computed(() => Math.round((model.status.value?.interval_level ?? 0.9) * 100))

// ── Running ──────────────────────────────────────────────────────────────────
function schedule(delay = 500) {
  stale = true
  if (!props.active) return
  clearTimeout(timer)
  timer = setTimeout(() => {
    stale = false
    rob.run(props.dss, locale.value)
  }, delay)
}

watch(() => props.active, a => { if (a && (stale || !rob.data.value)) schedule(0) }, { immediate: true })

// Warm the tab once in the background so the first visit opens on results, not a spinner.
// Later input changes still only re-run while the tab is visible.
onMounted(() => {
  const warm = () => {
    if (props.active || rob.data.value || rob.loading.value) return
    stale = false
    rob.run(props.dss, locale.value)
  }
  setTimeout(() => (window.requestIdleCallback ?? (f => f()))(warm), 1500)
})
watch(
  [
    () => props.dss.selectedContext.value,
    () => ({ ...props.dss.weights }),
    () => ({ ...props.dss.params }),
    () => [...props.dss.methods.value],
    () => ({ ...props.dss.weighting }),
    () => [...props.dss.ahpJudgements],
    () => JSON.stringify(settings),
    () => props.dss.valueSource.value,
    locale,
  ],
  () => schedule(),
  { deep: true },
)

// Model-sourced values and ranges change whenever the model is refitted.
watch(() => model.status.value?.revision, (now, before) => {
  if (before && now !== before && modelMode.value) schedule()
})

// In model mode the value ranges come from the model's prediction intervals; load the model
// status once so the hint can name the interval level.
watch(modelMode, m => { if (m && !model.status.value) model.load() }, { immediate: true })

// Keep the per-method views on a method that was actually run.
watch(() => props.dss.methods.value, ms => {
  if (!ms.includes(selectedMethod.value)) selectedMethod.value = ms[0]
}, { immediate: true })

// ── Helpers ──────────────────────────────────────────────────────────────────
const data = computed(() => rob.data.value)
const ink = computed(() => chartInk(props.dark))
const surface = computed(() => SURFACE[props.dark ? 'dark' : 'light'])
const methodIds = computed(() => Object.keys(data.value?.smaa ?? {}))
const methodLabel = id => t.value.methodLabels?.[id] ?? id
const methodColor = id => METHOD_COLORS[props.dark ? 'dark' : 'light'][id] ?? '#64748b'
const altColor = name => (props.dark ? data.value?.colors_dark : data.value?.colors)?.[name] ?? '#64748b'
const pct = (v, d = 0) => (v == null ? '—' : `${(v * 100).toFixed(d)}%`)

const criterionLabel = computed(() => ({
  construction_cost_mln: t.value.constructionCost,
  land_area_hectares:    t.value.landArea,
  throughput_vph:        t.value.throughput,
  safety_index:          t.value.safetyIndex,
}))

const smaa = computed(() => data.value?.smaa?.[selectedMethod.value])
const sens = computed(() => data.value?.sensitivity?.[selectedMethod.value])
const nAlts = computed(() => data.value?.alternatives?.length ?? 0)
const top = computed(() => smaa.value?.alternatives?.[0])

function baseLayout(height) {
  return {
    paper_bgcolor: 'rgba(0,0,0,0)', plot_bgcolor: 'rgba(0,0,0,0)',
    font: { family: ink.value.font, color: ink.value.text, size: narrow.value ? 11 : 12 },
    margin: { l: 16, r: 24, t: 8, b: 48 },
    height,
    autosize: true,
    hoverlabel: { font: { family: ink.value.font } },
  }
}

// Horizontal legend under the plot; on phones it's anchored to the bottom of the figure so
// wrapped rows never collide with the x-axis labels.
function bottomLegend(y) {
  const legend = { orientation: 'h', x: 0, bgcolor: 'rgba(0,0,0,0)' }
  return narrow.value ? { ...legend, xanchor: 'left', yref: 'container', y: 0, yanchor: 'bottom' } : { ...legend, y }
}

// ── Value-range editor (shown as ± percentages) ─────────────────────────────
// In model mode the editor is read-only and shows the ranges the backend actually used.
function shownRange(k) {
  return modelMode.value ? (data.value?.value_uncertainty?.[k] ?? null) : settings.values[k]
}
function lowPct(k) {
  const r = shownRange(k)
  if (!r) return ''
  const v = (1 - r.low) * 100
  return modelMode.value ? +v.toFixed(1) : Math.round(v)
}
function highPct(k) {
  const r = shownRange(k)
  if (!r) return ''
  const v = (r.high - 1) * 100
  return modelMode.value ? +v.toFixed(1) : Math.round(v)
}
function setLow(k, v) { settings.values[k].low = Math.min(Math.max(1 - Number(v) / 100, 0.05), 1) }
function setHigh(k, v) { settings.values[k].high = Math.min(Math.max(1 + Number(v) / 100, 1), 10) }

// ── Headline numbers ─────────────────────────────────────────────────────────
const critical = computed(() => sens.value?.critical_criterion)
const winnerRisk = computed(() => (top.value ? data.value.exceedance[top.value.alternative_name] : null))

// ── Chart: rank acceptability (stacked 100 % bars) ──────────────────────────
const acceptabilityChart = computed(() => {
  const rows = smaa.value.alternatives
  const colors = rankColors(nAlts.value, props.dark)
  return {
    data: colors.map((color, r) => ({
      type: 'bar',
      orientation: 'h',
      name: `${t.value.rankWord} ${r + 1}`,
      y: rows.map(a => a.alternative_name),
      x: rows.map(a => a.rank_acceptability[r] * 100),
      marker: { color, line: { color: surface.value, width: 2 } },
      hovertemplate: `<b>%{y}</b><br>${t.value.rankWord} ${r + 1}: %{x:.1f}%<extra></extra>`,
    })),
    layout: {
      ...baseLayout(narrow.value ? Math.max(200, 44 * rows.length + 120) : Math.max(160, 64 * rows.length + 90)),
      barmode: 'stack',
      margin: narrow.value ? { l: 4, r: 12, t: 4, b: 72 } : { l: 16, r: 24, t: 8, b: 56 },
      xaxis: { range: [0, 100], ticksuffix: '%', gridcolor: ink.value.grid, tickfont: { color: ink.value.muted }, automargin: true },
      yaxis: { autorange: 'reversed', automargin: true, ticksuffix: narrow.value ? ' ' : '  ' },
      legend: { ...bottomLegend(-0.12), yanchor: narrow.value ? 'bottom' : 'top', traceorder: 'normal' },
    },
  }
})

// ── Chart: probability of ranking first, by method ──────────────────────────
const firstByMethodChart = computed(() => {
  const names = data.value.alternatives
  return {
    data: methodIds.value.map(id => {
      const rows = data.value.smaa[id].alternatives
      return {
        type: 'bar',
        name: methodLabel(id),
        x: names,
        y: names.map(n => rows.find(a => a.alternative_name === n).rank_acceptability[0] * 100),
        marker: { color: methodColor(id), cornerradius: 4, line: { color: surface.value, width: 2 } },
        hovertemplate: `<b>%{x}</b><br>${methodLabel(id)}: %{y:.1f}%<extra></extra>`,
      }
    }),
    layout: {
      ...baseLayout(narrow.value ? 300 : 340),
      barmode: 'group',
      margin: narrow.value ? { l: 40, r: 4, t: 4, b: 84 } : { l: 56, r: 16, t: 8, b: 80 },
      xaxis: { automargin: true },
      yaxis: { range: [0, 105], ticksuffix: '%', gridcolor: ink.value.grid, tickfont: { color: ink.value.muted } },
      legend: bottomLegend(-0.22),
    },
  }
})

// ── Chart: weight stability intervals (point = current weight, whisker = interval) ──
const orderedSensitivity = computed(() => {
  const list = [...(sens.value?.criteria ?? [])]
  return list.sort((a, b) => (a.min_change ?? 2) - (b.min_change ?? 2))
})

const intervalChart = computed(() => {
  const rows = orderedSensitivity.value
  const labels = rows.map(c => criterionLabel.value[c.criterion])
  const lo = rows.map(c => c.lower ?? 0)
  const hi = rows.map(c => c.upper ?? 1)
  const w = rows.map(c => c.weight)
  const annotations = []
  // Takeover labels sit above (lower end) and below (upper end) the whisker, anchored to
  // point away from the axis so they never collide with the criterion labels.
  const note = (x, y, text, xanchor, yshift) => ({
    x, y, text, xanchor, yshift, showarrow: false, font: { size: 11, color: ink.value.muted },
  })
  rows.forEach((c, i) => {
    // Phones: criterion names sit above their whisker instead of eating half the width as tick labels.
    if (narrow.value) {
      annotations.push({
        xref: 'paper', x: 0, y: labels[i], text: labels[i], xanchor: 'left', yshift: 32, showarrow: false,
        font: { size: 12, color: ink.value.text },
      })
    }
    if (c.lower != null) annotations.push(note(c.lower, labels[i], `◂ ${c.winner_below}`, 'left', 14))
    if (c.upper != null) annotations.push(note(c.upper, labels[i], `${c.winner_above} ▸`, 'right', -14))
  })
  return {
    data: [{
      type: 'scatter',
      mode: 'markers',
      x: w,
      y: labels,
      marker: { size: 11, color: methodColor(selectedMethod.value), line: { color: surface.value, width: 2 } },
      error_x: {
        type: 'data', symmetric: false,
        array: hi.map((h, i) => h - w[i]), arrayminus: lo.map((l, i) => w[i] - l),
        color: ink.value.muted, thickness: 2, width: 8,
      },
      customdata: rows.map((c, i) => [lo[i], hi[i]]),
      hovertemplate: `<b>%{y}</b><br>${t.value.currentWeight}: %{x:.3f}<br>${t.value.stableRange}: %{customdata[0]:.3f} – %{customdata[1]:.3f}<extra></extra>`,
      showlegend: false,
    }],
    layout: {
      ...baseLayout(narrow.value ? Math.max(220, 80 * rows.length + 56) : Math.max(220, 70 * rows.length + 70)),
      margin: narrow.value ? { l: 8, r: 12, t: 4, b: 44 } : { l: 16, r: 24, t: 8, b: 48 },
      xaxis: { range: [-0.02, 1.02], title: { text: t.value.criterionWeight, font: { size: narrow.value ? 11 : 12 } }, gridcolor: ink.value.grid, tickfont: { color: ink.value.muted } },
      yaxis: { autorange: 'reversed', automargin: true, ticksuffix: '  ', showticklabels: !narrow.value },
      annotations,
    },
  }
})

// ── Chart: weight sweep for one criterion ───────────────────────────────────
const sweep = computed(() => sens.value?.criteria?.find(c => c.criterion === sweepCriterion.value))

const sweepChart = computed(() => {
  const c = sweep.value
  const names = data.value.alternatives
  const shapes = [{
    type: 'line', x0: c.weight, x1: c.weight, y0: 0, y1: 1, yref: 'paper',
    line: { color: ink.value.muted, width: 1.5, dash: 'dash' },
  }]
  for (const edge of [c.lower, c.upper]) {
    if (edge != null) shapes.push({ type: 'line', x0: edge, x1: edge, y0: 0, y1: 1, yref: 'paper', line: { color: '#e34948', width: 1.5, dash: 'dot' } })
  }
  return {
    data: names.map(n => ({
      type: 'scatter',
      mode: 'lines',
      name: n,
      x: c.grid,
      y: c.scores[n],
      line: { color: altColor(n), width: 2 },
      hovertemplate: `${n}: %{y:.4f}<extra></extra>`,
    })),
    layout: {
      ...baseLayout(narrow.value ? 320 : 340),
      margin: narrow.value ? { l: 44, r: 8, t: 4, b: 96 } : { l: 56, r: 24, t: 8, b: 80 },
      hovermode: 'x unified',
      xaxis: { range: [0, 1], title: { text: `${criterionLabel.value[c.criterion]} — ${t.value.criterionWeight}`, font: { size: narrow.value ? 11 : 12 } }, gridcolor: ink.value.grid, tickfont: { color: ink.value.muted } },
      yaxis: {
        // VIKOR's Q is a loss: flip the axis so "better" is always up.
        autorange: sens.value.higher_is_better ? true : 'reversed',
        title: { text: sens.value.higher_is_better ? t.value.methodScore : t.value.methodLoss, font: { size: narrow.value ? 11 : 12 } },
        gridcolor: ink.value.grid, tickfont: { color: ink.value.muted },
      },
      legend: bottomLegend(-0.28),
      shapes,
    },
  }
})
</script>

<template>
  <div class="space-y-3 md:space-y-4">
    <!-- Controls -->
    <section class="card p-4">
      <h2 class="card-title">{{ t.robustnessTitle }}</h2>
      <p class="card-desc">{{ t.robustnessDesc }}</p>

      <div class="mt-4 grid grid-cols-2 items-end gap-3 md:flex md:flex-wrap">
        <label class="min-w-0 md:w-40">
          <span class="field-label">{{ t.methodShown }}</span>
          <select v-model="selectedMethod" class="field">
            <option v-for="id in dss.methods.value" :key="id" :value="id">{{ methodLabel(id) }}</option>
          </select>
        </label>
        <label class="min-w-0 md:w-32">
          <span class="field-label">{{ t.iterations }}</span>
          <select v-model.number="settings.iterations" class="field num">
            <option v-for="n in [500, 1000, 2000, 5000]" :key="n" :value="n">{{ n.toLocaleString() }}</option>
          </select>
        </label>
        <label class="min-w-0 md:w-44">
          <span class="field-label">{{ t.weightUncertainty }}</span>
          <select v-model="settings.weight_model" class="field">
            <option v-for="m in ['fixed', 'perturbed', 'uniform']" :key="m" :value="m">{{ t.weightModels[m] }}</option>
          </select>
        </label>
        <label v-if="settings.weight_model === 'perturbed'" class="min-w-0 md:w-36">
          <span class="field-label">{{ t.weightConfidence }}</span>
          <select v-model.number="settings.concentration" class="field">
            <option :value="20">{{ t.confidenceLow }}</option>
            <option :value="100">{{ t.confidenceMedium }}</option>
            <option :value="500">{{ t.confidenceHigh }}</option>
          </select>
        </label>
        <div class="col-span-2 flex h-5 items-center gap-2 text-xs text-subtle md:ml-auto md:h-8" aria-live="polite">
          <span v-if="rob.loading.value" class="spinner"></span>
          <span v-if="rob.loading.value">{{ t.simulating }}</span>
          <span v-else-if="data"><span class="num">{{ data.iterations.toLocaleString() }}</span> {{ t.drawsDone }}</span>
        </div>
      </div>

      <details class="group mt-4 border-t border-line pt-3">
        <summary class="flex min-h-11 cursor-pointer list-none items-center gap-1.5 text-[15px] font-medium text-fg md:min-h-0 md:text-[13px] [&::-webkit-details-marker]:hidden">
          <Icon name="chevron-right" class="text-xs text-subtle transition-transform group-open:rotate-90" />
          {{ t.valueRanges }}
        </summary>
        <p class="mt-1 mb-2 text-xs text-muted">{{ t.valueRangesDesc }}</p>
        <p v-if="modelMode" class="notice mb-2 border-accent/25 bg-accent-soft text-xs text-accent-ink">
          {{ t.modelRangesHint.replace('{level}', intervalPct) }}
        </p>
        <!-- A table on desktop; on phones each criterion becomes a block of labelled fields. -->
        <div class="lg:grid lg:w-max lg:grid-cols-[auto_auto_auto_auto] lg:items-center lg:gap-x-4 lg:gap-y-1 lg:text-xs"
             :class="modelMode ? 'opacity-60' : ''">
          <div class="hidden font-medium text-muted lg:contents">
            <span class="py-1">{{ t.criterionLabel }}</span>
            <span class="py-1">{{ t.rangeLow }}</span>
            <span class="py-1">{{ t.rangeHigh }}</span>
            <span class="py-1">{{ t.distribution }}</span>
          </div>
          <div v-for="k in CRITERION_KEYS" :key="k" class="border-b border-line py-3 last:border-b-0 lg:contents">
            <p class="mb-2 text-[13px] font-medium text-fg lg:mb-0 lg:text-xs lg:font-normal">{{ criterionLabel[k] }}</p>
            <div class="grid grid-cols-2 gap-x-3 gap-y-2 lg:contents">
              <label class="min-w-0">
                <span class="field-label lg:hidden">{{ t.rangeLow }}</span>
                <span class="num flex items-center gap-1 text-muted">
                  −<input type="number" min="0" max="95" step="5" :value="lowPct(k)" @change="setLow(k, $event.target.value)"
                          :disabled="modelMode" inputmode="decimal"
                          class="field num min-w-0 disabled:cursor-not-allowed lg:w-16 lg:px-1.5 lg:py-0.5 lg:text-xs" />%
                </span>
              </label>
              <label class="min-w-0">
                <span class="field-label lg:hidden">{{ t.rangeHigh }}</span>
                <span class="num flex items-center gap-1 text-muted">
                  +<input type="number" min="0" max="900" step="5" :value="highPct(k)" @change="setHigh(k, $event.target.value)"
                          :disabled="modelMode" inputmode="decimal"
                          class="field num min-w-0 disabled:cursor-not-allowed lg:w-16 lg:px-1.5 lg:py-0.5 lg:text-xs" />%
                </span>
              </label>
              <label class="col-span-2 min-w-0 lg:col-span-1">
                <span class="field-label lg:hidden">{{ t.distribution }}</span>
                <select v-if="modelMode" disabled class="field cursor-not-allowed lg:w-auto lg:px-1.5 lg:py-0.5 lg:pr-7 lg:text-xs">
                  <option>{{ shownRange(k)?.distribution === 'uniform' ? t.distUniform : t.distTriangular }}</option>
                </select>
                <select v-else v-model="settings.values[k].distribution" class="field lg:w-auto lg:px-1.5 lg:py-0.5 lg:pr-7 lg:text-xs">
                  <option value="triangular">{{ t.distTriangular }}</option>
                  <option value="uniform">{{ t.distUniform }}</option>
                </select>
              </label>
            </div>
          </div>
        </div>
        <button v-if="!modelMode" type="button" class="btn-ghost mt-2 lg:!px-1.5 lg:!py-1 lg:text-xs" @click="rob.resetRanges()">
          <Icon name="refresh" class="text-xs" />{{ t.resetDefaults }}
        </button>
      </details>
    </section>

    <div v-if="rob.error.value" class="notice notice-bad">
      {{ rob.error.value }}
    </div>

    <!-- First run only; later runs keep the previous results on screen while they update. -->
    <div v-if="!data && rob.loading.value" class="space-y-4" aria-hidden="true">
      <div class="grid grid-cols-1 gap-3 md:grid-cols-3 md:gap-4">
        <div v-for="i in 3" :key="i" class="card h-32 animate-pulse bg-surface-2"></div>
      </div>
      <div class="card h-96 animate-pulse bg-surface-2"></div>
    </div>

    <template v-if="data && smaa && sens">
      <!-- Headline -->
      <div class="grid grid-cols-1 gap-3 sm:grid-cols-2 md:grid-cols-3 md:gap-4">
        <div class="card p-4">
          <p class="eyebrow mb-2">{{ t.likelyWinner }} · {{ methodLabel(selectedMethod) }}</p>
          <p class="flex items-center gap-1.5 text-[13px] font-medium text-fg">
            <span class="inline-block h-2 w-2 shrink-0 rounded-full" :style="{ background: altColor(top.alternative_name) }" aria-hidden="true"></span>{{ top.alternative_name }}
          </p>
          <p class="num mt-1 text-2xl font-semibold tracking-tight text-fg">{{ pct(top.rank_acceptability[0]) }}</p>
          <p class="text-xs text-muted">{{ t.firstPlaceShare }}</p>
        </div>
        <div class="card p-4">
          <p class="eyebrow mb-2">{{ t.mostSensitive }}</p>
          <template v-if="critical">
            <p class="text-[13px] font-medium text-fg">{{ criterionLabel[critical] }}</p>
            <p class="num mt-1 text-2xl font-semibold tracking-tight text-fg">±{{ sens.critical_change.toFixed(3) }}</p>
            <p class="text-xs text-muted">{{ t.weightChangeFlips }} {{ sens.winner }}</p>
          </template>
          <p v-else class="mt-2 text-[13px] text-fg">{{ t.noSingleFlip }}</p>
        </div>
        <div class="card p-4 sm:col-span-2 md:col-span-1">
          <p class="eyebrow mb-2">{{ t.constraintRisk }} · {{ top.alternative_name }}</p>
          <p class="num mt-1 text-2xl font-semibold tracking-tight text-fg">{{ pct(winnerRisk.construction_cost_mln) }}</p>
          <p class="text-xs text-muted">{{ t.overBudget }} (<span class="num">{{ dss.params.budget }}</span> M USD)</p>
          <p class="mt-2 text-[13px] text-fg"><span class="num font-medium">{{ pct(winnerRisk.land_area_hectares) }}</span>
            <span class="text-xs text-muted">{{ t.overLand }} (<span class="num">{{ dss.params.land_limit }}</span> ha)</span></p>
        </div>
      </div>

      <!-- Rank acceptability -->
      <section class="card p-4">
        <h3 class="card-title">{{ t.rankAcceptabilityTitle }} · {{ methodLabel(selectedMethod) }}</h3>
        <p class="card-desc mb-2">{{ t.rankAcceptabilityDesc }}</p>
        <PlotlyChart :chart="acceptabilityChart" :dark="dark" />
        <div class="table-scroll -mx-4 mt-2 border-t border-line">
          <table class="table min-w-[560px]">
            <thead>
              <tr>
                <th class="sticky left-0 z-[1] bg-surface !pl-4 max-md:shadow-[inset_-1px_0_0_var(--line)]">{{ t.alternative }}</th>
                <th v-for="r in nAlts" :key="r" class="!text-right">{{ t.rankWord }} {{ r }}</th>
                <th class="!text-right">{{ t.holistic }}</th>
                <th class="!text-right">{{ t.confidenceFactor }}</th>
                <th class="!text-right">{{ t.overBudget }}</th>
                <th class="!pr-4 !text-right">{{ t.overLand }}</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="a in smaa.alternatives" :key="a.alternative_name">
                <td class="sticky left-0 z-[1] whitespace-nowrap bg-surface !pl-4 font-medium max-md:shadow-[inset_-1px_0_0_var(--line)] [tr:nth-child(even)>&]:bg-[color-mix(in_srgb,var(--surface-2)_40%,var(--surface))]">
                  <span class="mr-1.5 inline-block h-2 w-2 rounded-full align-middle" :style="{ background: altColor(a.alternative_name) }" aria-hidden="true"></span>{{ a.alternative_name }}
                </td>
                <td v-for="(p, r) in a.rank_acceptability" :key="r" class="num text-right">{{ pct(p, 1) }}</td>
                <td class="num text-right font-medium">{{ a.holistic_acceptability.toFixed(3) }}</td>
                <td class="num text-right">{{ pct(a.confidence, 1) }}</td>
                <td class="num text-right">{{ pct(data.exceedance[a.alternative_name].construction_cost_mln, 1) }}</td>
                <td class="num !pr-4 text-right">{{ pct(data.exceedance[a.alternative_name].land_area_hectares, 1) }}</td>
              </tr>
            </tbody>
          </table>
        </div>
      </section>

      <div class="grid grid-cols-1 gap-3 md:gap-4 xl:grid-cols-2">
        <!-- First place by method -->
        <section class="card p-4">
          <h3 class="card-title">{{ t.firstByMethodTitle }}</h3>
          <p class="card-desc mb-2">{{ t.firstByMethodDesc }}</p>
          <PlotlyChart :chart="firstByMethodChart" :dark="dark" />
        </section>

        <!-- Stability intervals -->
        <section class="card p-4">
          <h3 class="card-title">{{ t.stabilityTitle }} · {{ methodLabel(selectedMethod) }}</h3>
          <p class="card-desc mb-2">{{ t.stabilityDesc }}</p>
          <PlotlyChart :chart="intervalChart" :dark="dark" />
        </section>
      </div>

      <!-- Weight sweep -->
      <section class="card p-4">
        <div class="mb-2 flex flex-wrap items-start justify-between gap-3">
          <div>
            <h3 class="card-title">{{ t.sweepTitle }} · {{ methodLabel(selectedMethod) }}</h3>
            <p class="card-desc">{{ t.sweepDesc }}</p>
          </div>
          <div class="seg grid w-full grid-cols-2 md:inline-flex md:w-auto md:flex-wrap" role="group">
            <button v-for="k in CRITERION_KEYS" :key="k" type="button" class="seg-item leading-tight pointer-coarse:min-h-11"
                    :aria-pressed="sweepCriterion === k" @click="sweepCriterion = k">
              {{ criterionLabel[k] }}
            </button>
          </div>
        </div>
        <PlotlyChart v-if="sweep" :chart="sweepChart" :dark="dark" />
      </section>
    </template>
  </div>
</template>

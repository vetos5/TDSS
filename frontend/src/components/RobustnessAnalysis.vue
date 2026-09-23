<script setup>
import { computed, ref, watch } from 'vue'
import PlotlyChart from './PlotlyChart.vue'
import { useLocale } from '../composables/useLocale.js'
import { useRobustness } from '../composables/useRobustness.js'
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

const selectedMethod = ref('wsm')
const sweepCriterion = ref(CRITERION_KEYS[0])
let stale = true
let timer = null

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
watch(
  [
    () => props.dss.selectedContext.value,
    () => ({ ...props.dss.weights }),
    () => ({ ...props.dss.params }),
    () => [...props.dss.methods.value],
    () => ({ ...props.dss.weighting }),
    () => [...props.dss.ahpJudgements],
    () => JSON.stringify(settings),
    locale,
  ],
  () => schedule(),
  { deep: true },
)

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
    font: { family: 'Inter, system-ui, sans-serif', color: ink.value.text, size: 12 },
    margin: { l: 16, r: 24, t: 16, b: 48 },
    height,
    autosize: true,
    hoverlabel: { font: { family: 'Inter, system-ui, sans-serif' } },
  }
}

// ── Value-range editor (shown as ± percentages) ─────────────────────────────
function lowPct(k) { return Math.round((1 - settings.values[k].low) * 100) }
function highPct(k) { return Math.round((settings.values[k].high - 1) * 100) }
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
      ...baseLayout(Math.max(160, 64 * rows.length + 90)),
      barmode: 'stack',
      margin: { l: 16, r: 24, t: 8, b: 56 },
      xaxis: { range: [0, 100], ticksuffix: '%', gridcolor: ink.value.grid, tickfont: { color: ink.value.muted } },
      yaxis: { autorange: 'reversed', automargin: true, ticksuffix: '  ' },
      legend: { orientation: 'h', y: -0.12, yanchor: 'top', x: 0, bgcolor: 'rgba(0,0,0,0)', traceorder: 'normal' },
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
      ...baseLayout(340),
      barmode: 'group',
      margin: { l: 56, r: 16, t: 8, b: 80 },
      yaxis: { range: [0, 105], ticksuffix: '%', gridcolor: ink.value.grid, tickfont: { color: ink.value.muted } },
      legend: { orientation: 'h', y: -0.22, x: 0, bgcolor: 'rgba(0,0,0,0)' },
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
      ...baseLayout(Math.max(220, 70 * rows.length + 70)),
      margin: { l: 16, r: 24, t: 8, b: 48 },
      xaxis: { range: [-0.02, 1.02], title: { text: t.value.criterionWeight, font: { size: 12 } }, gridcolor: ink.value.grid, tickfont: { color: ink.value.muted } },
      yaxis: { autorange: 'reversed', automargin: true, ticksuffix: '  ' },
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
      ...baseLayout(340),
      margin: { l: 56, r: 24, t: 16, b: 80 },
      hovermode: 'x unified',
      xaxis: { range: [0, 1], title: { text: `${criterionLabel.value[c.criterion]} — ${t.value.criterionWeight}`, font: { size: 12 } }, gridcolor: ink.value.grid, tickfont: { color: ink.value.muted } },
      yaxis: {
        // VIKOR's Q is a loss: flip the axis so "better" is always up.
        autorange: sens.value.higher_is_better ? true : 'reversed',
        title: { text: sens.value.higher_is_better ? t.value.methodScore : t.value.methodLoss, font: { size: 12 } },
        gridcolor: ink.value.grid, tickfont: { color: ink.value.muted },
      },
      legend: { orientation: 'h', y: -0.28, x: 0, bgcolor: 'rgba(0,0,0,0)' },
      shapes,
    },
  }
})

// ── Styles ───────────────────────────────────────────────────────────────────
const panel = computed(() => props.dark
  ? 'bg-white/[0.06] border border-white/10'
  : 'bg-white/60 border border-white/80 shadow-[0_8px_30px_rgb(0,0,0,0.04)]')
const input = computed(() => props.dark
  ? 'bg-slate-700 border border-slate-600 text-slate-200'
  : 'bg-white/80 border border-black/10 text-slate-800')
const muted = computed(() => props.dark ? 'text-slate-400' : 'text-slate-500')
const strong = computed(() => props.dark ? 'text-slate-100' : 'text-slate-900')
</script>

<template>
  <div>
    <!-- Controls -->
    <div class="rounded-[28px] backdrop-blur-2xl p-5 lg:p-6 mb-6" :class="panel">
      <h2 class="text-xl font-semibold tracking-tight mb-1" :class="strong">{{ t.robustnessTitle }}</h2>
      <p class="text-xs mb-4" :class="muted">{{ t.robustnessDesc }}</p>

      <div class="flex flex-wrap items-end gap-3 mb-4">
        <label class="text-xs font-medium" :class="muted">
          {{ t.methodShown }}
          <select v-model="selectedMethod" class="block mt-1 rounded-lg px-2 py-1.5 text-sm" :class="input">
            <option v-for="id in dss.methods.value" :key="id" :value="id">{{ methodLabel(id) }}</option>
          </select>
        </label>
        <label class="text-xs font-medium" :class="muted">
          {{ t.iterations }}
          <select v-model.number="settings.iterations" class="block mt-1 rounded-lg px-2 py-1.5 text-sm" :class="input">
            <option v-for="n in [500, 1000, 2000, 5000]" :key="n" :value="n">{{ n.toLocaleString() }}</option>
          </select>
        </label>
        <label class="text-xs font-medium" :class="muted">
          {{ t.weightUncertainty }}
          <select v-model="settings.weight_model" class="block mt-1 rounded-lg px-2 py-1.5 text-sm" :class="input">
            <option v-for="m in ['fixed', 'perturbed', 'uniform']" :key="m" :value="m">{{ t.weightModels[m] }}</option>
          </select>
        </label>
        <label v-if="settings.weight_model === 'perturbed'" class="text-xs font-medium" :class="muted">
          {{ t.weightConfidence }}
          <select v-model.number="settings.concentration" class="block mt-1 rounded-lg px-2 py-1.5 text-sm" :class="input">
            <option :value="20">{{ t.confidenceLow }}</option>
            <option :value="100">{{ t.confidenceMedium }}</option>
            <option :value="500">{{ t.confidenceHigh }}</option>
          </select>
        </label>
        <div class="flex items-center gap-2 h-9 ml-auto text-xs" :class="muted">
          <span v-if="rob.loading.value" class="animate-spin rounded-full h-3.5 w-3.5 border-b-2"
                :class="dark ? 'border-teal-400' : 'border-teal-600'"></span>
          <span v-if="rob.loading.value">{{ t.simulating }}</span>
          <span v-else-if="data">{{ data.iterations.toLocaleString() }} {{ t.drawsDone }}</span>
        </div>
      </div>

      <details class="text-sm">
        <summary class="cursor-pointer text-xs font-semibold" :class="strong">{{ t.valueRanges }}</summary>
        <p class="text-xs mt-1 mb-2" :class="muted">{{ t.valueRangesDesc }}</p>
        <div class="overflow-x-auto">
          <table class="text-xs">
            <thead>
              <tr :class="muted">
                <th class="text-left pr-4 py-1 font-semibold">{{ t.criterionLabel }}</th>
                <th class="text-left pr-3 py-1 font-semibold">{{ t.rangeLow }}</th>
                <th class="text-left pr-3 py-1 font-semibold">{{ t.rangeHigh }}</th>
                <th class="text-left py-1 font-semibold">{{ t.distribution }}</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="k in CRITERION_KEYS" :key="k">
                <td class="pr-4 py-1" :class="strong">{{ criterionLabel[k] }}</td>
                <td class="pr-3 py-1">
                  −<input type="number" min="0" max="95" step="5" :value="lowPct(k)" @change="setLow(k, $event.target.value)"
                          class="w-14 rounded-md px-1.5 py-0.5 mx-1" :class="input" />%
                </td>
                <td class="pr-3 py-1">
                  +<input type="number" min="0" max="900" step="5" :value="highPct(k)" @change="setHigh(k, $event.target.value)"
                          class="w-14 rounded-md px-1.5 py-0.5 mx-1" :class="input" />%
                </td>
                <td class="py-1">
                  <select v-model="settings.values[k].distribution" class="rounded-md px-1.5 py-0.5" :class="input">
                    <option value="triangular">{{ t.distTriangular }}</option>
                    <option value="uniform">{{ t.distUniform }}</option>
                  </select>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
        <button type="button" class="mt-2 text-xs underline" :class="muted" @click="rob.resetRanges()">{{ t.resetDefaults }}</button>
      </details>
    </div>

    <div v-if="rob.error.value" class="rounded-2xl px-4 py-3 mb-6 text-sm"
         :class="dark ? 'bg-red-500/10 border border-red-500/30 text-red-200' : 'bg-red-50 border border-red-200 text-red-800'">
      {{ rob.error.value }}
    </div>

    <template v-if="data && smaa && sens">
      <!-- Headline -->
      <div class="grid grid-cols-1 md:grid-cols-3 gap-4 mb-6">
        <div class="rounded-3xl p-5" :class="panel">
          <p class="text-xs font-semibold uppercase tracking-wider mb-2" :class="muted">{{ t.likelyWinner }} · {{ methodLabel(selectedMethod) }}</p>
          <p class="text-lg font-bold" :class="strong">
            <span class="inline-block w-2.5 h-2.5 rounded-full mr-1.5 align-middle" :style="{ background: altColor(top.alternative_name) }" aria-hidden="true"></span>{{ top.alternative_name }}
          </p>
          <p class="text-3xl font-extrabold tabular-nums mt-1" :class="strong">{{ pct(top.rank_acceptability[0]) }}</p>
          <p class="text-xs" :class="muted">{{ t.firstPlaceShare }}</p>
        </div>
        <div class="rounded-3xl p-5" :class="panel">
          <p class="text-xs font-semibold uppercase tracking-wider mb-2" :class="muted">{{ t.mostSensitive }}</p>
          <template v-if="critical">
            <p class="text-lg font-bold" :class="strong">{{ criterionLabel[critical] }}</p>
            <p class="text-3xl font-extrabold tabular-nums mt-1" :class="strong">±{{ sens.critical_change.toFixed(3) }}</p>
            <p class="text-xs" :class="muted">{{ t.weightChangeFlips }} {{ sens.winner }}</p>
          </template>
          <p v-else class="text-sm mt-2" :class="strong">{{ t.noSingleFlip }}</p>
        </div>
        <div class="rounded-3xl p-5" :class="panel">
          <p class="text-xs font-semibold uppercase tracking-wider mb-2" :class="muted">{{ t.constraintRisk }} · {{ top.alternative_name }}</p>
          <p class="text-3xl font-extrabold tabular-nums mt-1" :class="strong">{{ pct(winnerRisk.construction_cost_mln) }}</p>
          <p class="text-xs" :class="muted">{{ t.overBudget }} ({{ dss.params.budget }} M USD)</p>
          <p class="text-sm font-semibold tabular-nums mt-2" :class="strong">{{ pct(winnerRisk.land_area_hectares) }}
            <span class="font-normal text-xs" :class="muted">{{ t.overLand }} ({{ dss.params.land_limit }} ha)</span></p>
        </div>
      </div>

      <!-- Rank acceptability -->
      <div class="rounded-[28px] backdrop-blur-2xl p-5 lg:p-6 mb-6" :class="panel">
        <h3 class="text-base font-semibold" :class="strong">{{ t.rankAcceptabilityTitle }} · {{ methodLabel(selectedMethod) }}</h3>
        <p class="text-xs mb-2" :class="muted">{{ t.rankAcceptabilityDesc }}</p>
        <PlotlyChart :chart="acceptabilityChart" :dark="dark" />
        <div class="overflow-x-auto mt-2">
          <table class="w-full text-sm">
            <thead>
              <tr :class="muted">
                <th class="px-3 py-2 text-left font-semibold">{{ t.alternative }}</th>
                <th v-for="r in nAlts" :key="r" class="px-3 py-2 text-right font-semibold">{{ t.rankWord }} {{ r }}</th>
                <th class="px-3 py-2 text-right font-semibold">{{ t.holistic }}</th>
                <th class="px-3 py-2 text-right font-semibold">{{ t.confidenceFactor }}</th>
                <th class="px-3 py-2 text-right font-semibold">{{ t.overBudget }}</th>
                <th class="px-3 py-2 text-right font-semibold">{{ t.overLand }}</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="a in smaa.alternatives" :key="a.alternative_name" class="border-t tabular-nums"
                  :class="dark ? 'border-slate-700 text-slate-200' : 'border-black/5 text-slate-800'">
                <td class="px-3 py-2 font-semibold">
                  <span class="inline-block w-2.5 h-2.5 rounded-full mr-1.5 align-middle" :style="{ background: altColor(a.alternative_name) }" aria-hidden="true"></span>{{ a.alternative_name }}
                </td>
                <td v-for="(p, r) in a.rank_acceptability" :key="r" class="px-3 py-2 text-right">{{ pct(p, 1) }}</td>
                <td class="px-3 py-2 text-right font-semibold">{{ a.holistic_acceptability.toFixed(3) }}</td>
                <td class="px-3 py-2 text-right">{{ pct(a.confidence, 1) }}</td>
                <td class="px-3 py-2 text-right">{{ pct(data.exceedance[a.alternative_name].construction_cost_mln, 1) }}</td>
                <td class="px-3 py-2 text-right">{{ pct(data.exceedance[a.alternative_name].land_area_hectares, 1) }}</td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>

      <div class="grid grid-cols-1 xl:grid-cols-2 gap-6 mb-6">
        <!-- First place by method -->
        <div class="rounded-[28px] backdrop-blur-2xl p-5 lg:p-6" :class="panel">
          <h3 class="text-base font-semibold" :class="strong">{{ t.firstByMethodTitle }}</h3>
          <p class="text-xs mb-2" :class="muted">{{ t.firstByMethodDesc }}</p>
          <PlotlyChart :chart="firstByMethodChart" :dark="dark" />
        </div>

        <!-- Stability intervals -->
        <div class="rounded-[28px] backdrop-blur-2xl p-5 lg:p-6" :class="panel">
          <h3 class="text-base font-semibold" :class="strong">{{ t.stabilityTitle }} · {{ methodLabel(selectedMethod) }}</h3>
          <p class="text-xs mb-2" :class="muted">{{ t.stabilityDesc }}</p>
          <PlotlyChart :chart="intervalChart" :dark="dark" />
        </div>
      </div>

      <!-- Weight sweep -->
      <div class="rounded-[28px] backdrop-blur-2xl p-5 lg:p-6 mb-6" :class="panel">
        <div class="flex flex-wrap items-start justify-between gap-3 mb-2">
          <div>
            <h3 class="text-base font-semibold" :class="strong">{{ t.sweepTitle }} · {{ methodLabel(selectedMethod) }}</h3>
            <p class="text-xs" :class="muted">{{ t.sweepDesc }}</p>
          </div>
          <div class="flex flex-wrap gap-1">
            <button v-for="k in CRITERION_KEYS" :key="k" type="button" @click="sweepCriterion = k"
                    class="px-2.5 py-1 rounded-lg text-xs font-semibold border transition-colors"
                    :class="sweepCriterion === k
                      ? (dark ? 'bg-slate-600 border-slate-500 text-white' : 'bg-slate-800 border-slate-800 text-white')
                      : (dark ? 'border-slate-600 text-slate-400' : 'border-black/10 text-slate-500')">
              {{ criterionLabel[k] }}
            </button>
          </div>
        </div>
        <PlotlyChart v-if="sweep" :chart="sweepChart" :dark="dark" />
      </div>
    </template>
  </div>
</template>

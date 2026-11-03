<script setup>
import { computed, ref, watch } from 'vue'
import { useLocale } from '../composables/useLocale.js'
import { useAnalysis, siteBody } from '../composables/useAnalysis.js'
import { economics, breakeven } from '../api.js'
import { chartInk } from '../chartPalette.js'
import PlotlyChart from './PlotlyChart.vue'
import Icon from './Icon.vue'
import { downloadCsv, slug } from '../exporters.js'

// Life-cycle cost appraisal (POST /api/economics) and break-even values of the MCDA ranking
// (POST /api/breakeven). Both refresh while the tab is shown and their inputs change.
const props = defineProps({ dss: Object, active: Boolean, dark: Boolean })

const { t, locale } = useLocale()
const econ = useAnalysis('economics')
const be = useAnalysis('breakeven')
const data = econ.data

let timer = null
function schedule() {
  clearTimeout(timer)
  timer = setTimeout(() => {
    const d = props.dss
    if (!d.selectedContext.value) return
    const lang = locale.value
    econ.run(() => economics(siteBody(d), lang))
    be.run(() => breakeven({
      context: d.selectedContext.value,
      weights: d.normalizedWeights(),
      params: { ...d.params },
      methods: d.methods.value.length ? d.methods.value : ['wsm'],
      weighting: d.weightingPayload(),
      value_source: d.valueSource.value,
    }, lang))
  }, 300)
}

watch(
  () => [props.active, locale.value, props.dss.selectedContext.value, JSON.stringify(props.dss.params),
    JSON.stringify(props.dss.study), JSON.stringify(props.dss.weights), JSON.stringify(props.dss.weighting),
    JSON.stringify(props.dss.ahpJudgements), props.dss.methods.value.join(), props.dss.valueSource.value],
  () => { if (props.active) schedule() },
  { immediate: true },
)

const fill = (s, vars) => Object.entries(vars).reduce((acc, [k, v]) => acc.replaceAll(`{${k}}`, v), s)
const nf = (v, d = 1) => v == null ? '—' : Number(v).toLocaleString(locale.value === 'uk' ? 'uk-UA' : 'en-US',
  { minimumFractionDigits: d, maximumFractionDigits: d })
const colorOf = a => (props.dark ? a.color_dark : a.color) || '#2a78d6'
const alts = computed(() => data.value?.alternatives ?? [])

const basis = computed(() => {
  const s = data.value?.study
  if (!s) return ''
  return fill(t.value.econ.basis, {
    r: nf(s.discount_pct, 1), vot: nf(s.value_of_time, 0), m: nf(s.maintenance_pct, 1),
    fi: nf(data.value.crash_cost_fi, 0), pdo: nf(data.value.crash_cost_pdo, 0),
    from: data.value.years[1], to: data.value.years.at(-1),
  })
})

function layout(ink, extra = {}) {
  return {
    height: 320, margin: { l: 56, r: 16, t: 8, b: 40 },
    paper_bgcolor: 'rgba(0,0,0,0)', plot_bgcolor: 'rgba(0,0,0,0)',
    font: { family: ink.font, color: ink.text, size: 12 },
    legend: { orientation: 'h', y: -0.2 },
    ...extra,
  }
}

// Component colours: a fixed categorical set, the same in both charts' legends.
const PARTS = [
  { key: 'construction_mln', label: 'capital', light: '#2a78d6', dark: '#3987e5' },
  { key: 'pv_maintenance', label: 'maintenance', light: '#1baf7a', dark: '#199e70' },
  { key: 'pv_delay', label: 'delay', light: '#eda100', dark: '#c98500' },
  { key: 'pv_crash', label: 'crash', light: '#e34948', dark: '#d55181' },
]

const breakdownChart = computed(() => {
  if (!data.value) return null
  const ink = chartInk(props.dark)
  const names = alts.value.map(a => a.name)
  const bars = PARTS.map(p => ({
    type: 'bar', name: t.value.econ[p.label], x: names, y: alts.value.map(a => a[p.key]),
    marker: { color: props.dark ? p.dark : p.light },
    hovertemplate: `%{x}<br>${t.value.econ[p.label]}: %{y:.2f}<extra></extra>`,
  }))
  bars.push({
    type: 'bar', name: t.value.econ.residual, x: names, y: alts.value.map(a => -a.pv_residual),
    marker: { color: ink.muted },
    hovertemplate: `%{x}<br>${t.value.econ.residual}: %{y:.2f}<extra></extra>`,
  })
  return {
    data: bars,
    layout: layout(ink, {
      barmode: 'relative',
      yaxis: { title: { text: t.value.econ.musd }, gridcolor: ink.grid, zeroline: true, zerolinecolor: ink.grid },
      xaxis: { gridcolor: ink.grid },
    }),
  }
})

const cumulativeChart = computed(() => {
  if (!data.value) return null
  const ink = chartInk(props.dark)
  return {
    data: alts.value.map(a => ({
      type: 'scatter', mode: 'lines', name: a.name, x: data.value.years, y: a.cumulative_total,
      line: { color: colorOf(a), width: 2.5, dash: a.feasible ? 'solid' : 'dot' },
      hovertemplate: `${a.name}<br>%{x}: %{y:.1f}<extra></extra>`,
    })),
    layout: layout(ink, {
      yaxis: { title: { text: t.value.econ.musd }, gridcolor: ink.grid, zeroline: false, rangemode: 'tozero' },
      xaxis: { title: { text: t.value.econ.year }, gridcolor: ink.grid },
    }),
  }
})

function exportCsv() {
  const d = data.value
  if (!d) return
  const keys = ['construction_mln', 'pv_maintenance', 'pv_residual', 'pv_delay', 'pv_crash', 'pv_agency', 'pv_user',
    'pv_total', 'incremental_cost', 'benefits', 'npv', 'bcr', 'dominant', 'payback_year', 'is_base', 'feasible']
  const rows = [['Alternative', ...keys.map(k => k.startsWith('pv_') || k.endsWith('_mln') || ['incremental_cost', 'benefits', 'npv'].includes(k) ? `${k} (M USD)` : k)]]
  for (const a of d.alternatives) rows.push([a.name, ...keys.map(k => a[k])])
  rows.push([], ['Year', ...d.alternatives.map(a => `${a.name} cumulative (M USD)`)])
  d.years.forEach((y, i) => rows.push([y, ...d.alternatives.map(a => a.cumulative_total[i])]))
  const s = d.study
  rows.push([], ['discount_pct', s.discount_pct], ['value_of_time_usd', s.value_of_time], ['maintenance_pct', s.maintenance_pct],
    ['crash_cost_fi_usd', d.crash_cost_fi], ['crash_cost_pdo_usd', d.crash_cost_pdo])
  downloadCsv(`tdss-economics-${slug(d.context)}.csv`, rows)
}

// ── Break-even ──────────────────────────────────────────────────────────────
const beMethod = ref('')
watch(() => be.data.value, d => {
  const ids = Object.keys(d?.methods ?? {})
  if (!ids.includes(beMethod.value)) beMethod.value = ids[0] ?? ''
})
const beResult = computed(() => be.data.value?.methods?.[beMethod.value])
const criteria = computed(() => props.dss.evalData.value?.criteria ?? [])
const criterionLabel = k => props.dss.evalData.value?.criterion_labels?.[k] ?? k
const unitOf = k => criteria.value.find(c => c.name === k)?.unit ?? ''
const beRows = computed(() => {
  const r = beResult.value
  if (!r) return []
  const byAlt = {}
  for (const i of r.items) (byAlt[i.alternative] ??= {})[i.criterion] = i
  // The winner first, then the challengers in the order of the evaluation.
  return [r.winner, ...be.data.value.alternatives.filter(n => n !== r.winner)]
    .map(name => ({ name, cells: byAlt[name] ?? {} }))
})
const digits = k => (k === 'throughput_vph' ? 0 : 2)
</script>

<template>
  <div class="space-y-3 md:space-y-4">
    <section class="card p-4">
      <div class="flex items-start gap-3">
        <div class="min-w-0 flex-1">
          <h2 class="card-title">{{ t.econ.title }}</h2>
          <p class="card-desc">{{ t.econ.desc }}</p>
        </div>
        <span class="spinner mt-1 transition-opacity duration-200" :class="econ.loading.value ? 'opacity-100' : 'opacity-0'"></span>
        <button type="button" class="btn shrink-0" :disabled="!data" @click="exportCsv"><Icon name="download" class="text-sm" /> {{ t.exportCsv }}</button>
      </div>
      <p v-if="data" class="num mt-3 text-xs text-muted">{{ basis }}</p>
      <p v-if="econ.error.value" class="notice notice-bad mt-3">{{ econ.error.value }}</p>
    </section>

    <template v-if="data">
      <section class="card overflow-hidden">
        <div class="table-scroll">
          <table class="table w-full text-[13px]">
            <thead>
              <tr>
                <th class="text-left">{{ t.econ.alternative }}</th>
                <th class="text-right">{{ t.econ.construction }}</th>
                <th class="text-right">{{ t.econ.agency }}</th>
                <th class="text-right">{{ t.econ.users }}</th>
                <th class="text-right">{{ t.econ.total }}</th>
                <th class="text-right">{{ t.econ.incremental }}</th>
                <th class="text-right">{{ t.econ.benefits }}</th>
                <th class="text-right">{{ t.econ.npv }}</th>
                <th class="text-right">{{ t.econ.bcr }}</th>
                <th class="text-right">{{ t.econ.payback }}</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="a in alts" :key="a.name" :class="a.feasible ? '' : 'text-muted'">
                <td class="whitespace-nowrap">
                  <span class="mr-1.5 inline-block h-2.5 w-2.5 rounded-full align-middle" :style="{ background: colorOf(a) }"></span>
                  {{ a.name }}
                  <span v-if="a.is_base" class="badge ml-1">{{ t.econ.base }}</span>
                  <span v-if="a.name === data.best_lcc" class="badge badge-accent ml-1">{{ t.econ.bestLcc }}</span>
                  <span v-if="!a.feasible" class="badge ml-1">{{ t.eng.infeasible }}</span>
                </td>
                <td class="num text-right">{{ nf(a.construction_mln) }}</td>
                <td class="num text-right">{{ nf(a.pv_agency) }}</td>
                <td class="num text-right">{{ nf(a.pv_user) }}</td>
                <td class="num text-right font-medium">{{ nf(a.pv_total) }}</td>
                <td class="num text-right">{{ a.is_base ? '' : nf(a.incremental_cost) }}</td>
                <td class="num text-right">{{ a.is_base ? '' : nf(a.benefits) }}</td>
                <td class="num text-right" :class="a.npv > 0 ? 'text-ok' : a.npv < 0 ? 'text-bad' : ''">{{ a.is_base ? '' : nf(a.npv) }}</td>
                <td class="num text-right">
                  <template v-if="a.dominant">{{ t.econ.dominant }}</template>
                  <template v-else-if="!a.is_base">{{ nf(a.bcr, 2) }}</template>
                </td>
                <td class="num text-right">{{ a.is_base ? '' : (a.payback_year ?? t.econ.never) }}</td>
              </tr>
            </tbody>
          </table>
        </div>
        <p class="px-4 py-3 text-xs text-subtle">{{ t.econ.unit }} {{ t.econ.assumptions }}</p>
      </section>

      <div class="grid gap-3 md:gap-4 xl:grid-cols-2">
        <section class="card p-4">
          <h3 class="card-title">{{ t.econ.breakdownTitle }}</h3>
          <p class="card-desc">{{ t.econ.breakdownDesc }}</p>
          <PlotlyChart :chart="breakdownChart" :dark="dark" class="mt-2" />
        </section>
        <section class="card p-4">
          <h3 class="card-title">{{ t.econ.cumulativeTitle }}</h3>
          <p class="card-desc">{{ t.econ.cumulativeDesc }}</p>
          <PlotlyChart :chart="cumulativeChart" :dark="dark" class="mt-2" />
        </section>
      </div>
    </template>

    <section class="card overflow-hidden">
      <div class="flex flex-wrap items-end gap-3 px-4 pt-4">
        <div class="min-w-0 flex-1">
          <h3 class="card-title">{{ t.econ.beTitle }}</h3>
          <p class="card-desc">{{ t.econ.beDesc }}</p>
        </div>
        <span class="spinner transition-opacity duration-200" :class="be.loading.value ? 'opacity-100' : 'opacity-0'"></span>
        <label v-if="be.data.value" class="min-w-0">
          <span class="field-label">{{ t.econ.method }}</span>
          <select v-model="beMethod" class="field w-auto">
            <option v-for="(m, id) in be.data.value.methods" :key="id" :value="id">{{ m.label }}</option>
          </select>
        </label>
      </div>
      <p v-if="be.error.value" class="notice notice-bad mx-4 mt-3">{{ be.error.value }}</p>
      <div v-if="beResult" class="table-scroll mt-3">
        <table class="table w-full text-[13px]">
          <thead>
            <tr>
              <th class="text-left">{{ t.econ.alternative }}</th>
              <th v-for="c in criteria" :key="c.name" class="text-right">{{ criterionLabel(c.name) }} <span class="text-subtle">({{ c.unit }})</span></th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="row in beRows" :key="row.name">
              <td class="whitespace-nowrap">
                {{ row.name }}
                <span v-if="row.name === beResult.winner" class="badge badge-accent ml-1">{{ t.econ.winnerBadge }}</span>
              </td>
              <td v-for="c in criteria" :key="c.name" class="num text-right align-top">
                <template v-if="row.cells[c.name]">
                  <div class="text-muted">{{ nf(row.cells[c.name].current, digits(c.name)) }} →</div>
                  <div v-if="row.cells[c.name].value == null" class="text-subtle">{{ t.econ.notReachable }}</div>
                  <template v-else>
                    <div class="font-medium" :class="row.cells[c.name].kind === 'hold' ? 'text-warn' : 'text-accent-ink'">
                      {{ nf(row.cells[c.name].value, digits(c.name)) }}
                      <span class="text-xs">({{ row.cells[c.name].change_pct > 0 ? '+' : '' }}{{ nf(row.cells[c.name].change_pct, 0) }}%)</span>
                    </div>
                    <div v-if="row.cells[c.name].new_winner" class="text-xs text-subtle">
                      {{ fill(t.econ.losesTo, { name: row.cells[c.name].new_winner }) }}
                    </div>
                  </template>
                </template>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
      <p class="px-4 py-3 text-xs text-subtle">{{ t.econ.beHint }}</p>
    </section>
  </div>
</template>

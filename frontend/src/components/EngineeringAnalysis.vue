<script setup>
import { computed, ref, watch } from 'vue'
import { useLocale } from '../composables/useLocale.js'
import { useAnalysis, siteBody } from '../composables/useAnalysis.js'
import { engineering } from '../api.js'
import { chartInk } from '../chartPalette.js'
import PlotlyChart from './PlotlyChart.vue'
import Icon from './Icon.vue'
import { downloadCsv, slug } from '../exporters.js'

// Design-life traffic per interchange element and expected crashes (POST /api/engineering).
// Recomputed when the site, its parameters or the study inputs change while the tab is shown.
const props = defineProps({ dss: Object, active: Boolean, dark: Boolean })

const { t, locale } = useLocale()
const eng = useAnalysis('engineering')
const data = eng.data

let timer = null
function schedule() {
  clearTimeout(timer)
  timer = setTimeout(() => {
    if (!props.dss.selectedContext.value) return
    const body = siteBody(props.dss)
    eng.run(() => engineering(body, locale.value))
  }, 250)
}

watch(
  () => [props.active, locale.value, props.dss.selectedContext.value, JSON.stringify(props.dss.params),
    JSON.stringify(props.dss.study)],
  () => { if (props.active) schedule() },
  { immediate: true },
)

const fill = (s, vars) => Object.entries(vars).reduce((acc, [k, v]) => acc.replaceAll(`{${k}}`, v), s)
const nf = (v, d = 0) => Number(v).toLocaleString(locale.value === 'uk' ? 'uk-UA' : 'en-US',
  { minimumFractionDigits: d, maximumFractionDigits: d })

const alts = computed(() => data.value?.alternatives ?? [])
const firstYear = computed(() => data.value?.years?.[0])
const lastYear = computed(() => data.value?.years?.at(-1))
const colorOf = a => (props.dark ? a.color_dark : a.color) || '#2a78d6'

const selected = ref('')
watch(alts, list => {
  if (!list.some(a => a.name === selected.value)) selected.value = list[0]?.name ?? ''
})
const selectedAlt = computed(() => alts.value.find(a => a.name === selected.value))

function vcClass(vc) {
  if (vc > 1) return 'text-bad font-semibold'
  if (vc > 0.93) return 'text-warn font-semibold'
  return ''
}

function milestone(year) {
  return year ? String(year) : fill(t.value.eng.never, { year: lastYear.value })
}

function labelOf(alt, id) {
  return alt.opening.find(e => e.id === id)?.label ?? id
}

const vcChart = computed(() => {
  if (!data.value) return null
  const ink = chartInk(props.dark)
  const years = data.value.years
  const lines = alts.value.map(a => ({
    type: 'scatter', mode: 'lines', name: a.name, x: years, y: a.vc_series,
    line: { color: colorOf(a), width: 2.5, dash: a.feasible ? 'solid' : 'dot' },
    hovertemplate: `${a.name}<br>%{x}: V/C %{y:.2f}<extra></extra>`,
  }))
  const first = alts.value[0]
  if (first) {
    lines.push({
      type: 'scatter', mode: 'lines', name: t.value.eng.mainline, x: years, y: first.mainline_vc_series,
      line: { color: ink.muted, width: 1.5, dash: 'dash' },
      hovertemplate: `${t.value.eng.mainline}<br>%{x}: V/C %{y:.2f}<extra></extra>`,
    })
  }
  const hline = (y, label, color) => ({
    type: 'line', xref: 'paper', x0: 0, x1: 1, y0: y, y1: y, line: { color, width: 1, dash: 'dot' },
    label: { text: label, textposition: 'end', font: { size: 10, color } },
  })
  return {
    data: lines,
    layout: {
      height: 320, margin: { l: 48, r: 16, t: 8, b: 40 },
      paper_bgcolor: 'rgba(0,0,0,0)', plot_bgcolor: 'rgba(0,0,0,0)',
      font: { family: ink.font, color: ink.text, size: 12 },
      xaxis: { title: { text: t.value.eng.year }, gridcolor: ink.grid, zeroline: false },
      yaxis: { title: { text: t.value.eng.vc }, gridcolor: ink.grid, zeroline: false, rangemode: 'tozero' },
      legend: { orientation: 'h', y: -0.22 },
      shapes: [hline(0.93, t.value.eng.losE, '#c98500'), hline(1.0, t.value.eng.capacity, '#e34948')],
    },
  }
})

const crashChart = computed(() => {
  if (!data.value) return null
  const ink = chartInk(props.dark)
  const names = alts.value.map(a => a.name)
  return {
    data: [
      { type: 'bar', name: t.value.eng.fi, x: names, y: alts.value.map(a => a.fi_total),
        marker: { color: alts.value.map(colorOf) },
        hovertemplate: `%{x}<br>${t.value.eng.fi}: %{y:.1f}<extra></extra>` },
      { type: 'bar', name: t.value.eng.pdo, x: names, y: alts.value.map(a => a.crashes_total - a.fi_total),
        marker: { color: alts.value.map(colorOf), opacity: 0.4 },
        hovertemplate: `%{x}<br>${t.value.eng.pdo}: %{y:.1f}<extra></extra>` },
    ],
    layout: {
      barmode: 'stack', height: 300, margin: { l: 48, r: 16, t: 8, b: 40 },
      paper_bgcolor: 'rgba(0,0,0,0)', plot_bgcolor: 'rgba(0,0,0,0)',
      font: { family: ink.font, color: ink.text, size: 12 },
      xaxis: { gridcolor: ink.grid }, yaxis: { gridcolor: ink.grid, zeroline: false },
      legend: { orientation: 'h', y: -0.18 },
    },
  }
})

function exportCsv() {
  const d = data.value
  if (!d) return
  const rows = [['Alternative', 'Feasible', 'Element', 'Kind', 'Capacity (pc/h)',
    `Volume ${firstYear.value} (pc/h)`, `V/C ${firstYear.value}`, `LOS ${firstYear.value}`,
    `Volume ${lastYear.value} (pc/h)`, `V/C ${lastYear.value}`, `LOS ${lastYear.value}`, `Delay ${lastYear.value} (s/veh)`]]
  for (const a of d.alternatives) {
    a.opening.forEach((e, i) => {
      const x = a.design[i]
      rows.push([a.name, a.feasible, e.label, e.kind, e.capacity_pcph, e.volume_pcph, e.vc, e.los,
        x.volume_pcph, x.vc, x.los, x.delay_s])
    })
  }
  rows.push([], ['Year', ...d.alternatives.flatMap(a => [`${a.name} V/C`, `${a.name} crashes`, `${a.name} F+I`, `${a.name} delay (veh·h)`])])
  d.years.forEach((y, i) => rows.push([y, ...d.alternatives.flatMap(a => [a.vc_series[i], a.crashes[i], a.fi_crashes[i], a.delay_vehh[i]])]))
  downloadCsv(`tdss-traffic-safety-${slug(d.context)}.csv`, rows)
}

const elementRows = computed(() => {
  const a = selectedAlt.value
  if (!a) return []
  return a.opening.map((e, i) => ({ open: e, design: a.design[i] }))
})
</script>

<template>
  <div class="space-y-3 md:space-y-4">
    <section class="card p-4">
      <div class="flex items-start gap-3">
        <div class="min-w-0 flex-1">
          <h2 class="card-title">{{ t.eng.title }}</h2>
          <p class="card-desc">{{ t.eng.desc }}</p>
        </div>
        <span class="spinner mt-1 transition-opacity duration-200" :class="eng.loading.value ? 'opacity-100' : 'opacity-0'"></span>
        <button type="button" class="btn shrink-0" :disabled="!data" @click="exportCsv"><Icon name="download" class="text-sm" /> {{ t.exportCsv }}</button>
      </div>
      <p v-if="data" class="num mt-3 text-xs text-muted">
        {{ fill(t.eng.site, { v: nf(data.peak_hour_veh), q: nf(data.peak_direction_pcph), t: nf(data.turning_pcph),
                               c: nf(data.lane_capacity_pcph), hv: nf(data.hv_factor, 2) }) }}
      </p>
      <p v-if="eng.error.value" class="notice notice-bad mt-3">{{ eng.error.value }}</p>
    </section>

    <template v-if="data">
      <section class="card overflow-hidden">
        <h3 class="card-title px-4 pt-4">{{ t.eng.summaryTitle }}</h3>
        <div class="table-scroll mt-2">
          <table class="table w-full text-[13px]">
            <thead>
              <tr>
                <th class="text-left">{{ t.eng.alternative }}</th>
                <th class="text-left">{{ t.eng.critical }}</th>
                <th class="text-right">{{ fill(t.eng.vcOpening, { year: firstYear }) }}</th>
                <th class="text-right">{{ fill(t.eng.vcDesign, { year: lastYear }) }}</th>
                <th class="text-center">{{ t.eng.los }}</th>
                <th class="text-right">{{ t.eng.yearLosE }}</th>
                <th class="text-right">{{ t.eng.yearCapacity }}</th>
                <th class="text-right">{{ t.eng.crashesYear }}</th>
                <th class="text-right">{{ t.eng.fiTotal }}</th>
                <th class="text-right">{{ t.eng.delayTotal }}</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="a in alts" :key="a.name" class="cursor-pointer" :class="a.name === selected ? 'bg-accent-soft' : ''"
                  @click="selected = a.name">
                <td class="whitespace-nowrap">
                  <span class="mr-1.5 inline-block h-2.5 w-2.5 rounded-full align-middle" :style="{ background: colorOf(a) }"></span>
                  {{ a.name }}
                  <span v-if="!a.feasible" class="badge ml-1">{{ t.eng.infeasible }}</span>
                </td>
                <td class="text-muted">{{ labelOf(a, a.critical_element) }}</td>
                <td class="num text-right" :class="vcClass(a.vc_series[0])">{{ nf(a.vc_series[0], 2) }}</td>
                <td class="num text-right" :class="vcClass(a.vc_series.at(-1))">{{ nf(a.vc_series.at(-1), 2) }}</td>
                <td class="num text-center">
                  {{ a.opening.find(e => e.id === a.critical_element)?.los }} → {{ a.design.find(e => e.id === a.critical_element)?.los }}
                </td>
                <td class="num text-right" :class="a.year_los_e ? 'text-warn' : 'text-muted'">{{ milestone(a.year_los_e) }}</td>
                <td class="num text-right" :class="a.year_capacity ? 'text-bad' : 'text-muted'">{{ milestone(a.year_capacity) }}</td>
                <td class="num text-right">{{ nf(a.crashes[0], 1) }}</td>
                <td class="num text-right">{{ nf(a.fi_total, 1) }}</td>
                <td class="num text-right">{{ nf(a.delay_total_vehh) }}</td>
              </tr>
            </tbody>
          </table>
        </div>
      </section>

      <div class="grid gap-3 md:gap-4 xl:grid-cols-2">
        <section class="card p-4">
          <h3 class="card-title">{{ t.eng.vcChart }}</h3>
          <p class="card-desc">{{ t.eng.vcChartDesc }}</p>
          <PlotlyChart :chart="vcChart" :dark="dark" class="mt-2" />
        </section>
        <section class="card p-4">
          <h3 class="card-title">{{ t.eng.crashChart }}</h3>
          <p class="card-desc">{{ t.eng.crashChartDesc }}</p>
          <PlotlyChart :chart="crashChart" :dark="dark" class="mt-2" />
        </section>
      </div>

      <section v-if="selectedAlt" class="card overflow-hidden">
        <div class="flex flex-wrap items-end gap-3 px-4 pt-4">
          <div class="min-w-0 flex-1">
            <h3 class="card-title">{{ fill(t.eng.elementsTitle, { name: selectedAlt.name }) }}</h3>
            <p class="card-desc">{{ t.eng.elementsDesc }}</p>
          </div>
          <select v-model="selected" class="field w-auto">
            <option v-for="a in alts" :key="a.name" :value="a.name">{{ a.name }}</option>
          </select>
        </div>
        <div class="table-scroll mt-3">
          <table class="table w-full text-[13px]">
            <thead>
              <tr>
                <th class="text-left">{{ t.eng.element }}</th>
                <th class="text-right">{{ t.eng.capacityPcph }}</th>
                <th class="text-right">{{ t.eng.volume }} {{ firstYear }}</th>
                <th class="text-right">V/C</th>
                <th class="text-center">{{ t.eng.los }}</th>
                <th class="text-right">{{ t.eng.volume }} {{ lastYear }}</th>
                <th class="text-right">V/C</th>
                <th class="text-center">{{ t.eng.los }}</th>
                <th class="text-right">{{ t.eng.delay }} {{ lastYear }}</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="r in elementRows" :key="r.open.id" :class="r.open.shared ? 'text-muted' : ''">
                <td>
                  {{ r.open.label }}
                  <span v-if="r.open.shared" class="badge ml-1">{{ t.eng.shared }}</span>
                  <span v-else-if="r.open.id === selectedAlt.critical_element" class="badge badge-accent ml-1">{{ t.eng.critical }}</span>
                </td>
                <td class="num text-right">{{ nf(r.open.capacity_pcph) }}</td>
                <td class="num text-right">{{ nf(r.open.volume_pcph) }}</td>
                <td class="num text-right" :class="vcClass(r.open.vc)">{{ nf(r.open.vc, 2) }}</td>
                <td class="num text-center">{{ r.open.los }}</td>
                <td class="num text-right">{{ nf(r.design.volume_pcph) }}</td>
                <td class="num text-right" :class="vcClass(r.design.vc)">{{ nf(r.design.vc, 2) }}</td>
                <td class="num text-center">{{ r.design.los }}</td>
                <td class="num text-right">{{ nf(r.design.delay_s, 1) }}</td>
              </tr>
            </tbody>
          </table>
        </div>
        <p v-if="selectedAlt.cmf_speed > 1" class="px-4 pb-1 text-xs text-warn">{{ fill(t.eng.cmf, { cmf: nf(selectedAlt.cmf_speed, 2) }) }}</p>
        <p class="px-4 pb-4 pt-2 text-xs text-subtle">{{ t.eng.assumptions }}</p>
      </section>
    </template>
  </div>
</template>

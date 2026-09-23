<script setup>
import { computed, ref } from 'vue'
import PlotlyChart from './PlotlyChart.vue'
import { useLocale } from '../composables/useLocale.js'

const props = defineProps({
  data: Object,
  dark: Boolean,
})

const { t } = useLocale()
const corrKind = ref('spearman')

const METHOD_COLORS = {
  light: { wsm: '#0f766e', topsis: '#1d4ed8', ahp: '#7c3aed', promethee: '#ea580c', vikor: '#be123c' },
  dark:  { wsm: '#2dd4bf', topsis: '#60a5fa', ahp: '#a78bfa', promethee: '#fb923c', vikor: '#fb7185' },
}

const methodIds = computed(() => Object.keys(props.data?.method_results ?? {}))
const agreement = computed(() => props.data?.rank_agreement)
const methodLabel = id => t.value.methodLabels?.[id] ?? props.data.method_results[id].label
const methodColor = id => METHOD_COLORS[props.dark ? 'dark' : 'light'][id] ?? '#64748b'

function altColor(name) {
  const r = props.data?.results?.find(r => r.alternative_name === name)
  return props.dark ? (r?.color_dark || '#2dd4bf') : (r?.color || '#0f766e')
}

// Rows ordered by consensus rank (or by the first method's rank with a single method).
const rows = computed(() => {
  const order = agreement.value?.consensus ?? props.data.method_results[methodIds.value[0]].scores
  return order.map(o => ({
    name: o.alternative_name,
    consensus: agreement.value ? o.rank : null,
    ranks: Object.fromEntries(methodIds.value.map(id => [
      id, props.data.method_results[id].scores.find(s => s.alternative_name === o.alternative_name)?.rank,
    ])),
  }))
})

const nAlts = computed(() => rows.value.length)

function rankStyle(rank) {
  if (rank == null) return {}
  // 1 = strong teal, last = faint.
  const share = nAlts.value > 1 ? 1 - (rank - 1) / (nAlts.value - 1) : 1
  const alpha = (0.12 + 0.5 * share).toFixed(2)
  return { background: props.dark ? `rgba(45, 212, 191, ${alpha})` : `rgba(15, 118, 110, ${alpha})` }
}

const compromise = computed(() => {
  const v = props.data?.method_results?.vikor?.details
  return v && v.compromise_set?.length > 1 ? v.compromise_set : null
})

function baseLayout(title, height) {
  const p = props.dark
  return {
    paper_bgcolor: 'rgba(0,0,0,0)', plot_bgcolor: 'rgba(0,0,0,0)',
    font: { family: 'Inter, system-ui, sans-serif', color: p ? '#e2e8f0' : '#0f172a', size: 12 },
    title: { text: title, font: { size: 15 }, x: 0.02 },
    margin: { l: 56, r: 24, t: 56, b: 56 },
    height,
    autosize: true,
  }
}

const utilityChart = computed(() => {
  const p = props.dark
  const names = rows.value.map(r => r.name)
  return {
    data: methodIds.value.map(id => {
      const scores = props.data.method_results[id].scores
      return {
        type: 'bar',
        name: methodLabel(id),
        x: names,
        y: names.map(n => scores.find(s => s.alternative_name === n)?.utility),
        marker: { color: methodColor(id) },
        hovertemplate: `<b>%{x}</b><br>${methodLabel(id)}: %{y:.3f}<extra></extra>`,
      }
    }),
    layout: {
      ...baseLayout(t.value.chartUtilityTitle, 360),
      barmode: 'group',
      yaxis: { title: t.value.chartUtilityAxis, range: [0, 1.05], gridcolor: p ? '#334155' : '#cbd5e1' },
      xaxis: { tickfont: { size: 12 } },
      legend: { orientation: 'h', y: -0.2, x: 0.5, xanchor: 'center', bgcolor: 'rgba(0,0,0,0)' },
    },
  }
})

const corrChart = computed(() => {
  const a = agreement.value
  const labels = a.methods.map(methodLabel)
  const z = a[corrKind.value]
  return {
    data: [{
      type: 'heatmap',
      x: labels,
      y: labels,
      z,
      zmin: -1,
      zmax: 1,
      colorscale: [[0, '#be123c'], [0.5, props.dark ? '#1e293b' : '#f8fafc'], [1, '#0f766e']],
      text: z.map(row => row.map(v => (v == null ? '—' : v.toFixed(2)))),
      texttemplate: '%{text}',
      hovertemplate: '%{y} × %{x}: %{text}<extra></extra>',
      showscale: false,
    }],
    layout: {
      ...baseLayout('', 330),
      margin: { l: 56, r: 24, t: 16, b: 56 },
      yaxis: { autorange: 'reversed', automargin: true },
      xaxis: { automargin: true },
    },
  }
})

const panelClass = computed(() => props.dark
  ? 'bg-white/[0.06] border border-white/10'
  : 'bg-white/60 border border-white/80 shadow-[0_8px_30px_rgb(0,0,0,0.04)]')
</script>

<template>
  <div v-if="methodIds.length" class="mb-6">
    <div class="rounded-[28px] backdrop-blur-2xl p-6 lg:p-8 mb-6" :class="panelClass">
      <div class="flex flex-wrap items-start justify-between gap-3 mb-4">
        <div>
          <h2 class="text-xl font-semibold tracking-tight mb-1" :class="dark ? 'text-white/90' : 'text-slate-900'">
            {{ t.comparisonTitle }}
          </h2>
          <p class="text-xs" :class="dark ? 'text-white/40' : 'text-slate-500'">{{ t.comparisonDesc }}</p>
        </div>
        <span v-if="agreement" class="px-3 py-1 rounded-full text-xs font-semibold"
              :class="agreement.unanimous_winner
                ? (dark ? 'bg-teal-500/20 text-teal-200' : 'bg-teal-100 text-teal-800')
                : (dark ? 'bg-orange-500/20 text-orange-200' : 'bg-orange-100 text-orange-800')">
          {{ agreement.unanimous_winner ? t.unanimous : t.disagree }}
        </span>
      </div>

      <div class="overflow-x-auto">
        <table class="w-full text-sm">
          <thead>
            <tr>
              <th class="px-3 py-2 text-left font-semibold" :class="dark ? 'text-slate-300' : 'text-slate-500'">{{ t.alternative }}</th>
              <th v-for="id in methodIds" :key="id" class="px-3 py-2 text-center font-semibold"
                  :class="dark ? 'text-slate-300' : 'text-slate-500'">{{ methodLabel(id) }}</th>
              <th v-if="agreement" class="px-3 py-2 text-center font-bold"
                  :class="dark ? 'text-slate-100' : 'text-slate-900'">{{ t.consensus }}</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="row in rows" :key="row.name" class="border-t" :class="dark ? 'border-slate-700' : 'border-black/5'">
              <td class="px-3 py-2 font-semibold" :style="{ color: altColor(row.name) }">{{ row.name }}</td>
              <td v-for="id in methodIds" :key="id" class="px-3 py-2 text-center font-medium tabular-nums"
                  :class="dark ? 'text-slate-100' : 'text-slate-900'" :style="rankStyle(row.ranks[id])">
                #{{ row.ranks[id] }}
              </td>
              <td v-if="agreement" class="px-3 py-2 text-center font-bold tabular-nums"
                  :class="dark ? 'text-slate-100' : 'text-slate-900'" :style="rankStyle(row.consensus)">
                #{{ row.consensus }}
              </td>
            </tr>
          </tbody>
        </table>
      </div>

      <p v-if="compromise" class="text-xs mt-3" :class="dark ? 'text-slate-400' : 'text-slate-500'">
        {{ t.vikorCompromise }}: <b>{{ compromise.join(', ') }}</b>
      </p>
      <p v-if="!agreement" class="text-xs mt-3" :class="dark ? 'text-slate-400' : 'text-slate-500'">
        {{ t.agreementNeedsTwo }}
      </p>
    </div>

    <div class="grid grid-cols-1 lg:grid-cols-2 gap-6">
      <div class="rounded-[28px] overflow-hidden backdrop-blur-2xl" :class="panelClass">
        <PlotlyChart :chart="utilityChart" :dark="dark" />
      </div>
      <div v-if="agreement" class="rounded-[28px] overflow-hidden backdrop-blur-2xl" :class="panelClass">
        <div class="flex flex-wrap items-center justify-between gap-2 px-4 pt-4 text-xs">
          <span class="text-[15px]" :class="dark ? 'text-slate-200' : 'text-slate-900'">{{ t.agreementTitle }}</span>
          <div class="flex gap-1">
          <button v-for="k in ['spearman', 'kendall']" :key="k" type="button" @click="corrKind = k"
                  class="px-2 py-0.5 rounded-md font-semibold"
                  :class="corrKind === k
                    ? (dark ? 'bg-slate-600 text-white' : 'bg-slate-800 text-white')
                    : (dark ? 'text-slate-400' : 'text-slate-500')">
            {{ t[k] }}
          </button>
          </div>
        </div>
        <PlotlyChart :chart="corrChart" :dark="dark" />
      </div>
    </div>
  </div>
</template>

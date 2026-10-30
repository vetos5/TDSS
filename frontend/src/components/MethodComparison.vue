<script setup>
import { computed, ref } from 'vue'
import PlotlyChart from './PlotlyChart.vue'
import Icon from './Icon.vue'
import { useLocale } from '../composables/useLocale.js'
import { METHOD_COLORS, SURFACE, chartInk, divergingScale } from '../chartPalette.js'
import { useViewport } from '../composables/useViewport.js'

const props = defineProps({
  data: Object,
  dark: Boolean,
})

const { t } = useLocale()
const { narrow } = useViewport()
const corrKind = ref('spearman')

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
  return { background: props.dark ? `rgba(57, 135, 229, ${alpha})` : `rgba(42, 120, 214, ${alpha})` }
}

const compromise = computed(() => {
  const v = props.data?.method_results?.vikor?.details
  return v && v.compromise_set?.length > 1 ? v.compromise_set : null
})

// Chart titles live in the card header, so layouts carry none.
function baseLayout(height) {
  const ink = chartInk(props.dark)
  return {
    paper_bgcolor: 'rgba(0,0,0,0)', plot_bgcolor: 'rgba(0,0,0,0)',
    font: { family: ink.font, color: ink.text, size: 11 },
    margin: narrow.value ? { l: 32, r: 8, t: 8, b: 40 } : { l: 56, r: 24, t: 12, b: 56 },
    height,
    autosize: true,
  }
}

const utilityChart = computed(() => {
  const ink = chartInk(props.dark)
  const names = rows.value.map(r => r.name)
  return {
    data: methodIds.value.map(id => {
      const scores = props.data.method_results[id].scores
      return {
        type: 'bar',
        name: methodLabel(id),
        x: names,
        y: names.map(n => scores.find(s => s.alternative_name === n)?.utility),
        marker: { color: methodColor(id), cornerradius: 4, line: { color: SURFACE[props.dark ? 'dark' : 'light'], width: 2 } },
        hovertemplate: `<b>%{x}</b><br>${methodLabel(id)}: %{y:.3f}<extra></extra>`,
      }
    }),
    layout: {
      ...baseLayout(narrow.value ? 300 : 320),
      barmode: 'group',
      bargap: narrow.value ? 0.18 : undefined,
      yaxis: { title: { text: narrow.value ? '' : t.value.chartUtilityAxis, font: { color: ink.muted } }, range: [0, 1.05], gridcolor: ink.grid, zerolinecolor: ink.grid, tickfont: { color: ink.muted }, automargin: true },
      xaxis: { tickfont: { size: 11, color: ink.text }, automargin: true },
      legend: { orientation: 'h', y: narrow.value ? -0.14 : -0.2, x: 0.5, xanchor: 'center', yanchor: narrow.value ? 'top' : undefined, font: { color: ink.muted }, bgcolor: 'rgba(0,0,0,0)' },
    },
  }
})

const corrChart = computed(() => {
  const ink = chartInk(props.dark)
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
      colorscale: divergingScale(props.dark),
      xgap: 2,
      ygap: 2,
      text: z.map(row => row.map(v => (v == null ? '—' : v.toFixed(2)))),
      texttemplate: '%{text}',
      hovertemplate: '%{y} × %{x}: %{text}<extra></extra>',
      showscale: false,
    }],
    layout: {
      ...baseLayout(narrow.value ? 300 : 320),
      margin: narrow.value ? { l: 8, r: 8, t: 8, b: 8 } : { l: 56, r: 24, t: 8, b: 56 },
      yaxis: { autorange: 'reversed', automargin: true, tickfont: { color: ink.text, ...(narrow.value && { size: 10 }) } },
      xaxis: { automargin: true, tickfont: { color: ink.text, ...(narrow.value && { size: 10 }) }, ...(narrow.value && { tickangle: -40 }) },
    },
  }
})
</script>

<template>
  <div v-if="methodIds.length" class="space-y-4">
    <section class="card overflow-hidden">
      <div class="flex flex-wrap items-start justify-between gap-3 border-b border-line px-4 py-3">
        <div class="min-w-0">
          <h2 class="card-title">{{ t.comparisonTitle }}</h2>
          <p class="card-desc">{{ t.comparisonDesc }}</p>
        </div>
        <span v-if="agreement" class="shrink-0"
              :class="agreement.unanimous_winner
                ? 'badge-accent'
                : 'inline-flex items-center gap-1 rounded-md bg-warn-soft px-1.5 py-0.5 text-[0.7rem] font-medium text-warn'">
          <Icon :name="agreement.unanimous_winner ? 'check' : 'alert-triangle'" />
          {{ agreement.unanimous_winner ? t.unanimous : t.disagree }}
        </span>
      </div>

      <div class="table-scroll">
        <table class="table border-separate border-spacing-0 [&_td]:whitespace-nowrap">
          <thead>
            <tr>
              <th class="sticky-col">{{ t.alternative }}</th>
              <th v-for="id in methodIds" :key="id" class="text-center">{{ methodLabel(id) }}</th>
              <th v-if="agreement" class="text-center text-fg">{{ t.consensus }}</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="row in rows" :key="row.name">
              <td class="sticky-col font-medium">
                <span class="mr-1.5 inline-block h-2 w-2 rounded-full align-middle" :style="{ background: altColor(row.name) }" aria-hidden="true"></span>{{ row.name }}
              </td>
              <td v-for="id in methodIds" :key="id" class="num text-center" :style="rankStyle(row.ranks[id])">
                #{{ row.ranks[id] }}
              </td>
              <td v-if="agreement" class="num text-center font-semibold" :style="rankStyle(row.consensus)">
                #{{ row.consensus }}
              </td>
            </tr>
          </tbody>
        </table>
      </div>

      <p v-if="compromise" class="border-t border-line px-4 py-2.5 text-xs text-muted">
        {{ t.vikorCompromise }}: <span class="font-medium text-fg">{{ compromise.join(', ') }}</span>
      </p>
      <p v-if="!agreement" class="border-t border-line px-4 py-2.5 text-xs text-muted">
        {{ t.agreementNeedsTwo }}
      </p>
    </section>

    <div class="grid grid-cols-1 gap-4 lg:grid-cols-2">
      <section class="card overflow-hidden">
        <h2 class="card-title px-4 pt-4">{{ t.chartUtilityTitle }}</h2>
        <PlotlyChart :chart="utilityChart" :dark="dark" />
      </section>
      <section v-if="agreement" class="card overflow-hidden">
        <div class="flex flex-wrap items-center justify-between gap-2 px-4 pt-4">
          <h2 class="card-title">{{ t.agreementTitle }}</h2>
          <div class="seg">
            <button v-for="k in ['spearman', 'kendall']" :key="k" type="button" @click="corrKind = k"
                    :aria-pressed="corrKind === k" class="seg-item">
              {{ t[k] }}
            </button>
          </div>
        </div>
        <PlotlyChart :chart="corrChart" :dark="dark" />
      </section>
    </div>
  </div>
</template>

<style scoped>
/* The alternative column stays put while the method ranks scroll sideways on phones. */
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

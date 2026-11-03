<script setup>
import { computed, watch } from 'vue'
import { useLocale } from '../composables/useLocale.js'
import { useAnalysis } from '../composables/useAnalysis.js'
import { useGroup, MAX_STAKEHOLDERS } from '../composables/useGroup.js'
import { CRITERION_KEYS } from '../composables/useDSS.js'
import { group as fetchGroup } from '../api.js'
import { downloadCsv, slug } from '../exporters.js'
import Icon from './Icon.vue'

// Several stakeholders' weights, each one's ranking, the aggregated group weights and ranking,
// and how far each stakeholder agrees with the group (POST /api/group).
const props = defineProps({ dss: Object, active: Boolean, dark: Boolean })

const { t, locale } = useLocale()
const { stakeholders, add, remove, reset } = useGroup()
const req = useAnalysis('group')
const data = req.data

const BAR_COLORS = {
  construction_cost_mln: '#0f766e',
  land_area_hectares: '#ea580c',
  throughput_vph: '#7c3aed',
  safety_index: '#1d4ed8',
}
const criterionLabel = computed(() => ({
  construction_cost_mln: t.value.constructionCost,
  land_area_hectares: t.value.landArea,
  throughput_vph: t.value.throughput,
  safety_index: t.value.safetyIndex,
}))

function payload() {
  const d = props.dss
  return {
    context: d.selectedContext.value,
    weights: d.normalizedWeights(),
    params: { ...d.params },
    methods: d.methods.value.length ? d.methods.value : ['wsm'],
    value_source: d.valueSource.value,
    stakeholders: stakeholders.map(s => ({
      name: (s.name || '').trim().slice(0, 40) || '—',
      influence: Math.min(10, Math.max(0.1, Number(s.influence) || 1)),
      weights: Object.fromEntries(CRITERION_KEYS.map(k => [k, Math.min(1, Math.max(0, (Number(s.weights[k]) || 0) / 100))])),
    })),
  }
}

let timer = null
function schedule() {
  clearTimeout(timer)
  timer = setTimeout(() => {
    if (!props.dss.selectedContext.value) return
    const body = payload()
    req.run(() => fetchGroup(body, locale.value))
  }, 350)
}

watch(
  () => [props.active, locale.value, props.dss.selectedContext.value, JSON.stringify(props.dss.params),
    props.dss.methods.value.join(), props.dss.valueSource.value, JSON.stringify(stakeholders)],
  () => { if (props.active) schedule() },
  { immediate: true },
)

const fill = (s, vars) => Object.entries(vars).reduce((acc, [k, v]) => acc.replaceAll(`{${k}}`, v), s)
const nf = (v, d = 2) => v == null ? '—' : Number(v).toLocaleString(locale.value === 'uk' ? 'uk-UA' : 'en-US',
  { minimumFractionDigits: d, maximumFractionDigits: d })

const colorOf = name => {
  const r = props.dss.evalData.value?.results?.find(x => x.alternative_name === name)
  return (props.dark ? r?.color_dark : r?.color) || '#2a78d6'
}

const basis = computed(() => {
  const b = data.value?.basis
  if (!b) return ''
  return b === 'consensus' ? t.value.group.basisConsensus
    : fill(t.value.group.basisMethod, { method: t.value.methodLabels[b] ?? b })
})

function tauClass(tau) {
  if (tau == null) return 'text-subtle'
  if (tau >= 0.6) return 'text-ok'
  if (tau < 0) return 'text-bad'
  return 'text-warn'
}

function exportCsv() {
  const d = data.value
  if (!d) return
  const head = [t.value.group.stakeholder, t.value.group.influence,
    ...CRITERION_KEYS.map(k => criterionLabel.value[k]), t.value.group.winner, t.value.group.kendall,
    ...d.alternatives.map(a => `${a} (utility)`)]
  const rows = d.stakeholders.map(s => [s.name, s.influence, ...CRITERION_KEYS.map(k => s.weights[k].toFixed(4)),
    s.winner, s.kendall?.toFixed(3) ?? '', ...d.alternatives.map(a => s.utility[a].toFixed(4))])
  rows.push([t.value.group.group, '', ...CRITERION_KEYS.map(k => d.group_weights[k].toFixed(4)), d.group_winner, '',
    ...d.alternatives.map(a => d.group_utility[a].toFixed(4))])
  downloadCsv(`tdss-group-${slug(d.context)}.csv`, [head, ...rows])
}
</script>

<template>
  <div class="space-y-3 md:space-y-4">
    <section class="card p-4">
      <div class="flex items-start gap-3">
        <div class="min-w-0 flex-1">
          <h2 class="card-title">{{ t.group.title }}</h2>
          <p class="card-desc">{{ t.group.desc }}</p>
        </div>
        <span class="spinner mt-1 transition-opacity duration-200" :class="req.loading.value ? 'opacity-100' : 'opacity-0'"></span>
      </div>

      <div class="table-scroll mt-4">
        <table class="table w-full text-[13px]">
          <thead>
            <tr>
              <th class="text-left">{{ t.group.name }}</th>
              <th class="text-right">{{ t.group.influence }}</th>
              <th v-for="k in CRITERION_KEYS" :key="k" class="text-right">{{ criterionLabel[k] }} %</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="(s, i) in stakeholders" :key="i">
              <td><input v-model="s.name" maxlength="40" class="field min-w-36" :aria-label="t.group.name" /></td>
              <td class="text-right">
                <input v-model.number="s.influence" type="number" min="0.1" max="10" step="0.5"
                       class="field num w-20 text-right" :aria-label="t.group.influence" />
              </td>
              <td v-for="k in CRITERION_KEYS" :key="k" class="text-right">
                <input v-model.number="s.weights[k]" type="number" min="0" max="100" step="5"
                       class="field num w-20 text-right" :aria-label="criterionLabel[k]" />
              </td>
              <td class="text-right">
                <button type="button" class="icon-btn" :disabled="stakeholders.length <= 2"
                        :aria-label="t.group.remove" :title="t.group.remove" @click="remove(i)">
                  <Icon name="trash" class="text-sm" />
                </button>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
      <div class="mt-3 flex flex-wrap gap-2">
        <button type="button" class="btn" :disabled="stakeholders.length >= MAX_STAKEHOLDERS" @click="add">{{ t.group.add }}</button>
        <button type="button" class="btn-ghost btn" @click="reset">{{ t.group.reset }}</button>
        <button type="button" class="btn ml-auto" :disabled="!data" @click="exportCsv">
          <Icon name="download" class="text-sm" /> {{ t.exportCsv }}
        </button>
      </div>
      <p v-if="req.error.value" class="notice notice-bad mt-3">{{ req.error.value }}</p>
    </section>

    <template v-if="data">
      <div class="notice notice-ok flex items-start gap-2">
        <Icon name="users" class="mt-0.5 text-sm" />
        <span>
          <strong class="font-semibold">{{ fill(t.group.groupWinner, { name: data.group_winner }) }}</strong>
          <span class="text-muted"> · {{ basis }}</span>
        </span>
      </div>

      <div class="grid gap-3 md:gap-4 xl:grid-cols-2">
        <section class="card p-4">
          <h3 class="card-title">{{ t.group.groupWeights }}</h3>
          <div class="mt-3 space-y-2">
            <div v-for="k in CRITERION_KEYS" :key="k" class="flex items-center gap-2 text-xs text-muted">
              <span class="w-36 truncate">{{ criterionLabel[k] }}</span>
              <div class="relative h-1.5 flex-1 overflow-hidden rounded-full bg-surface-3">
                <div class="h-full rounded-full transition-all duration-300"
                     :style="{ width: (data.group_weights[k] * 100) + '%', background: BAR_COLORS[k] }"></div>
              </div>
              <span class="num w-10 text-right text-fg">{{ nf(data.group_weights[k]) }}</span>
            </div>
          </div>
        </section>

        <section class="card p-4">
          <h3 class="card-title">{{ t.group.share }}</h3>
          <p class="card-desc">{{ t.group.shareDesc }}</p>
          <div class="mt-3 flex h-3 overflow-hidden rounded-full bg-surface-3">
            <div v-for="(v, name) in data.winner_share" :key="name" :style="{ width: (v * 100) + '%', background: colorOf(name) }"
                 :title="`${name}: ${Math.round(v * 100)}%`"></div>
          </div>
          <ul class="mt-2 space-y-1 text-xs">
            <li v-for="(v, name) in data.winner_share" :key="name" class="flex items-center gap-2">
              <span class="inline-block h-2.5 w-2.5 rounded-full" :style="{ background: colorOf(name) }"></span>
              <span class="flex-1">{{ name }}</span>
              <span class="num text-muted">{{ Math.round(v * 100) }}%</span>
            </li>
          </ul>
        </section>
      </div>

      <section class="card overflow-hidden">
        <h3 class="card-title px-4 pt-4">{{ t.group.rankings }}</h3>
        <div class="table-scroll mt-2">
          <table class="table w-full text-[13px]">
            <thead>
              <tr>
                <th class="text-left">{{ t.group.stakeholder }}</th>
                <th class="text-left">{{ t.group.ranking }}</th>
                <th class="text-right" :title="t.group.kendallHint">{{ t.group.kendall }}</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="s in data.stakeholders" :key="s.name">
                <td class="whitespace-nowrap">{{ s.name }} <span class="num text-subtle">×{{ nf(s.influence, 1) }}</span></td>
                <td>
                  <span v-for="(name, i) in s.ranking" :key="name" class="whitespace-nowrap">
                    <span class="mr-1 inline-block h-2 w-2 rounded-full align-middle" :style="{ background: colorOf(name) }"></span>{{ name }}<span v-if="i < s.ranking.length - 1" class="px-1.5 text-subtle">›</span>
                  </span>
                </td>
                <td class="num text-right" :class="tauClass(s.kendall)">{{ nf(s.kendall) }}</td>
              </tr>
              <tr class="font-semibold">
                <td>{{ t.group.group }}</td>
                <td>
                  <span v-for="(name, i) in data.group_ranking" :key="name" class="whitespace-nowrap">
                    <span class="mr-1 inline-block h-2 w-2 rounded-full align-middle" :style="{ background: colorOf(name) }"></span>{{ name }}<span v-if="i < data.group_ranking.length - 1" class="px-1.5 text-subtle">›</span>
                  </span>
                </td>
                <td></td>
              </tr>
            </tbody>
          </table>
        </div>
        <p class="px-4 py-3 text-xs text-subtle">{{ t.group.kendallHint }}</p>
      </section>
    </template>
  </div>
</template>

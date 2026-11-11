<script setup>
import { computed } from 'vue'
import { blueprintUrl } from '../api.js'
import { useLocale } from '../composables/useLocale.js'
import Icon from './Icon.vue'

const props = defineProps({
  data: Object,
  params: Object,
  dark: Boolean,
})

const { t } = useLocale()

function displayTerrain(val) { return t.value.terrainDisplay?.[val] ?? val }
function displayEnv(val)     { return t.value.envDisplay?.[val] ?? val }

const winner = computed(() => props.data?.results?.[0])
const maxScore = computed(() => winner.value?.total_score || 1)

function altColor(name) {
  const r = props.data?.results?.find(r => r.alternative_name === name)
  return props.dark ? (r?.color_dark || '#2dd4bf') : (r?.color || '#0f766e')
}

function isFeasible(rv) {
  return rv.construction_cost_mln <= props.params.budget && rv.land_area_hectares <= props.params.land_limit
}
</script>

<template>
  <div v-if="data" class="space-y-4">
    <!-- Project parameters summary -->
    <section class="card p-4">
      <h2 class="card-title">{{ t.blueprints }}</h2>
      <p class="card-desc">{{ t.projectParamsSummary }}</p>
      <dl class="mt-3 grid grid-cols-2 gap-x-4 gap-y-2.5 sm:grid-cols-4 xl:grid-cols-8">
        <div><dt class="text-xs text-muted">{{ t.designSpeedShort }}</dt><dd class="num text-[13px] font-medium">{{ params.design_speed }} km/h</dd></div>
        <div><dt class="text-xs text-muted">AADT</dt><dd class="num text-[13px] font-medium">{{ params.aadt.toLocaleString() }}</dd></div>
        <div><dt class="text-xs text-muted">{{ t.peakFactorShort }}</dt><dd class="num text-[13px] font-medium">{{ params.peak_factor }}%</dd></div>
        <div><dt class="text-xs text-muted">{{ t.lanesShort }}</dt><dd class="num text-[13px] font-medium">{{ params.num_lanes }}{{ t.dir }}</dd></div>
        <div><dt class="text-xs text-muted">{{ t.budgetShort }}</dt><dd class="num text-[13px] font-medium">${{ params.budget }}M</dd></div>
        <div><dt class="text-xs text-muted">{{ t.landShort }}</dt><dd class="num text-[13px] font-medium">{{ params.land_limit }} ha</dd></div>
        <div><dt class="text-xs text-muted">{{ t.terrainShort }}</dt><dd class="text-[13px] font-medium">{{ displayTerrain(params.terrain) }}</dd></div>
        <div><dt class="text-xs text-muted">{{ t.envShort }}</dt><dd class="text-[13px] font-medium">{{ displayEnv(params.env_sensitivity) }}</dd></div>
      </dl>
    </section>

    <!-- Winner spotlight -->
    <div class="grid grid-cols-1 gap-4 md:grid-cols-7">
      <section class="card flex flex-col p-4 md:col-span-2">
        <div class="flex items-center justify-between gap-2">
          <span class="badge-accent"><Icon name="trophy" />{{ t.recommended }}</span>
          <span class="badge" :class="isFeasible(winner.raw_values) ? '!border-ok/25 !bg-ok-soft !text-ok' : '!border-bad/25 !bg-bad-soft !text-bad'">
            {{ isFeasible(winner.raw_values) ? t.feasibleCheck : t.exceedsLimits }}
          </span>
        </div>
        <p class="mt-3 flex items-center gap-1.5 text-[15px] font-semibold">
          <span class="h-2.5 w-2.5 shrink-0 rounded-full" :style="{ background: altColor(winner.alternative_name) }" aria-hidden="true"></span>
          {{ winner.alternative_name }}
        </p>
        <p class="mt-0.5 text-xs text-muted">WSM <span class="num text-sm font-semibold text-fg">{{ winner.total_score.toFixed(4) }}</span></p>
        <div class="mt-3 overflow-hidden rounded-lg border border-line">
          <img :src="blueprintUrl(winner.alternative_name)" :alt="winner.alternative_name"
               class="mx-auto max-h-64 w-full object-contain" />
        </div>
      </section>

      <section class="card p-4 md:col-span-5">
        <h3 class="card-title flex items-center gap-1.5">
          <span class="h-2.5 w-2.5 shrink-0 rounded-full" :style="{ background: altColor(winner.alternative_name) }" aria-hidden="true"></span>
          {{ winner.alternative_name }} — {{ t.criterionLabel }} {{ t.directionCol }}
        </h3>
        <p class="mt-1 max-w-3xl text-[13px] leading-relaxed text-muted [overflow-wrap:anywhere]">{{ winner.description }}</p>
        <div class="table-scroll mt-3 rounded-lg border border-line">
          <table class="table min-w-[34rem]">
            <thead>
              <tr>
                <th class="sticky-col">{{ t.criterionLabel }}</th>
                <th>{{ t.directionCol }}</th>
                <th class="text-right">{{ t.rawValue }}</th>
                <th class="text-right">{{ t.normalised }}</th>
                <th class="text-right">{{ t.weight }}</th>
                <th class="text-right">{{ t.contribution }}</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="crit in data.criteria" :key="crit.name">
                <td class="sticky-col font-medium">{{ data.criterion_labels[crit.name] }}</td>
                <td class="text-muted">{{ crit.direction === 'maximize' ? t.maximize : t.minimize }}</td>
                <td class="num whitespace-nowrap text-right">{{ winner.raw_values[crit.name] }} <span class="text-subtle">{{ crit.unit }}</span></td>
                <td class="num text-right">{{ winner.normalised_values[crit.name]?.toFixed(3) }}</td>
                <td class="num text-right">{{ data.normalised_weights[crit.name]?.toFixed(2) }}</td>
                <td class="num text-right font-semibold">{{ winner.weighted_scores[crit.name]?.toFixed(4) }}</td>
              </tr>
            </tbody>
          </table>
        </div>
      </section>
    </div>

    <!-- All alternatives grid -->
    <section>
      <h3 class="card-title mb-3">{{ t.allAlternatives }}</h3>
      <div class="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
        <div v-for="res in data.results" :key="res.alternative_name"
             class="card flex flex-col p-3 transition-colors hover:border-line-strong">
          <div class="flex items-center gap-2">
            <span :class="res.rank === 1 ? 'badge-accent' : 'badge'">
              <Icon v-if="res.rank === 1" name="trophy" />{{ t.ordinals[res.rank - 1] }}
            </span>
            <span class="h-2 w-2 shrink-0 rounded-full" :style="{ background: altColor(res.alternative_name) }" aria-hidden="true"></span>
            <span class="flex-1 truncate text-[13px] font-medium">{{ res.alternative_name }}</span>
            <span class="num text-xs text-muted">{{ res.total_score.toFixed(4) }}</span>
          </div>

          <div class="mt-2.5 overflow-hidden rounded-lg border border-line">
            <img :src="blueprintUrl(res.alternative_name)" :alt="res.alternative_name"
                 class="mx-auto max-h-52 w-full object-contain" />
          </div>

          <div class="mt-2.5 h-1 overflow-hidden rounded-full bg-surface-3">
            <div class="h-full rounded-full transition-all"
                 :style="{ width: Math.round((res.total_score / maxScore) * 100) + '%', background: altColor(res.alternative_name) }"></div>
          </div>

          <p class="mt-2 text-[0.7rem] font-medium" :class="isFeasible(res.raw_values) ? 'text-ok' : 'text-bad'">
            {{ isFeasible(res.raw_values) ? t.feasibleCheck : t.exceedsLimits }}
          </p>
          <p class="mt-0.5 line-clamp-2 text-[0.7rem] text-subtle">
            {{ res.description?.slice(0, 90) }}…
          </p>
        </div>
      </div>
    </section>
  </div>
</template>

<style scoped>
/* First column stays put while the table scrolls sideways on phones. */
.sticky-col {
  position: sticky;
  left: 0;
  z-index: 1;
  background-color: var(--surface-solid) !important;
}
tbody tr:nth-child(even) > .sticky-col {
  background-color: color-mix(in oklab, var(--surface-2) 40%, var(--surface-solid)) !important;
}
</style>

<script setup>
import { computed } from 'vue'
import { useLocale } from '../composables/useLocale.js'

const props = defineProps({
  data: Object,
  dark: Boolean,
})

const { t } = useLocale()

const RANK_BADGES = { 1: { bg: '#fbbf24', fg: '#78350f', icon: '🏆' }, 2: { bg: '#cbd5e1', fg: '#1e293b', icon: '🥈' }, 3: { bg: '#d6a06c', fg: '#422006', icon: '🥉' } }

function altColor(name) {
  const r = props.data?.results?.find(r => r.alternative_name === name)
  return props.dark ? (r?.color_dark || '#2dd4bf') : (r?.color || '#0f766e')
}
</script>

<template>
  <div v-if="data" class="grid grid-cols-10 gap-8">
    <!-- Left column — methodology text -->
    <div class="col-span-6 prose max-w-none" :class="dark ? 'prose-invert' : ''">
      <h2 class="text-xl font-bold mb-4" :class="dark ? 'text-slate-100' : 'text-slate-900'">{{ t.wsmTitle }}</h2>

      <p :class="dark ? 'text-slate-300' : 'text-slate-600'">
        {{ t.wsmDesc }}
      </p>

      <div class="rounded-xl border p-4 my-4 text-center text-lg font-mono"
           :class="dark ? 'bg-slate-800 border-slate-700 text-slate-200' : 'bg-slate-50 border-slate-200 text-slate-800'">
        S<sub>i</sub> = Σ<sub>j=1..n</sub> w<sub>j</sub> · x̄<sub>ij</sub>
      </div>

      <div class="overflow-x-auto rounded-xl border mb-6"
           :class="dark ? 'border-slate-700' : 'border-slate-200'">
        <table class="w-full text-sm">
          <thead>
            <tr :class="dark ? 'bg-slate-800' : 'bg-slate-50'">
              <th class="px-4 py-2 text-left font-semibold" :class="dark ? 'text-slate-300' : 'text-slate-600'">{{ t.symbol }}</th>
              <th class="px-4 py-2 text-left font-semibold" :class="dark ? 'text-slate-300' : 'text-slate-600'">{{ t.definition }}</th>
            </tr>
          </thead>
          <tbody :class="dark ? 'text-slate-300' : 'text-slate-600'">
            <tr class="border-t" :class="dark ? 'border-slate-700' : 'border-slate-100'">
              <td class="px-4 py-2 font-mono">S<sub>i</sub></td>
              <td class="px-4 py-2">{{ t.defSi }}</td>
            </tr>
            <tr class="border-t" :class="dark ? 'border-slate-700' : 'border-slate-100'">
              <td class="px-4 py-2 font-mono">n</td>
              <td class="px-4 py-2">{{ t.defN }}</td>
            </tr>
            <tr class="border-t" :class="dark ? 'border-slate-700' : 'border-slate-100'">
              <td class="px-4 py-2 font-mono">w<sub>j</sub></td>
              <td class="px-4 py-2">{{ t.defWj }}</td>
            </tr>
            <tr class="border-t" :class="dark ? 'border-slate-700' : 'border-slate-100'">
              <td class="px-4 py-2 font-mono">x̄<sub>ij</sub></td>
              <td class="px-4 py-2">{{ t.defXij }}</td>
            </tr>
          </tbody>
        </table>
      </div>

      <hr class="my-6" :class="dark ? 'border-slate-700' : 'border-slate-200'" />

      <h2 class="text-xl font-bold mb-4" :class="dark ? 'text-slate-100' : 'text-slate-900'">{{ t.minMaxTitle }}</h2>

      <p :class="dark ? 'text-slate-300' : 'text-slate-600'">
        {{ t.minMaxDesc }}
      </p>

      <p class="font-semibold mt-3" :class="dark ? 'text-slate-200' : 'text-slate-700'">
        {{ t.maxDir }}
      </p>
      <div class="rounded-xl border p-3 my-2 text-center font-mono"
           :class="dark ? 'bg-slate-800 border-slate-700 text-slate-200' : 'bg-slate-50 border-slate-200'">
        x̄<sub>ij</sub> = (x<sub>ij</sub> − min<sub>j</sub>) / (max<sub>j</sub> − min<sub>j</sub>)
      </div>

      <p class="font-semibold mt-3" :class="dark ? 'text-slate-200' : 'text-slate-700'">
        {{ t.minDir }}
      </p>
      <div class="rounded-xl border p-3 my-2 text-center font-mono"
           :class="dark ? 'bg-slate-800 border-slate-700 text-slate-200' : 'bg-slate-50 border-slate-200'">
        x̄<sub>ij</sub> = (max<sub>j</sub> − x<sub>ij</sub>) / (max<sub>j</sub> − min<sub>j</sub>)
      </div>

      <p class="text-sm italic mt-2" :class="dark ? 'text-slate-400' : 'text-slate-500'">
        {{ t.edgeCase }}
      </p>

      <hr class="my-6" :class="dark ? 'border-slate-700' : 'border-slate-200'" />

      <h2 class="text-xl font-bold mb-4" :class="dark ? 'text-slate-100' : 'text-slate-900'">{{ t.criteriaDataTitle }}</h2>

      <div class="overflow-x-auto rounded-xl border mb-6"
           :class="dark ? 'border-slate-700' : 'border-slate-200'">
        <table class="w-full text-sm">
          <thead>
            <tr :class="dark ? 'bg-slate-800' : 'bg-slate-50'">
              <th class="px-4 py-2 text-left font-semibold" :class="dark ? 'text-slate-300' : 'text-slate-600'">{{ t.criterionLabel }}</th>
              <th class="px-4 py-2 text-left font-semibold" :class="dark ? 'text-slate-300' : 'text-slate-600'">{{ t.directionCol }}</th>
              <th class="px-4 py-2 text-left font-semibold" :class="dark ? 'text-slate-300' : 'text-slate-600'">{{ t.weight }}</th>
              <th class="px-4 py-2 text-left font-semibold" :class="dark ? 'text-slate-300' : 'text-slate-600'">{{ t.source }}</th>
            </tr>
          </thead>
          <tbody :class="dark ? 'text-slate-300' : 'text-slate-600'">
            <tr class="border-t" :class="dark ? 'border-slate-700' : 'border-slate-100'">
              <td class="px-4 py-2">{{ t.constructionCost }}</td><td class="px-4 py-2">{{ t.minimize }}</td><td class="px-4 py-2">M USD</td>
              <td class="px-4 py-2">FHWA Interchange Justification Report Guidelines (2023)</td>
            </tr>
            <tr class="border-t" :class="dark ? 'border-slate-700' : 'border-slate-100'">
              <td class="px-4 py-2">{{ t.landArea }}</td><td class="px-4 py-2">{{ t.minimize }}</td><td class="px-4 py-2">ha</td>
              <td class="px-4 py-2">TRB NCHRP Report 659</td>
            </tr>
            <tr class="border-t" :class="dark ? 'border-slate-700' : 'border-slate-100'">
              <td class="px-4 py-2">{{ t.throughput }}</td><td class="px-4 py-2">{{ t.maximize }}</td><td class="px-4 py-2">veh/hr</td>
              <td class="px-4 py-2">HCM 7th Edition, Chapter 14</td>
            </tr>
            <tr class="border-t" :class="dark ? 'border-slate-700' : 'border-slate-100'">
              <td class="px-4 py-2">{{ t.safetyIndex }}</td><td class="px-4 py-2">{{ t.maximize }}</td><td class="px-4 py-2">1–10</td>
              <td class="px-4 py-2">PIARC Road Safety Manual (2019); AASHTO HSM (2022)</td>
            </tr>
          </tbody>
        </table>
      </div>

      <hr class="my-6" :class="dark ? 'border-slate-700' : 'border-slate-200'" />

      <h2 class="text-xl font-bold mb-3" :class="dark ? 'text-slate-100' : 'text-slate-900'">{{ t.referencesTitle }}</h2>
      <ul class="list-disc pl-5 space-y-1.5 text-sm" :class="dark ? 'text-slate-300' : 'text-slate-600'">
        <li>Fishburn, P. C. (1967). Additive utilities with incomplete product sets. <em>Operations Research</em>, 15(3), 537–542.</li>
        <li>Triantaphyllou, E. (2000). <em>Multi-Criteria Decision Making Methods: A Comparative Study.</em> Kluwer Academic Publishers.</li>
        <li>Transportation Research Board (2022). <em>Highway Capacity Manual, 7th Edition.</em></li>
        <li>FHWA (2023). <em>Interchange Justification Report Guidelines.</em></li>
        <li>PIARC (2019). <em>Road Safety Manual.</em></li>
        <li>AASHTO (2022). <em>Highway Safety Manual, 2nd Edition.</em></li>
      </ul>
    </div>

    <!-- Right column — weight profile + ranking -->
    <div class="col-span-4">
      <p class="font-semibold text-sm mb-2" :class="dark ? 'text-slate-100' : 'text-slate-900'">{{ t.activeWeightProfile }}</p>
      <div class="overflow-x-auto rounded-xl border mb-6"
           :class="dark ? 'border-slate-700' : 'border-slate-200'">
        <table class="w-full text-sm">
          <thead>
            <tr :class="dark ? 'bg-slate-800' : 'bg-slate-50'">
              <th class="px-4 py-2 text-left font-semibold" :class="dark ? 'text-slate-300' : 'text-slate-600'">{{ t.criterionLabel }}</th>
              <th class="px-4 py-2 text-left font-semibold" :class="dark ? 'text-slate-300' : 'text-slate-600'">{{ t.weight }}</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="crit in data.criteria" :key="crit.name"
                class="border-t" :class="dark ? 'border-slate-700' : 'border-slate-100'">
              <td class="px-4 py-2" :class="dark ? 'text-slate-300' : 'text-slate-600'">{{ data.criterion_labels[crit.name] }}</td>
              <td class="px-4 py-2 font-medium" :class="dark ? 'text-slate-100' : 'text-slate-900'">
                {{ (data.normalised_weights[crit.name] * 100).toFixed(0) }}%
              </td>
            </tr>
          </tbody>
        </table>
      </div>

      <p class="font-semibold text-sm mb-2" :class="dark ? 'text-slate-100' : 'text-slate-900'">{{ t.currentRanking }}</p>
      <div class="space-y-2">
        <div v-for="res in data.results" :key="res.alternative_name"
             class="flex items-center gap-3 rounded-lg border px-4 py-2.5"
             :class="dark ? 'bg-slate-800 border-slate-700' : 'bg-white border-slate-200'">
          <span class="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[0.65rem] font-bold"
                :style="{
                  background: RANK_BADGES[res.rank]?.bg || (dark ? '#334155' : '#e2e8f0'),
                  color: RANK_BADGES[res.rank]?.fg || (dark ? '#94a3b8' : '#334155'),
                }">
            {{ RANK_BADGES[res.rank]?.icon }} {{ t.ordinals[res.rank - 1] }}
          </span>
          <span class="flex-1 font-bold text-sm" :style="{ color: altColor(res.alternative_name) }">
            {{ res.alternative_name }}
          </span>
          <span class="font-bold text-sm" :class="dark ? 'text-slate-100' : 'text-slate-900'">
            {{ res.total_score.toFixed(4) }}
          </span>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { useLocale } from '../composables/useLocale.js'
import { AHP_PAIRS, CRITERION_KEYS } from '../composables/useDSS.js'

const props = defineProps({
  dark: Boolean,
  dss: Object,
})

const { t } = useLocale()

const MODES = ['manual', 'entropy', 'critic', 'ahp', 'combined']
const SAATY = [9, 7, 5, 3, 1, 1 / 3, 1 / 5, 1 / 7, 1 / 9]

const shortLabel = computed(() => ({
  construction_cost_mln: t.value.constructionCost,
  land_area_hectares:    t.value.landArea,
  throughput_vph:        t.value.throughput,
  safety_index:          t.value.safetyIndex,
}))

function saatyText(v) {
  return v >= 1 ? String(v) : `1/${Math.round(1 / v)}`
}

const w = computed(() => props.dss.weighting)
const cr = computed(() => props.dss.evalData.value?.weighting?.details?.consistency_ratio)

const inputClass = computed(() => props.dark
  ? 'bg-slate-700 border border-slate-600 text-slate-200'
  : 'bg-white/80 border border-black/5 text-slate-800 shadow-[0_1px_3px_rgb(0,0,0,0.04)]')
</script>

<template>
  <div class="mb-3 space-y-3">
    <div>
      <label class="text-xs font-medium" :class="dark ? 'text-slate-300' : 'text-slate-600'">{{ t.weightingMode }}</label>
      <select v-model="w.mode" class="w-full rounded-xl px-3 py-1.5 text-sm mt-1" :class="inputClass">
        <option v-for="m in MODES" :key="m" :value="m">{{ t.weightingModes[m] }}</option>
      </select>
      <p class="text-xs mt-1" :class="dark ? 'text-slate-400' : 'text-slate-500'">{{ t.weightingModeDesc[w.mode] }}</p>
    </div>

    <div v-if="w.mode === 'combined'" class="grid grid-cols-2 gap-2">
      <div>
        <label class="text-xs font-medium" :class="dark ? 'text-slate-300' : 'text-slate-600'">{{ t.subjectiveSource }}</label>
        <select v-model="w.subjective" class="w-full rounded-xl px-2 py-1.5 text-xs mt-1" :class="inputClass">
          <option value="manual">{{ t.weightingModes.manual }}</option>
          <option value="ahp">{{ t.methodLabels.ahp }}</option>
        </select>
      </div>
      <div>
        <label class="text-xs font-medium" :class="dark ? 'text-slate-300' : 'text-slate-600'">{{ t.objectiveSource }}</label>
        <select v-model="w.objective" class="w-full rounded-xl px-2 py-1.5 text-xs mt-1" :class="inputClass">
          <option value="entropy">{{ t.weightingModes.entropy }}</option>
          <option value="critic">{{ t.weightingModes.critic }}</option>
        </select>
      </div>
      <div class="col-span-2">
        <label class="text-xs font-medium" :class="dark ? 'text-slate-300' : 'text-slate-600'">
          {{ t.alphaLabel }} = {{ w.alpha.toFixed(2) }}
        </label>
        <input type="range" v-model.number="w.alpha" min="0" max="1" step="0.05" class="ios-slider ios-slider--teal mt-1" />
      </div>
    </div>

    <div v-if="dss.usesAhp()">
      <p class="text-xs font-semibold" :class="dark ? 'text-slate-200' : 'text-slate-800'">{{ t.ahpTitle }}</p>
      <p class="text-[0.7rem] mb-2" :class="dark ? 'text-slate-400' : 'text-slate-500'">{{ t.ahpHint }}</p>
      <div class="space-y-1.5">
        <div v-for="([i, j], k) in AHP_PAIRS" :key="k" class="flex items-center gap-1.5 text-[0.7rem]"
             :class="dark ? 'text-slate-300' : 'text-slate-600'">
          <span class="flex-1 truncate text-right">{{ shortLabel[CRITERION_KEYS[i]] }}</span>
          <select v-model.number="dss.ahpJudgements[k]" class="w-16 rounded-lg px-1 py-0.5 text-xs" :class="inputClass">
            <option v-for="v in SAATY" :key="v" :value="v">{{ saatyText(v) }}</option>
          </select>
          <span class="flex-1 truncate">{{ shortLabel[CRITERION_KEYS[j]] }}</span>
        </div>
      </div>
      <p v-if="cr !== undefined && cr !== null" class="text-xs font-medium mt-2"
         :class="cr < 0.1 ? (dark ? 'text-teal-400' : 'text-teal-700') : 'text-orange-500'">
        {{ t.consistencyRatio }} = {{ cr.toFixed(3) }} — {{ cr < 0.1 ? t.crOk : t.crBad }}
      </p>
    </div>
  </div>
</template>

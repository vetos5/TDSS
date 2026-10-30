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
</script>

<template>
  <div class="mb-3 space-y-3">
    <div>
      <label class="field-label">{{ t.weightingMode }}</label>
      <select v-model="w.mode" class="field">
        <option v-for="m in MODES" :key="m" :value="m">{{ t.weightingModes[m] }}</option>
      </select>
      <p class="mt-1 text-xs text-muted">{{ t.weightingModeDesc[w.mode] }}</p>
    </div>

    <div v-if="w.mode === 'combined'" class="grid grid-cols-2 gap-2">
      <div>
        <label class="field-label">{{ t.subjectiveSource }}</label>
        <select v-model="w.subjective" class="field">
          <option value="manual">{{ t.weightingModes.manual }}</option>
          <option value="ahp">{{ t.methodLabels.ahp }}</option>
        </select>
      </div>
      <div>
        <label class="field-label">{{ t.objectiveSource }}</label>
        <select v-model="w.objective" class="field">
          <option value="entropy">{{ t.weightingModes.entropy }}</option>
          <option value="critic">{{ t.weightingModes.critic }}</option>
        </select>
      </div>
      <div class="col-span-2">
        <div class="mb-1.5 flex items-baseline justify-between text-xs">
          <label class="text-muted">{{ t.alphaLabel }}</label>
          <span class="num font-medium">{{ w.alpha.toFixed(2) }}</span>
        </div>
        <input type="range" v-range-fill v-model.number="w.alpha" min="0" max="1" step="0.05" class="ios-slider" />
      </div>
    </div>

    <div v-if="dss.usesAhp()" class="rounded-lg border border-line bg-surface p-3">
      <p class="text-xs font-medium">{{ t.ahpTitle }}</p>
      <p class="mb-2 text-[0.7rem] text-muted">{{ t.ahpHint }}</p>
      <div class="space-y-1.5">
        <div v-for="([i, j], k) in AHP_PAIRS" :key="k" class="flex items-center gap-1.5 text-[0.7rem] text-muted">
          <span class="flex-1 truncate text-right">{{ shortLabel[CRITERION_KEYS[i]] }}</span>
          <select v-model.number="dss.ahpJudgements[k]" class="field num !w-16 !px-1 !py-0.5 !text-xs">
            <option v-for="v in SAATY" :key="v" :value="v">{{ saatyText(v) }}</option>
          </select>
          <span class="flex-1 truncate">{{ shortLabel[CRITERION_KEYS[j]] }}</span>
        </div>
      </div>
      <p v-if="cr !== undefined && cr !== null" class="num mt-2 text-xs font-medium"
         :class="cr < 0.1 ? 'text-accent-ink' : 'text-warn'">
        {{ t.consistencyRatio }} = {{ cr.toFixed(3) }} — {{ cr < 0.1 ? t.crOk : t.crBad }}
      </p>
    </div>
  </div>
</template>

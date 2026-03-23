<script setup>
import { computed } from 'vue'
import { useLocale } from '../composables/useLocale.js'

const props = defineProps({
  dark: Boolean,
  dss: Object,
  open: Boolean,
})
const emit = defineEmits(['toggle-theme', 'close'])

const { lang, toggleLang, t } = useLocale()

const CRITERION_KEYS = ['construction_cost_mln', 'land_area_hectares', 'throughput_vph', 'safety_index']
const criterionLabel = computed(() => ({
  construction_cost_mln: t.value.constructionCost,
  land_area_hectares:    t.value.landArea,
  throughput_vph:        t.value.throughput,
  safety_index:          t.value.safetyIndex,
}))

const BAR_COLORS = {
  construction_cost_mln: '#0f766e',
  land_area_hectares: '#ea580c',
  throughput_vph: '#7c3aed',
  safety_index: '#1d4ed8',
}

const normW = computed(() => props.dss.normalizedWeights())
const rawTotal = computed(() =>
  props.dss.weights.construction_cost_mln +
  props.dss.weights.land_area_hectares +
  props.dss.weights.throughput_vph +
  props.dss.weights.safety_index
)

const terrainOptions = computed(() => [
  { value: 'Flat',        label: t.value.terrainFlat },
  { value: 'Rolling',     label: t.value.terrainRolling },
  { value: 'Mountainous', label: t.value.terrainMountainous },
])
const envOptions = computed(() => [
  { value: 'Low',      label: t.value.envLow },
  { value: 'Medium',   label: t.value.envMedium },
  { value: 'High',     label: t.value.envHigh },
  { value: 'Critical', label: t.value.envCritical },
])
</script>

<template>
  <aside class="fixed left-0 top-0 h-screen w-80 overflow-y-auto border-r z-30 transition-all duration-300"
         :class="[
           dark
             ? 'bg-slate-800 border-slate-700'
             : 'bg-white/60 backdrop-blur-2xl border-white/80 shadow-[0_8px_30px_rgb(0,0,0,0.04)]',
           open ? 'translate-x-0' : '-translate-x-full md:translate-x-0',
         ]">
    <div class="p-5">
      <!-- Mobile close button -->
      <div class="flex justify-end mb-2 md:hidden">
        <button @click="emit('close')"
                class="w-8 h-8 rounded-xl flex items-center justify-center text-lg transition-colors"
                :class="dark
                  ? 'bg-slate-700 border border-slate-600 text-slate-300 hover:bg-slate-600'
                  : 'bg-white/80 border border-black/5 shadow-[0_1px_3px_rgb(0,0,0,0.06)] text-slate-500 hover:bg-white'"
                aria-label="Close sidebar">
          ✕
        </button>
      </div>

      <!-- Theme + Language toggles -->
      <div class="flex items-center justify-between mb-4">
        <span class="text-xs font-semibold uppercase tracking-wider"
              :class="dark ? 'text-slate-400' : 'text-slate-500'">{{ t.sidebarVersion }}</span>

        <div class="flex items-center gap-2">
          <!-- Language toggle -->
          <button @click="toggleLang"
                  class="h-8 px-2.5 rounded-xl flex items-center justify-center text-[0.68rem] font-bold tracking-widest transition-all duration-200 active:scale-[0.92]"
                  :class="dark
                    ? 'bg-slate-700 border border-slate-600 hover:bg-slate-600 text-slate-200'
                    : 'bg-white/80 border border-black/5 shadow-[0_1px_3px_rgb(0,0,0,0.06)] hover:bg-white text-slate-600'">
            {{ lang === 'EN' ? 'UA' : 'ENG' }}
          </button>

          <!-- Theme toggle -->
          <button @click="emit('toggle-theme')"
                  class="w-8 h-8 rounded-xl flex items-center justify-center text-sm transition-all duration-200 active:scale-[0.92]"
                  :class="dark
                    ? 'bg-slate-700 border border-slate-600 hover:bg-slate-600'
                    : 'bg-white/80 border border-black/5 shadow-[0_1px_3px_rgb(0,0,0,0.06)] hover:bg-white'">
            {{ dark ? '☀️' : '🌙' }}
          </button>
        </div>
      </div>

      <hr class="mb-4" :class="dark ? 'border-slate-700' : 'border-black/5'" />

      <!-- Context selector -->
      <div class="mb-4">
        <p class="font-bold text-sm mb-1" :class="dark ? 'text-slate-100' : 'text-slate-900'">{{ t.taskContext }}</p>
        <p class="text-xs mb-2" :class="dark ? 'text-slate-400' : 'text-slate-500'">
          {{ t.taskContextDesc }}
        </p>
        <select v-model="dss.selectedContext.value"
                class="w-full rounded-xl px-3 py-2 text-sm transition-colors"
                :class="dark
                  ? 'bg-slate-700 border border-slate-600 text-slate-200'
                  : 'bg-white/80 border border-black/5 text-slate-800 shadow-[0_1px_3px_rgb(0,0,0,0.04)]'">
          <option v-for="ctx in dss.contexts.value" :key="ctx" :value="ctx">{{ ctx }}</option>
        </select>
      </div>

      <hr class="mb-4" :class="dark ? 'border-slate-700' : 'border-black/5'" />

      <!-- Criteria weights -->
      <div class="mb-4">
        <p class="font-bold text-sm mb-1" :class="dark ? 'text-slate-100' : 'text-slate-900'">{{ t.criteriaWeights }}</p>
        <p class="text-xs mb-3" :class="dark ? 'text-slate-400' : 'text-slate-500'">
          {{ t.criteriaWeightsDesc }}
        </p>

        <div class="space-y-4">
          <div>
            <label class="text-xs font-medium" :class="dark ? 'text-slate-300' : 'text-slate-600'">
              {{ t.constructionCost }} — {{ t.minimize }}
            </label>
            <input type="range" v-model.number="dss.weights.construction_cost_mln" min="0" max="100" step="5"
                   class="ios-slider ios-slider--teal mt-1" />
            <span class="text-xs font-semibold" :class="dark ? 'text-slate-300' : 'text-blue-600'">{{ dss.weights.construction_cost_mln }}%</span>
          </div>
          <div>
            <label class="text-xs font-medium" :class="dark ? 'text-slate-300' : 'text-slate-600'">
              {{ t.landArea }} — {{ t.minimize }}
            </label>
            <input type="range" v-model.number="dss.weights.land_area_hectares" min="0" max="100" step="5"
                   class="ios-slider ios-slider--orange mt-1" />
            <span class="text-xs font-semibold" :class="dark ? 'text-slate-300' : 'text-orange-500'">{{ dss.weights.land_area_hectares }}%</span>
          </div>
          <div>
            <label class="text-xs font-medium" :class="dark ? 'text-slate-300' : 'text-slate-600'">
              {{ t.throughput }} — {{ t.maximize }}
            </label>
            <input type="range" v-model.number="dss.weights.throughput_vph" min="0" max="100" step="5"
                   class="ios-slider ios-slider--violet mt-1" />
            <span class="text-xs font-semibold" :class="dark ? 'text-slate-300' : 'text-violet-600'">{{ dss.weights.throughput_vph }}%</span>
          </div>
          <div>
            <label class="text-xs font-medium" :class="dark ? 'text-slate-300' : 'text-slate-600'">
              {{ t.safetyIndex }} — {{ t.maximize }}
            </label>
            <input type="range" v-model.number="dss.weights.safety_index" min="0" max="100" step="5"
                   class="ios-slider ios-slider--blue mt-1" />
            <span class="text-xs font-semibold" :class="dark ? 'text-slate-300' : 'text-blue-600'">{{ dss.weights.safety_index }}%</span>
          </div>
        </div>
      </div>

      <hr class="mb-4" :class="dark ? 'border-slate-700' : 'border-black/5'" />

      <!-- Project Parameters -->
      <div class="mb-4">
        <p class="font-bold text-sm mb-1" :class="dark ? 'text-slate-100' : 'text-slate-900'">{{ t.projectParameters }}</p>
        <p class="text-xs mb-3" :class="dark ? 'text-slate-400' : 'text-slate-500'">
          {{ t.projectParamsDesc }}
        </p>
        <div class="space-y-2.5">
          <div>
            <label class="text-xs font-medium" :class="dark ? 'text-slate-300' : 'text-slate-600'">{{ t.designSpeed }}</label>
            <select v-model.number="dss.params.design_speed"
                    class="w-full rounded-xl px-3 py-1.5 text-sm"
                    :class="dark ? 'bg-slate-700 border border-slate-600 text-slate-200' : 'bg-white/80 border border-black/5 text-slate-800 shadow-[0_1px_3px_rgb(0,0,0,0.04)]'">
              <option v-for="s in [60,80,100,120,140]" :key="s" :value="s">{{ s }}</option>
            </select>
          </div>
          <div>
            <label class="text-xs font-medium" :class="dark ? 'text-slate-300' : 'text-slate-600'">{{ t.aadt }}</label>
            <input type="number" v-model.number="dss.params.aadt" min="1000" max="200000" step="5000"
                   class="w-full rounded-xl px-3 py-1.5 text-sm"
                   :class="dark ? 'bg-slate-700 border border-slate-600 text-slate-200' : 'bg-white/80 border border-black/5 text-slate-800 shadow-[0_1px_3px_rgb(0,0,0,0.04)]'" />
          </div>
          <div>
            <label class="text-xs font-medium" :class="dark ? 'text-slate-300' : 'text-slate-600'">{{ t.peakFactor }}</label>
            <input type="range" v-model.number="dss.params.peak_factor" min="5" max="20" step="1"
                   class="ios-slider ios-slider--teal mt-1" />
            <span class="text-xs font-semibold" :class="dark ? 'text-slate-300' : 'text-teal-600'">{{ dss.params.peak_factor }}%</span>
          </div>
          <div>
            <label class="text-xs font-medium" :class="dark ? 'text-slate-300' : 'text-slate-600'">{{ t.numLanes }}</label>
            <select v-model.number="dss.params.num_lanes"
                    class="w-full rounded-xl px-3 py-1.5 text-sm"
                    :class="dark ? 'bg-slate-700 border border-slate-600 text-slate-200' : 'bg-white/80 border border-black/5 text-slate-800 shadow-[0_1px_3px_rgb(0,0,0,0.04)]'">
              <option v-for="n in [1,2,3,4,5]" :key="n" :value="n">{{ n }}</option>
            </select>
          </div>
          <div>
            <label class="text-xs font-medium" :class="dark ? 'text-slate-300' : 'text-slate-600'">{{ t.budget }}</label>
            <input type="number" v-model.number="dss.params.budget" min="0" max="500" step="5"
                   class="w-full rounded-xl px-3 py-1.5 text-sm"
                   :class="dark ? 'bg-slate-700 border border-slate-600 text-slate-200' : 'bg-white/80 border border-black/5 text-slate-800 shadow-[0_1px_3px_rgb(0,0,0,0.04)]'" />
          </div>
          <div>
            <label class="text-xs font-medium" :class="dark ? 'text-slate-300' : 'text-slate-600'">{{ t.landLimit }}</label>
            <input type="number" v-model.number="dss.params.land_limit" min="0" max="100" step="1"
                   class="w-full rounded-xl px-3 py-1.5 text-sm"
                   :class="dark ? 'bg-slate-700 border border-slate-600 text-slate-200' : 'bg-white/80 border border-black/5 text-slate-800 shadow-[0_1px_3px_rgb(0,0,0,0.04)]'" />
          </div>
          <div>
            <label class="text-xs font-medium" :class="dark ? 'text-slate-300' : 'text-slate-600'">{{ t.terrainType }}</label>
            <select v-model="dss.params.terrain"
                    class="w-full rounded-xl px-3 py-1.5 text-sm"
                    :class="dark ? 'bg-slate-700 border border-slate-600 text-slate-200' : 'bg-white/80 border border-black/5 text-slate-800 shadow-[0_1px_3px_rgb(0,0,0,0.04)]'">
              <option v-for="opt in terrainOptions" :key="opt.value" :value="opt.value">{{ opt.label }}</option>
            </select>
          </div>
          <div>
            <label class="text-xs font-medium" :class="dark ? 'text-slate-300' : 'text-slate-600'">{{ t.envSensitivity }}</label>
            <select v-model="dss.params.env_sensitivity"
                    class="w-full rounded-xl px-3 py-1.5 text-sm"
                    :class="dark ? 'bg-slate-700 border border-slate-600 text-slate-200' : 'bg-white/80 border border-black/5 text-slate-800 shadow-[0_1px_3px_rgb(0,0,0,0.04)]'">
              <option v-for="opt in envOptions" :key="opt.value" :value="opt.value">{{ opt.label }}</option>
            </select>
          </div>
        </div>
      </div>

      <hr class="mb-4" :class="dark ? 'border-slate-700' : 'border-black/5'" />

      <!-- Normalised weight bars -->
      <p class="text-xs mb-2" :class="dark ? 'text-slate-400' : 'text-slate-500'">
        {{ t.normWeightsLabel }}
      </p>
      <div class="space-y-1.5 mb-3">
        <div v-for="key in CRITERION_KEYS" :key="key"
             class="flex items-center gap-2 text-xs" :class="dark ? 'text-slate-300' : 'text-slate-600'">
          <span class="w-28 truncate">{{ criterionLabel[key] }}</span>
          <div class="flex-1 h-1.5 rounded-full overflow-hidden"
               :class="dark ? 'bg-slate-700' : 'bg-black/5'">
            <div class="h-full rounded-full transition-all duration-300"
                 :style="{ width: (normW[key] * 100) + '%', background: BAR_COLORS[key] }"></div>
          </div>
          <span class="w-8 text-right font-medium">{{ normW[key]?.toFixed(2) }}</span>
        </div>
      </div>

      <p class="text-xs font-medium" :class="Math.abs(rawTotal - 100) <= 1
        ? (dark ? 'text-teal-400' : 'text-teal-700')
        : 'text-orange-500'">
        {{ t.rawTotalLabel }}: {{ rawTotal }}%
      </p>

      <hr class="my-4" :class="dark ? 'border-slate-700' : 'border-black/5'" />
      <p class="text-[0.7rem]" :class="dark ? 'text-slate-500' : 'text-slate-400'">
        {{ t.dataFooter }}
      </p>
    </div>
  </aside>
</template>

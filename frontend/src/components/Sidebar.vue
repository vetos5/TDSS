<script setup>
import { computed } from 'vue'

const props = defineProps({
  dark: Boolean,
  dss: Object,
})
const emit = defineEmits(['toggle-theme'])

const CRITERION_LABELS = {
  construction_cost_mln: 'Construction Cost',
  land_area_hectares: 'Land Area',
  throughput_vph: 'Throughput (vph)',
  safety_index: 'Safety Index',
}
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
</script>

<template>
  <aside class="fixed left-0 top-0 h-screen w-80 overflow-y-auto border-r z-30 transition-colors"
         :class="dark
           ? 'bg-slate-800 border-slate-700'
           : 'bg-white/60 backdrop-blur-2xl border-white/80 shadow-[0_8px_30px_rgb(0,0,0,0.04)]'">
    <div class="p-5">
      <!-- Theme toggle -->
      <div class="flex items-center justify-between mb-4">
        <span class="text-xs font-semibold uppercase tracking-wider"
              :class="dark ? 'text-slate-400' : 'text-slate-500'">TDSS v4</span>
        <button @click="emit('toggle-theme')"
                class="w-8 h-8 rounded-xl flex items-center justify-center text-sm transition-all duration-200 active:scale-[0.92]"
                :class="dark
                  ? 'bg-slate-700 border border-slate-600 hover:bg-slate-600'
                  : 'bg-white/80 border border-black/5 shadow-[0_1px_3px_rgb(0,0,0,0.06)] hover:bg-white'">
          {{ dark ? '☀️' : '🌙' }}
        </button>
      </div>

      <hr class="mb-4" :class="dark ? 'border-slate-700' : 'border-black/5'" />

      <!-- Context selector -->
      <div class="mb-4">
        <p class="font-bold text-sm mb-1" :class="dark ? 'text-slate-100' : 'text-slate-900'">Task Context</p>
        <p class="text-xs mb-2" :class="dark ? 'text-slate-400' : 'text-slate-500'">
          Select the interchange type category to compare alternatives.
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
        <p class="font-bold text-sm mb-1" :class="dark ? 'text-slate-100' : 'text-slate-900'">Criteria Weights</p>
        <p class="text-xs mb-3" :class="dark ? 'text-slate-400' : 'text-slate-500'">
          Adjust slider values. Weights are auto-normalised to sum to 1.0.
        </p>

        <div class="space-y-4">
          <div>
            <label class="text-xs font-medium" :class="dark ? 'text-slate-300' : 'text-slate-600'">Construction Cost — Minimize</label>
            <input type="range" v-model.number="dss.weights.construction_cost_mln" min="0" max="100" step="5"
                   class="ios-slider ios-slider--teal mt-1" />
            <span class="text-xs font-semibold" :class="dark ? 'text-slate-300' : 'text-blue-600'">{{ dss.weights.construction_cost_mln }}%</span>
          </div>
          <div>
            <label class="text-xs font-medium" :class="dark ? 'text-slate-300' : 'text-slate-600'">Land Area — Minimize</label>
            <input type="range" v-model.number="dss.weights.land_area_hectares" min="0" max="100" step="5"
                   class="ios-slider ios-slider--orange mt-1" />
            <span class="text-xs font-semibold" :class="dark ? 'text-slate-300' : 'text-orange-500'">{{ dss.weights.land_area_hectares }}%</span>
          </div>
          <div>
            <label class="text-xs font-medium" :class="dark ? 'text-slate-300' : 'text-slate-600'">Throughput / Capacity — Maximize</label>
            <input type="range" v-model.number="dss.weights.throughput_vph" min="0" max="100" step="5"
                   class="ios-slider ios-slider--violet mt-1" />
            <span class="text-xs font-semibold" :class="dark ? 'text-slate-300' : 'text-violet-600'">{{ dss.weights.throughput_vph }}%</span>
          </div>
          <div>
            <label class="text-xs font-medium" :class="dark ? 'text-slate-300' : 'text-slate-600'">Safety Index — Maximize</label>
            <input type="range" v-model.number="dss.weights.safety_index" min="0" max="100" step="5"
                   class="ios-slider ios-slider--blue mt-1" />
            <span class="text-xs font-semibold" :class="dark ? 'text-slate-300' : 'text-blue-600'">{{ dss.weights.safety_index }}%</span>
          </div>
        </div>
      </div>

      <hr class="mb-4" :class="dark ? 'border-slate-700' : 'border-black/5'" />

      <!-- Project Parameters -->
      <div class="mb-4">
        <p class="font-bold text-sm mb-1" :class="dark ? 'text-slate-100' : 'text-slate-900'">Project Parameters</p>
        <p class="text-xs mb-3" :class="dark ? 'text-slate-400' : 'text-slate-500'">
          Define site-specific constraints and traffic characteristics.
        </p>
        <div class="space-y-2.5">
          <div>
            <label class="text-xs font-medium" :class="dark ? 'text-slate-300' : 'text-slate-600'">Design Speed (km/h)</label>
            <select v-model.number="dss.params.design_speed"
                    class="w-full rounded-xl px-3 py-1.5 text-sm"
                    :class="dark ? 'bg-slate-700 border border-slate-600 text-slate-200' : 'bg-white/80 border border-black/5 text-slate-800 shadow-[0_1px_3px_rgb(0,0,0,0.04)]'">
              <option v-for="s in [60,80,100,120,140]" :key="s" :value="s">{{ s }}</option>
            </select>
          </div>
          <div>
            <label class="text-xs font-medium" :class="dark ? 'text-slate-300' : 'text-slate-600'">AADT</label>
            <input type="number" v-model.number="dss.params.aadt" min="1000" max="200000" step="5000"
                   class="w-full rounded-xl px-3 py-1.5 text-sm"
                   :class="dark ? 'bg-slate-700 border border-slate-600 text-slate-200' : 'bg-white/80 border border-black/5 text-slate-800 shadow-[0_1px_3px_rgb(0,0,0,0.04)]'" />
          </div>
          <div>
            <label class="text-xs font-medium" :class="dark ? 'text-slate-300' : 'text-slate-600'">Peak Hour Factor (%)</label>
            <input type="range" v-model.number="dss.params.peak_factor" min="5" max="20" step="1"
                   class="ios-slider ios-slider--teal mt-1" />
            <span class="text-xs font-semibold" :class="dark ? 'text-slate-300' : 'text-teal-600'">{{ dss.params.peak_factor }}%</span>
          </div>
          <div>
            <label class="text-xs font-medium" :class="dark ? 'text-slate-300' : 'text-slate-600'">Lanes / Direction</label>
            <select v-model.number="dss.params.num_lanes"
                    class="w-full rounded-xl px-3 py-1.5 text-sm"
                    :class="dark ? 'bg-slate-700 border border-slate-600 text-slate-200' : 'bg-white/80 border border-black/5 text-slate-800 shadow-[0_1px_3px_rgb(0,0,0,0.04)]'">
              <option v-for="n in [1,2,3,4,5]" :key="n" :value="n">{{ n }}</option>
            </select>
          </div>
          <div>
            <label class="text-xs font-medium" :class="dark ? 'text-slate-300' : 'text-slate-600'">Budget (M USD)</label>
            <input type="number" v-model.number="dss.params.budget" min="0" max="500" step="5"
                   class="w-full rounded-xl px-3 py-1.5 text-sm"
                   :class="dark ? 'bg-slate-700 border border-slate-600 text-slate-200' : 'bg-white/80 border border-black/5 text-slate-800 shadow-[0_1px_3px_rgb(0,0,0,0.04)]'" />
          </div>
          <div>
            <label class="text-xs font-medium" :class="dark ? 'text-slate-300' : 'text-slate-600'">Available Land (ha)</label>
            <input type="number" v-model.number="dss.params.land_limit" min="0" max="100" step="1"
                   class="w-full rounded-xl px-3 py-1.5 text-sm"
                   :class="dark ? 'bg-slate-700 border border-slate-600 text-slate-200' : 'bg-white/80 border border-black/5 text-slate-800 shadow-[0_1px_3px_rgb(0,0,0,0.04)]'" />
          </div>
          <div>
            <label class="text-xs font-medium" :class="dark ? 'text-slate-300' : 'text-slate-600'">Terrain Type</label>
            <select v-model="dss.params.terrain"
                    class="w-full rounded-xl px-3 py-1.5 text-sm"
                    :class="dark ? 'bg-slate-700 border border-slate-600 text-slate-200' : 'bg-white/80 border border-black/5 text-slate-800 shadow-[0_1px_3px_rgb(0,0,0,0.04)]'">
              <option v-for="t in ['Flat','Rolling','Mountainous']" :key="t" :value="t">{{ t }}</option>
            </select>
          </div>
          <div>
            <label class="text-xs font-medium" :class="dark ? 'text-slate-300' : 'text-slate-600'">Environmental Sensitivity</label>
            <select v-model="dss.params.env_sensitivity"
                    class="w-full rounded-xl px-3 py-1.5 text-sm"
                    :class="dark ? 'bg-slate-700 border border-slate-600 text-slate-200' : 'bg-white/80 border border-black/5 text-slate-800 shadow-[0_1px_3px_rgb(0,0,0,0.04)]'">
              <option v-for="e in ['Low','Medium','High','Critical']" :key="e" :value="e">{{ e }}</option>
            </select>
          </div>
        </div>
      </div>

      <hr class="mb-4" :class="dark ? 'border-slate-700' : 'border-black/5'" />

      <!-- Normalised weight bars -->
      <p class="text-xs mb-2" :class="dark ? 'text-slate-400' : 'text-slate-500'">
        Normalised weights (sum = 1.0)
      </p>
      <div class="space-y-1.5 mb-3">
        <div v-for="(label, key) in CRITERION_LABELS" :key="key"
             class="flex items-center gap-2 text-xs" :class="dark ? 'text-slate-300' : 'text-slate-600'">
          <span class="w-28 truncate">{{ label }}</span>
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
        Raw slider total: {{ rawTotal }}%
      </p>

      <hr class="my-4" :class="dark ? 'border-slate-700' : 'border-black/5'" />
      <p class="text-[0.7rem]" :class="dark ? 'text-slate-500' : 'text-slate-400'">
        Data: FHWA (2023) · HCM 7th Ed. · PIARC Road Safety Manual (2022).
      </p>
    </div>
  </aside>
</template>

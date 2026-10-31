<script setup>
import { computed } from 'vue'
import { useLocale } from '../composables/useLocale.js'
import { CRITERION_KEYS, VALUE_SOURCES, DESIGN_SPEEDS, LANE_COUNTS } from '../composables/useDSS.js'
import MethodSelector from './MethodSelector.vue'
import WeightingControls from './WeightingControls.vue'
import Icon from './Icon.vue'
import PanelSection from './PanelSection.vue'
import ScenarioPanel from './ScenarioPanel.vue'
import { useScenarios } from '../composables/useScenarios.js'

const props = defineProps({
  dark: Boolean,
  dss: Object,
  // Phone layout: the inputs are their own tab, drawn as a grouped card in the page.
  page: Boolean,
})
const emit = defineEmits(['toggle-theme', 'show-results', 'show-compare', 'open-report'])
const { scenarios } = useScenarios()

const { locale, setLocale, t } = useLocale()

const criterionLabel = computed(() => ({
  construction_cost_mln: t.value.constructionCost,
  land_area_hectares:    t.value.landArea,
  throughput_vph:        t.value.throughput,
  safety_index:          t.value.safetyIndex,
}))

// Weight sliders, in criterion order: label key, direction key, slider tint.
const SLIDERS = [
  { key: 'construction_cost_mln', dir: 'minimize', tint: 'teal' },
  { key: 'land_area_hectares',    dir: 'minimize', tint: 'orange' },
  { key: 'throughput_vph',        dir: 'maximize', tint: 'violet' },
  { key: 'safety_index',          dir: 'maximize', tint: 'blue' },
]

const BAR_COLORS = {
  construction_cost_mln: '#0f766e',
  land_area_hectares: '#ea580c',
  throughput_vph: '#7c3aed',
  safety_index: '#1d4ed8',
}

// Weights the backend actually used (objective / AHP modes differ from the sliders).
const normW = computed(() => props.dss.evalData.value?.normalised_weights ?? props.dss.normalizedWeights())
const showSliders = computed(() => {
  const w = props.dss.weighting
  return w.mode === 'manual' || (w.mode === 'combined' && w.subjective === 'manual')
})
const rawTotal = computed(() =>
  props.dss.weights.construction_cost_mln +
  props.dss.weights.land_area_hectares +
  props.dss.weights.throughput_vph +
  props.dss.weights.safety_index
)

// One-line state of each section, shown in its header while it is collapsed.
const summaries = computed(() => {
  const d = props.dss
  const terrain = terrainOptions.value.find(o => o.value === d.params.terrain)?.label
  return {
    methods: d.methods.value.map(m => t.value.methodLabels[m]).join(' · '),
    weights: t.value.weightingModes[d.weighting.mode],
    scenarios: scenarios.value.length ? `${scenarios.value.length}` : '',
    params: `${d.params.design_speed} km/h · ${d.params.aadt.toLocaleString()} · ${terrain}`,
  }
})

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
  <!-- Left panel: every input that feeds the evaluation, always in view from md up. -->
  <aside :class="page ? '' : 'flex w-72 shrink-0 flex-col border-r border-line bg-panel lg:w-80'">
    <!-- Brand + app preferences (on phones these live in the More sheet) -->
    <div v-if="!page" class="flex h-[52px] shrink-0 items-center gap-2.5 border-b border-line px-4">
      <div class="flex h-6 w-6 items-center justify-center rounded-md bg-fg text-[0.7rem] font-bold text-app">T</div>
      <p class="min-w-0 flex-1 truncate text-[13px] font-semibold" :title="t.appTitle">{{ t.sidebarVersion }}</p>
      <div class="seg" role="radiogroup" :aria-label="t.switchLang">
        <button type="button" role="radio" class="seg-item !px-2 !py-0.5" :aria-checked="locale === 'uk'" @click="setLocale('uk')">UA</button>
        <button type="button" role="radio" class="seg-item !px-2 !py-0.5" :aria-checked="locale === 'en'" @click="setLocale('en')">EN</button>
      </div>
      <button class="icon-btn" :aria-label="t.toggleTheme" :title="t.toggleTheme" @click="emit('toggle-theme')">
        <Icon :name="dark ? 'sun' : 'moon'" class="text-[15px]" />
      </button>
    </div>

    <div :class="page ? 'card overflow-hidden [&>section:last-of-type]:border-b-0' : 'flex-1 overflow-y-auto overscroll-contain'">
      <!-- Context selector: the one input every view depends on, so it is never collapsed. -->
      <section class="border-b border-line p-4">
        <label class="eyebrow" for="ctx">{{ t.taskContext }}</label>
        <select id="ctx" v-model="dss.selectedContext.value" class="field mt-2">
          <option v-for="ctx in dss.contexts.value" :key="ctx" :value="ctx">{{ ctx }}</option>
        </select>
        <p class="mt-1.5 text-xs text-subtle">{{ t.taskContextDesc }}</p>
      </section>

      <PanelSection id="params" :title="t.projectParameters" :summary="summaries.params">
        <p class="mb-3 text-xs text-subtle">{{ t.projectParamsDesc }}</p>
        <div class="grid grid-cols-2 items-end gap-x-2 gap-y-3">
          <div>
            <label class="field-label">{{ t.designSpeed }}</label>
            <select v-model.number="dss.params.design_speed" class="field">
              <option v-for="s in DESIGN_SPEEDS" :key="s" :value="s">{{ s }}</option>
            </select>
          </div>
          <div>
            <label class="field-label">{{ t.numLanes }}</label>
            <select v-model.number="dss.params.num_lanes" class="field">
              <option v-for="n in LANE_COUNTS" :key="n" :value="n">{{ n }}</option>
            </select>
          </div>
          <div class="col-span-2">
            <label class="field-label">{{ t.aadt }}</label>
            <input type="number" v-model.number="dss.params.aadt" min="1000" max="200000" step="5000" class="field num" />
          </div>
          <div class="col-span-2">
            <div class="mb-1.5 flex items-baseline justify-between text-xs">
              <label class="text-muted">{{ t.peakFactor }}</label>
              <span class="num font-medium">{{ dss.params.peak_factor }}%</span>
            </div>
            <input type="range" v-range-fill v-model.number="dss.params.peak_factor" min="5" max="20" step="1"
                   class="ios-slider" />
          </div>
          <div>
            <label class="field-label">{{ t.budget }}</label>
            <input type="number" v-model.number="dss.params.budget" min="0" max="500" step="5" class="field num" />
          </div>
          <div>
            <label class="field-label">{{ t.landLimit }}</label>
            <input type="number" v-model.number="dss.params.land_limit" min="0" max="100" step="1" class="field num" />
          </div>
          <div>
            <label class="field-label">{{ t.terrainType }}</label>
            <select v-model="dss.params.terrain" class="field">
              <option v-for="opt in terrainOptions" :key="opt.value" :value="opt.value">{{ opt.label }}</option>
            </select>
          </div>
          <div>
            <label class="field-label">{{ t.envSensitivity }}</label>
            <select v-model="dss.params.env_sensitivity" class="field">
              <option v-for="opt in envOptions" :key="opt.value" :value="opt.value">{{ opt.label }}</option>
            </select>
          </div>
        </div>
      </PanelSection>

      <PanelSection id="methods" :title="t.methodsTitle" :summary="summaries.methods">
        <MethodSelector :dark="dark" :dss="dss" />
      </PanelSection>

      <PanelSection id="weights" :title="t.criteriaWeights" :summary="summaries.weights">
        <p v-if="showSliders" class="mb-3 text-xs text-subtle">{{ t.criteriaWeightsDesc }}</p>

        <WeightingControls :dark="dark" :dss="dss" />

        <div v-if="showSliders" class="space-y-3.5">
          <div v-for="s in SLIDERS" :key="s.key">
            <div class="mb-1.5 flex items-baseline justify-between gap-2 text-xs">
              <label :for="'w-' + s.key" class="text-muted">
                {{ criterionLabel[s.key] }} <span class="text-subtle">· {{ t[s.dir] }}</span>
              </label>
              <span class="num font-medium text-fg">{{ dss.weights[s.key] }}%</span>
            </div>
            <input :id="'w-' + s.key" type="range" v-range-fill v-model.number="dss.weights[s.key]" min="0" max="100" step="5"
                   class="ios-slider" :class="'ios-slider--' + s.tint" />
          </div>
        </div>

        <!-- Normalised weight bars -->
        <div class="mt-4 rounded-lg border border-line bg-surface p-3">
          <p class="mb-2 text-xs text-muted">{{ t.weightsUsedLabel }}</p>
          <div class="space-y-1.5">
            <div v-for="key in CRITERION_KEYS" :key="key" class="flex items-center gap-2 text-xs text-muted">
              <span class="w-24 truncate">{{ criterionLabel[key] }}</span>
              <div class="h-1 flex-1 overflow-hidden rounded-full bg-surface-3">
                <div class="h-full rounded-full transition-all duration-300"
                     :style="{ width: (normW[key] * 100) + '%', background: BAR_COLORS[key] }"></div>
              </div>
              <span class="num w-9 text-right text-fg">{{ normW[key]?.toFixed(2) }}</span>
            </div>
          </div>
          <p v-if="showSliders" class="num mt-2 text-xs"
             :class="Math.abs(rawTotal - 100) <= 1 ? 'text-accent-ink' : 'text-warn'">
            {{ t.rawTotalLabel }}: {{ rawTotal }}%
          </p>
        </div>
      </PanelSection>

      <!-- Criterion value source: expert constants or the document-trained model -->
      <section class="border-b border-line p-4">
        <h3 class="eyebrow mb-2">{{ t.valueSourceTitle }}</h3>
        <div role="radiogroup" :aria-label="t.valueSourceTitle" class="seg grid w-full grid-cols-2">
          <button v-for="src in VALUE_SOURCES" :key="src" type="button" role="radio"
                  :aria-checked="dss.valueSource.value === src"
                  @click="dss.valueSource.value = src"
                  class="seg-item">
            {{ t.valueSources[src] }}
          </button>
        </div>
        <p class="mt-1.5 text-xs text-subtle">{{ t.valueSourceHint[dss.valueSource.value] }}</p>
      </section>

      <PanelSection id="scenarios" :title="t.scenariosTitle" :summary="summaries.scenarios">
        <ScenarioPanel :dss="dss" @compare="emit('show-compare')" />
      </PanelSection>

      <p v-if="!page" class="p-4 text-[0.68rem] leading-snug text-subtle">{{ t.dataFooter }}</p>
    </div>

    <!-- The report summarises these inputs, so it is pinned under them (on phones it is in the More sheet). -->
    <div v-if="!page" class="shrink-0 border-t border-line p-3">
      <button type="button" class="btn w-full" :disabled="!dss.evalData.value" :title="t.report.title"
              @click="emit('open-report')">
        <Icon name="file" class="text-sm" /> {{ t.report.button }}
      </button>
    </div>

    <template v-if="page">
      <button type="button" class="btn-primary mt-4 w-full" @click="emit('show-results')">
        {{ t.showResults }} <Icon name="chevron-right" class="text-sm" />
      </button>
      <p class="mt-4 px-4 text-xs leading-snug text-subtle">{{ t.dataFooter }}</p>
    </template>
  </aside>
</template>

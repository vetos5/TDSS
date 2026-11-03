<script setup>
import { onMounted, watch, ref, nextTick, computed } from 'vue'
import { useDSS } from './composables/useDSS.js'
import { useTheme } from './composables/useTheme.js'
import { useLocale } from './composables/useLocale.js'
import { useModel } from './composables/useModel.js'
import { useViewport } from './composables/useViewport.js'
import Sidebar from './components/Sidebar.vue'
import TabNav from './components/TabNav.vue'
import MobileTabBar from './components/MobileTabBar.vue'
import DssEvaluation from './components/DssEvaluation.vue'
import BlueprintGallery from './components/BlueprintGallery.vue'
import Methodology from './components/Methodology.vue'
import RobustnessAnalysis from './components/RobustnessAnalysis.vue'
import SiteMap from './components/SiteMap.vue'
import PredictionModel from './components/PredictionModel.vue'
import ScenarioComparison from './components/ScenarioComparison.vue'
import DecisionReport from './components/DecisionReport.vue'
import EngineeringAnalysis from './components/EngineeringAnalysis.vue'
import { useScenarios } from './composables/useScenarios.js'

const { dark, toggle } = useTheme()
const { locale, t } = useLocale()
const dss = useDSS()
const model = useModel()
const { narrow } = useViewport()
const activeTab = ref('evaluation')
const reportOpen = ref(false)

const title = computed(() => ({
  inputs: t.value.tabInputs,
  evaluation: t.value.tabEvaluation,
  site: t.value.tabSiteAnalysis,
  engineering: t.value.tabEngineering,
  robustness: t.value.tabRobustness,
  model: t.value.tabModel,
  compare: t.value.tabCompare,
  gallery: t.value.tabGallery,
  methodology: t.value.tabMethodology,
}[activeTab.value]))

// Each view keeps its own scroll position, so switching back lands where you left off.
const scroller = ref(null)
const scrollTops = {}

async function selectTab(id) {
  if (id === 'report') return (reportOpen.value = true)
  // Re-selecting the current view scrolls it back to the top, as on iOS.
  if (id === activeTab.value) return scroller.value?.scrollTo({ top: 0, behavior: 'smooth' })
  scrollTops[activeTab.value] = scroller.value?.scrollTop ?? 0
  activeTab.value = id
  await nextTick()
  if (scroller.value) scroller.value.scrollTop = scrollTops[id] ?? 0
}

// "Inputs" is a tab on phones only; on wider screens the panel is always beside the content.
watch(narrow, n => { if (!n && activeTab.value === 'inputs') selectTab('evaluation') })

let debounceTimer = null

function scheduleEvaluation() {
  clearTimeout(debounceTimer)
  debounceTimer = setTimeout(async () => {
    if (dss.selectedContext.value) {
      await dss.runEvaluation(locale.value)
    }
  }, 300)
}

onMounted(async () => {
  await dss.loadContexts()
  // A shared link (#s=…) opens with its inputs; the input watcher below then re-evaluates.
  const shared = useScenarios().takeSharedState()
  if (shared) dss.applyState(shared.state)
  await dss.runEvaluation(locale.value)
})

watch(
  [
    () => dss.selectedContext.value,
    () => ({ ...dss.weights }),
    () => ({ ...dss.params }),
    () => [...dss.methods.value],
    () => ({ ...dss.weighting }),
    () => [...dss.ahpJudgements],
    () => dss.valueSource.value,
  ],
  scheduleEvaluation,
  { deep: true }
)

watch(locale, scheduleEvaluation)

// A retrain / upload / delete refits the model; model-sourced values must follow it.
watch(() => model.status.value?.revision, (now, before) => {
  if (before && now !== before && dss.valueSource.value === 'model') scheduleEvaluation()
})
</script>

<template>
  <div class="flex h-dvh overflow-hidden bg-app text-fg">
    <Sidebar v-if="!narrow" :dark="dark" :dss="dss" @toggle-theme="toggle" @show-compare="selectTab('compare')"
             @open-report="reportOpen = true" />

    <main ref="scroller" class="relative min-w-0 flex-1 overflow-y-auto pb-[calc(52px+env(safe-area-inset-bottom))] md:pb-0">
      <!-- Desktop toolbar: title on the left, view switcher centred, activity on the right.
           Equal 1fr side columns keep the switcher centred whatever the language. The title
           only shows while the switcher is icons only: once its labels appear (TabNav, 1360px)
           they name the view, and the title would be squeezed to a few letters. -->
      <header class="material-bar sticky top-0 z-20 hidden h-[52px] grid-cols-[minmax(0,1fr)_auto_minmax(0,1fr)] items-center gap-3 border-b border-line px-4 md:grid">
        <div class="min-w-0 min-[1360px]:invisible">
          <h1 class="truncate text-[15px] leading-tight font-semibold">{{ title }}</h1>
          <p class="truncate text-[11px] text-muted">
            {{ dss.selectedContext.value }}<template v-if="dss.valueSource.value === 'model'"> · {{ t.valueSources.model }}</template>
          </p>
        </div>
        <TabNav :active="activeTab" @update="selectTab" />
        <div class="flex min-w-0 items-center justify-end gap-1.5 text-xs text-subtle transition-opacity duration-200"
             :class="dss.loading.value ? 'opacity-100' : 'opacity-0'" aria-live="polite">
          <span class="spinner shrink-0"></span>
          <span class="hidden truncate lg:inline">{{ t.updating }}</span>
        </div>
      </header>

      <!-- Phone navigation bar -->
      <header class="material-bar sticky top-0 z-20 border-b border-line pt-safe md:hidden">
        <div class="relative flex h-11 flex-col items-center justify-center px-12">
          <h1 class="max-w-full truncate text-[17px] leading-tight font-semibold">{{ title }}</h1>
          <p v-if="activeTab !== 'inputs'" class="max-w-full truncate text-[11px] leading-tight text-muted">
            {{ dss.selectedContext.value }}
          </p>
          <span class="spinner absolute right-4 transition-opacity duration-200"
                :class="dss.loading.value ? 'opacity-100' : 'opacity-0'"></span>
        </div>
      </header>

      <div class="mx-auto max-w-[1400px] px-4 py-4 sm:p-6">
        <!-- Phone only: the inputs as a page of their own -->
        <Sidebar v-if="narrow" v-show="activeTab === 'inputs'" page class="tab-pane"
                 :dark="dark" :dss="dss" @show-results="selectTab('evaluation')"
                 @show-compare="selectTab('compare')" />

        <template v-if="activeTab !== 'inputs'">
          <!-- Full-page spinner only on initial load (no data yet) -->
          <div v-if="dss.loading.value && !dss.evalData.value" class="flex items-center justify-center py-24">
            <span class="spinner !h-6 !w-6"></span>
          </div>

          <div v-if="dss.evalError.value && activeTab === 'evaluation'" class="notice notice-bad mb-4">
            <span class="font-semibold">{{ t.evaluationFailed }}</span> {{ dss.evalError.value }}
          </div>
        </template>

        <!-- Panes stay mounted (v-show) so views keep their state; .tab-pane fades each one in on show. -->
        <template v-if="dss.evalData.value">
          <DssEvaluation
            v-show="activeTab === 'evaluation'"
            class="tab-pane"
            :data="dss.evalData.value"
            :params="dss.params"
            :dark="dark"
          />
          <SiteMap
            v-show="activeTab === 'site'"
            class="tab-pane"
            :dss="dss"
            :active="activeTab === 'site'"
            :dark="dark"
          />
          <EngineeringAnalysis
            v-show="activeTab === 'engineering'"
            class="tab-pane"
            :dss="dss"
            :active="activeTab === 'engineering'"
            :dark="dark"
          />
          <RobustnessAnalysis
            v-show="activeTab === 'robustness'"
            class="tab-pane"
            :dss="dss"
            :active="activeTab === 'robustness'"
            :dark="dark"
          />
          <PredictionModel
            v-show="activeTab === 'model'"
            class="tab-pane"
            :dss="dss"
            :active="activeTab === 'model'"
            :dark="dark"
          />
          <ScenarioComparison
            v-show="activeTab === 'compare'"
            class="tab-pane"
            :dss="dss"
            :active="activeTab === 'compare'"
            :dark="dark"
          />
          <BlueprintGallery
            v-show="activeTab === 'gallery'"
            class="tab-pane"
            :data="dss.evalData.value"
            :params="dss.params"
            :dark="dark"
          />
          <Methodology
            v-show="activeTab === 'methodology'"
            class="tab-pane"
            :data="dss.evalData.value"
            :dark="dark"
          />
        </template>
      </div>
    </main>

    <MobileTabBar :active="activeTab" @update="selectTab" />
    <DecisionReport :open="reportOpen" :dss="dss" @close="reportOpen = false" />
  </div>
</template>

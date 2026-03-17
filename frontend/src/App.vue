<script setup>
import { onMounted, watch, ref } from 'vue'
import { useDSS } from './composables/useDSS.js'
import { useTheme } from './composables/useTheme.js'
import Sidebar from './components/Sidebar.vue'
import TabNav from './components/TabNav.vue'
import DssEvaluation from './components/DssEvaluation.vue'
import BlueprintGallery from './components/BlueprintGallery.vue'
import Methodology from './components/Methodology.vue'

const { dark, toggle } = useTheme()
const dss = useDSS()
const activeTab = ref('evaluation')

let debounceTimer = null

onMounted(async () => {
  await dss.loadContexts()
  await dss.runEvaluation()
})

watch(
  [() => dss.selectedContext.value, () => ({ ...dss.weights }), () => ({ ...dss.params })],
  () => {
    clearTimeout(debounceTimer)
    debounceTimer = setTimeout(async () => {
      if (dss.selectedContext.value) {
        await dss.runEvaluation()
      }
    }, 300)
  },
  { deep: true }
)
</script>

<template>
  <div class="min-h-screen transition-colors duration-200"
       :class="dark ? 'bg-slate-900 text-slate-200' : 'bg-slate-50 text-slate-900'">
    <div class="flex">
      <Sidebar :dark="dark" :dss="dss" @toggle-theme="toggle" />

      <main class="flex-1 ml-80 p-6 lg:p-8">
        <header class="mb-6">
          <h1 class="text-2xl lg:text-3xl font-extrabold tracking-tight"
              :class="dark ? 'text-slate-100' : 'text-slate-900'">
            Transport Interchange Decision Support System
          </h1>
          <p class="text-sm mt-1" :class="dark ? 'text-slate-400' : 'text-slate-500'">
            Multi-Criteria Decision Analysis (MCDA) · Weighted Sum Model (WSM)
          </p>
        </header>

        <TabNav :active="activeTab" :dark="dark" @update="activeTab = $event" />

        <div v-if="dss.loading.value" class="flex items-center justify-center py-20">
          <div class="animate-spin rounded-full h-10 w-10 border-b-2"
               :class="dark ? 'border-teal-400' : 'border-teal-700'"></div>
        </div>

        <template v-else-if="dss.evalData.value">
          <DssEvaluation
            v-show="activeTab === 'evaluation'"
            :data="dss.evalData.value"
            :params="dss.params"
            :dark="dark"
          />
          <BlueprintGallery
            v-show="activeTab === 'gallery'"
            :data="dss.evalData.value"
            :params="dss.params"
            :dark="dark"
          />
          <Methodology
            v-show="activeTab === 'methodology'"
            :data="dss.evalData.value"
            :dark="dark"
          />
        </template>
      </main>
    </div>
  </div>
</template>

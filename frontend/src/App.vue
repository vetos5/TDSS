<script setup>
import { onMounted, watch, ref } from 'vue'
import { useDSS } from './composables/useDSS.js'
import { useTheme } from './composables/useTheme.js'
import { useLocale } from './composables/useLocale.js'
import Sidebar from './components/Sidebar.vue'
import TabNav from './components/TabNav.vue'
import DssEvaluation from './components/DssEvaluation.vue'
import BlueprintGallery from './components/BlueprintGallery.vue'
import Methodology from './components/Methodology.vue'

const { dark, toggle } = useTheme()
const { locale, t } = useLocale()
const dss = useDSS()
const activeTab = ref('evaluation')
const sidebarOpen = ref(false)

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
  await dss.runEvaluation(locale.value)
})

watch(
  [() => dss.selectedContext.value, () => ({ ...dss.weights }), () => ({ ...dss.params })],
  scheduleEvaluation,
  { deep: true }
)

watch(locale, scheduleEvaluation)
</script>

<template>
  <div class="relative min-h-screen overflow-hidden transition-colors duration-200"
       :class="dark ? 'bg-slate-900 text-slate-200' : 'bg-[#F5F5F7] text-slate-900'">

    <!-- Global ambient blobs (light mode glassmorphism backdrop) -->
    <div v-if="!dark" class="pointer-events-none fixed inset-0 -z-10 overflow-hidden">
      <div class="absolute -top-32 left-1/4 h-[480px] w-[480px] rounded-full bg-blue-200/60 blur-[120px]"></div>
      <div class="absolute top-1/3 -right-24 h-[420px] w-[420px] rounded-full bg-rose-200/60 blur-[120px]"></div>
      <div class="absolute bottom-0 left-1/2 h-[360px] w-[360px] -translate-x-1/2 rounded-full bg-violet-200/40 blur-[140px]"></div>
    </div>

    <div class="flex">
      <!-- Mobile sidebar backdrop -->
      <div v-if="sidebarOpen"
           class="fixed inset-0 z-20 bg-black/40 backdrop-blur-sm md:hidden"
           @click="sidebarOpen = false"></div>

      <!-- Hamburger (mobile only) — fixed so it stays visible when scrolling -->
      <button v-if="!sidebarOpen"
              class="fixed top-3 left-3 z-40 md:hidden w-9 h-9 rounded-xl flex items-center justify-center transition-colors"
              :class="dark
                ? 'bg-slate-700 border border-slate-600 text-slate-200 hover:bg-slate-600'
                : 'bg-white/80 border border-black/5 shadow-[0_1px_3px_rgb(0,0,0,0.06)] text-slate-700 hover:bg-white'"
              @click="sidebarOpen = true"
              aria-label="Open settings">
        <svg class="w-4 h-4" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24">
          <path stroke-linecap="round" stroke-linejoin="round" d="M4 6h16M4 12h16M4 18h16"/>
        </svg>
      </button>

      <Sidebar :dark="dark" :dss="dss" :open="sidebarOpen"
               @toggle-theme="toggle"
               @close="sidebarOpen = false" />

      <main class="flex-1 md:ml-80 p-4 sm:p-6 lg:p-8 min-w-0">
        <header class="mb-6 flex items-start gap-3">
          <!-- Spacer so the title doesn't sit under the fixed hamburger on mobile -->
          <div class="md:hidden shrink-0 w-9 h-9" aria-hidden="true"></div>
          <div>
            <h1 class="text-2xl lg:text-3xl font-extrabold tracking-tight"
                :class="dark ? 'text-slate-100' : 'text-slate-900'">
              {{ t.appTitle }}
            </h1>
            <p class="text-sm mt-1" :class="dark ? 'text-slate-400' : 'text-slate-500'">
              {{ t.appSubtitle }}
            </p>
          </div>
        </header>

        <TabNav :active="activeTab" :dark="dark" @update="v => { activeTab = v; sidebarOpen = false }" />

        <!-- Full-page spinner only on initial load (no data yet) -->
        <div v-if="dss.loading.value && !dss.evalData.value" class="flex items-center justify-center py-20">
          <div class="animate-spin rounded-full h-10 w-10 border-b-2"
               :class="dark ? 'border-teal-400' : 'border-teal-700'"></div>
        </div>

        <template v-if="dss.evalData.value">
          <!-- Subtle re-evaluation indicator -->
          <div class="flex items-center gap-2 mb-3 h-5 transition-opacity duration-200"
               :class="dss.loading.value ? 'opacity-100' : 'opacity-0 pointer-events-none'">
            <div class="animate-spin rounded-full h-3.5 w-3.5 border-b-2"
                 :class="dark ? 'border-teal-400' : 'border-teal-600'"></div>
            <span class="text-xs" :class="dark ? 'text-slate-400' : 'text-slate-500'">{{ t.updating }}</span>
          </div>

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

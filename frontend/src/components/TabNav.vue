<script setup>
import { computed, ref, watch, onMounted, onBeforeUnmount, nextTick } from 'vue'
import { useLocale } from '../composables/useLocale.js'
import Icon from './Icon.vue'

// Toolbar view switcher (macOS segmented control, as in Activity Monitor). Labels show on
// wide windows, icons only below that. Keys 1–9 and 0 switch views when no field has focus.
const props = defineProps({ active: String })
const emit = defineEmits(['update'])

const { t, locale } = useLocale()

const tabs = computed(() => [
  { id: 'evaluation',  label: t.value.tabEvaluation,   icon: 'chart-column' },
  { id: 'site',        label: t.value.tabSiteAnalysis, icon: 'map' },
  { id: 'engineering', label: t.value.tabEngineering,  icon: 'gauge' },
  { id: 'robustness',  label: t.value.tabRobustness,   icon: 'shield-check' },
  { id: 'model',       label: t.value.tabModel,        icon: 'activity' },
  { id: 'compare',     label: t.value.tabCompare,      icon: 'columns' },
  { id: 'gallery',     label: t.value.tabGallery,      icon: 'layout-grid' },
  { id: 'methodology', label: t.value.tabMethodology,  icon: 'book-open' },
])

// Selection pill that slides between segments.
const bar = ref(null)
const buttons = ref({})
const pill = ref({ left: 0, width: 0 })

function place() {
  const el = buttons.value[props.active]
  if (el) pill.value = { left: el.offsetLeft, width: el.offsetWidth }
}

function onKey(e) {
  if (e.metaKey || e.ctrlKey || e.altKey) return
  if (e.target.closest?.('input, select, textarea, [contenteditable], [role=dialog]')) return
  if (!/^[0-9]$/.test(e.key)) return
  const tab = tabs.value[e.key === '0' ? 9 : Number(e.key) - 1]
  if (tab) emit('update', tab.id)
}

let ro = null
onMounted(() => {
  nextTick(place)
  ro = new ResizeObserver(place)
  ro.observe(bar.value)
  window.addEventListener('keydown', onKey)
  document.fonts?.ready.then(place)
})
onBeforeUnmount(() => {
  ro?.disconnect()
  window.removeEventListener('keydown', onKey)
})
watch(() => [props.active, locale.value], () => nextTick(place))
</script>

<template>
  <div ref="bar" role="tablist" class="seg relative">
    <span class="pointer-events-none absolute top-0.5 bottom-0.5 rounded-md bg-control transition-[left,width] duration-300 ease-[cubic-bezier(0.32,0.72,0,1)]"
          :style="{ left: pill.left + 'px', width: pill.width + 'px', boxShadow: 'var(--control-shadow)' }"></span>
    <button v-for="(tab, i) in tabs" :key="tab.id" :ref="el => { if (el) buttons[tab.id] = el }"
            type="button" role="tab" :aria-selected="active === tab.id" :aria-label="tab.label"
            :title="i < 10 ? `${tab.label}  (${(i + 1) % 10})` : tab.label"
            @click="$emit('update', tab.id)"
            class="relative flex items-center gap-1.5 rounded-md px-2.5 py-1 text-xs font-medium whitespace-nowrap transition-colors duration-200"
            :class="active === tab.id ? 'text-fg' : 'text-muted hover:text-fg'">
      <Icon :name="tab.icon" class="text-sm" :class="active === tab.id ? 'text-accent' : ''" />
      <span class="hidden min-[1360px]:inline">{{ tab.label }}</span>
    </button>
  </div>
</template>

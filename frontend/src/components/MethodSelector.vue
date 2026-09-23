<script setup>
import { useLocale } from '../composables/useLocale.js'
import { ALL_METHODS } from '../composables/useDSS.js'

const props = defineProps({
  dark: Boolean,
  dss: Object,
})

const { t } = useLocale()

function toggle(id) {
  const selected = props.dss.methods.value
  if (selected.includes(id)) {
    if (selected.length > 1) props.dss.methods.value = selected.filter(m => m !== id)
  } else {
    props.dss.methods.value = ALL_METHODS.filter(m => m === id || selected.includes(m))
  }
}
</script>

<template>
  <div class="mb-4">
    <p class="font-bold text-sm mb-1" :class="dark ? 'text-slate-100' : 'text-slate-900'">{{ t.methodsTitle }}</p>
    <p class="text-xs mb-2" :class="dark ? 'text-slate-400' : 'text-slate-500'">{{ t.methodsDesc }}</p>
    <div class="flex flex-wrap gap-1.5">
      <button v-for="id in ALL_METHODS" :key="id" type="button" @click="toggle(id)"
              :aria-pressed="dss.methods.value.includes(id)"
              class="px-2.5 py-1 rounded-lg text-xs font-semibold border transition-colors"
              :class="dss.methods.value.includes(id)
                ? (dark ? 'bg-teal-500/20 border-teal-400/60 text-teal-200' : 'bg-teal-600 border-teal-600 text-white')
                : (dark ? 'bg-slate-700 border-slate-600 text-slate-400 hover:text-slate-200' : 'bg-white/80 border-black/10 text-slate-500 hover:text-slate-800')">
        {{ t.methodLabels[id] }}
      </button>
    </div>
  </div>
</template>

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
  <div>
    <p class="mb-2 text-xs text-subtle">{{ t.methodsDesc }}</p>
    <div class="flex flex-wrap gap-1.5">
      <button v-for="id in ALL_METHODS" :key="id" type="button" @click="toggle(id)"
              :aria-pressed="dss.methods.value.includes(id)"
              class="rounded-md border px-2 py-1 text-xs font-medium transition-colors"
              :class="dss.methods.value.includes(id)
                ? 'border-accent/40 bg-accent-soft text-accent-ink'
                : 'border-line bg-surface text-muted hover:text-fg'">
        {{ t.methodLabels[id] }}
      </button>
    </div>
  </div>
</template>

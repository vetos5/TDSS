<script setup>
import { computed } from 'vue'
import { useLocale } from '../composables/useLocale.js'

defineProps({ active: String, dark: Boolean })
defineEmits(['update'])

const { t } = useLocale()

const tabs = computed(() => [
  { id: 'evaluation', label: t.value.tabEvaluation },
  { id: 'gallery',    label: t.value.tabGallery },
  { id: 'methodology', label: t.value.tabMethodology },
])
</script>

<template>
  <div class="flex border-b mb-6" :class="dark ? 'border-slate-700' : 'border-slate-200'">
    <button v-for="tab in tabs" :key="tab.id"
            @click="$emit('update', tab.id)"
            class="px-4 py-2.5 text-sm font-medium transition-colors border-b-2 -mb-px"
            :class="active === tab.id
              ? (dark ? 'text-teal-400 border-teal-400' : 'text-teal-700 border-teal-700')
              : (dark ? 'text-slate-400 border-transparent hover:text-slate-300' : 'text-slate-500 border-transparent hover:text-slate-700')">
      {{ tab.label }}
    </button>
  </div>
</template>

<script setup>
import { ref, watch } from 'vue'
import Icon from './Icon.vue'

// Collapsible group in the inputs panel. The open state is remembered per section, and a
// collapsed section still shows its current value in `summary` so nothing has to be opened
// just to read it.
const props = defineProps({
  id: { type: String, required: true },
  title: String,
  summary: String,
})

const key = `panel:${props.id}`
const open = ref(localStorage.getItem(key) !== '0')
watch(open, v => localStorage.setItem(key, v ? '1' : '0'))
</script>

<template>
  <section class="border-b border-line">
    <button type="button" class="group flex min-h-11 w-full items-center gap-2 px-4 py-3 text-left"
            :aria-expanded="open" @click="open = !open">
      <Icon name="chevron-right" class="text-xs text-subtle transition-transform duration-200"
            :class="open ? 'rotate-90' : ''" />
      <h3 class="eyebrow shrink-0 whitespace-nowrap group-hover:text-muted">{{ title }}</h3>
      <Transition name="fade">
        <span v-if="summary && !open" class="ml-auto min-w-0 truncate pl-2 text-xs text-muted">{{ summary }}</span>
      </Transition>
    </button>
    <div class="grid transition-[grid-template-rows] duration-200 ease-out"
         :class="open ? 'grid-rows-[1fr]' : 'grid-rows-[0fr]'">
      <div class="min-h-0 overflow-hidden">
        <div class="px-4 pb-4" :inert="!open">
          <slot />
        </div>
      </div>
    </div>
  </section>
</template>

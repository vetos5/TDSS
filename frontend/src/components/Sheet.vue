<script setup>
import { ref, watch, nextTick, onBeforeUnmount } from 'vue'

// iOS-style bottom sheet: slides up over a dimmed backdrop, closes on backdrop tap, Escape,
// the Done button, or a downward drag on the grabber/header.
const props = defineProps({ open: Boolean, title: String, doneLabel: String })
const emit = defineEmits(['close'])

const panel = ref(null)
const dragY = ref(0)
let startY = null

function onKey(e) {
  if (e.key === 'Escape') emit('close')
}

watch(() => props.open, async o => {
  if (o) {
    dragY.value = 0
    window.addEventListener('keydown', onKey)
    await nextTick()
    panel.value?.focus()
  } else {
    window.removeEventListener('keydown', onKey)
  }
})
onBeforeUnmount(() => window.removeEventListener('keydown', onKey))

function dragStart(e) {
  startY = e.clientY
  e.currentTarget.setPointerCapture(e.pointerId)
}
function dragMove(e) {
  if (startY !== null) dragY.value = Math.max(0, e.clientY - startY)
}
function dragEnd() {
  if (startY === null) return
  startY = null
  if (dragY.value > 80) emit('close')
  else dragY.value = 0
}
</script>

<template>
  <Teleport to="body">
    <Transition name="fade">
      <div v-if="open" class="fixed inset-0 z-50 bg-black/30" @click="emit('close')"></div>
    </Transition>
    <Transition name="sheet">
      <div v-if="open" ref="panel" role="dialog" aria-modal="true" :aria-label="title" tabindex="-1"
           class="fixed inset-x-0 bottom-0 z-50 mx-auto flex max-h-[85dvh] max-w-lg flex-col rounded-t-2xl bg-app pb-safe outline-none"
           :style="{ boxShadow: 'var(--sheet-shadow)', transform: dragY ? `translateY(${dragY}px)` : undefined,
                     transition: dragY && startY !== null ? 'none' : undefined }">
        <div class="shrink-0 touch-none select-none" @pointerdown="dragStart" @pointermove="dragMove"
             @pointerup="dragEnd" @pointercancel="dragEnd">
          <div class="mx-auto mt-2 h-1.5 w-9 rounded-full bg-line-strong"></div>
          <div class="relative flex h-11 items-center px-4">
            <h2 class="flex-1 text-center text-[17px] font-semibold">{{ title }}</h2>
            <button class="absolute right-2 min-h-11 px-3 text-[17px] font-semibold text-accent-ink" @click="emit('close')">
              {{ doneLabel }}
            </button>
          </div>
        </div>
        <div class="overflow-y-auto overscroll-contain px-4 pb-4">
          <slot />
        </div>
      </div>
    </Transition>
  </Teleport>
</template>

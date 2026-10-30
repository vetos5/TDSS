import { ref } from 'vue'

// Shared breakpoint state. `narrow` matches Tailwind's below-md range (phones), where the
// app switches to the bottom tab bar; `coarse` is a touch-first pointer.
const narrowQuery = window.matchMedia('(max-width: 767px)')
const coarseQuery = window.matchMedia('(pointer: coarse)')

const narrow = ref(narrowQuery.matches)
const coarse = ref(coarseQuery.matches)

narrowQuery.addEventListener('change', e => { narrow.value = e.matches })
coarseQuery.addEventListener('change', e => { coarse.value = e.matches })

export function useViewport() {
  return { narrow, coarse }
}

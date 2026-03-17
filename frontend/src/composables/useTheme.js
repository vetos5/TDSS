import { ref, watchEffect } from 'vue'

const dark = ref(false)

function toggle() {
  dark.value = !dark.value
}

watchEffect(() => {
  document.documentElement.classList.toggle('dark', dark.value)
})

export function useTheme() {
  return { dark, toggle }
}

import { ref, watchEffect } from 'vue'

// Remembered choice first, then the OS preference.
const stored = localStorage.getItem('theme')
const dark = ref(stored ? stored === 'dark' : window.matchMedia('(prefers-color-scheme: dark)').matches)

function setDark(value) {
  dark.value = value
  localStorage.setItem('theme', value ? 'dark' : 'light')
}

function toggle() {
  setDark(!dark.value)
}

watchEffect(() => {
  document.documentElement.classList.toggle('dark', dark.value)
})

export function useTheme() {
  return { dark, toggle, setDark }
}

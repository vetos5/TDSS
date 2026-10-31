import { createApp } from 'vue'
// Leaflet's stylesheet is bundled (no CDN) and comes first, so the app's rules still win.
import 'leaflet/dist/leaflet.css'
import './style.css'
import App from './App.vue'
import { i18n } from './i18n.js'

// v-range-fill on an <input type="range" class="ios-slider"> paints the track up to the value.
function paintRange(el) {
  const min = Number(el.min || 0)
  const max = Number(el.max || 100)
  el.style.setProperty('--pct', `${((Number(el.value) - min) / (max - min || 1)) * 100}%`)
}

const rangeFill = {
  mounted(el) {
    // v-model writes a range's value in its own mounted hook, which may run after this one.
    queueMicrotask(() => paintRange(el))
    el.addEventListener('input', () => paintRange(el))
  },
  updated: paintRange,
}

createApp(App).use(i18n).directive('range-fill', rangeFill).mount('#app')

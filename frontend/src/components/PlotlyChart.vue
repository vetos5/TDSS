<script setup>
import { ref, onMounted, onBeforeUnmount, watch, nextTick } from 'vue'
import Plotly from 'plotly.js-dist-min'
import { useViewport } from '../composables/useViewport.js'

const props = defineProps({
  chart: Object,
  dark: Boolean,
})

const container = ref(null)
const { coarse } = useViewport()
let ro = null
// Charts in hidden tabs (display: none) have no width; drawing them there and resizing on
// show makes them visibly jump. Defer the draw until the container is laid out instead.
let pending = true
let lastWidth = 0

function visible() {
  return container.value && container.value.offsetWidth > 0
}

async function render() {
  if (!container.value || !props.chart) return
  await nextTick()
  if (!visible()) { pending = true; return }
  pending = false
  lastWidth = container.value.offsetWidth
  // On touch screens a drag should scroll the page, not zoom the chart.
  const layout = coarse.value ? { ...props.chart.layout, dragmode: false } : props.chart.layout
  Plotly.react(container.value, props.chart.data, layout, { responsive: true, displayModeBar: false, scrollZoom: false })
}

function onResize() {
  if (!visible()) return
  if (pending) return render()
  const w = container.value.offsetWidth
  if (w === lastWidth) return
  lastWidth = w
  Plotly.relayout(container.value, { autosize: true })
}

onMounted(() => {
  render()
  ro = new ResizeObserver(onResize)
  ro.observe(container.value)
})

onBeforeUnmount(() => {
  ro?.disconnect()
  if (container.value) Plotly.purge(container.value)
})

watch(() => [props.chart, props.dark], render, { deep: true })
</script>

<template>
  <!-- min-height keeps the card from collapsing before the first draw. -->
  <div ref="container" class="w-full min-w-0"
       :style="{ minHeight: (chart?.layout?.height ?? 0) + 'px' }"></div>
</template>

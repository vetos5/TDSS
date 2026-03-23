<script setup>
import { ref, onMounted, onBeforeUnmount, watch, nextTick } from 'vue'
import Plotly from 'plotly.js-dist-min'

const props = defineProps({
  chart: Object,
  dark: Boolean,
})

const container = ref(null)
let ro = null

async function render() {
  if (!container.value || !props.chart) return
  await nextTick()
  Plotly.react(container.value, props.chart.data, props.chart.layout, { responsive: true, displayModeBar: false })
}

function relayout() {
  if (!container.value) return
  Plotly.relayout(container.value, { autosize: true })
}

onMounted(() => {
  render()
  ro = new ResizeObserver(relayout)
  ro.observe(container.value)
})

onBeforeUnmount(() => ro?.disconnect())

watch(() => [props.chart, props.dark], render, { deep: true })
</script>

<template>
  <div ref="container" class="w-full min-w-0"></div>
</template>

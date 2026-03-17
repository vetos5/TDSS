<script setup>
import { ref, onMounted, watch, nextTick } from 'vue'
import Plotly from 'plotly.js-dist-min'

const props = defineProps({
  chart: Object,
  dark: Boolean,
})

const container = ref(null)

async function render() {
  if (!container.value || !props.chart) return
  await nextTick()
  Plotly.react(container.value, props.chart.data, props.chart.layout, { responsive: true, displayModeBar: false })
}

onMounted(render)
watch(() => [props.chart, props.dark], render, { deep: true })
</script>

<template>
  <div ref="container" class="w-full"></div>
</template>

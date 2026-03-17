<script setup>
import { ref, onMounted, watch, nextTick } from 'vue'
import L from 'leaflet'

const props = defineProps({
  lat: Number,
  lon: Number,
  name: String,
  example: String,
  dark: Boolean,
})

const mapContainer = ref(null)
let map = null
let marker = null
let circle = null

function initMap() {
  if (!mapContainer.value) return

  if (map) {
    map.remove()
    map = null
  }

  map = L.map(mapContainer.value, { zoomControl: true }).setView([props.lat, props.lon], 15)

  L.tileLayer(
    'https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}',
    { attribution: 'Esri World Imagery', maxZoom: 19 }
  ).addTo(map)

  marker = L.marker([props.lat, props.lon]).addTo(map)
    .bindPopup(`<b>${props.name}</b><br>${props.example}`)

  circle = L.circle([props.lat, props.lon], {
    radius: 300,
    color: '#2dd4bf',
    fillColor: '#2dd4bf',
    fillOpacity: 0.1,
    weight: 2,
  }).addTo(map)
}

onMounted(() => {
  nextTick(initMap)
})

watch(() => [props.lat, props.lon], () => {
  nextTick(initMap)
})
</script>

<template>
  <div ref="mapContainer" class="w-full h-96 rounded-xl z-0"></div>
</template>

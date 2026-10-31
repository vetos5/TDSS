<script setup>
import { ref, onMounted, onBeforeUnmount, watch, nextTick } from 'vue'
import L from 'leaflet'
import markerIcon from 'leaflet/dist/images/marker-icon.png'
import markerIcon2x from 'leaflet/dist/images/marker-icon-2x.png'
import markerShadow from 'leaflet/dist/images/marker-shadow.png'
import { useViewport } from '../composables/useViewport.js'

// Leaflet finds its default marker images through leaflet.css; bundled, they are renamed (or
// inlined), so that lookup fails. Point the default icon at the bundled files instead.
L.Icon.Default.imagePath = ''
L.Icon.Default.mergeOptions({ iconUrl: markerIcon, iconRetinaUrl: markerIcon2x, shadowUrl: markerShadow })

const props = defineProps({
  lat: Number,
  lon: Number,
  name: String,
  example: String,
  dark: Boolean,
})

const mapContainer = ref(null)
const { coarse } = useViewport()
let map = null
let marker = null
let circle = null
let ro = null

// Built from DOM nodes: an HTML string would let the names inject markup.
function popupContent() {
  const el = document.createElement('div')
  const name = document.createElement('b')
  name.textContent = props.name ?? ''
  el.append(name, document.createElement('br'), props.example ?? '')
  return el
}

function initMap() {
  if (!mapContainer.value) return

  if (map) {
    map.remove()
    map = null
  }

  // On touch screens one finger scrolls the page; pinch or the +/- buttons zoom the map.
  map = L.map(mapContainer.value, { zoomControl: true, dragging: !coarse.value }).setView([props.lat, props.lon], 15)

  L.tileLayer(
    'https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}',
    { attribution: 'Esri World Imagery', maxZoom: 19 }
  ).addTo(map)

  marker = L.marker([props.lat, props.lon]).addTo(map)
    .bindPopup(popupContent())

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
  ro = new ResizeObserver(() => map?.invalidateSize())
  ro.observe(mapContainer.value)
})

onBeforeUnmount(() => {
  ro?.disconnect()
  map?.remove()
  map = null
})

watch(() => [props.lat, props.lon, props.name, props.example], () => {
  nextTick(initMap)
})
</script>

<template>
  <div class="overflow-hidden rounded-lg border border-line">
    <div ref="mapContainer" class="z-0 h-64 w-full !rounded-none sm:h-80 md:h-96"></div>
  </div>
</template>

<style scoped>
/* macOS-style zoom buttons; 44px on touch screens. */
:deep(.leaflet-bar) {
  border: 0;
  border-radius: 0.5rem;
  overflow: hidden;
  box-shadow: var(--control-shadow);
}
:deep(.leaflet-bar a) {
  background: var(--control);
  color: var(--fg);
  border-bottom-color: var(--line);
}
:deep(.leaflet-bar a:hover) {
  background: var(--surface-2);
}
@media (pointer: coarse) {
  :deep(.leaflet-touch .leaflet-bar a) {
    width: 44px;
    height: 44px;
    line-height: 44px;
    font-size: 20px;
  }
}
</style>

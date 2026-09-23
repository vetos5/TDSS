<script setup>
import { ref, computed, onMounted, onBeforeUnmount, watch, nextTick } from 'vue'
import L from 'leaflet'
import { useLocale } from '../composables/useLocale.js'
import { useSiteAnalysis } from '../composables/useSiteAnalysis.js'

const props = defineProps({
  dss: Object,
  dark: Boolean,
  active: Boolean,
})

const { t, locale } = useLocale()
const site = useSiteAnalysis()

// Conventional cartographic colours (not the chart categorical palette -- this is a basemap
// overlay legend, where blue-for-water / green-for-nature are the reader's existing expectation).
const FEATURE_STYLE = {
  road: { color: '#e34948', weight: 3, fillOpacity: 0 },
  building: { color: '#78716c', weight: 1, fillColor: '#78716c', fillOpacity: 0.5 },
  water: { color: '#2a78d6', weight: 1, fillColor: '#2a78d6', fillOpacity: 0.45 },
  protected: { color: '#1baf7a', weight: 1, fillColor: '#1baf7a', fillOpacity: 0.25, dashArray: '4 3' },
  residential: { color: '#eda100', weight: 1, fillColor: '#eda100', fillOpacity: 0.12 },
}

const mapContainer = ref(null)
let map = null
let markerA = null
let markerB = null
let bearingLine = null
let featuresLayer = null
let footprintLayer = null

function iconFor(color) {
  return L.divIcon({
    className: '',
    html: `<div style="width:16px;height:16px;border-radius:50%;background:${color};border:2px solid white;box-shadow:0 1px 4px rgba(0,0,0,0.4)"></div>`,
    iconSize: [16, 16],
    iconAnchor: [8, 8],
  })
}

function redrawMarkers() {
  if (markerA) { markerA.remove(); markerA = null }
  if (markerB) { markerB.remove(); markerB = null }
  if (bearingLine) { bearingLine.remove(); bearingLine = null }

  if (site.pointA.value) {
    markerA = L.marker([site.pointA.value.lat, site.pointA.value.lon], {
      icon: iconFor('#2a78d6'), draggable: true, zIndexOffset: 1000,
    }).addTo(map)
    markerA.on('dragend', () => {
      const { lat, lng } = markerA.getLatLng()
      site.setPointA(lat, lng)
    })
  }
  if (site.pointB.value) {
    markerB = L.marker([site.pointB.value.lat, site.pointB.value.lon], {
      icon: iconFor('#eb6834'), draggable: true, zIndexOffset: 999,
    }).addTo(map)
    markerB.on('dragend', () => {
      const { lat, lng } = markerB.getLatLng()
      site.setPointB(lat, lng)
    })
    bearingLine = L.polyline(
      [[site.pointA.value.lat, site.pointA.value.lon], [site.pointB.value.lat, site.pointB.value.lon]],
      { color: '#eb6834', weight: 2, dashArray: '6 4' }
    ).addTo(map)
  }
}

function redrawFeatures() {
  if (featuresLayer) { featuresLayer.remove(); featuresLayer = null }
  const geojson = site.analysis.value?.osm_features
  if (!geojson) return
  featuresLayer = L.geoJSON(geojson, {
    style: (feature) => FEATURE_STYLE[feature.properties.category] || { color: '#94a3b8', weight: 1 },
  }).addTo(map)
  featuresLayer.bringToBack()
}

function redrawFootprint() {
  if (footprintLayer) { footprintLayer.remove(); footprintLayer = null }
  const fp = site.footprint.value
  if (!fp || !fp.available) return
  footprintLayer = L.layerGroup(
    fp.segments.map(seg => L.polyline(seg.coords, {
      color: '#7c3aed', weight: Math.max(3, Math.min(seg.width_m, 14)), opacity: 0.85,
    }).bindTooltip(`${seg.id} (${seg.width_m.toFixed(1)} m)`))
  ).addTo(map)
}

function initMap() {
  if (!mapContainer.value || map) return
  map = L.map(mapContainer.value, { zoomControl: true }).setView([50.4501, 30.5234], 14)
  L.tileLayer(
    'https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}',
    { attribution: 'Esri World Imagery', maxZoom: 19 }
  ).addTo(map)
  map.on('click', (e) => site.handleMapClick(e.latlng.lat, e.latlng.lng))
  redrawMarkers()
}

onMounted(() => nextTick(initMap))
onBeforeUnmount(() => map?.remove())

watch([site.pointA, site.pointB], redrawMarkers, { deep: true })
watch(site.analysis, () => { redrawFeatures() })
watch(site.footprint, () => { redrawFootprint() })

// The tab is v-show'd, not v-if'd, so this component mounts while hidden (display:none) and
// Leaflet computes a broken zero-size map. Force it to recompute once the tab actually becomes
// visible -- the standard fix for "Leaflet map in a hidden container" (see Leaflet's own docs).
watch(() => props.active, (isActive) => {
  if (isActive) nextTick(() => map?.invalidateSize())
})

// ── Results helpers ──────────────────────────────────────────────────────────

const criterionLabel = computed(() => ({
  construction_cost_mln: t.value.constructionCost,
  land_area_hectares:    t.value.landArea,
  throughput_vph:        t.value.throughput,
  safety_index:          t.value.safetyIndex,
}))

const alternatives = computed(() => props.dss.evalData.value?.results?.map(r => r.alternative_name) ?? [])

function applyToParams() {
  const a = site.analysis.value
  if (!a) return
  if (a.context !== props.dss.selectedContext.value) {
    const ok = window.confirm(t.value.confirmContextChange)
    if (!ok) return
    props.dss.selectedContext.value = a.context
  }
  props.dss.params.terrain = a.terrain
  props.dss.params.env_sensitivity = a.env_sensitivity
  props.dss.params.land_limit = Math.round(a.land_limit_ha)
}

function onAnalyseClick() {
  site.analyse(locale.value)
}

function onAlternativeChange(e) {
  const name = e.target.value
  if (name) site.loadFootprint(name, locale.value)
}

watch(locale, () => {
  if (site.analysis.value) site.analyse(locale.value)
})

const panel = computed(() => props.dark
  ? 'bg-white/[0.06] border border-white/10'
  : 'bg-white/60 border border-white/80 shadow-[0_8px_30px_rgb(0,0,0,0.04)]')
const inputClass = computed(() => props.dark
  ? 'bg-slate-700 border border-slate-600 text-slate-200'
  : 'bg-white/80 border border-black/10 text-slate-800')
const muted = computed(() => props.dark ? 'text-slate-400' : 'text-slate-500')
const strong = computed(() => props.dark ? 'text-slate-100' : 'text-slate-900')
</script>

<template>
  <div>
    <div class="rounded-[28px] backdrop-blur-2xl p-5 lg:p-6 mb-6" :class="panel">
      <h2 class="text-xl font-semibold tracking-tight mb-1" :class="strong">{{ t.siteAnalysisTitle }}</h2>
      <p class="text-xs mb-4" :class="muted">{{ t.siteAnalysisDesc }}</p>

      <div class="flex flex-wrap items-center gap-3 mb-3 text-xs">
        <span :class="muted">{{ site.hasPointA.value ? t.pointAPlaced : t.clickToPlaceHint }}</span>
        <button type="button"
                class="px-2.5 py-1 rounded-lg font-semibold border transition-colors"
                :class="site.settingDirection.value
                  ? (dark ? 'bg-orange-500/20 border-orange-400/60 text-orange-200' : 'bg-orange-500 border-orange-500 text-white')
                  : (dark ? 'border-slate-600 text-slate-300' : 'border-black/10 text-slate-600')"
                :disabled="!site.hasPointA.value"
                @click="site.settingDirection.value = !site.settingDirection.value">
          {{ site.settingDirection.value ? t.clickToSetDirection : t.setDirectionButton }}
        </button>
        <button type="button" class="px-2.5 py-1 rounded-lg font-semibold border" :class="dark ? 'border-slate-600 text-slate-400' : 'border-black/10 text-slate-500'"
                @click="site.reset()">
          {{ t.resetSiteButton }}
        </button>
        <label class="flex items-center gap-1.5 ml-auto">
          <span :class="muted">{{ t.radiusLabel }}</span>
          <input type="range" min="200" max="1500" step="50" v-model.number="site.radiusM.value"
                 class="ios-slider ios-slider--teal w-28" />
          <span class="font-semibold w-14 text-right" :class="strong">{{ site.radiusM.value }} m</span>
        </label>
        <button type="button"
                class="px-3 py-1.5 rounded-lg font-semibold text-white transition-colors disabled:opacity-40"
                :class="dark ? 'bg-teal-600 hover:bg-teal-500' : 'bg-teal-700 hover:bg-teal-600'"
                :disabled="!site.hasPointA.value || site.loading.value"
                @click="onAnalyseClick">
          {{ site.loading.value ? t.analysingLabel : t.analyseButton }}
        </button>
      </div>

      <div ref="mapContainer" class="w-full h-[420px] rounded-2xl z-0 mb-3"></div>

      <div class="flex flex-wrap gap-3 text-[0.7rem]" :class="muted">
        <span v-for="key in ['road', 'building', 'water', 'protected', 'residential']" :key="key" class="flex items-center gap-1">
          <span class="inline-block w-2.5 h-2.5 rounded-full" :style="{ background: FEATURE_STYLE[key].color }"></span>
          {{ t.legend[key] }}
        </span>
      </div>

      <div v-if="site.error.value" class="rounded-xl px-4 py-2.5 mt-3 text-sm"
           :class="dark ? 'bg-red-500/10 border border-red-500/30 text-red-200' : 'bg-red-50 border border-red-200 text-red-800'">
        {{ site.error.value }}
      </div>
    </div>

    <div v-if="site.analysis.value" class="rounded-[28px] backdrop-blur-2xl p-5 lg:p-6 mb-6" :class="panel">
      <div class="flex flex-wrap items-start justify-between gap-3 mb-4">
        <h3 class="text-base font-semibold" :class="strong">{{ t.resultsInferred }}</h3>
        <span class="px-3 py-1 rounded-full text-xs font-semibold"
              :class="site.analysis.value.context_confident
                ? (dark ? 'bg-teal-500/20 text-teal-200' : 'bg-teal-100 text-teal-800')
                : (dark ? 'bg-orange-500/20 text-orange-200' : 'bg-orange-100 text-orange-800')">
          {{ site.analysis.value.context_confident ? t.confidentBadge : t.lowConfidenceBadge }}
        </span>
      </div>

      <div class="grid grid-cols-2 sm:grid-cols-4 gap-3 mb-4 text-sm">
        <div><p class="text-xs" :class="muted">{{ t.taskContext }}</p><p class="font-semibold" :class="strong">{{ site.analysis.value.context }}</p></div>
        <div><p class="text-xs" :class="muted">{{ t.terrainType }}</p><p class="font-semibold" :class="strong">{{ t.terrainDisplay?.[site.analysis.value.terrain] ?? site.analysis.value.terrain }}</p></div>
        <div><p class="text-xs" :class="muted">{{ t.envSensitivity }}</p><p class="font-semibold" :class="strong">{{ t.envDisplay?.[site.analysis.value.env_sensitivity] ?? site.analysis.value.env_sensitivity }}</p></div>
        <div><p class="text-xs" :class="muted">{{ t.landLimit }}</p><p class="font-semibold" :class="strong">{{ site.analysis.value.land_limit_ha.toFixed(1) }} ha</p></div>
      </div>

      <div class="grid grid-cols-2 sm:grid-cols-3 gap-2 mb-4 text-xs" :class="muted">
        <span v-if="site.analysis.value.max_grade_pct !== null">{{ t.maxGradeLabel }}: {{ site.analysis.value.max_grade_pct.toFixed(1) }}%</span>
        <span v-if="site.analysis.value.nearest_water_m !== null">{{ t.nearestWaterLabel }}: {{ Math.round(site.analysis.value.nearest_water_m) }} m</span>
        <span>{{ t.residentialShareLabel }}: {{ (site.analysis.value.residential_share * 100).toFixed(0) }}%</span>
        <span>{{ t.buildingCountLabel }}: {{ site.analysis.value.building_count }}</span>
        <span>{{ t.buildingAreaLabel }}: {{ Math.round(site.analysis.value.building_area_m2).toLocaleString() }} m²</span>
        <span>{{ t.waterAreaLabel }}: {{ Math.round(site.analysis.value.water_area_m2).toLocaleString() }} m²</span>
      </div>

      <ul v-if="site.analysis.value.notes.length" class="text-xs space-y-1 mb-4" :class="dark ? 'text-orange-300' : 'text-orange-700'">
        <li v-for="(note, i) in site.analysis.value.notes" :key="i">⚠ {{ note }}</li>
      </ul>

      <button type="button" class="px-3 py-1.5 rounded-lg text-sm font-semibold text-white"
              :class="dark ? 'bg-teal-600 hover:bg-teal-500' : 'bg-teal-700 hover:bg-teal-600'"
              @click="applyToParams">
        {{ t.applyParamsButton }}
      </button>
    </div>

    <div v-if="site.analysis.value" class="rounded-[28px] backdrop-blur-2xl p-5 lg:p-6" :class="panel">
      <h3 class="text-base font-semibold mb-1" :class="strong">{{ t.footprintSectionTitle }}</h3>
      <p class="text-xs mb-3" :class="muted">{{ t.footprintSectionDesc }}</p>

      <label class="text-xs font-medium" :class="muted">
        {{ t.selectAlternativeLabel }}
        <select class="block mt-1 rounded-xl px-3 py-1.5 text-sm" :class="inputClass" @change="onAlternativeChange" :value="site.footprintAlternative.value ?? ''">
          <option value="" disabled>{{ t.selectAlternativeLabel }}</option>
          <option v-for="name in alternatives" :key="name" :value="name">{{ name }}</option>
        </select>
      </label>

      <p v-if="site.footprintLoading.value" class="text-xs mt-3" :class="muted">{{ t.analysingLabel }}</p>

      <template v-if="site.footprint.value && !site.footprintLoading.value">
        <p v-if="!site.footprint.value.available" class="text-xs mt-3" :class="muted">{{ site.footprint.value.message }}</p>
        <div v-else class="grid grid-cols-3 gap-3 mt-3 text-sm">
          <div><p class="text-xs" :class="muted">{{ t.buildingsAffectedLabel }}</p><p class="font-bold" :class="strong">{{ site.footprint.value.right_of_way.buildings_affected }}</p></div>
          <div><p class="text-xs" :class="muted">{{ t.demolishedAreaLabel }}</p><p class="font-bold" :class="strong">{{ Math.round(site.footprint.value.right_of_way.demolished_area_m2).toLocaleString() }} m²</p></div>
          <div><p class="text-xs" :class="muted">{{ t.estimatedCostLabel }}</p><p class="font-bold" :class="strong">${{ Math.round(site.footprint.value.right_of_way.estimated_cost_usd / 1000).toLocaleString() }}k</p></div>
        </div>
      </template>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, onBeforeUnmount, watch, nextTick } from 'vue'
import L from 'leaflet'
import { useLocale } from '../composables/useLocale.js'
import { useSiteAnalysis } from '../composables/useSiteAnalysis.js'
import Icon from './Icon.vue'
import { siteNoteKeyMap } from '../locales/backendKeys.js'

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

// The footprint is drawn like a road plan: every segment at its real paved width for the current
// zoom, with a white casing so it reads on aerial imagery (the basemap is the same in both themes).
// Ramps are purple so the movements stand out from the through carriageways.
const FOOTPRINT_STYLE = {
  mainline: { color: '#334155' },
  crossroad: { color: '#64748b' },
  ramp: { color: '#7c3aed' },
  road: { color: '#64748b' },
}
const FOOTPRINT_ORDER = ['mainline', 'crossroad', 'road', 'ramp']
const FOOTPRINT_CASING_PX = 3

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
      const { lat, lng } = markerA.getLatLng().wrap()
      site.setPointA(lat, lng)
    })
  }
  if (site.pointB.value) {
    markerB = L.marker([site.pointB.value.lat, site.pointB.value.lon], {
      icon: iconFor('#eb6834'), draggable: true, zIndexOffset: 999,
    }).addTo(map)
    markerB.on('dragend', () => {
      const { lat, lng } = markerB.getLatLng().wrap()
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

// Web Mercator ground resolution: metres per CSS pixel at this latitude and zoom.
function metresPerPixel(lat) {
  return 156543.03392 * Math.cos(lat * Math.PI / 180) / 2 ** map.getZoom()
}

function footprintWeight(seg, mpp) {
  return Math.max(2, Math.min(seg.width_m / mpp, 60))
}

function redrawFootprint() {
  if (footprintLayer) { footprintLayer.remove(); footprintLayer = null }
  const fp = site.footprint.value
  if (!fp || !fp.available || !map) return
  const mpp = metresPerPixel(map.getCenter().lat)
  const kindOf = seg => (FOOTPRINT_STYLE[seg.kind] ? seg.kind : 'road')
  const segments = [...fp.segments].sort(
    (a, b) => FOOTPRINT_ORDER.indexOf(kindOf(a)) - FOOTPRINT_ORDER.indexOf(kindOf(b))
  )
  const line = { lineCap: 'round', lineJoin: 'round', interactive: false }
  // All casings first, then all fills: where a ramp merges into a carriageway the fills run into
  // each other instead of being cut by a white edge.
  const casings = segments.map(seg => L.polyline(seg.coords, {
    ...line, color: '#ffffff', opacity: 0.9,
    weight: footprintWeight(seg, mpp) + 2 * FOOTPRINT_CASING_PX,
  }))
  // Tooltips get a text node: Leaflet would parse a string as HTML.
  const fills = segments.map(seg => L.polyline(seg.coords, {
    ...line, interactive: true, color: FOOTPRINT_STYLE[kindOf(seg)].color, opacity: 0.95,
    weight: footprintWeight(seg, mpp),
  }).bindTooltip(document.createTextNode(`${seg.id} (${seg.width_m.toFixed(1)} m)`), { sticky: true }))
  footprintLayer = L.layerGroup([...casings, ...fills]).addTo(map)
}

function initMap() {
  if (!mapContainer.value || map) return
  map = L.map(mapContainer.value, { zoomControl: true }).setView([50.4501, 30.5234], 14)
  L.tileLayer(
    'https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}',
    { attribution: 'Esri World Imagery', maxZoom: 19 }
  ).addTo(map)
  // wrap(): the world repeats sideways, so a click past the antimeridian can be outside ±180°.
  // Widths are real metres, so the footprint is redrawn whenever the zoom changes the scale.
  map.on('zoomend', redrawFootprint)
  map.on('click', (e) => {
    const { lat, lng } = e.latlng.wrap()
    site.handleMapClick(lat, lng)
  })
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
</script>

<template>
  <div class="space-y-3 md:space-y-4">
    <section class="card overflow-hidden">
      <div class="p-4">
        <h2 class="card-title">{{ t.siteAnalysisTitle }}</h2>
        <p class="card-desc">{{ t.siteAnalysisDesc }}</p>

        <div class="mt-4 grid grid-cols-2 items-center gap-2 text-xs md:flex md:flex-wrap">
          <span class="col-span-2 flex items-center gap-1.5 text-[13px] text-muted md:text-xs">
            <Icon name="map-pin" class="text-subtle" />
            {{ site.hasPointA.value ? t.pointAPlaced : t.clickToPlaceHint }}
          </span>
          <button type="button" class="btn leading-tight md:px-2.5 md:py-1 md:text-xs"
                  :class="site.settingDirection.value ? '!border-accent/30 !bg-accent-soft !text-accent-ink' : ''"
                  :aria-pressed="site.settingDirection.value"
                  :disabled="!site.hasPointA.value"
                  @click="site.settingDirection.value = !site.settingDirection.value">
            {{ site.settingDirection.value ? t.clickToSetDirection : t.setDirectionButton }}
          </button>
          <button type="button" class="btn-ghost md:px-2 md:py-1 md:text-xs" @click="site.reset()">
            <Icon name="refresh" />{{ t.resetSiteButton }}
          </button>
          <label class="col-span-2 flex min-h-11 items-center gap-3 md:ml-auto md:min-h-0 md:gap-2">
            <span class="text-[13px] text-muted md:text-xs">{{ t.radiusLabel }}</span>
            <input type="range" v-range-fill min="200" max="1500" step="50" v-model.number="site.radiusM.value"
                   class="ios-slider ios-slider--teal min-w-0 flex-1 md:w-28! md:flex-none" />
            <span class="num w-16 text-right text-[13px] font-medium text-fg md:w-14 md:text-xs">{{ site.radiusM.value }} m</span>
          </label>
          <button type="button" class="btn-primary col-span-2"
                  :disabled="!site.hasPointA.value || site.loading.value"
                  @click="onAnalyseClick">
            <span v-if="site.loading.value" class="spinner"></span>
            {{ site.loading.value ? (site.fetchingInBrowser.value ? t.analysingInBrowserLabel : t.analysingLabel) : t.analyseButton }}
          </button>
        </div>
      </div>

      <div ref="mapContainer"
           class="site-map z-0 h-[58svh] min-h-[320px] w-full border-y border-line !rounded-none md:h-[420px] md:min-h-0"></div>

      <div class="flex flex-wrap gap-x-4 gap-y-1.5 px-4 py-2.5 text-xs text-muted md:gap-y-1 md:text-[0.7rem]">
        <span v-for="key in ['road', 'building', 'water', 'protected', 'residential']" :key="key" class="flex items-center gap-1.5">
          <span class="inline-block h-2 w-2 shrink-0 rounded-full" :style="{ background: FEATURE_STYLE[key].color }"></span>
          {{ t.legend[key] }}
        </span>
        <template v-if="site.footprint.value?.available">
          <span v-for="key in ['mainline', 'crossroad', 'ramp']" :key="key" class="flex items-center gap-1.5">
            <span class="inline-block h-1.5 w-3.5 shrink-0 rounded-full ring-1 ring-line" :style="{ background: FOOTPRINT_STYLE[key].color }"></span>
            {{ t.legend[key] }}
          </span>
        </template>
      </div>

      <div v-if="site.error.value" class="px-4 pb-4">
        <div class="notice notice-bad">{{ site.error.value }}</div>
      </div>
    </section>

    <section v-if="site.analysis.value" class="card p-4">
      <div class="mb-4 flex flex-wrap items-start justify-between gap-3">
        <h3 class="card-title">{{ t.resultsInferred }}</h3>
        <span v-if="site.analysis.value.context_confident" class="badge-accent">
          <Icon name="check" />{{ t.confidentBadge }}
        </span>
        <span v-else class="badge !border-warn/25 !bg-warn-soft !text-warn">
          <Icon name="alert-triangle" />{{ t.lowConfidenceBadge }}
        </span>
      </div>

      <div class="mb-4 grid grid-cols-2 gap-3 sm:grid-cols-4">
        <div><p class="eyebrow">{{ t.taskContext }}</p><p class="mt-0.5 text-[13px] font-medium text-fg">{{ site.analysis.value.context }}</p></div>
        <div><p class="eyebrow">{{ t.terrainType }}</p><p class="mt-0.5 text-[13px] font-medium text-fg">{{ t.terrainDisplay?.[site.analysis.value.terrain] ?? site.analysis.value.terrain }}</p></div>
        <div><p class="eyebrow">{{ t.envSensitivity }}</p><p class="mt-0.5 text-[13px] font-medium text-fg">{{ t.envDisplay?.[site.analysis.value.env_sensitivity] ?? site.analysis.value.env_sensitivity }}</p></div>
        <div><p class="eyebrow">{{ t.landLimit }}</p><p class="num mt-0.5 text-[13px] font-medium text-fg">{{ site.analysis.value.land_limit_ha.toFixed(1) }} ha</p></div>
      </div>

      <!-- Phones: one label/value row per measure with hairlines between; wider: a compact grid. -->
      <div class="mb-4 grid grid-cols-1 divide-y divide-line rounded-lg border border-line bg-surface-2 px-3 text-[13px] text-muted
                  sm:grid-cols-3 sm:gap-x-3 sm:gap-y-1.5 sm:divide-y-0 sm:py-2.5 sm:text-xs">
        <span v-if="site.analysis.value.max_grade_pct !== null" class="stat-row">{{ t.maxGradeLabel }}<span class="max-sm:hidden">:</span> <span class="num text-fg">{{ site.analysis.value.max_grade_pct.toFixed(1) }}%</span></span>
        <span v-if="site.analysis.value.nearest_water_m !== null" class="stat-row">{{ t.nearestWaterLabel }}<span class="max-sm:hidden">:</span> <span class="num text-fg">{{ Math.round(site.analysis.value.nearest_water_m) }} m</span></span>
        <span class="stat-row">{{ t.residentialShareLabel }}<span class="max-sm:hidden">:</span> <span class="num text-fg">{{ (site.analysis.value.residential_share * 100).toFixed(0) }}%</span></span>
        <span class="stat-row">{{ t.buildingCountLabel }}<span class="max-sm:hidden">:</span> <span class="num text-fg">{{ site.analysis.value.building_count }}</span></span>
        <span class="stat-row">{{ t.buildingAreaLabel }}<span class="max-sm:hidden">:</span> <span class="num text-fg">{{ Math.round(site.analysis.value.building_area_m2).toLocaleString() }} m²</span></span>
        <span class="stat-row">{{ t.waterAreaLabel }}<span class="max-sm:hidden">:</span> <span class="num text-fg">{{ Math.round(site.analysis.value.water_area_m2).toLocaleString() }} m²</span></span>
      </div>

      <ul v-if="site.analysis.value.notes.length" class="notice notice-warn mb-4 space-y-1 text-xs">
        <li v-for="(note, i) in site.analysis.value.notes" :key="i" class="flex items-start gap-1.5">
          <Icon name="alert-triangle" class="mt-0.5" />{{ t.siteNotes[siteNoteKeyMap[note]] ?? note }}
        </li>
      </ul>

      <button type="button" class="btn-primary w-full md:w-auto" @click="applyToParams">
        {{ t.applyParamsButton }}
      </button>
    </section>

    <section v-if="site.analysis.value" class="card p-4">
      <h3 class="card-title">{{ t.footprintSectionTitle }}</h3>
      <p class="card-desc mb-3">{{ t.footprintSectionDesc }}</p>

      <label class="block md:max-w-xs">
        <span class="field-label">{{ t.selectAlternativeLabel }}</span>
        <select class="field" @change="onAlternativeChange" :value="site.footprintAlternative.value ?? ''">
          <option value="" disabled>{{ t.selectAlternativeLabel }}</option>
          <option v-for="name in alternatives" :key="name" :value="name">{{ name }}</option>
        </select>
      </label>

      <p v-if="site.footprintLoading.value" class="mt-3 flex items-center gap-2 text-xs text-muted">
        <span class="spinner"></span>{{ t.analysingLabel }}
      </p>
      <div v-else-if="site.footprintError.value" class="notice notice-bad mt-3">{{ site.footprintError.value }}</div>

      <template v-if="site.footprint.value && !site.footprintLoading.value">
        <p v-if="!site.footprint.value.available" class="mt-3 text-xs text-muted">{{ site.footprint.value.message }}</p>
        <div v-else class="mt-3 grid grid-cols-2 gap-3 sm:grid-cols-3">
          <div><p class="eyebrow">{{ t.buildingsAffectedLabel }}</p><p class="num mt-0.5 text-lg font-semibold text-fg">{{ site.footprint.value.right_of_way.buildings_affected }}</p></div>
          <div><p class="eyebrow">{{ t.demolishedAreaLabel }}</p><p class="num mt-0.5 text-lg font-semibold text-fg">{{ Math.round(site.footprint.value.right_of_way.demolished_area_m2).toLocaleString() }} m²</p></div>
          <div><p class="eyebrow">{{ t.estimatedCostLabel }}</p><p class="num mt-0.5 text-lg font-semibold text-fg">${{ Math.round(site.footprint.value.right_of_way.estimated_cost_usd / 1000).toLocaleString() }}k</p></div>
        </div>
      </template>
    </section>
  </div>
</template>

<style scoped>
@reference "../style.css";

.stat-row {
  @apply flex items-baseline justify-between gap-3 py-2 sm:block sm:py-0;
}

/* Leaflet's zoom buttons: macOS-style plate, and full-size tap targets on touch screens. */
.site-map :deep(.leaflet-bar) {
  @apply overflow-hidden rounded-lg border-0;
  box-shadow: var(--control-shadow);
}
.site-map :deep(.leaflet-bar a) {
  @apply border-line bg-control text-fg;
}
@media (pointer: coarse) {
  .site-map :deep(.leaflet-bar a) {
    width: 44px;
    height: 44px;
    line-height: 44px;
    font-size: 20px;
  }
}
</style>

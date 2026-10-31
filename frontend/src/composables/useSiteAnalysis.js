import { ref, reactive, computed } from 'vue'
import { analyseSite, getFootprint, errorText } from '../api.js'

// Point A = the interchange centre (required). Point B = an optional second click that sets the
// footprint's bearing (the direction from A to B becomes the interchange's primary-road axis).
const pointA = ref(null) // { lat, lon } | null
const pointB = ref(null) // { lat, lon } | null
const settingDirection = ref(false) // true while the next map click should set point B, not A

const radiusM = reactive({ value: 500 })

const analysis = ref(null) // last /api/site/analyse response
const loading = ref(false)
const error = ref('')

const footprintAlternative = ref(null)
const footprint = ref(null) // last /api/site/footprint response
const footprintLoading = ref(false)
const footprintError = ref('')

const hasPointA = computed(() => pointA.value !== null)
const hasBearing = computed(() => pointB.value !== null)

function requestBody() {
  const body = { lat: pointA.value.lat, lon: pointA.value.lon, radius_m: radiusM.value }
  if (pointB.value) {
    body.bearing_lat = pointB.value.lat
    body.bearing_lon = pointB.value.lon
  }
  return body
}

// The API takes |lat| ≤ 85 (about where the web map ends) and lon within ±180 (the map wraps
// clicks before they get here).
const clampLat = lat => Math.max(-85, Math.min(85, lat))

function setPointA(lat, lon) {
  pointA.value = { lat: clampLat(lat), lon }
  pointB.value = null
  analysis.value = null
  footprint.value = null
}

function setPointB(lat, lon) {
  pointB.value = { lat: clampLat(lat), lon }
  footprint.value = null
}

function handleMapClick(lat, lon) {
  // A plain click always (re)places the interchange centre (point A); the user must explicitly
  // toggle "set direction" before their next click sets the bearing point (point B).
  if (settingDirection.value) {
    setPointB(lat, lon)
    settingDirection.value = false
  } else {
    setPointA(lat, lon)
  }
}

function reset() {
  pointA.value = null
  pointB.value = null
  settingDirection.value = false
  analysis.value = null
  footprint.value = null
  error.value = ''
  footprintError.value = ''
}

async function analyse(lang = 'en') {
  if (!pointA.value) return
  loading.value = true
  error.value = ''
  try {
    analysis.value = await analyseSite(requestBody(), lang)
    if (footprintAlternative.value) await loadFootprint(footprintAlternative.value, lang)
  } catch (e) {
    error.value = errorText(e)
    analysis.value = null
  } finally {
    loading.value = false
  }
}

async function loadFootprint(alternativeName, lang = 'en') {
  if (!pointA.value) return
  footprintAlternative.value = alternativeName
  footprintLoading.value = true
  footprintError.value = ''
  try {
    footprint.value = await getFootprint({ alternative_name: alternativeName, ...requestBody() }, lang)
  } catch (e) {
    footprintError.value = errorText(e)
    footprint.value = null
  } finally {
    footprintLoading.value = false
  }
}

export function useSiteAnalysis() {
  return {
    pointA, pointB, settingDirection, radiusM,
    hasPointA, hasBearing,
    analysis, loading, error,
    footprintAlternative, footprint, footprintLoading, footprintError,
    setPointA, setPointB, handleMapClick, reset,
    analyse, loadFootprint,
  }
}

<script>
// Models are small (tens of kB). An in-flight request is cached as a promise per alternative
// name, shared by every viewer instance, and dropped on failure so that a retry works.
import { getModel3d } from '../api.js'

const modelCache = {
  map: new Map(),
  get(name) {
    let p = this.map.get(name)
    if (!p) {
      p = getModel3d(name)
      this.map.set(name, p)
      p.catch(() => { if (this.map.get(name) === p) this.map.delete(name) })
    }
    return p
  },
}
</script>

<script setup>
// Interactive 3D model of one interchange alternative. The backend computes every height and pier
// (GET /api/interchange/{name}/model3d); this component only draws it with three.js, which is
// loaded on first use so that it stays out of the main bundle. Geometry comes from the pure
// builders in composables/interchangeGeometry.js.
import { ref, computed, watch, onMounted, onBeforeUnmount } from 'vue'
import { useLocale } from '../composables/useLocale.js'
import { buildInterchange, buildCarGeometry, planTraffic, placeCar } from '../composables/interchangeGeometry.js'
import Icon from './Icon.vue'

const props = defineProps({
  name: { type: String, default: '' },
  dark: Boolean,
  active: { type: Boolean, default: true },
  color: { type: String, default: '' },
})
const emit = defineEmits(['loaded'])

const { t } = useLocale()

// ── State ───────────────────────────────────────────────────────────────────
const root = ref(null)
const canvas = ref(null)
const loading = ref(false)
const hasModel = ref(false)
const failure = ref('')            // '' | 'webgl' | 'load'
const paused = ref(false)
const reduced = ref(false)
const fsSupported = ref(false)
const isFullscreen = ref(false)

const message = computed(() =>
  failure.value === 'webgl' ? t.value.viewer3dNoWebgl
    : failure.value === 'load' ? t.value.viewer3dLoadFailed : '')

// Everything below is plain (non-reactive) state: three.js objects must not be proxied.
let THREE = null
let OrbitControls = null
let renderer = null
let scene = null
let camera = null
let controls = null
let sun = null
let hemi = null
let mats = null
let fade = null                    // uniforms of the radial fade shared by every material
let fadeBroken = false
let current = null                 // { group, geometries, cars, bodyMesh, lampMesh, extent }
let requestId = 0
let disposed = false
let ready = null
let size = { w: 0, h: 0 }
let onScreen = false
let docVisible = true
let ctxLost = false
let looping = false
let rafId = 0
let simTime = 0
let lastTick = 0
let ro = null
let io = null
let mq = null
const carOut = new Float64Array(8)

// ── Palettes ────────────────────────────────────────────────────────────────
const PALETTE = {
  light: {
    bg: '#d5e0ea', ground: '#a7b6a1', asphalt: '#3c3f45', concrete: '#c8c8c2', marks: '#f5f5f0',
    hemiSky: '#ffffff', hemiGround: '#8d9a8a', hemi: 1.5, sun: '#fff4e0', sunI: 2.3,
  },
  dark: {
    bg: '#0a0f1d', ground: '#141b27', asphalt: '#1c1f26', concrete: '#656b76', marks: '#cfd3da',
    hemiSky: '#5a6f9a', hemiGround: '#1a2030', hemi: 0.9, sun: '#9db4ff', sunI: 0.75,
  },
}
const CAR_COLOURS = ['#e8eaee', '#1f2937', '#b91c1c', '#1d4ed8', '#f59e0b', '#0f766e', '#94a3b8']

// Roads that leave the interchange are drawn on to REACH x extent, and everything fades into the
// background between FADE_FROM and FADE_TO x extent from the centre, so no road end and no edge
// of the ground is ever visible, whatever the camera does.
const REACH = 2.0
const TRAFFIC_SPEED = 1.5          // the traffic runs this much faster than real time
const FADE_FROM = 1.15
const FADE_TO = 1.8

// Fade a material into the background by distance from the scene centre (not from the camera, as
// fog does). Injected into the built-in shaders; if a marker is missing in some future three, or
// the program fails to compile, the material is left exactly as three ships it.
function withFade(material) {
  material.onBeforeCompile = (shader) => {
    const vs = shader.vertexShader, fs = shader.fragmentShader
    const ok = vs.includes('#include <common>') && vs.includes('#include <project_vertex>')
      && fs.includes('#include <common>') && fs.includes('#include <dithering_fragment>')
    if (!ok || fadeBroken) return
    shader.uniforms.uFadeRange = fade.range
    shader.uniforms.uFadeColor = fade.color
    shader.vertexShader = vs
      .replace('#include <common>', '#include <common>\nvarying vec2 vFadeXZ;')
      .replace('#include <project_vertex>', `#include <project_vertex>
        vec4 fadeWorld = vec4( transformed, 1.0 );
        #ifdef USE_INSTANCING
          fadeWorld = instanceMatrix * fadeWorld;
        #endif
        vFadeXZ = ( modelMatrix * fadeWorld ).xz;`)
    shader.fragmentShader = fs
      .replace('#include <common>', '#include <common>\nvarying vec2 vFadeXZ;\nuniform vec2 uFadeRange;\nuniform vec3 uFadeColor;')
      .replace('#include <dithering_fragment>', `#include <dithering_fragment>
        gl_FragColor.rgb = mix( gl_FragColor.rgb, uFadeColor, smoothstep( uFadeRange.x, uFadeRange.y, length( vFadeXZ ) ) );`)
  }
  material.customProgramCacheKey = () => (fadeBroken ? 'plain' : 'radial-fade')
  return material
}

function onShaderError() {
  if (fadeBroken || !mats) return
  fadeBroken = true                 // recompile every material without the fade
  for (const m of Object.values(mats)) m.needsUpdate = true
  requestRender()
}

function applyTheme() {
  if (!scene || !mats) return
  const p = props.dark ? PALETTE.dark : PALETTE.light
  scene.background.set(p.bg)
  scene.fog.color.set(p.bg)
  // The shader mixes after the output colour space conversion, so the uniform holds sRGB values.
  fade.color.value.set(p.bg).convertLinearToSRGB()
  mats.ground.color.set(p.ground)
  mats.asphalt.color.set(p.asphalt)
  mats.concrete.color.set(p.concrete)
  mats.marks.color.set(p.marks)
  hemi.color.set(p.hemiSky); hemi.groundColor.set(p.hemiGround); hemi.intensity = p.hemi
  sun.color.set(p.sun); sun.intensity = p.sunI
  if (current?.lampMesh) current.lampMesh.visible = props.dark
  requestRender()
}

// ── Setup ───────────────────────────────────────────────────────────────────
async function init() {
  try {
    const [three, orbit] = await Promise.all([
      import('three'),
      import('three/examples/jsm/controls/OrbitControls.js'),
    ])
    if (disposed) return
    THREE = three
    OrbitControls = orbit.OrbitControls
    renderer = new THREE.WebGLRenderer({
      canvas: canvas.value, antialias: true, powerPreference: 'high-performance',
    })
  } catch {
    failure.value = 'webgl'
    renderer = null
    return
  }
  renderer.shadowMap.enabled = true
  // PCFSoftShadowMap was removed in recent three; PCFShadowMap is the filtered one.
  renderer.shadowMap.type = THREE.PCFShadowMap
  canvas.value.addEventListener('webglcontextlost', onContextLost)
  canvas.value.addEventListener('webglcontextrestored', onContextRestored)

  scene = new THREE.Scene()
  scene.background = new THREE.Color()
  scene.fog = new THREE.Fog('#ffffff', 500, 2000)
  camera = new THREE.PerspectiveCamera(40, 1, 5, 6000)

  hemi = new THREE.HemisphereLight('#ffffff', '#888888', 1)
  sun = new THREE.DirectionalLight('#ffffff', 2)
  sun.castShadow = true
  sun.shadow.bias = -0.0004
  sun.shadow.normalBias = 0.5
  const coarse = window.matchMedia?.('(pointer: coarse)').matches
  const map = coarse ? 1024 : 2048
  sun.shadow.mapSize.set(map, map)
  scene.add(hemi, sun, sun.target)

  const lambert = (extra = {}) => new THREE.MeshLambertMaterial(extra)
  mats = {
    ground: lambert({ polygonOffset: true, polygonOffsetFactor: 1, polygonOffsetUnits: 1 }),
    asphalt: lambert({ side: THREE.DoubleSide, polygonOffset: true, polygonOffsetFactor: -1, polygonOffsetUnits: -1 }),
    marks: lambert({ side: THREE.DoubleSide, polygonOffset: true, polygonOffsetFactor: -3, polygonOffsetUnits: -3 }),
    concrete: lambert({ side: THREE.DoubleSide }),
    car: lambert({ vertexColors: true }),
    lamp: new THREE.MeshBasicMaterial({ vertexColors: true }),
  }
  fade = { range: { value: new THREE.Vector2(1e6, 2e6) }, color: { value: new THREE.Color() } }
  Object.values(mats).forEach(withFade)
  renderer.debug.onShaderError = onShaderError

  controls = new OrbitControls(camera, canvas.value)
  controls.enableDamping = !reduced.value
  controls.dampingFactor = 0.08
  controls.maxPolarAngle = Math.PI * 0.49
  controls.screenSpacePanning = false
  controls.autoRotate = !reduced.value
  controls.autoRotateSpeed = 0.7
  controls.addEventListener('start', () => { controls.autoRotate = false })
  controls.addEventListener('change', () => { if (!looping) requestRender() })

  applyTheme()
  onResize()
}

function onContextLost(e) { e.preventDefault(); ctxLost = true; syncLoop() }
function onContextRestored() { ctxLost = false; syncLoop(); requestRender() }

// ── Building a model ────────────────────────────────────────────────────────
function makeGeometry(data) {
  const g = new THREE.BufferGeometry()
  g.setAttribute('position', new THREE.BufferAttribute(data.positions, 3))
  if (data.colors) g.setAttribute('color', new THREE.BufferAttribute(data.colors, 3))
  g.setIndex(new THREE.BufferAttribute(data.indices, 1))
  g.computeVertexNormals()
  return g
}

function buildModel(model) {
  const geometries = []
  const group = new THREE.Group()
  const extent = model.extent_m || 400
  const add = (data, material, { cast = false, receive = true } = {}) => {
    const g = makeGeometry(data)
    geometries.push(g)
    const m = new THREE.Mesh(g, material)
    m.castShadow = cast
    m.receiveShadow = receive
    group.add(m)
    return m
  }

  const ground = new THREE.CircleGeometry(extent * 3, 72)
  ground.rotateX(-Math.PI / 2)
  geometries.push(ground)
  const groundMesh = new THREE.Mesh(ground, mats.ground)
  groundMesh.position.y = -0.05
  groundMesh.receiveShadow = true
  group.add(groundMesh)

  const built = buildInterchange(model, { reach: extent * REACH })
  add(built.asphalt, mats.asphalt)
  add(built.markings, mats.marks)
  add(built.concrete, mats.concrete, { cast: true })

  // Traffic: one instanced body mesh and one instanced lamp mesh sharing the same matrices.
  const cars = planTraffic(model, { colours: CAR_COLOURS.length, reach: extent * REACH })
  let bodyMesh = null, lampMesh = null
  if (cars.length) {
    const car = buildCarGeometry()
    const bg = makeGeometry(car.body), lg = makeGeometry(car.lamps)
    geometries.push(bg, lg)
    bodyMesh = new THREE.InstancedMesh(bg, mats.car, cars.length)
    lampMesh = new THREE.InstancedMesh(lg, mats.lamp, cars.length)
    bodyMesh.frustumCulled = false
    lampMesh.frustumCulled = false
    lampMesh.visible = props.dark
    const c = new THREE.Color()
    cars.forEach((car2, i) => bodyMesh.setColorAt(i, c.set(CAR_COLOURS[car2.colour])))
    bodyMesh.instanceColor.needsUpdate = true
    group.add(bodyMesh, lampMesh)
  }

  const next = { group, geometries, cars, bodyMesh, lampMesh, extent }
  return next
}

function disposeModel(m) {
  if (!m) return
  scene.remove(m.group)
  for (const g of m.geometries) g.dispose()
  m.bodyMesh?.dispose()
  m.lampMesh?.dispose()
}

function placeSceneFor(extent) {
  fade.range.value.set(extent * FADE_FROM, extent * FADE_TO)
  scene.fog.near = extent * 2.0
  scene.fog.far = extent * 4.4
  camera.far = extent * 14
  const s = sun.shadow.camera
  const r = extent * 1.25
  s.left = -r; s.right = r; s.top = r; s.bottom = -r
  s.near = 1; s.far = extent * 6
  s.updateProjectionMatrix()
  sun.position.set(extent * 0.9, extent * 1.8, extent * 0.6)
  sun.target.position.set(0, 0, 0)
  controls.minDistance = Math.max(30, extent * 0.12)
  controls.maxDistance = extent * 5
}

function resetView(animate = false) {
  if (!controls || !current) return
  const d = current.extent * 2.3
  const az = 0.62, el = 0.62     // radians: a 3/4 aerial view
  controls.target.set(0, 5, 0)
  camera.position.set(
    d * Math.sin(az) * Math.cos(el),
    5 + d * Math.sin(el),
    d * Math.cos(az) * Math.cos(el),
  )
  camera.updateProjectionMatrix()
  controls.update()
  if (animate) requestRender()
}

function applyModel(model) {
  const next = buildModel(model)
  const old = current
  scene.add(next.group)
  current = next
  disposeModel(old)           // the old frame stays on screen until this swap: no blank flash
  placeSceneFor(next.extent)
  resetView()
  updateCars(simTime)
  applyTheme()
  hasModel.value = true
  requestRender()
}

// ── Traffic ─────────────────────────────────────────────────────────────────
function updateCars(time) {
  const m = current
  if (!m || !m.bodyMesh) return
  const arr = m.bodyMesh.instanceMatrix.array
  const cars = m.cars
  const out = carOut
  for (let k = 0; k < cars.length; k++) {
    // A car shrinks to nothing where its lane ends inside the model (a ramp terminal), and stays
    // that way until its next turn on the lane.
    const sc = Math.max(0.001, placeCar(cars[k], time * TRAFFIC_SPEED, out))
    // Basis: x = forward (with pitch), y = up, z = right, so that x cross y = z.
    const fx = out[3], fy = out[4], fz = out[5]
    const rx = -out[6], rz = -out[7]
    const ux = -rz * fy, uy = rz * fx - rx * fz, uz = rx * fy
    const o = k * 16
    arr[o] = fx * sc; arr[o + 1] = fy * sc; arr[o + 2] = fz * sc; arr[o + 3] = 0
    arr[o + 4] = ux * sc; arr[o + 5] = uy * sc; arr[o + 6] = uz * sc; arr[o + 7] = 0
    arr[o + 8] = rx * sc; arr[o + 9] = 0; arr[o + 10] = rz * sc; arr[o + 11] = 0
    arr[o + 12] = out[0]; arr[o + 13] = out[1] + 0.06; arr[o + 14] = out[2]; arr[o + 15] = 1
  }
  m.bodyMesh.instanceMatrix.needsUpdate = true
  m.lampMesh.instanceMatrix.array.set(arr)
  m.lampMesh.instanceMatrix.needsUpdate = true
}

// ── Loop ────────────────────────────────────────────────────────────────────
function draw() {
  if (!renderer || !current || size.w === 0 || size.h === 0 || ctxLost) return
  controls.update()
  renderer.render(scene, camera)
}

function tick() {
  const now = performance.now()
  const dt = Math.min(0.1, (now - lastTick) / 1000)
  lastTick = now
  if (!paused.value) { simTime += dt; updateCars(simTime) }
  controls.update(dt)
  if (current && size.w > 0 && size.h > 0) renderer.render(scene, camera)
}

function requestRender() {
  if (rafId || looping || !renderer) return
  rafId = requestAnimationFrame(() => {
    rafId = 0
    if (props.active && onScreen && docVisible) draw()
  })
}

// The loop runs only while the pane is visible, the canvas is on screen and has a size.
function syncLoop() {
  if (!renderer) return
  const run = props.active && onScreen && docVisible && !ctxLost && size.w > 0 && size.h > 0
  if (run && !reduced.value) {
    if (!looping) { lastTick = performance.now(); renderer.setAnimationLoop(tick); looping = true }
  } else {
    if (looping) { renderer.setAnimationLoop(null); looping = false }
    if (run) requestRender()
  }
}

function onResize() {
  const el = root.value
  if (!el) return
  const w = el.clientWidth, h = el.clientHeight
  size = { w, h }
  if (renderer && w > 0 && h > 0) {
    renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2))
    renderer.setSize(w, h, false)
    camera.aspect = w / h
    camera.updateProjectionMatrix()
  }
  syncLoop()
  requestRender()
}

function onVisibility() { docVisible = document.visibilityState !== 'hidden'; syncLoop() }
function onFullscreenChange() { isFullscreen.value = document.fullscreenElement === root.value }
function onMotionChange() {
  reduced.value = !!mq?.matches
  if (reduced.value) paused.value = true
  if (controls) { controls.enableDamping = !reduced.value; if (reduced.value) controls.autoRotate = false }
  syncLoop()
}

function toggleFullscreen() {
  const el = root.value
  if (!el) return
  if (document.fullscreenElement === el) document.exitFullscreen?.()
  else el.requestFullscreen?.().catch(() => {})
}

// ── Loading a model ─────────────────────────────────────────────────────────
async function load(name) {
  if (!name) return
  const id = ++requestId
  loading.value = true
  if (failure.value === 'load') failure.value = ''
  try {
    const request = modelCache.get(name)
    await ready                      // settles in either case; sets `renderer` or leaves it null
    if (!renderer && !disposed) { if (id === requestId) failure.value = 'webgl'; return }
    const model = await request
    if (id !== requestId || disposed) return
    applyModel(model)
    emit('loaded', model)
  } catch {
    if (id !== requestId || disposed) return
    failure.value = 'load'
  } finally {
    if (id === requestId) loading.value = false
  }
}

watch(() => props.name, n => load(n))
watch(() => props.dark, applyTheme)
watch(() => props.active, () => { syncLoop(); requestRender() })

onMounted(() => {
  mq = window.matchMedia?.('(prefers-reduced-motion: reduce)') ?? null
  reduced.value = !!mq?.matches
  paused.value = reduced.value
  mq?.addEventListener?.('change', onMotionChange)
  fsSupported.value = !!root.value?.requestFullscreen
  document.addEventListener('fullscreenchange', onFullscreenChange)
  document.addEventListener('visibilitychange', onVisibility)
  docVisible = document.visibilityState !== 'hidden'

  ro = new ResizeObserver(onResize)
  ro.observe(root.value)
  if ('IntersectionObserver' in window) {
    io = new IntersectionObserver((entries) => {
      onScreen = entries[entries.length - 1].isIntersecting
      syncLoop(); requestRender()
    })
    io.observe(root.value)
  } else {
    onScreen = true
  }
  ready = init()
  load(props.name)
})

onBeforeUnmount(() => {
  disposed = true
  requestId++
  if (rafId) cancelAnimationFrame(rafId)
  ro?.disconnect()
  io?.disconnect()
  mq?.removeEventListener?.('change', onMotionChange)
  document.removeEventListener('fullscreenchange', onFullscreenChange)
  document.removeEventListener('visibilitychange', onVisibility)
  if (document.fullscreenElement === root.value) document.exitFullscreen?.()
  if (renderer) {
    renderer.setAnimationLoop(null)
    canvas.value?.removeEventListener('webglcontextlost', onContextLost)
    canvas.value?.removeEventListener('webglcontextrestored', onContextRestored)
    controls?.dispose()
    if (current) disposeModel(current)
    if (mats) Object.values(mats).forEach(m => m.dispose())
    sun?.shadow?.dispose?.()
    renderer.dispose()
    renderer.forceContextLoss()
  }
  current = null; renderer = null; scene = null; camera = null; controls = null
})

defineExpose({ resetView })
</script>

<template>
  <div ref="root" class="relative h-full w-full overflow-hidden bg-surface-2" role="group" :aria-label="t.viewer3dLabel">
    <canvas v-show="!failure || hasModel" ref="canvas" class="block h-full w-full outline-none"
            role="img" :aria-label="t.viewer3dLabel"></canvas>

    <!-- First load: centred spinner. Later switches keep the old frame and show a small one. -->
    <div v-if="loading && !hasModel" class="absolute inset-0 flex items-center justify-center gap-2 text-[13px] text-muted">
      <span class="spinner" aria-hidden="true"></span>{{ t.viewer3dLoading }}
    </div>

    <div v-if="message" class="absolute inset-x-3 top-3 z-10 md:inset-x-auto md:left-3 md:max-w-md">
      <p class="notice notice-warn" role="alert">{{ message }}</p>
    </div>

    <template v-if="failure !== 'webgl'">
      <!-- Name chip -->
      <div v-if="name" class="pointer-events-none absolute bottom-3 left-3 flex max-w-[60%] items-center gap-1.5 rounded-full border border-line bg-surface-solid/85 px-2.5 py-1 text-xs font-medium backdrop-blur">
        <span class="h-2 w-2 shrink-0 rounded-full" :style="{ background: color || 'var(--accent)' }" aria-hidden="true"></span>
        <span class="truncate">{{ name }}</span>
        <span v-if="loading && hasModel" class="spinner !h-3 !w-3" aria-hidden="true"></span>
      </div>
      <p class="pointer-events-none absolute bottom-3 right-3 hidden max-w-[40%] rounded-full bg-surface-solid/70 px-2.5 py-1 text-[0.7rem] text-muted backdrop-blur lg:block">
        {{ t.viewer3dHint }}
      </p>

      <!-- Controls -->
      <div class="absolute right-3 top-3 flex items-center gap-0.5 rounded-full border border-line bg-surface-solid/85 p-0.5 backdrop-blur">
        <button type="button" class="icon-btn" :aria-label="t.viewer3dResetView" :title="t.viewer3dResetView" @click="resetView(true)">
          <Icon name="rotate-ccw" class="text-[15px]" />
        </button>
        <button v-if="!reduced" type="button" class="icon-btn" :aria-pressed="paused"
                :aria-label="paused ? t.viewer3dPlayTraffic : t.viewer3dPauseTraffic"
                :title="paused ? t.viewer3dPlayTraffic : t.viewer3dPauseTraffic" @click="paused = !paused">
          <Icon :name="paused ? 'play' : 'pause'" class="text-[15px]" />
        </button>
        <button v-if="fsSupported" type="button" class="icon-btn"
                :aria-label="isFullscreen ? t.viewer3dExitFullscreen : t.viewer3dFullscreen"
                :title="isFullscreen ? t.viewer3dExitFullscreen : t.viewer3dFullscreen" @click="toggleFullscreen">
          <Icon :name="isFullscreen ? 'minimize' : 'maximize'" class="text-[15px]" />
        </button>
      </div>
    </template>
  </div>
</template>

<script setup>
import { computed, reactive, ref, watch } from 'vue'
import PlotlyChart from './PlotlyChart.vue'
import { useLocale } from '../composables/useLocale.js'
import { useModel, ALLOWED_EXTENSIONS, MAX_UPLOAD_BYTES } from '../composables/useModel.js'
import { CRITERION_KEYS } from '../composables/useDSS.js'
import { MODEL_COLORS, SURFACE, chartInk } from '../chartPalette.js'

const props = defineProps({
  dss: Object,
  active: Boolean,
  dark: Boolean,
})

const { t, locale } = useLocale()
const model = useModel()
const status = model.status
const prediction = model.prediction

const chartCriterion = ref(CRITERION_KEYS[0])
const coefCriterion = ref(CRITERION_KEYS[0])
const expandedWarnings = reactive(new Set())
const dragActive = ref(false)
const fileInput = ref(null)
const localError = ref('')

// ── Loading & prediction ─────────────────────────────────────────────────────
// Like the robustness tab: work only while visible, remember that inputs changed meanwhile.
let stale = true
let timer = null

function schedulePredict(delay = 300) {
  stale = true
  if (!props.active) return
  clearTimeout(timer)
  timer = setTimeout(() => {
    stale = false
    model.predict(props.dss, locale.value)
  }, delay)
}

watch(() => props.active, a => {
  if (!a) return
  model.load()
  if (stale || !prediction.value) schedulePredict(0)
}, { immediate: true })

watch(
  [() => props.dss.selectedContext.value, () => ({ ...props.dss.params }), locale],
  () => schedulePredict(),
  { deep: true },
)

// Upload / delete / retrain refit the model, so the predictions are out of date.
watch(() => status.value?.revision, (now, before) => {
  if (before && now !== before) schedulePredict(0)
})

// ── Formatting helpers ──────────────────────────────────────────────────────
// Locale strings use {name} placeholders filled here (the app reads messages directly).
const fmt = (str, vars) => (str ?? '').replace(/\{(\w+)\}/g, (m, k) => (k in vars ? vars[k] : m))
const numLocale = computed(() => (locale.value === 'uk' ? 'uk-UA' : 'en-US'))
const DECIMALS = { construction_cost_mln: 1, land_area_hectares: 1, throughput_vph: 0, safety_index: 2 }
const D3_FORMAT = { construction_cost_mln: ',.1f', land_area_hectares: ',.1f', throughput_vph: ',.0f', safety_index: '.2f' }

function num(v, digits) {
  if (v == null || Number.isNaN(v)) return '—'
  // Typographic minus, matching the signed percentages.
  return v.toLocaleString(numLocale.value, { minimumFractionDigits: digits, maximumFractionDigits: digits })
    .replace(/^-/, '−')
}
const fmtValue = (k, v) => num(v, DECIMALS[k])
const pct = (v, d = 1) => (v == null ? '—' : `${num(v * 100, d)}%`)
const signedPct = (v, d = 1) => (v == null ? '—' : `${v > 0 ? '+' : v < 0 ? '−' : ''}${num(Math.abs(v) * 100, d)}%`)

function fmtSize(bytes) {
  const u = t.value.modelSizeUnits
  if (bytes < 1024) return `${bytes} ${u.b}`
  if (bytes < 1024 * 1024) return `${num(bytes / 1024, 1)} ${u.kb}`
  return `${num(bytes / (1024 * 1024), 1)} ${u.mb}`
}

const criterionLabel = computed(() => ({
  construction_cost_mln: t.value.constructionCost,
  land_area_hectares:    t.value.landArea,
  throughput_vph:        t.value.throughput,
  safety_index:          t.value.safetyIndex,
}))

const levelPct = computed(() =>
  Math.round((status.value?.interval_level ?? prediction.value?.interval_level ?? 0.9) * 100))

// ── Status cards ─────────────────────────────────────────────────────────────
const documents = computed(() => status.value?.documents ?? [])
const totalBytes = computed(() => documents.value.reduce((s, d) => s + (d.size_bytes ?? 0), 0))
const docsWithWarnings = computed(() => documents.value.filter(d => d.warnings?.length).length)
const nRecords = computed(() => status.value?.n_records ?? 0)
const nSynthetic = computed(() => status.value?.n_synthetic ?? 0)
const trainedAt = computed(() => {
  const iso = status.value?.trained_at
  if (!iso) return null
  return new Date(iso).toLocaleString(numLocale.value, { dateStyle: 'medium', timeStyle: 'medium' })
})
const trainMs = computed(() => {
  const ms = status.value?.train_ms ?? 0
  return num(ms, ms < 10 ? 1 : 0)
})

// ── Document manager ─────────────────────────────────────────────────────────
const formatsText = ALLOWED_EXTENSIONS.join(' ')
const maxMb = MAX_UPLOAD_BYTES / (1024 * 1024)

function checkFile(file) {
  const dot = file.name.lastIndexOf('.')
  const ext = dot >= 0 ? file.name.slice(dot).toLowerCase() : ''
  if (!ALLOWED_EXTENSIONS.includes(ext)) return fmt(t.value.modelBadExtension, { name: file.name, formats: formatsText })
  if (file.size === 0) return fmt(t.value.modelEmptyFile, { name: file.name })
  if (file.size > MAX_UPLOAD_BYTES) return fmt(t.value.modelTooLarge, { name: file.name, size: maxMb })
  return ''
}

async function uploadFiles(files) {
  localError.value = ''
  model.clearError()
  const problems = []
  for (const file of files) {
    const problem = checkFile(file)
    if (problem) {
      problems.push(problem)
      localError.value = problems.join('\n')
      continue
    }
    const result = await model.upload(file)
    if (result === 'conflict' && window.confirm(fmt(t.value.modelOverwriteConfirm, { name: file.name }))) {
      await model.upload(file, true)
    }
  }
}

function pickFiles() {
  if (!model.uploading.value) fileInput.value?.click()
}

function onFileInput(e) {
  const files = [...(e.target.files ?? [])]
  e.target.value = '' // so choosing the same file again still fires change
  if (files.length) uploadFiles(files)
}

function onDrop(e) {
  dragActive.value = false
  const files = [...(e.dataTransfer?.files ?? [])]
  if (files.length) uploadFiles(files)
}

function removeDocument(name) {
  if (window.confirm(fmt(t.value.modelDeleteConfirm, { name }))) {
    expandedWarnings.delete(name)
    model.remove(name)
  }
}

function toggleWarnings(name) {
  if (expandedWarnings.has(name)) expandedWarnings.delete(name)
  else expandedWarnings.add(name)
}

const busy = computed(() => model.loading.value || model.uploading.value)
const retraining = ref(false)

async function retrain() {
  retraining.value = true
  try {
    await model.retrain()
  } finally {
    retraining.value = false
  }
}

// ── Accuracy ─────────────────────────────────────────────────────────────────
const accuracyRows = computed(() => CRITERION_KEYS.map(k => ({ key: k, ...(status.value?.criteria?.[k] ?? {}) })))

function modelBetter(row) {
  if (row.loo_mape_model == null || row.loo_mape_expert == null) return null
  return row.loo_mape_model < row.loo_mape_expert
}

// ── Chart: expert vs model with prediction intervals ─────────────────────────
const ink = computed(() => chartInk(props.dark))
const surface = computed(() => SURFACE[props.dark ? 'dark' : 'light'])
const colors = computed(() => MODEL_COLORS[props.dark ? 'dark' : 'light'])
const predictionRows = computed(() => (prediction.value?.alternatives ?? []).map(a => ({
  name: a.name, ...a.values[chartCriterion.value],
})))

const intervalChart = computed(() => {
  const k = chartCriterion.value
  const rows = predictionRows.value
  const unit = t.value.modelUnits[k]
  const f = D3_FORMAT[k]
  const names = rows.map(r => r.name)
  const intervalLabel = fmt(t.value.modelIntervalLabel, { level: levelPct.value })
  return {
    data: [
      {
        type: 'scatter',
        mode: 'markers',
        name: t.value.modelExpertSeries,
        x: names,
        y: rows.map(r => r.expert),
        marker: { symbol: 'diamond', size: 13, color: colors.value.expert, line: { color: surface.value, width: 2 } },
        hovertemplate: `<b>%{x}</b><br>${t.value.modelExpertSeries}: %{y:${f}} ${unit}<extra></extra>`,
      },
      {
        type: 'scatter',
        mode: 'markers',
        name: `${t.value.modelSeries} · ${intervalLabel}`,
        x: names,
        y: rows.map(r => r.predicted),
        marker: { symbol: 'circle', size: 12, color: colors.value.model, line: { color: surface.value, width: 2 } },
        error_y: {
          type: 'data', symmetric: false,
          array: rows.map(r => r.high - r.predicted),
          arrayminus: rows.map(r => r.predicted - r.low),
          color: colors.value.model, thickness: 2, width: 8,
        },
        customdata: rows.map(r => [r.low, r.high]),
        hovertemplate: `<b>%{x}</b><br>${t.value.modelSeries}: %{y:${f}} ${unit}`
          + `<br>${intervalLabel}: %{customdata[0]:${f}} – %{customdata[1]:${f}}<extra></extra>`,
      },
    ],
    layout: {
      paper_bgcolor: 'rgba(0,0,0,0)', plot_bgcolor: 'rgba(0,0,0,0)',
      font: { family: 'Inter, system-ui, sans-serif', color: ink.value.text, size: 12 },
      hoverlabel: { font: { family: 'Inter, system-ui, sans-serif' } },
      height: 360,
      autosize: true,
      scattermode: 'group',
      scattergap: 0.75,
      margin: { l: 64, r: 16, t: 8, b: 80 },
      xaxis: { tickfont: { size: 12, color: ink.value.text } },
      yaxis: {
        title: { text: `${criterionLabel.value[k]} (${unit})`, font: { size: 12 } },
        gridcolor: ink.value.grid, tickfont: { color: ink.value.muted }, zeroline: false,
      },
      legend: { orientation: 'h', y: -0.18, x: 0, bgcolor: 'rgba(0,0,0,0)' },
    },
  }
})

// ── Coefficients ─────────────────────────────────────────────────────────────
function featureLabel(feature) {
  const i = feature.indexOf(':')
  if (i < 0) return t.value.modelFeatures?.[feature] ?? feature
  const group = feature.slice(0, i)
  const value = feature.slice(i + 1)
  if (group === 'type') return `${t.value.modelFeatureType}: ${value}`
  if (group === 'terrain') return `${t.value.terrainType}: ${t.value.terrainDisplay?.[value] ?? value}`
  if (group === 'env') return `${t.value.envSensitivity}: ${t.value.envDisplay?.[value] ?? value}`
  return feature
}

// 1.645 ≈ two-sided 90 % normal quantile: marks effects whose interval excludes zero.
const coefRows = computed(() => (status.value?.coefficients?.[coefCriterion.value] ?? []).map(c => ({
  ...c,
  label: featureLabel(c.feature),
  effect: Math.exp(c.mean) - 1,
  credible: c.sd > 0 && Math.abs(c.mean) > 1.645 * c.sd,
})))

// ── Styles ───────────────────────────────────────────────────────────────────
const panel = computed(() => props.dark
  ? 'bg-white/[0.06] border border-white/10'
  : 'bg-white/60 border border-white/80 shadow-[0_8px_30px_rgb(0,0,0,0.04)]')
const muted = computed(() => props.dark ? 'text-slate-400' : 'text-slate-500')
const strong = computed(() => props.dark ? 'text-slate-100' : 'text-slate-900')
const rowBorder = computed(() => props.dark ? 'border-slate-700 text-slate-200' : 'border-black/5 text-slate-800')
const primaryButton = computed(() => props.dark ? 'bg-teal-600 hover:bg-teal-500' : 'bg-teal-700 hover:bg-teal-600')
const amberBox = computed(() => props.dark
  ? 'bg-amber-900/20 border border-amber-700/50 text-amber-200'
  : 'bg-amber-50/80 border border-amber-200/80 text-amber-800')
const errorBox = computed(() => props.dark
  ? 'bg-red-500/10 border border-red-500/30 text-red-200'
  : 'bg-red-50 border border-red-200 text-red-800')
const chip = computed(() => props.dark
  ? 'bg-white/10 text-slate-300'
  : 'bg-slate-200/80 text-slate-600')

function segmentClass(selected) {
  return selected
    ? (props.dark ? 'bg-slate-600 border-slate-500 text-white' : 'bg-slate-800 border-slate-800 text-white')
    : (props.dark ? 'border-slate-600 text-slate-400' : 'border-black/10 text-slate-500')
}
</script>

<template>
  <div>
    <!-- (1) Header -->
    <div class="rounded-[28px] backdrop-blur-2xl p-5 lg:p-6 mb-6" :class="panel">
      <h2 class="text-xl font-semibold tracking-tight mb-1" :class="strong">{{ t.modelTitle }}</h2>
      <p class="text-xs mb-3 max-w-4xl leading-relaxed" :class="muted">{{ t.modelIntro }}</p>
      <div class="flex flex-wrap items-center gap-2 text-xs">
        <span :class="muted">{{ t.modelEvaluationUses }}:</span>
        <span class="font-semibold" :class="strong">{{ t.valueSources[dss.valueSource.value] }}</span>
        <button type="button" class="px-2.5 py-1 rounded-lg font-semibold border transition-colors"
                :class="dark ? 'border-slate-600 text-slate-300 hover:text-white' : 'border-black/10 text-slate-600 hover:text-slate-900'"
                @click="dss.valueSource.value = dss.valueSource.value === 'model' ? 'expert' : 'model'">
          {{ dss.valueSource.value === 'model' ? t.modelBackToExpert : t.modelUseInEvaluation }}
        </button>
        <span v-if="model.loading.value" class="flex items-center gap-1.5 ml-auto" :class="muted">
          <span class="animate-spin rounded-full h-3.5 w-3.5 border-b-2" :class="dark ? 'border-teal-400' : 'border-teal-600'"></span>
          {{ t.updating }}
        </span>
      </div>
    </div>

    <div v-if="model.error.value || localError" class="rounded-2xl px-4 py-3 mb-6 text-sm space-y-1 whitespace-pre-line" :class="errorBox">
      <p v-if="localError">{{ localError }}</p>
      <p v-if="model.error.value">{{ model.error.value }}</p>
    </div>

    <template v-if="status">
      <!-- (2) Status cards -->
      <div class="grid grid-cols-1 md:grid-cols-3 gap-4 mb-6">
        <div class="rounded-3xl p-5" :class="panel">
          <p class="text-xs font-semibold uppercase tracking-wider mb-2" :class="muted">{{ t.modelStatDocuments }}</p>
          <p class="text-3xl font-extrabold tabular-nums" :class="strong">{{ documents.length }}</p>
          <p class="text-xs mt-1" :class="muted">
            {{ fmtSize(totalBytes) }}
            <template v-if="docsWithWarnings"> · {{ fmt(t.modelDocsWithWarnings, { n: docsWithWarnings }) }}</template>
          </p>
        </div>
        <div class="rounded-3xl p-5" :class="panel">
          <p class="text-xs font-semibold uppercase tracking-wider mb-2" :class="muted">{{ t.modelStatRecords }}</p>
          <p class="text-3xl font-extrabold tabular-nums" :class="strong">{{ nRecords }}</p>
          <p class="text-xs mt-1" :class="muted">
            {{ fmt(t.modelRealCount, { n: nRecords - nSynthetic }) }} · {{ fmt(t.modelSyntheticCount, { n: nSynthetic }) }}
          </p>
          <p v-if="nSynthetic > 0" class="text-[0.7rem] leading-snug mt-2 rounded-lg px-2.5 py-1.5" :class="amberBox">
            ⚠ {{ t.modelSyntheticBadge }}
          </p>
        </div>
        <div class="rounded-3xl p-5" :class="panel">
          <p class="text-xs font-semibold uppercase tracking-wider mb-2" :class="muted">{{ t.modelStatTrained }}</p>
          <p class="text-lg font-bold mt-1" :class="strong">{{ trainedAt ?? t.modelNeverTrained }}</p>
          <p class="text-xs mt-1" :class="muted">{{ fmt(t.modelTrainedIn, { ms: trainMs }) }}</p>
        </div>
      </div>

      <div v-if="nRecords === 0" class="rounded-2xl px-4 py-3 mb-6 text-sm" :class="amberBox">
        {{ t.modelEmptyCorpus }}
      </div>

      <!-- (3) Document manager -->
      <div class="rounded-[28px] backdrop-blur-2xl p-5 lg:p-6 mb-6" :class="panel">
        <div class="flex flex-wrap items-start justify-between gap-3 mb-3">
          <div>
            <h3 class="text-base font-semibold" :class="strong">{{ t.modelDocsTitle }}</h3>
            <p class="text-xs" :class="muted">{{ t.modelDocsDesc }}</p>
          </div>
          <button type="button"
                  class="px-3 py-1.5 rounded-lg text-sm font-semibold text-white transition-colors disabled:opacity-40"
                  :class="primaryButton" :disabled="busy" @click="retrain">
            {{ retraining ? t.modelRetraining : t.modelRetrain }}
          </button>
        </div>

        <div role="button" tabindex="0"
             class="rounded-2xl border-2 border-dashed px-4 py-6 text-center cursor-pointer transition-colors"
             :class="dragActive
               ? (dark ? 'border-teal-400 bg-teal-500/10' : 'border-teal-600 bg-teal-50/70')
               : (dark ? 'border-slate-600 hover:border-slate-500' : 'border-black/15 hover:border-black/30')"
             @click="pickFiles" @keydown.enter.prevent="pickFiles" @keydown.space.prevent="pickFiles"
             @dragenter.prevent="dragActive = true" @dragover.prevent="dragActive = true"
             @dragleave.prevent="dragActive = false" @drop.prevent="onDrop">
          <input ref="fileInput" type="file" multiple class="hidden" :accept="ALLOWED_EXTENSIONS.join(',')" @change="onFileInput" />
          <p class="text-sm font-semibold pointer-events-none" :class="strong">
            <span v-if="model.uploading.value" class="inline-block animate-spin rounded-full h-3.5 w-3.5 border-b-2 mr-1.5 align-middle"
                  :class="dark ? 'border-teal-400' : 'border-teal-600'"></span>
            {{ model.uploading.value ? t.modelUploading : t.modelDropHint }}
          </p>
          <p class="text-xs mt-1 pointer-events-none" :class="muted">{{ fmt(t.modelDropFormats, { formats: formatsText, size: maxMb }) }}</p>
        </div>

        <div class="flex flex-wrap gap-2 mt-2 text-[0.7rem]">
          <span class="px-2 py-0.5 rounded-full" :class="chip">{{ status.pdf_available ? t.modelPdfOn : t.modelPdfOff }}</span>
          <span class="px-2 py-0.5 rounded-full" :class="chip">{{ status.llm_available ? t.modelLlmOn : t.modelLlmOff }}</span>
        </div>

        <p v-if="!documents.length" class="text-sm mt-4" :class="muted">{{ t.modelNoDocuments }}</p>
        <div v-else class="overflow-x-auto mt-4">
          <table class="w-full text-sm">
            <thead>
              <tr :class="muted">
                <th class="px-3 py-2 text-left font-semibold">{{ t.modelColDocument }}</th>
                <th class="px-3 py-2 text-left font-semibold">{{ t.modelColKind }}</th>
                <th class="px-3 py-2 text-left font-semibold">{{ t.modelColExtractor }}</th>
                <th class="px-3 py-2 text-right font-semibold">{{ t.modelColRecords }}</th>
                <th class="px-3 py-2 text-right font-semibold">{{ t.modelColSize }}</th>
                <th class="px-3 py-2 text-left font-semibold">{{ t.modelColWarnings }}</th>
                <th class="px-3 py-2"></th>
              </tr>
            </thead>
            <tbody>
              <template v-for="doc in documents" :key="doc.name">
                <tr class="border-t" :class="rowBorder">
                  <td class="px-3 py-2 font-medium break-all">
                    {{ doc.name }}
                    <span v-if="doc.synthetic" class="ml-1.5 inline-block px-1.5 py-0.5 rounded text-[0.6rem] font-bold uppercase tracking-wide align-middle"
                          :class="dark ? 'bg-amber-700/40 text-amber-300' : 'bg-amber-200 text-amber-700'">
                      {{ t.modelSyntheticTag }}
                    </span>
                  </td>
                  <td class="px-3 py-2">{{ t.modelKinds[doc.kind] ?? doc.kind }}</td>
                  <td class="px-3 py-2">{{ t.modelExtractors[doc.extractor] ?? doc.extractor }}</td>
                  <td class="px-3 py-2 text-right tabular-nums font-semibold"
                      :class="doc.records === 0 ? (dark ? 'text-amber-300' : 'text-amber-700') : ''">{{ doc.records }}</td>
                  <td class="px-3 py-2 text-right tabular-nums whitespace-nowrap">{{ fmtSize(doc.size_bytes) }}</td>
                  <td class="px-3 py-2">
                    <button v-if="doc.warnings.length" type="button" class="text-xs underline whitespace-nowrap"
                            :class="dark ? 'text-amber-300' : 'text-amber-700'"
                            :aria-expanded="expandedWarnings.has(doc.name)" @click="toggleWarnings(doc.name)">
                      {{ expandedWarnings.has(doc.name) ? `▾ ${t.modelHide}` : `▸ ${t.modelShow}` }} ({{ doc.warnings.length }})
                    </button>
                    <span v-else :class="muted">—</span>
                  </td>
                  <td class="px-3 py-2 text-right">
                    <button type="button" class="text-xs font-semibold px-2 py-1 rounded-lg border transition-colors disabled:opacity-40"
                            :class="dark ? 'border-red-500/40 text-red-300 hover:bg-red-500/10' : 'border-red-200 text-red-700 hover:bg-red-50'"
                            :disabled="busy" @click="removeDocument(doc.name)">
                      {{ t.modelDelete }}
                    </button>
                  </td>
                </tr>
                <tr v-if="expandedWarnings.has(doc.name)">
                  <td colspan="7" class="px-3 pb-3">
                    <ul class="text-xs space-y-0.5 rounded-lg px-3 py-2" :class="amberBox">
                      <li v-for="(w, i) in doc.warnings" :key="i">⚠ {{ w }}</li>
                    </ul>
                  </td>
                </tr>
              </template>
            </tbody>
          </table>
        </div>
      </div>

      <!-- (4) Accuracy -->
      <div class="rounded-[28px] backdrop-blur-2xl p-5 lg:p-6 mb-6" :class="panel">
        <h3 class="text-base font-semibold" :class="strong">{{ t.modelAccuracyTitle }}</h3>
        <p class="text-xs mb-3" :class="muted">{{ t.modelAccuracyDesc }}</p>
        <div class="overflow-x-auto">
          <table class="w-full text-sm">
            <thead>
              <tr :class="muted">
                <th class="px-3 py-2 text-left font-semibold">{{ t.criterionLabel }}</th>
                <th class="px-3 py-2 text-right font-semibold">{{ t.modelColObs }}</th>
                <th class="px-3 py-2 text-right font-semibold">{{ t.modelColMapeExpert }}</th>
                <th class="px-3 py-2 text-right font-semibold">{{ t.modelColMapeModel }}</th>
                <th class="px-3 py-2 text-right font-semibold">{{ fmt(t.modelColCoverage, { level: levelPct }) }}</th>
                <th class="px-3 py-2 text-right font-semibold">{{ t.modelColNoise }}</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="row in accuracyRows" :key="row.key" class="border-t tabular-nums" :class="rowBorder">
                <td class="px-3 py-2 font-semibold">{{ criterionLabel[row.key] }}</td>
                <td class="px-3 py-2 text-right">{{ row.n_obs ?? 0 }}</td>
                <td class="px-3 py-2 text-right">{{ pct(row.loo_mape_expert) }}</td>
                <td class="px-3 py-2 text-right font-semibold"
                    :class="modelBetter(row) === true ? (dark ? 'text-teal-300' : 'text-teal-700')
                      : modelBetter(row) === false ? 'text-orange-500' : ''">
                  {{ pct(row.loo_mape_model) }}
                </td>
                <td class="px-3 py-2 text-right">{{ pct(row.coverage90, 0) }}</td>
                <td class="px-3 py-2 text-right whitespace-nowrap">
                  {{ num(row.noise_sd, 3) }}
                  <span v-if="row.noise_sd != null" class="text-xs" :class="muted">(≈ ±{{ num((Math.exp(row.noise_sd) - 1) * 100, 0) }}%)</span>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
        <p class="text-[0.7rem] mt-2 leading-relaxed" :class="muted">{{ fmt(t.modelAccuracyNote, { level: levelPct }) }}</p>
      </div>
    </template>

    <!-- (5) Expert vs model for the current context and parameters -->
    <div class="rounded-[28px] backdrop-blur-2xl p-5 lg:p-6 mb-6" :class="panel">
      <div class="flex flex-wrap items-start justify-between gap-3 mb-2">
        <div>
          <h3 class="text-base font-semibold" :class="strong">
            {{ t.modelChartTitle }}<template v-if="prediction"> · {{ prediction.context }}</template>
          </h3>
          <p class="text-xs" :class="muted">{{ fmt(t.modelChartDesc, { level: levelPct }) }}</p>
        </div>
        <div class="flex flex-wrap gap-1">
          <button v-for="k in CRITERION_KEYS" :key="k" type="button" @click="chartCriterion = k"
                  class="px-2.5 py-1 rounded-lg text-xs font-semibold border transition-colors"
                  :class="segmentClass(chartCriterion === k)">
            {{ criterionLabel[k] }}
          </button>
        </div>
      </div>

      <div v-if="model.predictError.value" class="rounded-xl px-4 py-2.5 my-3 text-sm" :class="errorBox">
        {{ model.predictError.value }}
      </div>
      <p v-else-if="!prediction" class="text-sm py-8 text-center" :class="muted">
        {{ model.predicting.value ? t.modelPredicting : '—' }}
      </p>

      <template v-if="prediction && predictionRows.length">
        <PlotlyChart :chart="intervalChart" :dark="dark" />
        <div class="overflow-x-auto mt-2">
          <table class="w-full text-sm">
            <thead>
              <tr :class="muted">
                <th class="px-3 py-2 text-left font-semibold">{{ t.alternative }}</th>
                <th class="px-3 py-2 text-right font-semibold">{{ t.modelExpertSeries }}</th>
                <th class="px-3 py-2 text-right font-semibold">{{ t.modelSeries }}</th>
                <th class="px-3 py-2 text-right font-semibold">{{ fmt(t.modelIntervalLabel, { level: levelPct }) }}</th>
                <th class="px-3 py-2 text-right font-semibold">{{ t.modelColChange }}</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="r in predictionRows" :key="r.name" class="border-t tabular-nums" :class="rowBorder">
                <td class="px-3 py-2 font-semibold">{{ r.name }}</td>
                <td class="px-3 py-2 text-right">{{ fmtValue(chartCriterion, r.expert) }}</td>
                <td class="px-3 py-2 text-right font-semibold">{{ fmtValue(chartCriterion, r.predicted) }}</td>
                <td class="px-3 py-2 text-right whitespace-nowrap">{{ fmtValue(chartCriterion, r.low) }} – {{ fmtValue(chartCriterion, r.high) }}</td>
                <td class="px-3 py-2 text-right">{{ r.expert ? signedPct(r.predicted / r.expert - 1) : '—' }}</td>
              </tr>
            </tbody>
          </table>
        </div>
        <p class="text-[0.7rem] mt-2" :class="muted">
          {{ t.modelUnitsLabel }}: {{ t.modelUnits[chartCriterion] }} · {{ fmt(t.modelTrainedOn, { n: prediction.n_records }) }}
        </p>
      </template>
    </div>

    <!-- (6) Coefficients -->
    <details v-if="status" class="rounded-[28px] backdrop-blur-2xl p-5 lg:p-6 mb-6" :class="panel">
      <summary class="cursor-pointer text-base font-semibold" :class="strong">{{ t.modelCoefTitle }}</summary>
      <div class="flex flex-wrap items-start justify-between gap-3 mt-2 mb-2">
        <p class="text-xs max-w-3xl" :class="muted">{{ t.modelCoefDesc }}</p>
        <div class="flex flex-wrap gap-1">
          <button v-for="k in CRITERION_KEYS" :key="k" type="button" @click="coefCriterion = k"
                  class="px-2.5 py-1 rounded-lg text-xs font-semibold border transition-colors"
                  :class="segmentClass(coefCriterion === k)">
            {{ criterionLabel[k] }}
          </button>
        </div>
      </div>
      <div class="overflow-x-auto">
        <table class="w-full text-sm">
          <thead>
            <tr :class="muted">
              <th class="px-3 py-2 text-left font-semibold">{{ t.modelColFeature }}</th>
              <th class="px-3 py-2 text-right font-semibold">{{ t.modelColMean }}</th>
              <th class="px-3 py-2 text-right font-semibold">{{ t.modelColSd }}</th>
              <th class="px-3 py-2 text-right font-semibold">{{ t.modelColEffect }}</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="c in coefRows" :key="c.feature" class="border-t tabular-nums" :class="rowBorder">
              <td class="px-3 py-1.5" :class="c.credible ? 'font-semibold' : ''">
                {{ c.label }}<span v-if="c.credible" class="ml-1" :class="dark ? 'text-teal-300' : 'text-teal-700'" aria-hidden="true">●</span>
              </td>
              <td class="px-3 py-1.5 text-right">{{ num(c.mean, 3) }}</td>
              <td class="px-3 py-1.5 text-right">{{ num(c.sd, 3) }}</td>
              <td class="px-3 py-1.5 text-right" :class="c.credible ? 'font-semibold' : ''">{{ signedPct(c.effect) }}</td>
            </tr>
          </tbody>
        </table>
      </div>
      <p class="text-[0.7rem] mt-2" :class="muted">● {{ t.modelCoefCredible }}</p>
    </details>
  </div>
</template>

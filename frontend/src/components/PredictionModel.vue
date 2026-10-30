<script setup>
import { computed, reactive, ref, watch, onMounted } from 'vue'
import PlotlyChart from './PlotlyChart.vue'
import Icon from './Icon.vue'
import { useLocale } from '../composables/useLocale.js'
import { useViewport } from '../composables/useViewport.js'
import { useModel, ALLOWED_EXTENSIONS, MAX_UPLOAD_BYTES } from '../composables/useModel.js'
import { CRITERION_KEYS } from '../composables/useDSS.js'
import { MODEL_COLORS, SURFACE, chartInk } from '../chartPalette.js'

const props = defineProps({
  dss: Object,
  active: Boolean,
  dark: Boolean,
})

const { t, locale } = useLocale()
const { narrow, coarse } = useViewport()
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

// Load once in the background so the first visit opens on data.
onMounted(() => {
  setTimeout(() => (window.requestIdleCallback ?? (f => f()))(() => {
    if (props.active || prediction.value) return
    model.load()
    stale = false
    model.predict(props.dss, locale.value)
  }), 2500)
})

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
  const n = narrow.value
  return {
    data: [
      {
        type: 'scatter',
        mode: 'markers',
        name: t.value.modelExpertSeries,
        x: names,
        y: rows.map(r => r.expert),
        marker: { symbol: 'diamond', size: n ? 11 : 13, color: colors.value.expert, line: { color: surface.value, width: 2 } },
        hovertemplate: `<b>%{x}</b><br>${t.value.modelExpertSeries}: %{y:${f}} ${unit}<extra></extra>`,
      },
      {
        type: 'scatter',
        mode: 'markers',
        name: `${t.value.modelSeries} · ${intervalLabel}`,
        x: names,
        y: rows.map(r => r.predicted),
        marker: { symbol: 'circle', size: n ? 10 : 12, color: colors.value.model, line: { color: surface.value, width: 2 } },
        error_y: {
          type: 'data', symmetric: false,
          array: rows.map(r => r.high - r.predicted),
          arrayminus: rows.map(r => r.predicted - r.low),
          color: colors.value.model, thickness: 2, width: n ? 6 : 8,
        },
        customdata: rows.map(r => [r.low, r.high]),
        hovertemplate: `<b>%{x}</b><br>${t.value.modelSeries}: %{y:${f}} ${unit}`
          + `<br>${intervalLabel}: %{customdata[0]:${f}} – %{customdata[1]:${f}}<extra></extra>`,
      },
    ],
    layout: {
      paper_bgcolor: 'rgba(0,0,0,0)', plot_bgcolor: 'rgba(0,0,0,0)',
      font: { family: ink.value.font, color: ink.value.text, size: n ? 11 : 12 },
      hoverlabel: { font: { family: ink.value.font } },
      height: n ? 300 : 360,
      autosize: true,
      scattermode: 'group',
      scattergap: 0.75,
      // The legend sits at the bottom of the container; automargin makes room for ticks above it.
      margin: n ? { l: 8, r: 4, t: 4, b: 44 } : { l: 64, r: 16, t: 8, b: 56 },
      xaxis: { tickfont: { size: n ? 11 : 12, color: ink.value.text }, gridcolor: ink.value.grid, automargin: true },
      yaxis: {
        title: { text: `${criterionLabel.value[k]} (${unit})`, font: { size: n ? 11 : 12 }, standoff: n ? 6 : 10 },
        gridcolor: ink.value.grid, tickfont: { color: ink.value.muted }, zeroline: false, automargin: true,
      },
      legend: {
        orientation: 'h', x: 0, xanchor: 'left', yref: 'container', y: 0, yanchor: 'bottom',
        bgcolor: 'rgba(0,0,0,0)', font: { size: n ? 11 : 12 },
      },
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
</script>


<template>
  <div class="space-y-4">
    <!-- (1) Header -->
    <div class="card p-4">
      <h2 class="card-title">{{ t.modelTitle }}</h2>
      <p class="card-desc max-w-3xl leading-relaxed">{{ t.modelIntro }}</p>
      <div class="mt-3 flex flex-wrap items-center gap-2 text-xs">
        <span class="text-muted">{{ t.modelEvaluationUses }}:</span>
        <span class="badge-accent">{{ t.valueSources[dss.valueSource.value] }}</span>
        <button type="button" class="btn md:!px-2.5 md:!py-1 md:!text-xs"
                @click="dss.valueSource.value = dss.valueSource.value === 'model' ? 'expert' : 'model'">
          {{ dss.valueSource.value === 'model' ? t.modelBackToExpert : t.modelUseInEvaluation }}
        </button>
        <span v-if="model.loading.value" class="ml-auto flex items-center gap-1.5 text-subtle">
          <span class="spinner"></span>
          {{ t.updating }}
        </span>
      </div>
    </div>

    <div v-if="model.error.value || localError" class="notice notice-bad space-y-1 whitespace-pre-line">
      <p v-if="localError">{{ localError }}</p>
      <p v-if="model.error.value">{{ model.error.value }}</p>
    </div>

    <template v-if="status">
      <!-- (2) Status cards -->
      <div class="grid grid-cols-2 gap-3 md:grid-cols-3">
        <div class="card p-4">
          <p class="eyebrow">{{ t.modelStatDocuments }}</p>
          <p class="num mt-1.5 text-2xl font-semibold tracking-tight">{{ documents.length }}</p>
          <p class="mt-0.5 text-xs text-muted">
            <span class="num">{{ fmtSize(totalBytes) }}</span>
            <template v-if="docsWithWarnings"> · <span class="text-warn">{{ fmt(t.modelDocsWithWarnings, { n: docsWithWarnings }) }}</span></template>
          </p>
        </div>
        <div class="card p-4">
          <p class="eyebrow">{{ t.modelStatRecords }}</p>
          <p class="num mt-1.5 text-2xl font-semibold tracking-tight">{{ nRecords }}</p>
          <p class="mt-0.5 text-xs text-muted">
            {{ fmt(t.modelRealCount, { n: nRecords - nSynthetic }) }} · {{ fmt(t.modelSyntheticCount, { n: nSynthetic }) }}
          </p>
          <p v-if="nSynthetic > 0" class="notice notice-warn mt-2 hidden gap-1.5 !px-2.5 !py-1.5 text-[0.7rem] leading-snug md:flex">
            <Icon name="alert-triangle" class="mt-px text-xs" />
            <span>{{ t.modelSyntheticBadge }}</span>
          </p>
        </div>
        <!-- Phones: the notice gets the full row instead of squeezing into a half-width card. -->
        <p v-if="nSynthetic > 0" class="notice notice-warn col-span-2 flex gap-1.5 text-xs leading-snug md:hidden">
          <Icon name="alert-triangle" class="mt-px shrink-0" />
          <span>{{ t.modelSyntheticBadge }}</span>
        </p>
        <div class="card col-span-2 p-4 md:col-span-1">
          <p class="eyebrow">{{ t.modelStatTrained }}</p>
          <p class="mt-1.5 text-[15px] font-semibold">{{ trainedAt ?? t.modelNeverTrained }}</p>
          <p class="mt-0.5 text-xs text-muted">{{ fmt(t.modelTrainedIn, { ms: trainMs }) }}</p>
        </div>
      </div>

      <div v-if="nRecords === 0" class="notice notice-warn flex items-start gap-2">
        <Icon name="alert-triangle" class="mt-0.5" />
        <span>{{ t.modelEmptyCorpus }}</span>
      </div>

      <!-- (3) Document manager -->
      <div class="card p-4">
        <div class="mb-3 flex flex-wrap items-start justify-between gap-3">
          <div>
            <h3 class="card-title">{{ t.modelDocsTitle }}</h3>
            <p class="card-desc">{{ t.modelDocsDesc }}</p>
          </div>
          <button type="button" class="btn" :disabled="busy" @click="retrain">
            <Icon name="refresh" :class="retraining ? 'animate-spin' : ''" />
            {{ retraining ? t.modelRetraining : t.modelRetrain }}
          </button>
        </div>

        <div role="button" tabindex="0"
             class="flex cursor-pointer flex-col items-center rounded-lg border border-dashed px-4 py-5 text-center transition-colors"
             :class="dragActive ? 'border-accent bg-accent-soft' : 'border-line-strong hover:bg-surface-2 active:bg-surface-2'"
             @click="pickFiles" @keydown.enter.prevent="pickFiles" @keydown.space.prevent="pickFiles"
             @dragenter.prevent="dragActive = true" @dragover.prevent="dragActive = true"
             @dragleave.prevent="dragActive = false" @drop.prevent="onDrop">
          <input ref="fileInput" type="file" multiple class="hidden" :accept="ALLOWED_EXTENSIONS.join(',')" @change="onFileInput" />
          <span v-if="model.uploading.value" class="spinner pointer-events-none mb-2 !h-4 !w-4"></span>
          <Icon v-else name="upload" class="pointer-events-none mb-2 text-lg text-subtle" />
          <p class="pointer-events-none text-[13px] font-medium">
            {{ model.uploading.value ? t.modelUploading : coarse ? t.modelTapHint : t.modelDropHint }}
          </p>
          <p class="pointer-events-none mt-0.5 text-xs text-muted">{{ fmt(t.modelDropFormats, { formats: formatsText, size: maxMb }) }}</p>
        </div>

        <div class="mt-2 flex flex-wrap gap-1.5">
          <span class="badge">
            <Icon :name="status.pdf_available ? 'check' : 'x'" :class="status.pdf_available ? 'text-ok' : 'text-subtle'" />
            {{ status.pdf_available ? t.modelPdfOn : t.modelPdfOff }}
          </span>
          <span class="badge">
            <Icon :name="status.llm_available ? 'check' : 'x'" :class="status.llm_available ? 'text-ok' : 'text-subtle'" />
            {{ status.llm_available ? t.modelLlmOn : t.modelLlmOff }}
          </span>
        </div>

        <p v-if="!documents.length" class="mt-4 text-[13px] text-muted">{{ t.modelNoDocuments }}</p>
        <ul v-if="documents.length" class="mt-4 divide-y divide-line rounded-lg border border-line md:hidden">
          <li v-for="doc in documents" :key="doc.name" class="flex items-center gap-2.5 py-1.5 pr-1 pl-3">
            <Icon name="file" class="mt-1.5 shrink-0 self-start text-subtle" />
            <div class="min-w-0 flex-1 py-0.5">
              <p class="text-sm font-medium [overflow-wrap:anywhere]">{{ doc.name }}</p>
              <p class="mt-0.5 text-xs text-muted">
                <span v-if="doc.synthetic" class="badge mr-1 !bg-warn-soft !py-0 !text-warn">{{ t.modelSyntheticTag }}</span>
                {{ t.modelKinds[doc.kind] ?? doc.kind }} · {{ t.modelExtractors[doc.extractor] ?? doc.extractor }}
                · <span :class="doc.records === 0 ? 'text-warn' : ''">{{ t.modelColRecords }}: <span class="num">{{ doc.records }}</span></span>
                · <span class="num whitespace-nowrap">{{ fmtSize(doc.size_bytes) }}</span>
              </p>
              <button v-if="doc.warnings.length" type="button"
                      class="-mb-2 inline-flex min-h-11 items-center gap-1 text-xs font-medium text-warn"
                      :aria-expanded="expandedWarnings.has(doc.name)" @click="toggleWarnings(doc.name)">
                <Icon :name="expandedWarnings.has(doc.name) ? 'chevron-down' : 'chevron-right'" />
                {{ t.modelColWarnings }}
                <span class="num">({{ doc.warnings.length }})</span>
              </button>
              <ul v-if="expandedWarnings.has(doc.name)" class="notice notice-warn mt-2 mb-1 space-y-1 text-xs">
                <li v-for="(w, i) in doc.warnings" :key="i" class="flex gap-1.5">
                  <Icon name="alert-triangle" class="mt-px shrink-0" />
                  <span class="min-w-0 break-words">{{ w }}</span>
                </li>
              </ul>
            </div>
            <button type="button" class="icon-btn shrink-0 active:!bg-bad-soft active:!text-bad disabled:pointer-events-none disabled:opacity-40"
                    :aria-label="`${t.modelDelete}: ${doc.name}`"
                    :disabled="busy" @click="removeDocument(doc.name)">
              <Icon name="trash" />
            </button>
          </li>
        </ul>
        <div v-if="documents.length" class="table-scroll mt-4 hidden rounded-lg border border-line md:block">
          <table class="table">
            <thead>
              <tr>
                <th>{{ t.modelColDocument }}</th>
                <th>{{ t.modelColKind }}</th>
                <th>{{ t.modelColExtractor }}</th>
                <th class="text-right">{{ t.modelColRecords }}</th>
                <th class="text-right">{{ t.modelColSize }}</th>
                <th>{{ t.modelColWarnings }}</th>
                <th class="w-10"></th>
              </tr>
            </thead>
            <tbody>
              <template v-for="doc in documents" :key="doc.name">
                <tr>
                  <td class="!py-1.5">
                    <div class="flex items-center gap-2">
                      <Icon name="file" class="text-subtle" />
                      <span class="break-all font-medium">{{ doc.name }}</span>
                      <span v-if="doc.synthetic" class="badge !border-warn/25 !bg-warn-soft !text-warn">{{ t.modelSyntheticTag }}</span>
                    </div>
                  </td>
                  <td class="!py-1.5 text-muted">{{ t.modelKinds[doc.kind] ?? doc.kind }}</td>
                  <td class="!py-1.5 text-muted">{{ t.modelExtractors[doc.extractor] ?? doc.extractor }}</td>
                  <td class="num !py-1.5 text-right" :class="doc.records === 0 ? '!text-warn' : ''">{{ doc.records }}</td>
                  <td class="num !py-1.5 whitespace-nowrap text-right text-muted">{{ fmtSize(doc.size_bytes) }}</td>
                  <td class="!py-1.5">
                    <button v-if="doc.warnings.length" type="button"
                            class="inline-flex items-center gap-1 whitespace-nowrap text-xs font-medium text-warn hover:underline"
                            :aria-expanded="expandedWarnings.has(doc.name)" @click="toggleWarnings(doc.name)">
                      <Icon :name="expandedWarnings.has(doc.name) ? 'chevron-down' : 'chevron-right'" />
                      {{ expandedWarnings.has(doc.name) ? t.modelHide : t.modelShow }}
                      <span class="num">({{ doc.warnings.length }})</span>
                    </button>
                    <span v-else class="text-subtle">—</span>
                  </td>
                  <td class="!py-1.5 text-right">
                    <button type="button" class="icon-btn hover:!bg-bad-soft hover:!text-bad disabled:pointer-events-none disabled:opacity-40"
                            :title="t.modelDelete" :aria-label="`${t.modelDelete}: ${doc.name}`"
                            :disabled="busy" @click="removeDocument(doc.name)">
                      <Icon name="trash" />
                    </button>
                  </td>
                </tr>
                <tr v-if="expandedWarnings.has(doc.name)">
                  <td colspan="7" class="!bg-transparent !pt-0">
                    <ul class="notice notice-warn space-y-1 text-xs">
                      <li v-for="(w, i) in doc.warnings" :key="i" class="flex gap-1.5">
                        <Icon name="alert-triangle" class="mt-px" />
                        <span>{{ w }}</span>
                      </li>
                    </ul>
                  </td>
                </tr>
              </template>
            </tbody>
          </table>
        </div>
      </div>

      <!-- (4) Accuracy -->
      <div class="card p-4">
        <h3 class="card-title">{{ t.modelAccuracyTitle }}</h3>
        <p class="card-desc">{{ t.modelAccuracyDesc }}</p>
        <div class="table-scroll mt-3 rounded-lg border border-line">
          <table class="table min-w-[38rem]">
            <thead>
              <tr>
                <th class="sticky-col">{{ t.criterionLabel }}</th>
                <th class="text-right">{{ t.modelColObs }}</th>
                <th class="text-right">{{ t.modelColMapeExpert }}</th>
                <th class="text-right">{{ t.modelColMapeModel }}</th>
                <th class="text-right">{{ fmt(t.modelColCoverage, { level: levelPct }) }}</th>
                <th class="text-right">{{ t.modelColNoise }}</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="row in accuracyRows" :key="row.key">
                <td class="sticky-col font-medium">{{ criterionLabel[row.key] }}</td>
                <td class="num text-right">{{ row.n_obs ?? 0 }}</td>
                <td class="num text-right">{{ pct(row.loo_mape_expert) }}</td>
                <td class="num text-right font-semibold"
                    :class="modelBetter(row) === true ? '!text-ok' : modelBetter(row) === false ? '!text-warn' : ''">
                  {{ pct(row.loo_mape_model) }}
                </td>
                <td class="num text-right">{{ pct(row.coverage90, 0) }}</td>
                <td class="num whitespace-nowrap text-right">
                  {{ num(row.noise_sd, 3) }}
                  <span v-if="row.noise_sd != null" class="text-xs text-subtle">(≈ ±{{ num((Math.exp(row.noise_sd) - 1) * 100, 0) }}%)</span>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
        <p class="mt-2 max-w-3xl text-xs leading-relaxed text-subtle">{{ fmt(t.modelAccuracyNote, { level: levelPct }) }}</p>
      </div>
    </template>

    <!-- (5) Expert vs model for the current context and parameters -->
    <div class="card p-4">
      <div class="mb-2 flex flex-wrap items-start justify-between gap-3">
        <div>
          <h3 class="card-title">
            {{ t.modelChartTitle }}<template v-if="prediction"><span class="font-normal text-muted"> · {{ prediction.context }}</span></template>
          </h3>
          <p class="card-desc">{{ fmt(t.modelChartDesc, { level: levelPct }) }}</p>
        </div>
        <div class="seg grid w-full grid-cols-2 md:inline-flex md:w-auto md:flex-wrap">
          <button v-for="k in CRITERION_KEYS" :key="k" type="button" class="seg-item"
                  :aria-pressed="chartCriterion === k" @click="chartCriterion = k">
            {{ criterionLabel[k] }}
          </button>
        </div>
      </div>

      <div v-if="model.predictError.value" class="notice notice-bad my-3">
        {{ model.predictError.value }}
      </div>
      <p v-else-if="!prediction" class="flex items-center justify-center gap-2 py-8 text-[13px] text-muted">
        <span v-if="model.predicting.value" class="spinner"></span>
        {{ model.predicting.value ? t.modelPredicting : '—' }}
      </p>

      <template v-if="prediction && predictionRows.length">
        <PlotlyChart :chart="intervalChart" :dark="dark" />
        <div class="table-scroll mt-2 rounded-lg border border-line">
          <table class="table min-w-[32rem]">
            <thead>
              <tr>
                <th class="sticky-col">{{ t.alternative }}</th>
                <th class="text-right">{{ t.modelExpertSeries }}</th>
                <th class="text-right">{{ t.modelSeries }}</th>
                <th class="text-right">{{ fmt(t.modelIntervalLabel, { level: levelPct }) }}</th>
                <th class="text-right">{{ t.modelColChange }}</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="r in predictionRows" :key="r.name">
                <td class="sticky-col font-medium">{{ r.name }}</td>
                <td class="num text-right">{{ fmtValue(chartCriterion, r.expert) }}</td>
                <td class="num text-right font-semibold">{{ fmtValue(chartCriterion, r.predicted) }}</td>
                <td class="num whitespace-nowrap text-right text-muted">{{ fmtValue(chartCriterion, r.low) }} – {{ fmtValue(chartCriterion, r.high) }}</td>
                <td class="num text-right">{{ r.expert ? signedPct(r.predicted / r.expert - 1) : '—' }}</td>
              </tr>
            </tbody>
          </table>
        </div>
        <p class="mt-2 text-xs text-subtle">
          {{ t.modelUnitsLabel }}: {{ t.modelUnits[chartCriterion] }} · {{ fmt(t.modelTrainedOn, { n: prediction.n_records }) }}
        </p>
      </template>
    </div>

    <!-- (6) Coefficients -->
    <details v-if="status" class="card group p-4">
      <summary class="card-title flex cursor-pointer list-none items-center gap-1.5 [&::-webkit-details-marker]:hidden">
        <Icon name="chevron-right" class="text-subtle transition-transform group-open:rotate-90" />
        {{ t.modelCoefTitle }}
      </summary>
      <div class="mt-2 mb-3 flex flex-wrap items-start justify-between gap-3">
        <p class="max-w-3xl text-xs leading-relaxed text-muted">{{ t.modelCoefDesc }}</p>
        <div class="seg grid w-full grid-cols-2 md:inline-flex md:w-auto md:flex-wrap">
          <button v-for="k in CRITERION_KEYS" :key="k" type="button" class="seg-item"
                  :aria-pressed="coefCriterion === k" @click="coefCriterion = k">
            {{ criterionLabel[k] }}
          </button>
        </div>
      </div>
      <div class="table-scroll rounded-lg border border-line">
        <table class="table min-w-[24rem]">
          <thead>
            <tr>
              <th>{{ t.modelColFeature }}</th>
              <th class="text-right">{{ t.modelColMean }}</th>
              <th class="text-right">{{ t.modelColSd }}</th>
              <th class="text-right">{{ t.modelColEffect }}</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="c in coefRows" :key="c.feature">
              <td class="!py-1.5" :class="c.credible ? 'font-medium' : '!text-muted'">
                {{ c.label }}<span v-if="c.credible" class="ml-1.5 inline-block h-1.5 w-1.5 rounded-full bg-accent align-middle" aria-hidden="true"></span>
              </td>
              <td class="num !py-1.5 text-right">{{ num(c.mean, 3) }}</td>
              <td class="num !py-1.5 text-right text-muted">{{ num(c.sd, 3) }}</td>
              <td class="num !py-1.5 text-right" :class="c.credible ? 'font-semibold' : ''">{{ signedPct(c.effect) }}</td>
            </tr>
          </tbody>
        </table>
      </div>
      <p class="mt-2 flex items-center gap-1.5 text-xs text-subtle">
        <span class="inline-block h-1.5 w-1.5 shrink-0 rounded-full bg-accent" aria-hidden="true"></span>
        {{ t.modelCoefCredible }}
      </p>
    </details>
  </div>
</template>

<style scoped>
/* First column stays put while a wide table scrolls sideways on phones (opaque, so the
   scrolled cells don't show through; even rows keep their stripe). */
.sticky-col {
  position: sticky;
  left: 0;
  z-index: 1;
  background-color: var(--surface) !important;
}
tbody tr:nth-child(even) > .sticky-col {
  background-color: color-mix(in oklab, var(--surface-2) 40%, var(--surface)) !important;
}
</style>

<script setup>
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { useLocale } from '../composables/useLocale.js'
import { useModel } from '../composables/useModel.js'
import { useRobustness } from '../composables/useRobustness.js'
import { useScenarios } from '../composables/useScenarios.js'
import { CRITERION_KEYS } from '../composables/useDSS.js'
import Icon from './Icon.vue'

// Printable decision report of the current inputs: what was assumed, what the engine
// recommends, how far the methods agree, how robust the choice is, and what the prediction
// model says. "Print / Save as PDF" uses the system print dialog (style.css hides the app in
// print). It is always drawn as a light paper document, whatever the app theme.
const props = defineProps({ open: Boolean, dss: Object })
const emit = defineEmits(['close'])

const { t, locale, ctxName } = useLocale()
const robust = useRobustness()
const model = useModel()
const { scenarios, shareUrl } = useScenarios()

const r = computed(() => t.value.report)
const evalData = computed(() => props.dss.evalData.value)
const state = computed(() => props.dss.snapshotState())
const openedAt = ref(new Date())
const generatedAt = computed(() => openedAt.value.toLocaleString(locale.value === 'uk' ? 'uk-UA' : 'en-GB',
  { dateStyle: 'long', timeStyle: 'short' }))

// SMAA and the model prediction for exactly these inputs, refreshed each time the report opens.
watch(() => props.open, open => {
  if (!open) return
  openedAt.value = new Date()
  robust.run(props.dss, locale.value)
  model.predict(props.dss, locale.value)
  if (!model.status.value) model.load()
}, { immediate: true })

const busy = computed(() => props.dss.loading.value || robust.loading.value || model.predicting.value)

function onKey(e) { if (e.key === 'Escape' && props.open) emit('close') }
window.addEventListener('keydown', onKey)
onBeforeUnmount(() => window.removeEventListener('keydown', onKey))

const scenarioName = computed(() => {
  const now = JSON.stringify(state.value)
  return scenarios.value.find(s => JSON.stringify(s.state) === now)?.name ?? ''
})
const link = computed(() => shareUrl(state.value, scenarioName.value))

const criterionLabel = computed(() => ({
  construction_cost_mln: t.value.constructionCost,
  land_area_hectares: t.value.landArea,
  throughput_vph: t.value.throughput,
  safety_index: t.value.safetyIndex,
}))
const unitOf = computed(() => Object.fromEntries((evalData.value?.criteria ?? [])
  .map(c => [c.name, criterionLabel.value[c.name]?.endsWith(')') ? '' : c.unit])))
const directionOf = computed(() => Object.fromEntries((evalData.value?.criteria ?? []).map(c => [c.name, c.direction])))

function value(key, v) {
  if (v == null) return '—'
  return key === 'throughput_vph' ? Math.round(v).toLocaleString() : (Math.round(v * 100) / 100).toLocaleString()
}
const pct = v => (v == null ? '—' : `${Math.round(v * 100)} %`)

const terrainLabel = computed(() => ({ Flat: t.value.terrainFlat, Rolling: t.value.terrainRolling, Mountainous: t.value.terrainMountainous }))
const envLabel = computed(() => ({ Low: t.value.envLow, Medium: t.value.envMedium, High: t.value.envHigh, Critical: t.value.envCritical }))

const inputRows = computed(() => {
  const p = state.value.params
  return [
    [t.value.taskContext, ctxName(state.value.context)],
    [t.value.designSpeed, p.design_speed],
    [t.value.aadt, p.aadt.toLocaleString()],
    [t.value.peakFactor, p.peak_factor],
    [t.value.numLanes, p.num_lanes],
    [t.value.budget, p.budget],
    [t.value.landLimit, p.land_limit],
    [t.value.terrainType, terrainLabel.value[p.terrain]],
    [t.value.envSensitivity, envLabel.value[p.env_sensitivity]],
    [t.value.methodsTitle, state.value.methods.map(m => t.value.methodLabels[m]).join(', ')],
    [t.value.criteriaWeights, t.value.weightingModes[state.value.weighting.mode]],
    [t.value.valueSourceTitle, t.value.valueSources[state.value.valueSource]],
  ]
})

const methods = computed(() => Object.keys(evalData.value?.method_results ?? {}))
const winner = computed(() => evalData.value?.results?.[0])

function rankBy(method, name) {
  return evalData.value?.method_results?.[method]?.scores?.find(s => s.alternative_name === name)?.rank
}
const consensus = computed(() => evalData.value?.rank_agreement?.consensus ?? [])
function consensusRank(name) {
  return consensus.value.find(c => c.alternative_name === name)?.rank
}
// Methods whose first place includes the recommended alternative.
const agreeing = computed(() => methods.value.filter(m => rankBy(m, winner.value?.alternative_name) === 1))

const kendall = computed(() => evalData.value?.rank_agreement?.kendall ?? null)
const agreementMethods = computed(() => evalData.value?.rank_agreement?.methods ?? [])

const smaa = computed(() => robust.data.value)
const smaaMethods = computed(() => Object.keys(smaa.value?.smaa ?? {}))

const prediction = computed(() => model.prediction.value)
const modelRecords = computed(() => prediction.value?.n_records ?? 0)
const nSynthetic = computed(() => model.status.value?.n_synthetic ?? 0)
const ranked = computed(() => (evalData.value?.results ?? []).map(x => x.alternative_name))
const predictionRows = computed(() => (prediction.value?.alternatives ?? [])
  .filter(a => ranked.value.includes(a.name))
  .sort((a, b) => ranked.value.indexOf(a.name) - ranked.value.indexOf(b.name)))

function print() {
  window.print()
}
</script>

<template>
  <Teleport to="body">
    <Transition name="fade">
      <div v-if="open" class="report-overlay fixed inset-0 z-50 overflow-y-auto bg-neutral-500/40 backdrop-blur-sm"
           role="dialog" aria-modal="true" :aria-label="r.title">
        <!-- Screen-only toolbar -->
        <div class="report-toolbar material-bar sticky top-0 z-10 flex items-center gap-2 border-b border-line px-4 py-2 pt-safe">
          <p class="min-w-0 flex-1 truncate text-[13px] font-semibold text-fg">{{ r.title }}</p>
          <span class="spinner transition-opacity duration-200" :class="busy ? 'opacity-100' : 'opacity-0'"></span>
          <button type="button" class="btn-primary" :disabled="busy || !evalData" @click="print">
            <Icon name="download" class="text-sm" /> {{ r.print }}
          </button>
          <button type="button" class="btn" @click="emit('close')">{{ t.done }}</button>
        </div>

        <article v-if="evalData"
                 class="report mx-auto my-6 max-w-[820px] rounded-lg bg-white px-8 py-10 text-[12.5px] leading-relaxed text-neutral-900 shadow-xl sm:px-12">
          <header class="report-section border-b-2 border-neutral-900 pb-4">
            <p class="text-[11px] font-semibold tracking-[0.12em] text-neutral-500 uppercase">TDSS v5 · {{ t.appTitle }}</p>
            <h1 class="mt-1 text-[24px] leading-tight font-bold">{{ r.title }}</h1>
            <p class="mt-1 text-neutral-600">
              {{ ctxName(state.context) }}<template v-if="scenarioName"> · {{ r.scenario }}: <strong>{{ scenarioName }}</strong></template>
            </p>
            <p class="mt-0.5 text-neutral-500">{{ r.generated }} {{ generatedAt }}</p>
          </header>

          <!-- 1. Recommendation -->
          <section class="report-section mt-6">
            <h2 class="report-h2">1. {{ r.recommendation }}</h2>
            <div v-if="winner" class="mt-2 rounded border border-neutral-300 bg-neutral-50 p-4">
              <p class="text-[17px] font-bold">{{ winner.alternative_name }}</p>
              <p class="mt-1 text-neutral-700">
                {{ t.wsmScore }} <span class="num">{{ winner.total_score.toFixed(4) }}</span>.
                {{ r.agreeing.replace('{k}', agreeing.length).replace('{n}', methods.length)
                }}{{ agreeing.length ? ` (${agreeing.map(m => t.methodLabels[m]).join(', ')})` : '' }}.
              </p>
              <p v-if="winner.description" class="mt-2 text-neutral-600">{{ winner.description }}</p>
            </div>
            <p v-else class="mt-2 font-semibold text-red-700">{{ r.noneFeasible }}</p>
          </section>

          <!-- 2. Inputs -->
          <section class="report-section mt-6">
            <h2 class="report-h2">2. {{ r.inputs }}</h2>
            <div class="mt-2 grid gap-6 sm:grid-cols-2">
              <table class="report-table">
                <tbody>
                  <tr v-for="[label, v] in inputRows" :key="label"><th>{{ label }}</th><td class="num">{{ v }}</td></tr>
                </tbody>
              </table>
              <table class="report-table">
                <thead><tr><th>{{ r.criterion }}</th><th class="text-right">{{ r.weight }}</th></tr></thead>
                <tbody>
                  <tr v-for="k in CRITERION_KEYS" :key="k">
                    <th>{{ criterionLabel[k] }} <span class="font-normal text-neutral-500">· {{ t[directionOf[k]] }}</span></th>
                    <td class="num text-right">{{ evalData.normalised_weights[k]?.toFixed(3) }}</td>
                  </tr>
                </tbody>
              </table>
            </div>
          </section>

          <!-- 3. Site adjustments -->
          <section v-if="evalData.adjustments?.length" class="report-section mt-6">
            <h2 class="report-h2">3. {{ r.adjustments }}</h2>
            <ul class="mt-2 list-disc space-y-1 pl-5 text-neutral-700">
              <li v-for="(a, i) in evalData.adjustments" :key="i">{{ a.message }}</li>
            </ul>
          </section>

          <!-- 4. Ranking -->
          <section class="report-section mt-6">
            <h2 class="report-h2">4. {{ r.ranking }}</h2>
            <table class="report-table mt-2">
              <thead>
                <tr>
                  <th>{{ r.alternative }}</th>
                  <th v-for="k in CRITERION_KEYS" :key="k" class="text-right">{{ criterionLabel[k] }}<br><span class="font-normal text-neutral-500">{{ unitOf[k] }}</span></th>
                  <th class="text-right">{{ t.wsmScore }}</th>
                  <th v-for="m in methods" :key="m" class="text-right">{{ t.methodLabels[m] }}</th>
                  <th v-if="methods.length > 1" class="text-right">{{ r.consensus }}</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="res in evalData.results" :key="res.alternative_name">
                  <th>{{ res.alternative_name }}</th>
                  <td v-for="k in CRITERION_KEYS" :key="k" class="num text-right">{{ value(k, res.raw_values[k]) }}</td>
                  <td class="num text-right font-semibold">{{ res.total_score.toFixed(3) }}</td>
                  <td v-for="m in methods" :key="m" class="num text-right">{{ rankBy(m, res.alternative_name) ?? '—' }}</td>
                  <td v-if="methods.length > 1" class="num text-right font-semibold">{{ consensusRank(res.alternative_name) ?? '—' }}</td>
                </tr>
              </tbody>
            </table>
            <p class="mt-1.5 text-[11px] text-neutral-500">{{ r.rankingNote }}</p>
          </section>

          <!-- 5. Method agreement -->
          <section v-if="kendall && agreementMethods.length > 1" class="report-section mt-6">
            <h2 class="report-h2">5. {{ r.agreement }}</h2>
            <table class="report-table mt-2 w-auto">
              <thead>
                <tr><th></th><th v-for="m in agreementMethods" :key="m" class="text-right">{{ t.methodLabels[m] }}</th></tr>
              </thead>
              <tbody>
                <tr v-for="(row, i) in kendall" :key="i">
                  <th>{{ t.methodLabels[agreementMethods[i]] }}</th>
                  <td v-for="(v, j) in row" :key="j" class="num text-right">{{ v.toFixed(2) }}</td>
                </tr>
              </tbody>
            </table>
            <p class="mt-1.5 text-[11px] text-neutral-500">{{ r.agreementNote }}</p>
          </section>

          <!-- 6. Robustness -->
          <section class="report-section mt-6">
            <h2 class="report-h2">6. {{ r.robustness }}</h2>
            <p v-if="robust.error.value" class="mt-2 text-red-700">{{ robust.error.value }}</p>
            <p v-else-if="!smaa" class="mt-2 text-neutral-500">{{ r.pending }}</p>
            <template v-else>
              <p class="mt-2 text-neutral-700">
                {{ r.smaaIntro.replace('{n}', smaa.iterations.toLocaleString()).replace('{model}', t.report.weightModels[smaa.weight_model] ?? smaa.weight_model) }}
              </p>
              <table class="report-table mt-2">
                <thead>
                  <tr>
                    <th>{{ r.alternative }}</th>
                    <th v-for="m in smaaMethods" :key="m" class="text-right">{{ r.firstPlace }} · {{ t.methodLabels[m] }}</th>
                    <th class="text-right">{{ r.overBudget }}</th>
                    <th class="text-right">{{ r.overLand }}</th>
                  </tr>
                </thead>
                <tbody>
                  <tr v-for="name in smaa.alternatives" :key="name">
                    <th>{{ name }}</th>
                    <td v-for="m in smaaMethods" :key="m" class="num text-right">
                      {{ pct(smaa.smaa[m].alternatives.find(a => a.alternative_name === name)?.rank_acceptability[0]) }}
                    </td>
                    <td class="num text-right">{{ pct(smaa.exceedance?.[name]?.construction_cost_mln) }}</td>
                    <td class="num text-right">{{ pct(smaa.exceedance?.[name]?.land_area_hectares) }}</td>
                  </tr>
                </tbody>
              </table>
              <ul class="mt-3 list-disc space-y-1 pl-5 text-neutral-700">
                <li v-for="m in Object.keys(smaa.sensitivity ?? {})" :key="m">
                  <strong>{{ t.methodLabels[m] }}:</strong>
                  <template v-if="smaa.sensitivity[m].critical_criterion">
                    {{ r.sensitivity
                      .replace('{winner}', smaa.sensitivity[m].winner)
                      .replace('{criterion}', criterionLabel[smaa.sensitivity[m].critical_criterion])
                      .replace('{change}', smaa.sensitivity[m].critical_change.toFixed(3))
                      .replace('{weight}', evalData.normalised_weights[smaa.sensitivity[m].critical_criterion].toFixed(3)) }}
                  </template>
                  <template v-else>{{ r.sensitivityStable.replace('{winner}', smaa.sensitivity[m].winner) }}</template>
                </li>
              </ul>
            </template>
          </section>

          <!-- 7. Prediction model -->
          <section class="report-section mt-6">
            <h2 class="report-h2">7. {{ r.model }}</h2>
            <p v-if="model.predictError.value" class="mt-2 text-red-700">{{ model.predictError.value }}</p>
            <p v-else-if="!prediction" class="mt-2 text-neutral-500">{{ r.pending }}</p>
            <p v-else-if="!modelRecords" class="mt-2 text-neutral-700">{{ r.modelEmpty }}</p>
            <template v-else>
              <p class="mt-2 text-neutral-700">
                {{ (state.valueSource === 'model' ? r.modelUsed : r.modelReference)
                  .replace('{n}', modelRecords).replace('{level}', Math.round(prediction.interval_level * 100)) }}
                <strong v-if="nSynthetic" class="text-amber-700">{{ r.modelSynthetic.replace('{n}', nSynthetic) }}</strong>
              </p>
              <table class="report-table mt-2">
                <thead>
                  <tr>
                    <th>{{ r.alternative }}</th>
                    <th v-for="k in CRITERION_KEYS" :key="k" class="text-right">{{ criterionLabel[k] }}<br><span class="font-normal text-neutral-500">{{ r.expertPredicted }}</span></th>
                  </tr>
                </thead>
                <tbody>
                  <tr v-for="a in predictionRows" :key="a.name">
                    <th>{{ a.name }}</th>
                    <td v-for="k in CRITERION_KEYS" :key="k" class="num text-right">
                      {{ value(k, a.values[k].expert) }} → <strong>{{ value(k, a.values[k].predicted) }}</strong>
                      <br><span class="text-neutral-500">{{ value(k, a.values[k].low) }} – {{ value(k, a.values[k].high) }}</span>
                    </td>
                  </tr>
                </tbody>
              </table>
            </template>
          </section>

          <footer class="report-section mt-8 border-t border-neutral-300 pt-3 text-[11px] text-neutral-500">
            <p>{{ r.footer }}</p>
            <p class="mt-1.5">{{ r.reproduce }}</p>
            <p class="num mt-0.5 break-all text-neutral-700">{{ link }}</p>
          </footer>
        </article>
      </div>
    </Transition>
  </Teleport>
</template>

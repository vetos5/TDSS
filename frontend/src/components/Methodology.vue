<script setup>
import { computed } from 'vue'
import { useLocale } from '../composables/useLocale.js'
import Icon from './Icon.vue'

const props = defineProps({
  data: Object,
  dark: Boolean,
})

const { t } = useLocale()

// Formulas are notation, shared by both locales; the prose comes from t.methodTheory.
const THEORY = [
  { key: 'topsis', formulas: [
    'r<sub>ij</sub> = x<sub>ij</sub> / ‖x<sub>j</sub>‖₂ ,  v<sub>ij</sub> = w<sub>j</sub> r<sub>ij</sub>',
    'C<sub>i</sub> = D<sub>i</sub><sup>−</sup> / (D<sub>i</sub><sup>+</sup> + D<sub>i</sub><sup>−</sup>)',
  ] },
  { key: 'ahp', formulas: [
    'A w = λ<sub>max</sub> w',
    'CI = (λ<sub>max</sub> − n) / (n − 1) ,  CR = CI / RI<sub>n</sub> &lt; 0.10',
    'P<sub>i</sub> = Σ<sub>j</sub> w<sub>j</sub> p<sub>ij</sub>',
  ] },
  { key: 'promethee', formulas: [
    'π(a, b) = Σ<sub>j</sub> w<sub>j</sub> P<sub>j</sub>(a, b)',
    'φ(a) = φ<sup>+</sup>(a) − φ<sup>−</sup>(a)',
  ] },
  { key: 'vikor', formulas: [
    'S<sub>i</sub> = Σ<sub>j</sub> w<sub>j</sub> (f<sub>j</sub><sup>*</sup> − f<sub>ij</sub>) / (f<sub>j</sub><sup>*</sup> − f<sub>j</sub><sup>−</sup>) ,  R<sub>i</sub> = max<sub>j</sub>(…)',
    'Q<sub>i</sub> = v (S<sub>i</sub> − S<sup>*</sup>)/(S<sup>−</sup> − S<sup>*</sup>) + (1 − v)(R<sub>i</sub> − R<sup>*</sup>)/(R<sup>−</sup> − R<sup>*</sup>)',
  ] },
  { key: 'entropy', formulas: [
    'e<sub>j</sub> = −(1 / ln m) Σ<sub>i</sub> p<sub>ij</sub> ln p<sub>ij</sub> ,  w<sub>j</sub> = (1 − e<sub>j</sub>) / Σ<sub>k</sub>(1 − e<sub>k</sub>)',
  ] },
  { key: 'critic', formulas: [
    'C<sub>j</sub> = σ<sub>j</sub> Σ<sub>k</sub> (1 − r<sub>jk</sub>) ,  w<sub>j</sub> = C<sub>j</sub> / Σ<sub>k</sub> C<sub>k</sub>',
  ] },
  { key: 'smaa', formulas: [
    'b<sub>i</sub><sup>r</sup> = P(rank(i) = r) ≈ (1/N) Σ<sub>k</sub> 𝟙[rank<sub>k</sub>(i) = r]',
    'a<sub>i</sub><sup>h</sup> = Σ<sub>r</sub> (m − r)/(m − 1) · b<sub>i</sub><sup>r</sup> ,  w<sub>i</sub><sup>c</sup> = E[w | rank(i) = 1]',
  ] },
  { key: 'sensitivity', formulas: [
    'w<sub>k</sub>(t) = w<sub>k</sub> (1 − t) / (1 − w<sub>j</sub>) ,  k ≠ j',
    'w<sub>j</sub> ∈ [t<sup>−</sup>, t<sup>+</sup>] ⇒ rank<sub>1</sub> = const',
  ] },
  { key: 'agreement', formulas: [
    'ρ = 1 − 6 Σ d<sub>i</sub>² / (m (m² − 1))',
    'B<sub>i</sub> = Σ<sub>k</sub> (m − rank<sub>k</sub>(i))',
  ] },
]

function altColor(name) {
  const r = props.data?.results?.find(r => r.alternative_name === name)
  return props.dark ? (r?.color_dark || '#2dd4bf') : (r?.color || '#0f766e')
}
</script>

<template>
  <div v-if="data" class="grid grid-cols-1 items-start gap-4 lg:grid-cols-10">
    <!-- Left column — methodology text -->
    <div class="space-y-4 lg:col-span-6">
      <section class="card p-4">
        <h2 class="card-title">{{ t.wsmTitle }}</h2>
        <p class="mt-1.5 max-w-3xl text-[13px] leading-relaxed text-muted">{{ t.wsmDesc }}</p>

        <div class="my-3 overflow-x-auto rounded-lg bg-surface-2 px-3 py-3 font-mono text-[15px]">
          <div class="w-max min-w-full text-center whitespace-nowrap">S<sub>i</sub> = Σ<sub>j=1..n</sub> w<sub>j</sub> · x̄<sub>ij</sub></div>
        </div>

        <div class="table-scroll rounded-lg border border-line">
          <table class="table">
            <thead>
              <tr>
                <th class="w-24">{{ t.symbol }}</th>
                <th>{{ t.definition }}</th>
              </tr>
            </thead>
            <tbody>
              <tr>
                <td class="font-mono">S<sub>i</sub></td>
                <td class="text-muted">{{ t.defSi }}</td>
              </tr>
              <tr>
                <td class="font-mono">n</td>
                <td class="text-muted">{{ t.defN }}</td>
              </tr>
              <tr>
                <td class="font-mono">w<sub>j</sub></td>
                <td class="text-muted">{{ t.defWj }}</td>
              </tr>
              <tr>
                <td class="font-mono">x̄<sub>ij</sub></td>
                <td class="text-muted">{{ t.defXij }}</td>
              </tr>
            </tbody>
          </table>
        </div>
      </section>

      <section class="card p-4">
        <h2 class="card-title">{{ t.minMaxTitle }}</h2>
        <p class="mt-1.5 max-w-3xl text-[13px] leading-relaxed text-muted">{{ t.minMaxDesc }}</p>

        <p class="mt-3 text-xs font-medium">{{ t.maxDir }}</p>
        <div class="mt-1.5 overflow-x-auto rounded-lg bg-surface-2 px-3 py-2.5 font-mono text-[13px]">
          <div class="w-max min-w-full text-center whitespace-nowrap">x̄<sub>ij</sub> = (x<sub>ij</sub> − min<sub>j</sub>) / (max<sub>j</sub> − min<sub>j</sub>)</div>
        </div>

        <p class="mt-3 text-xs font-medium">{{ t.minDir }}</p>
        <div class="mt-1.5 overflow-x-auto rounded-lg bg-surface-2 px-3 py-2.5 font-mono text-[13px]">
          <div class="w-max min-w-full text-center whitespace-nowrap">x̄<sub>ij</sub> = (max<sub>j</sub> − x<sub>ij</sub>) / (max<sub>j</sub> − min<sub>j</sub>)</div>
        </div>

        <p class="mt-3 flex max-w-3xl items-start gap-1.5 text-xs leading-relaxed text-subtle">
          <Icon name="info" class="mt-0.5" />
          <span>{{ t.edgeCase }}</span>
        </p>
      </section>

      <section class="card p-4">
        <h2 class="card-title">{{ t.methodsTheoryTitle }}</h2>
        <p class="card-desc max-w-3xl leading-relaxed">{{ t.methodsTheoryIntro }}</p>

        <div class="mt-3 divide-y divide-line">
          <div v-for="item in THEORY" :key="item.key" class="py-3 first:pt-1 last:pb-0">
            <h3 class="text-[13px] font-semibold">{{ t.methodTheory[item.key].title }}</h3>
            <p class="mt-1 max-w-3xl text-[13px] leading-relaxed text-muted">{{ t.methodTheory[item.key].desc }}</p>
            <div v-for="(f, i) in item.formulas" :key="i"
                 class="mt-1.5 overflow-x-auto rounded-lg bg-surface-2 px-3 py-2 font-mono text-[13px]">
              <div class="w-max min-w-full text-center whitespace-nowrap" v-html="f"></div>
            </div>
          </div>
        </div>
      </section>

      <section class="card p-4">
        <h2 class="card-title">{{ t.criteriaDataTitle }}</h2>
        <div class="table-scroll mt-3 rounded-lg border border-line">
          <table class="table min-w-[36rem]">
            <thead>
              <tr>
                <th>{{ t.criterionLabel }}</th>
                <th>{{ t.directionCol }}</th>
                <th>{{ t.weight }}</th>
                <th>{{ t.source }}</th>
              </tr>
            </thead>
            <tbody>
              <tr>
                <td class="font-medium">{{ t.constructionCost }}</td><td class="text-muted">{{ t.minimize }}</td><td class="num whitespace-nowrap text-muted">M USD</td>
                <td class="text-muted">FHWA Interchange Justification Report Guidelines (2023)</td>
              </tr>
              <tr>
                <td class="font-medium">{{ t.landArea }}</td><td class="text-muted">{{ t.minimize }}</td><td class="num whitespace-nowrap text-muted">ha</td>
                <td class="text-muted">TRB NCHRP Report 659</td>
              </tr>
              <tr>
                <td class="font-medium">{{ t.throughput }}</td><td class="text-muted">{{ t.maximize }}</td><td class="num whitespace-nowrap text-muted">veh/hr</td>
                <td class="text-muted">HCM 7th Edition, Chapter 14</td>
              </tr>
              <tr>
                <td class="font-medium">{{ t.safetyIndex }}</td><td class="text-muted">{{ t.maximize }}</td><td class="num whitespace-nowrap text-muted">1–10</td>
                <td class="text-muted">PIARC Road Safety Manual (2019); AASHTO HSM (2022)</td>
              </tr>
            </tbody>
          </table>
        </div>
      </section>

      <section class="card p-4">
        <h2 class="card-title">{{ t.referencesTitle }}</h2>
        <ul class="mt-2 max-w-3xl list-disc space-y-1.5 pl-5 text-[13px] leading-relaxed text-muted [overflow-wrap:anywhere] marker:text-subtle">
          <li>Fishburn, P. C. (1967). Additive utilities with incomplete product sets. <em>Operations Research</em>, 15(3), 537–542.</li>
          <li>Triantaphyllou, E. (2000). <em>Multi-Criteria Decision Making Methods: A Comparative Study.</em> Kluwer Academic Publishers.</li>
          <li>Transportation Research Board (2022). <em>Highway Capacity Manual, 7th Edition.</em></li>
          <li>FHWA (2023). <em>Interchange Justification Report Guidelines.</em></li>
          <li>PIARC (2019). <em>Road Safety Manual.</em></li>
          <li>AASHTO (2022). <em>Highway Safety Manual, 2nd Edition.</em></li>
          <li>Hwang, C. L., Yoon, K. (1981). <em>Multiple Attribute Decision Making: Methods and Applications.</em> Springer.</li>
          <li>Saaty, T. L. (1980). <em>The Analytic Hierarchy Process.</em> McGraw-Hill.</li>
          <li>Brans, J. P., Vincke, Ph. (1985). A preference ranking organisation method. <em>Management Science</em>, 31(6), 647–656.</li>
          <li>Opricovic, S., Tzeng, G.-H. (2004). Compromise solution by MCDM methods: a comparative analysis of VIKOR and TOPSIS. <em>European Journal of Operational Research</em>, 156(2), 445–455.</li>
          <li>Diakoulaki, D., Mavrotas, G., Papayannakis, L. (1995). Determining objective weights in multiple criteria problems: the CRITIC method. <em>Computers &amp; Operations Research</em>, 22(7), 763–770.</li>
          <li>Lahdelma, R., Salminen, P. (2001). SMAA-2: Stochastic multicriteria acceptability analysis for group decision making. <em>Operations Research</em>, 49(3), 444–454.</li>
          <li>Flyvbjerg, B., Holm, M. S., Buhl, S. (2002). Underestimating costs in public works projects: error or lie? <em>Journal of the American Planning Association</em>, 68(3), 279–295.</li>
          <li>Shannon, C. E. (1948). A mathematical theory of communication. <em>Bell System Technical Journal</em>, 27, 379–423.</li>
        </ul>
      </section>
    </div>

    <!-- Right column — weight profile + ranking -->
    <div class="space-y-4 lg:col-span-4">
      <section class="card p-4">
        <h2 class="card-title">{{ t.activeWeightProfile }}</h2>
        <div class="table-scroll mt-3 rounded-lg border border-line">
          <table class="table">
            <thead>
              <tr>
                <th>{{ t.criterionLabel }}</th>
                <th class="text-right">{{ t.weight }}</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="crit in data.criteria" :key="crit.name">
                <td class="text-muted">{{ data.criterion_labels[crit.name] }}</td>
                <td class="num text-right font-medium">{{ (data.normalised_weights[crit.name] * 100).toFixed(0) }}%</td>
              </tr>
            </tbody>
          </table>
        </div>
      </section>

      <section class="card p-4">
        <h2 class="card-title">{{ t.currentRanking }}</h2>
        <div class="mt-3 divide-y divide-line overflow-hidden rounded-lg border border-line">
          <div v-for="res in data.results" :key="res.alternative_name"
               class="flex items-center gap-2.5 px-3 py-2 text-[13px]">
            <span class="w-14 shrink-0">
              <span :class="res.rank === 1 ? 'badge-accent' : 'badge'">
                <Icon v-if="res.rank === 1" name="trophy" />{{ t.ordinals[res.rank - 1] }}
              </span>
            </span>
            <span class="h-2 w-2 shrink-0 rounded-full" :style="{ background: altColor(res.alternative_name) }" aria-hidden="true"></span>
            <span class="flex-1 truncate font-medium">{{ res.alternative_name }}</span>
            <span class="num text-muted">{{ res.total_score.toFixed(4) }}</span>
          </div>
        </div>
      </section>
    </div>
  </div>
</template>

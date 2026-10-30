<script setup>
import { ref } from 'vue'
import { useLocale } from '../composables/useLocale.js'
import { useScenarios } from '../composables/useScenarios.js'
import Icon from './Icon.vue'

// Saved scenarios in the inputs panel: save the current inputs under a name, load one back,
// pick which ones the Compare view shows, and copy a link that opens the same inputs.
const props = defineProps({ dss: Object })
const emit = defineEmits(['compare'])

const { t, locale } = useLocale()
const { scenarios, compared, save, remove, toggleCompared, shareUrl } = useScenarios()

const name = ref('')
const copiedId = ref(null)     // 'current' or a scenario id, for the "Copied" flash
const manualUrl = ref('')      // shown when the clipboard is unavailable (plain http)
let copiedTimer = null

function saveCurrent() {
  if (!name.value.trim()) return
  save(name.value, props.dss.snapshotState())
  name.value = ''
}

async function copyLink(id, state, label) {
  const url = shareUrl(state, label)
  try {
    await navigator.clipboard.writeText(url)
    manualUrl.value = ''
    copiedId.value = id
    clearTimeout(copiedTimer)
    copiedTimer = setTimeout(() => { copiedId.value = null }, 1800)
  } catch {
    manualUrl.value = url
  }
}

function savedAt(iso) {
  return new Date(iso).toLocaleString(locale.value === 'uk' ? 'uk-UA' : 'en-GB',
    { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' })
}
</script>

<template>
  <div>
    <p class="mb-3 text-xs text-subtle">{{ t.scenariosDesc }}</p>
    <form class="flex gap-1.5" @submit.prevent="saveCurrent">
      <input v-model="name" type="text" maxlength="60" class="field min-w-0 flex-1"
             :placeholder="t.scenarioNamePlaceholder" :aria-label="t.scenarioNamePlaceholder" />
      <button type="submit" class="btn shrink-0" :disabled="!name.trim()">{{ t.scenarioSave }}</button>
    </form>
    <button type="button" class="btn-ghost mt-1.5 -ml-2"
            @click="copyLink('current', dss.snapshotState(), '')">
      <Icon :name="copiedId === 'current' ? 'check' : 'link'" class="text-sm" />
      {{ copiedId === 'current' ? t.scenarioLinkCopied : t.scenarioCopyLink }}
    </button>
    <input v-if="manualUrl" :value="manualUrl" readonly class="field num mt-1.5 text-xs"
           :aria-label="t.scenarioCopyManually" :title="t.scenarioCopyManually" @focus="$event.target.select()" />

    <ul v-if="scenarios.length" class="mt-3 divide-y divide-line rounded-lg border border-line bg-surface">
      <li v-for="s in scenarios" :key="s.id" class="flex items-center gap-1 py-1 pr-1 pl-2">
        <button type="button" class="icon-btn shrink-0" role="checkbox" :aria-checked="compared.includes(s.id)"
                :title="t.scenarioCompareToggle" :aria-label="t.scenarioCompareToggle"
                @click="toggleCompared(s.id)">
          <span class="flex h-4 w-4 items-center justify-center rounded border transition-colors"
                :class="compared.includes(s.id) ? 'border-accent bg-accent text-accent-fg' : 'border-line-strong'">
            <Icon v-if="compared.includes(s.id)" name="check" class="text-[11px]" />
          </span>
        </button>
        <button type="button" class="min-w-0 flex-1 rounded-md px-1 py-1 text-left hover:bg-surface-2"
                :title="t.scenarioLoad" @click="dss.applyState(s.state)">
          <span class="block truncate text-[13px] font-medium">{{ s.name }}</span>
          <span class="block truncate text-[11px] text-subtle">{{ s.state.context }} · {{ savedAt(s.savedAt) }}</span>
        </button>
        <button type="button" class="icon-btn shrink-0" :title="t.scenarioCopyLink" :aria-label="t.scenarioCopyLink"
                @click="copyLink(s.id, s.state, s.name)">
          <Icon :name="copiedId === s.id ? 'check' : 'link'" class="text-sm" />
        </button>
        <button type="button" class="icon-btn shrink-0" :title="t.scenarioDelete" :aria-label="t.scenarioDelete"
                @click="remove(s.id)">
          <Icon name="trash" class="text-sm" />
        </button>
      </li>
    </ul>
    <button v-if="scenarios.length" type="button" class="btn mt-3 w-full" @click="emit('compare')">
      {{ t.scenarioCompare }} <Icon name="chevron-right" class="text-sm" />
    </button>
  </div>
</template>

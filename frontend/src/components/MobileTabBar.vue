<script setup>
import { computed, ref } from 'vue'
import { useLocale } from '../composables/useLocale.js'
import { useTheme } from '../composables/useTheme.js'
import Icon from './Icon.vue'
import Sheet from './Sheet.vue'

// Phone navigation: a bottom tab bar (iOS keeps it to five) with the less-used views and the
// app preferences in a "More" sheet.
const props = defineProps({ active: String })
const emit = defineEmits(['update'])

const { t, locale, setLocale } = useLocale()
const { dark, setDark } = useTheme()

const PRIMARY = [
  { id: 'inputs',     icon: 'sliders' },
  { id: 'evaluation', icon: 'chart-column' },
  { id: 'site',       icon: 'map' },
  { id: 'model',      icon: 'activity' },
]
const MORE = [
  { id: 'robustness',  icon: 'shield-check', title: 'tabRobustness' },
  { id: 'gallery',     icon: 'layout-grid',  title: 'tabGallery' },
  { id: 'methodology', icon: 'book-open',    title: 'tabMethodology' },
]

const moreOpen = ref(false)
const inMore = computed(() => MORE.some(m => m.id === props.active))

function label(id) {
  return id === 'inputs' ? t.value.tabInputs : t.value.tabShort[id]
}

function pick(id) {
  moreOpen.value = false
  emit('update', id)
}
</script>

<template>
  <nav class="material-bar fixed inset-x-0 bottom-0 z-30 border-t border-line pb-safe md:hidden">
    <div class="grid h-[52px] grid-cols-5">
      <button v-for="tab in PRIMARY" :key="tab.id" type="button"
              :aria-current="active === tab.id ? 'page' : undefined"
              class="flex flex-col items-center justify-center gap-0.5 transition-colors duration-150"
              :class="active === tab.id ? 'text-accent' : 'text-subtle'"
              @click="pick(tab.id)">
        <Icon :name="tab.icon" class="text-[22px]" />
        <span class="max-w-full truncate px-0.5 text-[10px] font-medium">{{ label(tab.id) }}</span>
      </button>
      <button type="button" :aria-expanded="moreOpen"
              class="flex flex-col items-center justify-center gap-0.5 transition-colors duration-150"
              :class="inMore || moreOpen ? 'text-accent' : 'text-subtle'"
              @click="moreOpen = true">
        <Icon name="more" class="text-[22px]" />
        <span class="text-[10px] font-medium">{{ inMore ? t.tabShort[active] : t.tabMore }}</span>
      </button>
    </div>
  </nav>

  <Sheet :open="moreOpen" :title="t.tabMore" :done-label="t.done" @close="moreOpen = false">
    <div class="card overflow-hidden">
      <button v-for="(item, i) in MORE" :key="item.id" type="button"
              class="flex min-h-11 w-full items-center gap-3 px-4 text-left text-[15px] active:bg-surface-2"
              :class="i ? 'border-t border-line' : ''"
              @click="pick(item.id)">
        <Icon :name="item.icon" class="text-lg text-accent" />
        <span class="flex-1">{{ t[item.title] }}</span>
        <Icon v-if="active === item.id" name="check" class="text-base text-accent" />
        <Icon v-else name="chevron-right" class="text-sm text-subtle" />
      </button>
    </div>

    <p class="eyebrow mt-5 mb-1.5 px-4">{{ t.appearance }}</p>
    <div class="seg grid w-full grid-cols-2" role="radiogroup" :aria-label="t.appearance">
      <button type="button" role="radio" class="seg-item" :aria-checked="!dark" @click="setDark(false)">{{ t.themeLight }}</button>
      <button type="button" role="radio" class="seg-item" :aria-checked="dark" @click="setDark(true)">{{ t.themeDark }}</button>
    </div>

    <p class="eyebrow mt-5 mb-1.5 px-4">{{ t.language }}</p>
    <div class="seg grid w-full grid-cols-2" role="radiogroup" :aria-label="t.language">
      <button type="button" role="radio" class="seg-item" :aria-checked="locale === 'uk'" @click="setLocale('uk')">Українська</button>
      <button type="button" role="radio" class="seg-item" :aria-checked="locale === 'en'" @click="setLocale('en')">English</button>
    </div>

    <p class="mt-5 px-4 text-xs leading-snug text-subtle">{{ t.dataFooter }}</p>
  </Sheet>
</template>

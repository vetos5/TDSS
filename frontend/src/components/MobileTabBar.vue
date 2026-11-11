<script setup>
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { useLocale } from '../composables/useLocale.js'
import { useTheme } from '../composables/useTheme.js'
import Icon from './Icon.vue'
import Sheet from './Sheet.vue'

// Phone navigation: a floating glass pill with the main views and a round glass "More" button
// beside it for the less-used views and the app preferences. The active tab widens to show its
// label and a highlight slides under it; the others are icons only.
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
  { id: 'engineering', icon: 'gauge',        title: 'tabEngineering' },
  { id: 'economics',   icon: 'coins',        title: 'tabEconomics' },
  { id: 'robustness',  icon: 'shield-check', title: 'tabRobustness' },
  { id: 'compare',     icon: 'columns',      title: 'tabCompare' },
  { id: 'group',       icon: 'users',        title: 'tabGroup' },
  { id: 'gallery',     icon: 'layout-grid',  title: 'tabGallery' },
  { id: 'methodology', icon: 'book-open',    title: 'tabMethodology' },
  { id: 'report',      icon: 'file' },   // opens the decision report, not a tab
]

const moreOpen = ref(false)
const moreItem = computed(() => MORE.find(m => m.id === props.active))
const activeIndex = computed(() => PRIMARY.findIndex(p => p.id === props.active))

// Slot geometry: the active slot takes ACTIVE_WEIGHT shares of the row, the others one each.
// The highlight is placed from the same arithmetic, so it moves in step with the flex-grow
// transition instead of waiting for layout to settle and measuring it.
const PAD = 6
const ACTIVE_WEIGHT = 2.4
const row = ref(null)
const rowWidth = ref(0)
let observer = null
onMounted(() => {
  observer = new ResizeObserver(([entry]) => { rowWidth.value = entry.contentRect.width })
  observer.observe(row.value)
})
onBeforeUnmount(() => observer?.disconnect())

const highlight = computed(() => {
  const i = activeIndex.value
  const unit = rowWidth.value / (PRIMARY.length - 1 + ACTIVE_WEIGHT)
  return {
    width: `${unit * ACTIVE_WEIGHT}px`,
    transform: `translateX(${Math.max(i, 0) * unit}px)`,
    opacity: i < 0 || !rowWidth.value ? 0 : 1,
  }
})

function label(id) {
  return t.value.tabShort[id]
}

function pick(id) {
  moreOpen.value = false
  emit('update', id)
}
</script>

<template>
  <nav class="pointer-events-none fixed inset-x-0 bottom-0 z-30 flex items-center gap-2 px-3 pb-[calc(env(safe-area-inset-bottom)+10px)] md:hidden">
    <div class="glass pointer-events-auto h-16 min-w-0 flex-1 rounded-full" :style="{ padding: `${PAD}px` }">
      <div ref="row" class="relative flex h-full" role="tablist">
        <span class="liquid-ease absolute inset-y-0 left-0 rounded-full bg-[var(--glass-track)]" :style="highlight"
              aria-hidden="true"></span>
        <button v-for="(tab, i) in PRIMARY" :key="tab.id" type="button" role="tab"
                :aria-selected="i === activeIndex" :aria-label="label(tab.id)"
                class="liquid-ease relative flex min-w-0 basis-0 items-center justify-center rounded-full px-2"
                :class="i === activeIndex ? 'text-fg' : 'text-muted'"
                :style="{ flexGrow: i === activeIndex ? ACTIVE_WEIGHT : 1 }"
                @click="pick(tab.id)">
          <Icon :name="tab.icon" class="shrink-0 text-[21px]" />
          <span class="liquid-ease truncate text-[13px] font-semibold"
                :class="i === activeIndex ? 'ml-1.5 max-w-[7rem] opacity-100' : 'ml-0 max-w-0 opacity-0'">
            {{ label(tab.id) }}
          </span>
        </button>
      </div>
    </div>

    <button type="button" :aria-expanded="moreOpen" :aria-label="moreItem ? label(moreItem.id) : t.tabMore"
            class="glass liquid-ease pointer-events-auto flex h-16 w-16 shrink-0 items-center justify-center rounded-full active:scale-95"
            :class="moreItem || moreOpen ? 'text-fg' : 'text-muted'"
            @click="moreOpen = true">
      <span class="liquid-ease absolute inset-1.5 rounded-full bg-[var(--glass-track)]"
            :class="moreItem ? 'opacity-100' : 'opacity-0'" aria-hidden="true"></span>
      <Icon :name="moreItem && moreItem.id !== 'report' ? moreItem.icon : 'more'" class="relative text-[22px]" />
    </button>
  </nav>

  <Sheet :open="moreOpen" :title="t.tabMore" :done-label="t.done" @close="moreOpen = false">
    <div class="card overflow-hidden">
      <button v-for="(item, i) in MORE" :key="item.id" type="button"
              class="flex min-h-12 w-full items-center gap-3 px-4 text-left text-[15px] active:bg-surface-2"
              :class="i ? 'border-t border-line' : ''"
              @click="pick(item.id)">
        <span class="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-[var(--glass-track)]">
          <Icon :name="item.icon" class="text-[17px]" />
        </span>
        <span class="flex-1" :class="active === item.id ? 'font-semibold' : ''">
          {{ item.title ? t[item.title] : t.report.title }}
        </span>
        <Icon v-if="active === item.id" name="check" class="text-base" />
        <Icon v-else name="chevron-right" class="text-sm text-subtle" />
      </button>
    </div>

    <div class="card mt-4 flex min-h-12 items-center gap-3 py-1.5 pl-4 pr-1.5">
      <span class="flex-1 text-[15px]">{{ t.appearance }}</span>
      <div class="seg" role="radiogroup" :aria-label="t.appearance">
        <button type="button" role="radio" class="seg-item inline-flex w-12 items-center justify-center !px-0"
                :aria-checked="!dark" :aria-label="t.themeLight" :title="t.themeLight" @click="setDark(false)">
          <Icon name="sun" class="text-[17px]" />
        </button>
        <button type="button" role="radio" class="seg-item inline-flex w-12 items-center justify-center !px-0"
                :aria-checked="dark" :aria-label="t.themeDark" :title="t.themeDark" @click="setDark(true)">
          <Icon name="moon" class="text-[17px]" />
        </button>
      </div>
    </div>

    <p class="eyebrow mt-5 mb-1.5 px-4">{{ t.language }}</p>
    <div class="seg grid w-full grid-cols-2" role="radiogroup" :aria-label="t.language">
      <button type="button" role="radio" class="seg-item" :aria-checked="locale === 'uk'" @click="setLocale('uk')">Українська</button>
      <button type="button" role="radio" class="seg-item" :aria-checked="locale === 'en'" @click="setLocale('en')">English</button>
    </div>

    <p class="mt-5 px-4 text-xs leading-snug text-subtle">{{ t.dataFooter }}</p>
  </Sheet>
</template>

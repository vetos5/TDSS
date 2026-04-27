<script setup>
import { useLocale } from '../composables/useLocale.js'

defineProps({ dark: Boolean })

const { locale, setLocale } = useLocale()
</script>

<template>
  <div class="flex items-center gap-1 rounded-xl p-0.5"
       :class="dark
         ? 'bg-slate-700 border border-slate-600'
         : 'bg-white/80 border border-black/5 shadow-[0_1px_3px_rgb(0,0,0,0.06)]'">
    <button
      @click="setLocale('uk')"
      class="h-7 px-2.5 rounded-lg text-[0.68rem] font-bold tracking-widest transition-all duration-200 active:scale-[0.92]"
      :class="locale === 'uk'
        ? (dark ? 'bg-teal-600 text-white' : 'bg-teal-700 text-white shadow-sm')
        : (dark ? 'text-slate-400 hover:text-slate-200' : 'text-slate-500 hover:text-slate-700')"
      :aria-label="$t('switchLang')"
    >
      UA
    </button>
    <button
      @click="setLocale('en')"
      class="h-7 px-2.5 rounded-lg text-[0.68rem] font-bold tracking-widest transition-all duration-200 active:scale-[0.92]"
      :class="locale === 'en'
        ? (dark ? 'bg-teal-600 text-white' : 'bg-teal-700 text-white shadow-sm')
        : (dark ? 'text-slate-400 hover:text-slate-200' : 'text-slate-500 hover:text-slate-700')"
      :aria-label="$t('switchLang')"
    >
      EN
    </button>
  </div>
</template>

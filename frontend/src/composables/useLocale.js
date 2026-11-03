import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { i18n } from '../i18n.js'

export function useLocale() {
  const { locale, messages, t: $t } = useI18n()

  const setLocale = (newLocale) => {
    locale.value = newLocale
    localStorage.setItem('locale', newLocale)
  }

  const toggleLang = () => setLocale(locale.value === 'uk' ? 'en' : 'uk')

  const lang = computed(() => locale.value === 'uk' ? 'UA' : 'EN')

  const t = computed(() => messages.value[locale.value] ?? messages.value['en'])

  // Display name of a task context; the API key (e.g. "T-Type (3 Directions)") stays the value.
  const ctxName = (key) => t.value.contextNames?.[key] ?? key

  return { locale, lang, setLocale, toggleLang, t, ctxName }
}

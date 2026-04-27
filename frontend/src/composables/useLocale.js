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

  return { locale, lang, setLocale, toggleLang, t }
}

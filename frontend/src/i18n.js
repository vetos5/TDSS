import { createI18n } from 'vue-i18n'
import uk from './locales/uk.json'
import en from './locales/en.json'

const savedLocale = localStorage.getItem('locale')
const defaultLocale = savedLocale && ['uk', 'en'].includes(savedLocale) ? savedLocale : 'uk'

export const i18n = createI18n({
  legacy: false,
  locale: defaultLocale,
  fallbackLocale: 'en',
  messages: { uk, en },
})

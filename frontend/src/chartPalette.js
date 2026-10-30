// Chart colours validated with the dataviz palette validator against this app's panel
// surfaces (light ≈ #f7f7f9, dark ≈ #1e293b). Colour follows the entity, never its rank.

// Categorical slots for MCDA methods (fixed order, never cycled). Light slots below 3:1
// contrast are always shipped with a legend plus a table view.
export const METHOD_COLORS = {
  light: { wsm: '#2a78d6', topsis: '#eb6834', ahp: '#1baf7a', promethee: '#eda100', vikor: '#e87ba4' },
  dark:  { wsm: '#3987e5', topsis: '#d95926', ahp: '#199e70', promethee: '#c98500', vikor: '#d55181' },
}

// Ordinal blue ramp for ranks: rank 1 carries the strongest step in each theme.
const RANK_RAMP = {
  light: ['#0d366b', '#184f95', '#256abf', '#3987e5', '#6da7ec'],
  dark:  ['#cde2fb', '#9ec5f4', '#6da7ec', '#3987e5', '#256abf'],
}

export function rankColors(m, dark) {
  const ramp = RANK_RAMP[dark ? 'dark' : 'light']
  if (m <= 1) return [ramp[0]]
  return Array.from({ length: m }, (_, i) => ramp[Math.round((i * (ramp.length - 1)) / (m - 1))])
}

// Diverging blue ↔ red with a neutral grey midpoint (for correlations in [-1, 1]).
export function divergingScale(dark) {
  return [[0, '#e34948'], [0.5, dark ? '#383835' : '#f0efec'], [1, dark ? '#3987e5' : '#2a78d6']]
}

export const SURFACE = { light: '#f7f7f9', dark: '#1e293b' }

export function chartInk(dark) {
  return {
    text: dark ? '#e2e8f0' : '#0f172a',
    muted: dark ? '#94a3b8' : '#475569',
    grid: dark ? '#334155' : '#e2e8f0',
  }
}

// Prediction-model chart: expert constant vs model prediction (two categorical slots,
// validated as a pair in both themes; markers also differ in shape: diamond vs circle).
export const MODEL_COLORS = {
  light: { expert: '#eb6834', model: '#2a78d6' },
  dark:  { expert: '#d95926', model: '#3987e5' },
}

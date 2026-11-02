export const backendKeyMap = {
  Active: 'backend.project_active',
  Closed: 'backend.project_closed',
  Pending: 'backend.project_pending',
  Flat: 'backend.terrain_flat',
  Rolling: 'backend.terrain_rolling',
  Mountainous: 'backend.terrain_mountainous',
  Low: 'backend.env_low',
  Medium: 'backend.env_medium',
  High: 'backend.env_high',
  Critical: 'backend.env_critical',
  maximize: 'backend.direction_maximize',
  minimize: 'backend.direction_minimize',
}

// The fixed 503 texts of the GIS clients (app/infrastructure/gis/errors.py), keyed by their
// exact English wording; api.js errorText() shows the localised apiErrors entry instead.
export const backendErrorKeyMap = {
  'The map data service is unavailable right now. Try again in a minute.': 'mapUnavailable',
  "Today's quota of map data requests is used up. Points analysed before still work; try new points tomorrow.": 'mapQuota',
  "You have used today's share of new map data requests. Points analysed before still work; try new points tomorrow.": 'mapClientQuota',
  'There is too much map data around this point. Choose a smaller radius.': 'mapTooMuchData',
  'The map data service could not finish this query. Try a smaller radius or try again later.': 'mapQueryFailed',
}

// The site analysis notes (app/application/site_analysis.py), keyed by their exact English
// wording; SiteMap.vue shows the localised siteNotes entry instead.
export const siteNoteKeyMap = {
  "Two road corridors found, but neither reaches motorway/trunk class; context guessed as the most common case -- confirm manually.": 'twoMinor',
  "Only one major road corridor found near this point; a junction needs at least two -- confirm the context manually.": 'oneCorridor',
  "No major roads (tertiary or above) found within the search radius; confirm the context manually or widen the radius.": 'noRoads',
  "No usable elevation data in the search grid; terrain defaulted to Flat -- confirm manually.": 'noElevationData',
  "Elevation data is unavailable right now; terrain defaulted to Flat -- confirm manually.": 'elevationUnavailable',
}

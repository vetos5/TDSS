// Downloads for professional tools: CSV for spreadsheets, GeoJSON and KML for GIS / Google Earth.
// Everything is built in the browser from data already on screen.

export function download(filename, text, mime) {
  const blob = new Blob([text], { type: mime })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  document.body.appendChild(a)
  a.click()
  a.remove()
  setTimeout(() => URL.revokeObjectURL(url), 1000)
}

function cell(v) {
  if (v == null) return ''
  const s = String(v)
  return /[",\n\r]/.test(s) ? `"${s.replaceAll('"', '""')}"` : s
}

// rows: arrays of values, the first one the header. A byte-order mark lets Excel read UTF-8.
export function downloadCsv(filename, rows) {
  const text = '﻿' + rows.map(r => r.map(cell).join(',')).join('\r\n') + '\r\n'
  download(filename, text, 'text/csv;charset=utf-8')
}

export function slug(s) {
  return String(s).toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '') || 'tdss'
}

// Footprint segments ([[lat, lon], …]) as GeoJSON LineStrings ([lon, lat], RFC 7946).
export function footprintGeoJSON(footprint, alternative) {
  return JSON.stringify({
    type: 'FeatureCollection',
    features: footprint.segments.map(s => ({
      type: 'Feature',
      properties: { alternative, id: s.id, kind: s.kind, width_m: s.width_m },
      geometry: { type: 'LineString', coordinates: s.coords.map(([lat, lon]) => [lon, lat]) },
    })),
  }, null, 1)
}

const xml = s => String(s).replace(/[<>&"']/g, c => ({ '<': '&lt;', '>': '&gt;', '&': '&amp;', '"': '&quot;', "'": '&apos;' }[c]))

export function footprintKML(footprint, alternative) {
  const STYLE = { mainline: 'ff3c3c3c', crossroad: 'ff787878', ramp: 'ffd6782a', road: 'ffa0a0a0' }
  const marks = footprint.segments.map(s => `
    <Placemark>
      <name>${xml(s.id)}</name>
      <description>${xml(`${s.kind}, ${s.width_m} m`)}</description>
      <Style><LineStyle><color>${STYLE[s.kind] ?? STYLE.road}</color><width>${Math.max(2, Math.round(s.width_m / 3))}</width></LineStyle></Style>
      <LineString><tessellate>1</tessellate><coordinates>${s.coords.map(([lat, lon]) => `${lon},${lat},0`).join(' ')}</coordinates></LineString>
    </Placemark>`).join('')
  return `<?xml version="1.0" encoding="UTF-8"?>
<kml xmlns="http://www.opengis.net/kml/2.2">
  <Document>
    <name>${xml(alternative)} — TDSS footprint</name>${marks}
  </Document>
</kml>
`
}

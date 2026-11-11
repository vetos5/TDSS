// Pure geometry builders for the 3D interchange viewer. Plain arrays in, typed arrays out, no
// three.js and no DOM, so they can be tested in Node. All heights, grades and pier positions come
// from the backend (`/api/interchange/{name}/model3d`); this file only turns them into triangles.
//
// Coordinates: the API is x east, y north, z up (metres). Output is three.js space:
// x = east, y = up, z = -north. Triangles wind counter-clockwise seen from outside.

export const BASE_Y = -0.2          // walls and piers start slightly below the ground (-0.05)
const SLAB_THICKNESS = 1.2
const SLAB_OVERHANG = 0.6           // slab edge beyond the carriageway
const PARAPET_WIDTH = 0.3
const PARAPET_HEIGHT = 0.9
const DECK_MIN_Z = 0.3              // below this the road is on the ground: asphalt only
const MARK_LIFT = 0.05
const EDGE_INSET = 0.3
const LINE_WIDTH = 0.15
const DASH_ON = 6
const DASH_OFF = 9

// ── Mesh accumulator ────────────────────────────────────────────────────────

class MeshData {
  constructor(withColor = false) {
    this.p = []
    this.c = withColor ? [] : null
    this.i = []
    this.n = 0
  }
  vert(x, y, z, rgb) {
    this.p.push(x, y, z)
    if (this.c) this.c.push(rgb[0], rgb[1], rgb[2])
    return this.n++
  }
  tri(a, b, c) { this.i.push(a, b, c) }
  quad(a, b, c, d) { this.i.push(a, b, c, a, c, d) }
  arrays() {
    const out = { positions: new Float32Array(this.p), indices: new Uint32Array(this.i) }
    if (this.c) out.colors = new Float32Array(this.c)
    return out
  }
}

// A quad given as four points, wound so that its normal points away from (cx, cy, cz).
function quadOut(md, q, cx, cy, cz, rgb) {
  const [a, b, c] = q
  const ux = b[0] - a[0], uy = b[1] - a[1], uz = b[2] - a[2]
  const vx = c[0] - a[0], vy = c[1] - a[1], vz = c[2] - a[2]
  const nx = uy * vz - uz * vy, ny = uz * vx - ux * vz, nz = ux * vy - uy * vx
  const mx = (q[0][0] + q[2][0]) / 2 - cx, my = (q[0][1] + q[2][1]) / 2 - cy, mz = (q[0][2] + q[2][2]) / 2 - cz
  const ids = q.map(p => md.vert(p[0], p[1], p[2], rgb))
  if (nx * mx + ny * my + nz * mz >= 0) md.quad(ids[0], ids[1], ids[2], ids[3])
  else md.quad(ids[0], ids[3], ids[2], ids[1])
}

// Closed box from eight corners indexed by bit (x:1, y:2, z:4), outward faces, flat normals.
function boxFromCorners(md, k, rgb) {
  const cx = k.reduce((s, p) => s + p[0], 0) / 8
  const cy = k.reduce((s, p) => s + p[1], 0) / 8
  const cz = k.reduce((s, p) => s + p[2], 0) / 8
  const faces = [
    [0, 1, 3, 2], [4, 5, 7, 6],   // z = lo, z = hi
    [0, 1, 5, 4], [2, 3, 7, 6],   // y = lo, y = hi
    [0, 2, 6, 4], [1, 3, 7, 5],   // x = lo, x = hi
  ]
  for (const f of faces) quadOut(md, f.map(j => k[j]), cx, cy, cz, rgb)
}

// Box with its length along (ux, uz) (unit, horizontal), spanning y0..y1.
function orientedBox(md, cx, cz, y0, y1, halfLen, halfWid, ux, uz, rgb) {
  const vx = -uz, vz = ux
  const k = []
  for (let b = 0; b < 8; b++) {
    const sl = (b & 1) ? halfLen : -halfLen
    const sw = (b & 2) ? halfWid : -halfWid
    k.push([cx + ux * sl + vx * sw, (b & 4) ? y1 : y0, cz + uz * sl + vz * sw])
  }
  boxFromCorners(md, k, rgb)
}

// Prism with a regular polygon base (a round-ish column), axis vertical.
function prism(md, cx, cz, y0, y1, radius, sides) {
  const ring = []
  for (let s = 0; s < sides; s++) {
    const a = (s / sides) * Math.PI * 2
    ring.push([cx + Math.cos(a) * radius, cz + Math.sin(a) * radius])
  }
  const my = (y0 + y1) / 2
  for (let s = 0; s < sides; s++) {
    const [ax, az] = ring[s], [bx, bz] = ring[(s + 1) % sides]
    quadOut(md, [[ax, y0, az], [bx, y0, bz], [bx, y1, bz], [ax, y1, az]], cx, my, cz)
  }
  // Caps as fans.
  const top = md.vert(cx, y1, cz), bot = md.vert(cx, y0, cz)
  const t = ring.map(([x, z]) => md.vert(x, y1, z)), b = ring.map(([x, z]) => md.vert(x, y0, z))
  for (let s = 0; s < sides; s++) {
    const n = (s + 1) % sides
    md.tri(top, t[n], t[s])   // up
    md.tri(bot, b[s], b[n])   // down
  }
}

// ── Paths ───────────────────────────────────────────────────────────────────

// Convert API points to three space, drop repeated points, and attach per-point frames:
// P (position), L (unit horizontal left vector), S (mitre scale for lateral offsets), cum (arc length).
function preparePath(points) {
  const P = []
  for (const q of points || []) {
    if (!q || q.length < 3 || !q.every(Number.isFinite)) continue
    const p = [q[0], q[2], -q[1]]
    const last = P[P.length - 1]
    if (last && Math.hypot(p[0] - last[0], p[2] - last[2]) < 1e-6 && Math.abs(p[1] - last[1]) < 1e-6) continue
    P.push(p)
  }
  const n = P.length
  if (n < 2) return null

  // Horizontal unit direction of each leg.
  const D = []
  for (let i = 0; i < n - 1; i++) {
    const dx = P[i + 1][0] - P[i][0], dz = P[i + 1][2] - P[i][2]
    const h = Math.hypot(dx, dz)
    D.push(h > 1e-9 ? [dx / h, dz / h] : (D[i - 1] || [1, 0]))
  }
  const L = [], S = []
  for (let i = 0; i < n; i++) {
    const a = D[Math.max(0, i - 1)], b = D[Math.min(n - 2, i)]
    let tx = a[0] + b[0], tz = a[1] + b[1]
    let h = Math.hypot(tx, tz)
    if (h < 1e-6) { tx = b[0]; tz = b[1]; h = 1 }   // a hairpin: use the outgoing leg
    tx /= h; tz /= h
    L.push([tz, -tx])
    const cos = Math.max(0.5, tx * b[0] + tz * b[1])
    S.push(1 / cos)
  }
  const cum = [0]
  for (let i = 1; i < n; i++) {
    cum.push(cum[i - 1] + Math.hypot(P[i][0] - P[i - 1][0], P[i][1] - P[i - 1][1], P[i][2] - P[i - 1][2]))
  }
  return { n, P, L, S, cum, length: cum[n - 1] }
}

// Point at lateral offset o (left positive) and absolute height y of path point i.
function lat(path, i, o, y) {
  const p = path.P[i], l = path.L[i], k = o * path.S[i]
  return [p[0] + l[0] * k, y, p[2] + l[1] * k]
}

// Strip along the path indices a..b between lateral offsets o0 (right) and o1 (left) at height
// y(i). Normal faces up. `from` / `to` give the interpolated sub-range of points to use.
function topStrip(md, pts) {
  // pts: array of [leftPoint, rightPoint]
  if (pts.length < 2) return
  const ids = pts.map(([l, r]) => [md.vert(...l), md.vert(...r)])
  for (let i = 0; i < ids.length - 1; i++) {
    const [l0, r0] = ids[i], [l1, r1] = ids[i + 1]
    md.tri(l0, r0, l1)
    md.tri(r0, r1, l1)
  }
}

// Vertical face strip: pairs of [a, b] points, quads between consecutive pairs, normal given by
// (b - a) x (a_next - a).
function faceStrip(md, pairs) {
  if (pairs.length < 2) return
  const ids = pairs.map(([a, b]) => [md.vert(...a), md.vert(...b)])
  for (let i = 0; i < ids.length - 1; i++) {
    const [a0, b0] = ids[i], [a1, b1] = ids[i + 1]
    md.tri(a0, b0, a1)
    md.tri(b0, b1, a1)
  }
}

// Contiguous index runs [a, b] (a < b) where pred(i) holds for every point of the run.
function runs(n, pred) {
  const out = []
  let a = -1
  for (let i = 0; i <= n; i++) {
    const ok = i < n && pred(i)
    if (ok && a < 0) a = i
    if (!ok && a >= 0) { if (i - 1 > a) out.push([a, i - 1]); a = -1 }
  }
  return out
}

// Prism along path indices a..b, lateral o0 < o1, bottom/top heights per point.
// Faces: top, left (o1), right (o0), optional bottom, and two end caps.
function prismRun(md, path, a, b, o0, o1, bot, top, { bottom = true, caps = true } = {}) {
  const idx = []
  for (let i = a; i <= b; i++) idx.push(i)
  topStrip(md, idx.map(i => [lat(path, i, o1, top[i]), lat(path, i, o0, top[i])]))
  faceStrip(md, idx.map(i => [lat(path, i, o1, bot[i]), lat(path, i, o1, top[i])]))   // left, outward
  faceStrip(md, idx.map(i => [lat(path, i, o0, top[i]), lat(path, i, o0, bot[i])]))   // right, outward
  if (bottom) topStrip(md, idx.map(i => [lat(path, i, o0, bot[i]), lat(path, i, o1, bot[i])]))   // normal down
  if (caps) {
    // End cap facing forward (+d): left to right, bottom row A, top row B.
    const e = b
    faceStrip(md, [
      [lat(path, e, o1, bot[e]), lat(path, e, o1, top[e])],
      [lat(path, e, o0, bot[e]), lat(path, e, o0, top[e])],
    ])
    // Start cap facing backward (-d): right to left.
    const s = a
    faceStrip(md, [
      [lat(path, s, o0, bot[s]), lat(path, s, o0, top[s])],
      [lat(path, s, o1, bot[s]), lat(path, s, o1, top[s])],
    ])
  }
}

// Interpolated frame at arc length s: { p: [x,y,z], l: [lx,lz] }.
function frameAt(path, s) {
  const cum = path.cum
  let lo = 0, hi = path.n - 1
  while (hi - lo > 1) {
    const mid = (lo + hi) >> 1
    if (cum[mid] <= s) lo = mid; else hi = mid
  }
  const span = cum[hi] - cum[lo]
  const f = span > 1e-9 ? Math.min(1, Math.max(0, (s - cum[lo]) / span)) : 0
  return { lo, hi, f }
}

function lerpFrame(path, s) {
  const { lo, hi, f } = frameAt(path, s)
  const a = path.P[lo], b = path.P[hi], la = path.L[lo], lb = path.L[hi]
  let lx = la[0] + (lb[0] - la[0]) * f, lz = la[1] + (lb[1] - la[1]) * f
  const h = Math.hypot(lx, lz) || 1
  lx /= h; lz /= h
  const sc = path.S[lo] + (path.S[hi] - path.S[lo]) * f
  return {
    p: [a[0] + (b[0] - a[0]) * f, a[1] + (b[1] - a[1]) * f, a[2] + (b[2] - a[2]) * f],
    l: [lx, lz],
    sc,
  }
}

// Strip between lateral offsets o0..o1 following the path from arc length s0 to s1 at height
// z(point) + lift. Used for lane markings (dashes and continuous lines).
function markingStrip(md, path, s0, s1, o0, o1, lift) {
  const pts = []
  const push = (s) => {
    const fr = lerpFrame(path, s)
    const mk = (o) => [fr.p[0] + fr.l[0] * o * fr.sc, fr.p[1] + lift, fr.p[2] + fr.l[1] * o * fr.sc]
    pts.push([mk(o1), mk(o0)])
  }
  push(s0)
  for (let i = 0; i < path.n; i++) {
    if (path.cum[i] > s0 + 1e-6 && path.cum[i] < s1 - 1e-6) push(path.cum[i])
  }
  push(s1)
  topStrip(md, pts)
}

// ── Public: road and structure meshes ───────────────────────────────────────

// Returns { asphalt, markings, concrete }, each { positions: Float32Array, indices: Uint32Array }.
export function buildInterchange(model) {
  const asphalt = new MeshData(), marks = new MeshData(), concrete = new MeshData()
  const fillBelow = Number.isFinite(model.fill_below_m) ? model.fill_below_m : 3

  const paths = []
  for (const seg of model.segments || []) {
    const path = preparePath(seg.points)
    if (!path) continue
    paths.push(path)
    const w = Number(seg.width_m) > 0 ? Number(seg.width_m) : 7
    const hw = w / 2
    const lanes = Math.max(1, Math.round(seg.lanes || 1))

    // Road surface.
    const all = []
    for (let i = 0; i < path.n; i++) all.push(i)
    topStrip(asphalt, all.map(i => [lat(path, i, hw, path.P[i][1]), lat(path, i, -hw, path.P[i][1])]))

    // Lane markings: solid edge lines inside each edge, dashed separators between lanes.
    const lift = MARK_LIFT
    const eo = hw - EDGE_INSET
    markingStrip(marks, path, 0, path.length, eo - LINE_WIDTH / 2, eo + LINE_WIDTH / 2, lift)
    markingStrip(marks, path, 0, path.length, -eo - LINE_WIDTH / 2, -eo + LINE_WIDTH / 2, lift)
    for (let k = 1; k < lanes; k++) {
      const o = -hw + (w / lanes) * k
      for (let s = DASH_ON * 0.5; s < path.length; s += DASH_ON + DASH_OFF) {
        const e = Math.min(path.length, s + DASH_ON)
        if (e - s > 0.5) markingStrip(marks, path, s, e, o - LINE_WIDTH / 2, o + LINE_WIDTH / 2, lift)
      }
    }

    // Decks, parapets, fill walls.
    const z = path.P.map(p => p[1])
    const slabTop = z.map(v => v - 0.05)
    const slabBot = z.map(v => (v < fillBelow ? BASE_Y : Math.max(BASE_Y, v - SLAB_THICKNESS)))
    const parTop = z.map(v => v + PARAPET_HEIGHT)
    const hwd = hw + SLAB_OVERHANG
    for (const [a, b] of runs(path.n, i => z[i] > DECK_MIN_Z)) {
      prismRun(concrete, path, a, b, -hwd, hwd, slabBot, slabTop)
      prismRun(concrete, path, a, b, hwd - PARAPET_WIDTH, hwd, slabTop, parTop, { bottom: false })
      prismRun(concrete, path, a, b, -hwd, -hwd + PARAPET_WIDTH, slabTop, parTop, { bottom: false })
    }
  }

  // Piers: a round column and a cap beam across the nearest road.
  for (const pier of model.piers || []) {
    const [x, y, top, width] = pier
    if (![x, y, top, width].every(Number.isFinite)) continue
    const px = x, pz = -y
    let ux = 1, uz = 0, best = Infinity
    for (const path of paths) {
      for (let i = 0; i < path.n; i++) {
        const d = (path.P[i][0] - px) ** 2 + (path.P[i][2] - pz) ** 2
        if (d < best) { best = d; ux = path.L[i][0]; uz = path.L[i][1] }   // beam runs across the road
      }
    }
    const capTop = top - SLAB_THICKNESS
    const capBot = Math.max(BASE_Y, capTop - 1.0)
    if (capTop <= BASE_Y + 0.05) continue
    orientedBox(concrete, px, pz, capBot, capTop, Math.max(1, width) / 2, 0.7, ux, uz)
    if (capBot - BASE_Y > 0.3) prism(concrete, px, pz, BASE_Y, capBot, 0.8, 8)
  }

  return { asphalt: asphalt.arrays(), markings: marks.arrays(), concrete: concrete.arrays() }
}

// ── Public: traffic ─────────────────────────────────────────────────────────

// Sampler along a polyline: at(s, lateral, out) fills out[0..2] position (three space, including
// the lateral offset, left positive), out[3..5] unit forward vector (with pitch), out[6..7] unit
// horizontal left vector.
export function makeSampler(points) {
  const path = preparePath(points)
  if (!path) return null
  return {
    length: path.length,
    at(s, lateral, out) {
      const ss = Math.min(path.length, Math.max(0, s))
      const { lo, hi } = frameAt(path, ss)
      const fr = lerpFrame(path, ss)
      out[0] = fr.p[0] + fr.l[0] * lateral
      out[1] = fr.p[1]
      out[2] = fr.p[2] + fr.l[1] * lateral
      let fx = path.P[hi][0] - path.P[lo][0], fy = path.P[hi][1] - path.P[lo][1], fz = path.P[hi][2] - path.P[lo][2]
      const h = Math.hypot(fx, fy, fz) || 1
      out[3] = fx / h; out[4] = fy / h; out[5] = fz / h
      out[6] = fr.l[0]; out[7] = fr.l[1]
      return out
    },
  }
}

export function seededRandom(seed) {
  let a = seed >>> 0
  return () => {
    a = (a + 0x6d2b79f5) >>> 0
    let t = a
    t = Math.imul(t ^ (t >>> 15), t | 1)
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61)
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296
  }
}

function hashString(s) {
  let h = 2166136261
  for (let i = 0; i < s.length; i++) { h ^= s.charCodeAt(i); h = Math.imul(h, 16777619) }
  return h >>> 0
}

// Cars for a whole model. Each car: { sampler, s0, lat, v (m/s of simulated time), colour (index) }.
// Spacing 45-70 m per lane, random phase, deterministic for a given model name.
export function planTraffic(model, { speedFactor = 1.5, colours = 7 } = {}) {
  const cars = []
  for (const seg of model.segments || []) {
    const sampler = makeSampler(seg.points)
    if (!sampler || sampler.length < 12) continue
    const rnd = seededRandom(hashString(`${model.name}:${seg.id}`))
    const w = Number(seg.width_m) > 0 ? Number(seg.width_m) : 7
    const lanes = Math.max(1, Math.round(seg.lanes || 1))
    const v = ((Number(seg.speed_kmh) || 50) / 3.6) * speedFactor
    for (let k = 0; k < lanes; k++) {
      const spacing = 45 + rnd() * 25
      const count = Math.max(1, Math.floor(sampler.length / spacing))
      const gap = sampler.length / count
      const phase = rnd() * gap
      for (let j = 0; j < count; j++) {
        cars.push({
          sampler,
          s0: (phase + j * gap + (rnd() - 0.5) * Math.min(8, gap * 0.15)) % sampler.length,
          lat: -w / 2 + (w / lanes) * (k + 0.5) + (rnd() - 0.5) * 0.4,
          v,
          colour: Math.floor(rnd() * colours),
        })
      }
    }
  }
  return cars
}

// One car: low body plus a cabin, with per-vertex colour (white body, dark cabin glass) that the
// instance colour tints, and a second mesh for the lamps (warm white in front, red behind).
// The car's length runs along +x, width along z, bottom at y = 0.
export function buildCarGeometry() {
  const body = new MeshData(true)
  const box = (md, cx, cz, y0, y1, hl, hw, rgb) => orientedBox(md, cx, cz, y0, y1, hl, hw, 1, 0, rgb)
  box(body, 0, 0, 0.25, 0.95, 2.2, 0.9, [1, 1, 1])
  box(body, -0.25, 0, 0.95, 1.45, 1.2, 0.8, [0.28, 0.3, 0.34])
  const lamps = new MeshData(true)
  for (const sz of [-0.62, 0.62]) {
    box(lamps, 2.21, sz, 0.5, 0.75, 0.06, 0.22, [1, 0.93, 0.7])
    box(lamps, -2.21, sz, 0.55, 0.75, 0.06, 0.22, [1, 0.08, 0.04])
  }
  return { body: body.arrays(), lamps: lamps.arrays() }
}

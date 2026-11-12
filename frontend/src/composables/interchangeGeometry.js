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
const MERGE_DASH = 3                // beside a lane that leaves or has just joined: short dashes
const MERGE_LINE_WIDTH = 0.25
const LEAD_STEP = 25                 // spacing of the points of a road drawn on beyond the model
const CAR_GAP = 0.15                // share of the release slots of a lane left empty
const CAR_FADE_S = 0.35             // a car grows in and shrinks out over this long at a lane end

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

const num = (v, fallback) => (Number.isFinite(v) ? v : fallback)

// Convert a segment's API points to three space, drop repeated points, and attach per point:
// P (position), L (unit horizontal left vector), S (mitre scale for lateral offsets), cum (arc
// length), l / r (centreline to the left / right pavement edge), el / er (what that edge is:
// 'f' free, 'm' narrow median, 's' shared with a lane alongside, 'o' open into a junction) and mk (lane lines drawn).
// The backend decides all of l, r, el, er and mk; a response without them means plain full width.
// With `reach` > 0, an end where the road carries on beyond the model (open_start / open_end) is
// drawn on, straight and level, until it is `reach` metres from the centre.
function preparePath(seg, reach = 0) {
  const hw = (Number(seg.width_m) > 0 ? Number(seg.width_m) : 7) / 2
  const P = [], l = [], r = [], el = [], er = [], mk = []
  const points = seg.points || []
  for (let k = 0; k < points.length; k++) {
    const q = points[k]
    if (!q || q.length < 3 || !q.every(Number.isFinite)) continue
    const p = [q[0], q[2], -q[1]]
    const last = P[P.length - 1]
    if (last && Math.hypot(p[0] - last[0], p[2] - last[2]) < 1e-6 && Math.abs(p[1] - last[1]) < 1e-6) continue
    P.push(p)
    l.push(num(seg.left_m?.[k], hw))
    r.push(num(seg.right_m?.[k], hw))
    el.push(seg.edge_left?.[k] || 'f')
    er.push(seg.edge_right?.[k] || 'f')
    mk.push(seg.marks ? seg.marks[k] !== '0' : true)
  }
  if (P.length < 2) return null
  if (reach > 0) {
    const edge = c => (c === 'm' ? 'm' : 'f')
    const extend = (atStart) => {
      const tip = atStart ? P[0] : P[P.length - 1]
      const prev = atStart ? P[1] : P[P.length - 2]
      const h = Math.hypot(tip[0] - prev[0], tip[2] - prev[2])
      if (h < 1e-6) return
      const ux = (tip[0] - prev[0]) / h, uz = (tip[2] - prev[2]) / h
      // Distance along the ray from the tip to the circle of radius `reach`.
      const along = tip[0] * ux + tip[2] * uz
      const inside = reach * reach - (tip[0] * tip[0] + tip[2] * tip[2]) + along * along
      const far = inside > 0 ? -along + Math.sqrt(inside) : 0
      if (far < 1) return
      const i = atStart ? 0 : P.length - 1
      const attrs = [l[i], r[i], edge(el[i]), edge(er[i])]
      const steps = Math.ceil(far / LEAD_STEP)
      for (let k = 1; k <= steps; k++) {
        const t = (far * k) / steps
        const p = [tip[0] + ux * t, tip[1], tip[2] + uz * t]
        const put = atStart ? 'unshift' : 'push'
        P[put](p); l[put](attrs[0]); r[put](attrs[1]); el[put](attrs[2]); er[put](attrs[3]); mk[put](true)
      }
    }
    if (seg.open_start) extend(true)
    if (seg.open_end) extend(false)
  }
  const n = P.length

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
  return { n, P, L, S, cum, length: cum[n - 1], l, r, el, er, mk, hw, lanes: Math.max(1, Math.round(seg.lanes || 1)) }
}

// Point at lateral offset o (left positive) and absolute height y of path point i.
function lat(path, i, o, y) {
  const p = path.P[i], l = path.L[i], k = o * path.S[i]
  return [p[0] + l[0] * k, y, p[2] + l[1] * k]
}

// Strip from [leftPoint, rightPoint] pairs, normal up.
function topStrip(md, pts) {
  if (pts.length < 2) return
  const ids = pts.map(([l, r]) => [md.vert(...l), md.vert(...r)])
  for (let i = 0; i < ids.length - 1; i++) {
    const [l0, r0] = ids[i], [l1, r1] = ids[i + 1]
    md.tri(l0, r0, l1)
    md.tri(r0, r1, l1)
  }
}

// Vertical face strip: pairs of [a, b] points, quads between consecutive pairs.
function faceStrip(md, pairs) {
  if (pairs.length < 2) return
  const ids = pairs.map(([a, b]) => [md.vert(...a), md.vert(...b)])
  for (let i = 0; i < ids.length - 1; i++) {
    const [a0, b0] = ids[i], [a1, b1] = ids[i + 1]
    md.tri(a0, b0, a1)
    md.tri(b0, b1, a1)
  }
}

// Contiguous index runs [a, b] (a < b) within [from, to] where pred(i) holds for every point.
function runs(from, to, pred) {
  const out = []
  let a = -1
  for (let i = from; i <= to + 1; i++) {
    const ok = i <= to && pred(i)
    if (ok && a < 0) a = i
    if (!ok && a >= 0) { if (i - 1 > a) out.push([a, i - 1]); a = -1 }
  }
  return out
}

// Prism along path indices a..b between the lateral offsets o0(i) < o1(i), with bottom and top
// heights per point. Faces: top, both sides, optional bottom, and two end caps.
function prismRun(md, path, a, b, o0, o1, bot, top, { bottom = true } = {}) {
  const idx = []
  for (let i = a; i <= b; i++) idx.push(i)
  topStrip(md, idx.map(i => [lat(path, i, o1(i), top[i]), lat(path, i, o0(i), top[i])]))
  faceStrip(md, idx.map(i => [lat(path, i, o1(i), bot[i]), lat(path, i, o1(i), top[i])]))   // left
  faceStrip(md, idx.map(i => [lat(path, i, o0(i), top[i]), lat(path, i, o0(i), bot[i])]))   // right
  if (bottom) topStrip(md, idx.map(i => [lat(path, i, o0(i), bot[i]), lat(path, i, o1(i), bot[i])]))
  faceStrip(md, [   // end cap, facing forward
    [lat(path, b, o1(b), bot[b]), lat(path, b, o1(b), top[b])],
    [lat(path, b, o0(b), bot[b]), lat(path, b, o0(b), top[b])],
  ])
  faceStrip(md, [   // start cap, facing backward
    [lat(path, a, o0(a), bot[a]), lat(path, a, o0(a), top[a])],
    [lat(path, a, o1(a), bot[a]), lat(path, a, o1(a), top[a])],
  ])
}

// Where arc length s falls: the two indices around it and the fraction between them.
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

// Interpolated frame at arc length s: position, left vector, mitre scale and both edge offsets.
function lerpFrame(path, s) {
  const { lo, hi, f } = frameAt(path, s)
  const a = path.P[lo], b = path.P[hi], la = path.L[lo], lb = path.L[hi]
  let lx = la[0] + (lb[0] - la[0]) * f, lz = la[1] + (lb[1] - la[1]) * f
  const h = Math.hypot(lx, lz) || 1
  lx /= h; lz /= h
  return {
    lo, hi, f,
    p: [a[0] + (b[0] - a[0]) * f, a[1] + (b[1] - a[1]) * f, a[2] + (b[2] - a[2]) * f],
    l: [lx, lz],
    sc: path.S[lo] + (path.S[hi] - path.S[lo]) * f,
    left: path.l[lo] + (path.l[hi] - path.l[lo]) * f,
    right: path.r[lo] + (path.r[hi] - path.r[lo]) * f,
  }
}

// Painted line from arc length s0 to s1. `centre(frame)` gives the lateral offset of its middle.
function paintLine(md, path, s0, s1, centre, width) {
  const pts = []
  const push = (s) => {
    const fr = lerpFrame(path, s)
    const c = centre(fr)
    const mk = (o) => [fr.p[0] + fr.l[0] * o * fr.sc, fr.p[1] + MARK_LIFT, fr.p[2] + fr.l[1] * o * fr.sc]
    pts.push([mk(c + width / 2), mk(c - width / 2)])
  }
  push(s0)
  for (let i = 0; i < path.n; i++) {
    if (path.cum[i] > s0 + 1e-6 && path.cum[i] < s1 - 1e-6) push(path.cum[i])
  }
  push(s1)
  topStrip(md, pts)
}

function paintDashes(md, path, s0, s1, on, off, centre, width, keep = () => true) {
  for (let s = s0 + off / 2; s < s1; s += on + off) {
    const e = Math.min(s1, s + on)
    if (e - s > 0.5 && keep(lerpFrame(path, (s + e) / 2))) paintLine(md, path, s, e, centre, width)
  }
}

// ── Public: road and structure meshes ───────────────────────────────────────

// Returns { asphalt, markings, concrete }, each { positions: Float32Array, indices: Uint32Array }.
// `reach`: how far from the centre to draw the roads that leave the interchange (0 = as given).
export function buildInterchange(model, { reach = 0 } = {}) {
  const asphalt = new MeshData(), marks = new MeshData(), concrete = new MeshData()
  const fillBelow = Number.isFinite(model.fill_below_m) ? model.fill_below_m : 3

  const paths = []
  for (const seg of model.segments || []) {
    const path = preparePath(seg, reach)
    if (!path) continue
    paths.push(path)
    const { n, l, r, el, er, hw, lanes } = path
    const last = n - 1
    const width = i => l[i] + r[i]

    // Road surface, between the two pavement edges.
    const all = []
    for (let i = 0; i < n; i++) all.push(i)
    topStrip(asphalt, all.map(i => [lat(path, i, l[i], path.P[i][1]), lat(path, i, -r[i], path.P[i][1])]))

    // Edge lines. A free or median edge has a solid line just inside it (two carriageways on one
    // deck so make a double centre line); an edge shared with a lane alongside has a broken lane
    // line on it (drawn once, by the ramp); an open edge has none.
    const inset = fr => Math.min(EDGE_INSET, (fr.left + fr.right) / 4)
    const sides = [
      { code: el, centre: fr => fr.left - inset(fr), shared: fr => fr.left },
      { code: er, centre: fr => -fr.right + inset(fr), shared: fr => -fr.right },
    ]
    for (const side of sides) {
      for (const [a, b] of runs(0, last, i => (side.code[i] === 'f' || side.code[i] === 'm') && width(i) > 0.5)) {
        paintLine(marks, path, path.cum[a], path.cum[b], side.centre, LINE_WIDTH)
      }
      if (seg.kind !== 'ramp') continue
      for (const [a, b] of runs(0, last, i => side.code[i] === 's')) {
        paintDashes(marks, path, path.cum[a], path.cum[b], MERGE_DASH, MERGE_DASH, side.shared, MERGE_LINE_WIDTH)
      }
    }

    // Lane lines stay where the lanes are. A carriageway loses a lane where a ramp takes it and
    // gains one where a ramp brings it, sometimes outside its nominal width, so a line is drawn
    // wherever there is at least half a lane of pavement on both sides of it. Inside a junction
    // there are none.
    const lane = (2 * hw) / lanes
    for (let k = -1; k <= lanes + 1; k++) {
      const o = -hw + lane * k
      const keep = fr => path.mk[fr.lo] && path.mk[fr.hi]
        && o < fr.left - lane / 2 && o > -fr.right + lane / 2
      paintDashes(marks, path, 0, path.length, DASH_ON, DASH_OFF, () => o, LINE_WIDTH, keep)
    }

    // Decks and fill under every elevated stretch; parapets only along free edges.
    const z = path.P.map(p => p[1])
    const slabTop = z.map(v => v - 0.05)
    const slabBot = z.map(v => (v < fillBelow ? BASE_Y : Math.max(BASE_Y, v - SLAB_THICKNESS)))
    const parTop = z.map(v => v + PARAPET_HEIGHT)
    const leftOut = i => l[i] + SLAB_OVERHANG, rightOut = i => -r[i] - SLAB_OVERHANG
    for (const [a, b] of runs(0, last, i => z[i] > DECK_MIN_Z)) {
      prismRun(concrete, path, a, b, rightOut, leftOut, slabBot, slabTop)
      for (const [c, d] of runs(a, b, i => el[i] === 'f')) {
        prismRun(concrete, path, c, d, i => leftOut(i) - PARAPET_WIDTH, leftOut, slabTop, parTop, { bottom: false })
      }
      for (const [c, d] of runs(a, b, i => er[i] === 'f')) {
        prismRun(concrete, path, c, d, rightOut, i => rightOut(i) + PARAPET_WIDTH, slabTop, parTop, { bottom: false })
      }
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

// Cars drive the routes the backend lays out: each route is one lane followed through the
// interchange, as points with the time a car reaches them, so a car never changes lane by itself
// and no lane ends under it. Every route releases a car each `headway_s`, offset by the route's
// `phase_s`, which the backend chooses so that cars of routes that cross pass between one another.

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

// A route in three space: P (positions), T (seconds at each), D (unit tangent at each point).
// With `reach` > 0, an end that carries on beyond the model is run on, straight and level and at
// the speed it has there, until it is `reach` metres from the centre.
function prepareRoute(route, reach = 0) {
  const P = [], T = []
  for (const q of route.points || []) {
    if (!q || q.length < 4 || !q.every(Number.isFinite)) continue
    if (T.length && q[3] <= T[T.length - 1]) continue
    P.push([q[0], q[2], -q[1]])
    T.push(q[3])
  }
  if (P.length < 2) return null
  const extend = (atStart) => {
    // Direction from a point well back along the lane, so that the rounding of two close points
    // does not send a long run-on off its line.
    const i = atStart ? 0 : P.length - 1, step = atStart ? 1 : -1
    const tip = P[i]
    let j = i + step
    while (P[j + step] && Math.hypot(tip[0] - P[j][0], tip[2] - P[j][2]) < 30) j += step
    const prev = P[j]
    const h = Math.hypot(tip[0] - prev[0], tip[2] - prev[2])
    const dt = Math.abs(T[i] - T[j])
    if (h < 1e-6 || dt < 1e-6) return
    const ux = (tip[0] - prev[0]) / h, uz = (tip[2] - prev[2]) / h
    const along = tip[0] * ux + tip[2] * uz
    const inside = reach * reach - (tip[0] * tip[0] + tip[2] * tip[2]) + along * along
    const far = inside > 0 ? -along + Math.sqrt(inside) : 0
    if (far < 1) return
    const p = [tip[0] + ux * far, tip[1], tip[2] + uz * far]
    const t = far / (h / dt)
    if (atStart) { P.unshift(p); T.unshift(T[0] - t) } else { P.push(p); T.push(T[T.length - 1] + t) }
  }
  if (reach > 0 && route.open_start) extend(true)
  if (reach > 0 && route.open_end) extend(false)
  const n = P.length
  const D = []
  for (let i = 0; i < n; i++) {
    const a = P[Math.max(0, i - 1)], b = P[Math.min(n - 1, i + 1)]
    const dx = b[0] - a[0], dy = b[1] - a[1], dz = b[2] - a[2]
    const h = Math.hypot(dx, dy, dz) || 1
    D.push([dx / h, dy / h, dz / h])
  }
  return { n, P, T, D, t0: T[0], t1: T[n - 1] }
}

// Cars for a whole model: { route, slot, cycle, back, phase, side, colour }. A car is in slot
// `slot` of its route's release cycle; about one slot in seven is left empty so the stream does
// not look like a conveyor. Deterministic for a given model.
export function planTraffic(model, { colours = 7, reach = 0 } = {}) {
  const cars = []
  const headway = Number(model.headway_s)
  if (!(headway > 0)) return cars
  for (const raw of model.routes || []) {
    const route = prepareRoute(raw, reach)
    if (!route) continue
    const rnd = seededRandom(hashString(`${model.name}:${raw.id}`))
    // Slots before the route's own start (on the road drawn on towards it) and after it.
    const back = Math.ceil(Math.max(0, -route.t0) / headway)
    const slots = back + Math.ceil(route.t1 / headway) + 1
    const phase = Number.isFinite(raw.phase_s) ? raw.phase_s : 0
    for (let k = 0; k < slots; k++) {
      const empty = rnd() < CAR_GAP
      const side = (rnd() - 0.5) * 0.4
      const colour = Math.floor(rnd() * colours)
      if (empty) continue
      cars.push({ route, headway, phase, slot: k, cycle: slots * headway, back: back * headway, side, colour })
    }
  }
  return cars
}

// Place a car at traffic time `time` (seconds). Fills out[0..2] position (three space),
// out[3..5] unit forward vector (with pitch), out[6..7] unit horizontal left vector, and returns
// the car's scale: 1 on the road, down to 0 as it leaves at a lane end, 0 while it waits its turn.
export function placeCar(car, time, out) {
  const { route } = car
  const x = time - car.phase - car.slot * car.headway
  const tau = (((x % car.cycle) + car.cycle) % car.cycle) - car.back
  if (tau <= route.t0 || tau >= route.t1) return 0
  const T = route.T
  let lo = 0, hi = route.n - 1
  while (hi - lo > 1) {
    const mid = (lo + hi) >> 1
    if (T[mid] <= tau) lo = mid; else hi = mid
  }
  const f = (tau - T[lo]) / (T[hi] - T[lo])
  const a = route.P[lo], b = route.P[hi], da = route.D[lo], db = route.D[hi]
  let fx = da[0] + (db[0] - da[0]) * f, fy = da[1] + (db[1] - da[1]) * f, fz = da[2] + (db[2] - da[2]) * f
  const h = Math.hypot(fx, fy, fz) || 1
  fx /= h; fy /= h; fz /= h
  const flat = Math.hypot(fx, fz) || 1
  const lx = fz / flat, lz = -fx / flat
  out[0] = a[0] + (b[0] - a[0]) * f + lx * car.side
  out[1] = a[1] + (b[1] - a[1]) * f
  out[2] = a[2] + (b[2] - a[2]) * f + lz * car.side
  out[3] = fx; out[4] = fy; out[5] = fz
  out[6] = lx; out[7] = lz
  const e = Math.min(tau - route.t0, route.t1 - tau) / CAR_FADE_S
  return e >= 1 ? 1 : e * e * (3 - 2 * e)
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

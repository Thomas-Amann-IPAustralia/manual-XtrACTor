/* The cross-reference network: every Part and every cited provision as a node,
 * the three citation fields SCHEMA.md defines as edges.
 *
 * Reads data/graph.json, a view viz/build.py derives from the same bundles
 * app.js reads — no field here is a fact this page invented. Layout is a
 * force-directed simulation, written from scratch (no CDN, no framework: the
 * page loads nothing from another origin). Node starting positions are seeded
 * from a hash of the node's own id rather than Math.random(), and every force
 * in the simulation is a deterministic function of the graph, so the same
 * data settles into the same picture on every reload rather than a fresh
 * scramble each time.
 *
 * Nodes are Parts and provisions, not chunks — see build_graph's own docstring
 * for why. This file does not know how to draw a chunk at all.
 */
'use strict';

/* ------------------------------------------------------------------ helpers */

function h(tag, attrs, ...kids) {
  const node = document.createElement(tag);
  if (attrs) {
    for (const [key, value] of Object.entries(attrs)) {
      if (value === null || value === undefined || value === false) continue;
      if (key === 'class') node.className = value;
      else if (key === 'text') node.textContent = value;
      else if (key.slice(0, 2) === 'on') node.addEventListener(key.slice(2), value);
      else node.setAttribute(key, value === true ? '' : value);
    }
  }
  for (const kid of kids.flat()) {
    if (kid === null || kid === undefined || kid === false) continue;
    node.append(kid.nodeType ? kid : document.createTextNode(String(kid)));
  }
  return node;
}

const num = (n) => (n === null || n === undefined ? '—' : n.toLocaleString('en-AU'));
const clamp = (v, lo, hi) => Math.max(lo, Math.min(hi, v));

/** A small, deterministic string hash (FNV-1a), so the layout's starting
 * positions are a pure function of the graph rather than of Math.random(). */
function hash32(str) {
  let hash = 0x811c9dc5;
  for (let i = 0; i < str.length; i++) {
    hash ^= str.charCodeAt(i);
    hash = Math.imul(hash, 0x01000193);
  }
  return hash >>> 0;
}

const INSTRUMENT_NAMES = {
  TMA1995: 'Trade Marks Act 1995',
  TMR1995: 'Trade Marks Regulations 1995',
};

const EDGE_KINDS = [
  ['manual_to_law', 'Practice → law', '--edge-manual-law'],
  ['law_to_law', 'Within the law', '--edge-law-law'],
  ['manual_to_manual', 'Within the Manual', '--edge-manual-manual'],
];

/* `weight` is a count of distinct citing chunks — except on law_to_law, where
 * build_graph fixes it at 1 because `cites` only ever states *that* A cites B,
 * never how many times. A "hide edges weaker than n" threshold therefore says
 * nothing about that kind, and applying it anyway silently deleted all 1,312 of
 * those edges at the slider's first notch. Only these two kinds answer to it. */
const WEIGHTED_KINDS = new Set(['manual_to_law', 'manual_to_manual']);

/* --------------------------------------------------------------- data load */

async function getJSON(url) {
  const response = await fetch(url);
  if (!response.ok) throw new Error(`${url}: ${response.status}`);
  return response.json();
}

/* ------------------------------------------------------------------- state */

const G = { nodes: [], edges: [] };
const nodeById = new Map();
const neighbours = new Map();   // node id -> [{ other, edge }]
const layout = new Map();       // node id -> { x, y, vx, vy, fx, fy, r }
const theme = {};

const filters = {
  kinds: new Set(EDGE_KINDS.map((k) => k[0])),
  instruments: new Set(),
  minWeight: 1,
  labelAll: false,
};

let visibleNodes = [];         // Node objects currently drawn
let visibleEdges = [];         // Edge objects currently drawn
// The same membership as the two arrays above, as sets, so the focus panel can
// ask "is this edge on the map?" without a linear scan per neighbour. Edge
// objects are the very objects in G.edges, so identity is the right test.
let visibleNodeIds = new Set();
let visibleEdgeSet = new Set();
let maxWeight = { manual_to_law: 1, law_to_law: 1, manual_to_manual: 1 };

// The controls, so a filter can be changed in code — "show me this node after
// all" — and the panel still shows the truth about what is filtered.
const kindInputs = new Map();
const instrumentInputs = new Map();
let weightInput = null;
// How many neighbours the focus panel lists before it stops. It used to slice
// at 60 and say nothing, so s6's 163 citing provisions became 60 with no hint
// that 103 were missing. Now the cap is disclosed and liftable, per focus.
const NEIGHBOUR_CAP = 40;
let neighbourCap = NEIGHBOUR_CAP;

let camera = { x: 0, y: 0, k: 1 };
// What the camera should keep framed while the layout is still moving: null for
// nothing, 'all' for the whole graph, or a node id for that node's
// neighbourhood. fitView() used to be called once at boot, against the seed ring
// — a ~2,500-unit circle — and never again, so once the springs had pulled the
// graph into the ~1,600 units it actually occupies the camera was left 35% too
// far out, drawing the map at two thirds of the stage for the rest of the
// session. Cleared the moment the reader takes the view themselves: their
// framing is not something to correct.
let autoFit = null;
let hoveredId = null;
let focusedId = null;
let alpha = 1;
let simActive = true;
let needsRedraw = true;

const ALPHA_DECAY = 0.026;
const ALPHA_MIN = 0.001;
const VELOCITY_DECAY = 0.35;
const LINK_DISTANCE = 60;
const LINK_STRENGTH = 1.1;
const CHARGE = 9000;
const CENTER_STRENGTH = 0.012;
const MIN_K = 0.04;
const MAX_K = 9;

/* --------------------------------------------------------------- indexing */

function buildIndex() {
  for (const node of G.nodes) {
    nodeById.set(node.id, node);
    neighbours.set(node.id, []);
  }
  for (const edge of G.edges) {
    const a = nodeById.get(edge.source);
    const b = nodeById.get(edge.target);
    if (!a || !b) continue;   // defensive only: build_graph guarantees both ends exist
    neighbours.get(a.id).push({ other: b, edge });
    neighbours.get(b.id).push({ other: a, edge });
    if (edge.weight > (maxWeight[edge.kind] || 0)) maxWeight[edge.kind] = edge.weight;
  }
  const instruments = new Set();
  for (const node of G.nodes) if (node.kind === 'provision') instruments.add(node.instrument);
  filters.instruments = instruments;

  for (const node of G.nodes) {
    const seed = seedPosition(node.id);
    const links = neighbours.get(node.id) || [];
    const degree = links.reduce((sum, n) => sum + n.edge.weight, 0);
    const r = node.kind === 'part'
      ? clamp(4 + Math.sqrt(node.chunks || 0) * 0.85, 5, 26)
      : clamp(3 + Math.sqrt(degree) * 1.05, 3, 22);
    // edgeCount (how many *distinct* edges touch this node) is what tempers a
    // hub's pull on the layout — see the spring force in tick(). Distinct
    // from `degree` above, which is citation-weighted and drives radius.
    layout.set(node.id, { x: seed.x, y: seed.y, vx: 0, vy: 0, fx: null, fy: null, r, degree, edgeCount: Math.max(links.length, 1) });
  }
}

/** A deterministic starting ring: same graph, same picture, every reload. */
function seedPosition(id) {
  const angle = (hash32(id) % 1000003) / 1000003 * Math.PI * 2;
  const spread = LINK_DISTANCE * Math.sqrt(G.nodes.length / Math.PI) * 1.4;
  const radius = spread * (0.35 + 0.65 * ((hash32('r:' + id) % 1000003) / 1000003));
  return { x: Math.cos(angle) * radius, y: Math.sin(angle) * radius };
}

/* -------------------------------------------------------------- filtering */

function recomputeVisibility() {
  const edgeOk = (edge) => {
    if (!filters.kinds.has(edge.kind)) return false;
    if (WEIGHTED_KINDS.has(edge.kind) && edge.weight < filters.minWeight) return false;
    const a = nodeById.get(edge.source), b = nodeById.get(edge.target);
    if (a.kind === 'provision' && !filters.instruments.has(a.instrument)) return false;
    if (b.kind === 'provision' && !filters.instruments.has(b.instrument)) return false;
    return true;
  };
  visibleEdges = G.edges.filter(edgeOk);
  visibleEdgeSet = new Set(visibleEdges);

  const touched = new Set();
  for (const edge of visibleEdges) { touched.add(edge.source); touched.add(edge.target); }
  visibleNodes = G.nodes.filter((node) => {
    if (node.kind === 'part') return true;
    return filters.instruments.has(node.instrument) && touched.has(node.id);
  });
  visibleNodeIds = new Set(visibleNodes.map((node) => node.id));

  updateStatus();
  // A node focused before the filter changed may have just left the map, or
  // rejoined it. Either way the panel's neighbour lists and its notice are now
  // stale, so re-state them against what is actually drawn.
  if (focusedId != null) {
    const node = nodeById.get(focusedId);
    if (node) { noteFocusVisibility(node); renderFocusPanel(node); }
  }
  needsRedraw = true;
}

/** Reflect `filters` back into the controls, so a filter changed in code — by
 * "Show it anyway" — does not leave the checkboxes lying about the state. */
function syncFilterInputs() {
  for (const [kind, input] of kindInputs) input.checked = filters.kinds.has(kind);
  for (const [code, input] of instrumentInputs) input.checked = filters.instruments.has(code);
  if (weightInput) {
    weightInput.value = String(filters.minWeight);
    updateWeightHint();
  }
}

/** Relax exactly the filters that are keeping `node` off the map, and no others. */
function revealNode(node) {
  if (node.kind === 'provision') filters.instruments.add(node.instrument);
  for (const { other, edge } of neighbours.get(node.id) || []) {
    filters.kinds.add(edge.kind);
    if (other.kind === 'provision') filters.instruments.add(other.instrument);
  }
  filters.minWeight = 1;
  syncFilterInputs();
  recomputeVisibility();
  focusNode(node);
}

function updateStatus() {
  const status = document.getElementById('g-status');
  if (!status) return;
  const total = G.nodes.length, totalE = G.edges.length;
  if (visibleNodes.length === total && visibleEdges.length === totalE) {
    status.textContent = `${num(total)} nodes · ${num(totalE)} edges`;
  } else {
    status.textContent =
      `${num(visibleNodes.length)} of ${num(total)} nodes · ${num(visibleEdges.length)} of ${num(totalE)} edges shown`;
  }
}

/* The panel's one line for "what you asked for is not what you are looking at".
 * Kept separate from the status line, which recomputeVisibility owns and would
 * otherwise overwrite it on the next keystroke. */
function setNotice(text, actionLabel, onAction) {
  const notice = document.getElementById('g-notice');
  if (!notice) return;
  notice.replaceChildren(...[
    h('span', { text }),
    // replaceChildren is the DOM's, not h()'s: a null argument becomes the text
    // "null" instead of being skipped.
    actionLabel ? h('button', { class: 'link-btn', type: 'button', text: actionLabel, onclick: onAction }) : null,
  ].filter(Boolean));
  notice.hidden = false;
}

function clearNotice() {
  const notice = document.getElementById('g-notice');
  if (!notice) return;
  notice.hidden = true;
  notice.replaceChildren();
}

/** Say so when the focused node is not on the map — the filters, not the data,
 * are why it is missing, and the reader is owed both facts and the way out. */
function noteFocusVisibility(node) {
  if (!node || visibleNodeIds.has(node.id)) { clearNotice(); return false; }
  setNotice(`${node.label} is filtered off the map — its neighbours are listed below, but nothing is drawn for it.`,
    'Show it anyway', () => revealNode(node));
  return true;
}

/* --------------------------------------------------------------- physics */

// A floor on the distance the repulsion force is computed over. Without one,
// two nodes seeded (or dragged) close together make 1/dist^2 spike toward
// infinity, one tick's velocity overflows, and — because NaN arithmetic never
// throws, it just silently propagates — every node the affected ones touch in
// the next O(n^2) pass is NaN within a handful of ticks and the whole graph
// vanishes with no error anywhere. Flooring dist bounds the force instead of
// merely guarding the divide-by-exactly-zero case.
const DIST_MIN = 1;
const MAX_SPEED = 60;

function tick() {
  const nodes = G.nodes;
  // Repulsion + collision: every pair, once. O(n^2), fine at this corpus's
  // scale (a few hundred nodes) — see viz/README.md for the size this was
  // measured against.
  for (let i = 0; i < nodes.length; i++) {
    const a = layout.get(nodes[i].id);
    for (let j = i + 1; j < nodes.length; j++) {
      const b = layout.get(nodes[j].id);
      let dx = b.x - a.x, dy = b.y - a.y;
      let dist = Math.sqrt(dx * dx + dy * dy);
      if (dist < DIST_MIN) {
        // Coincident or almost so: nudge apart along a direction fixed by the
        // pair's own indices, not Math.random() — the layout stays a pure
        // function of the graph, not of when it happened to run.
        const angle = ((i * 2654435761 + j * 40503) % 360) * (Math.PI / 180);
        dx = Math.cos(angle); dy = Math.sin(angle); dist = DIST_MIN;
      }
      const nx = dx / dist, ny = dy / dist;
      const minDist = a.r + b.r + 3;
      if (dist < minDist) {
        const overlap = (minDist - dist) / 2;
        if (a.fx == null) { a.x -= nx * overlap; a.y -= ny * overlap; }
        if (b.fx == null) { b.x += nx * overlap; b.y += ny * overlap; }
      }
      const force = (CHARGE * alpha) / (Math.max(dist, DIST_MIN) ** 2);
      const fx = nx * force, fy = ny * force;
      if (a.fx == null) { a.vx -= fx; a.vy -= fy; }
      if (b.fx == null) { b.vx += fx; b.vy += fy; }
    }
  }

  for (const edge of G.edges) {
    const a = layout.get(edge.source), b = layout.get(edge.target);
    const dx = b.x - a.x, dy = b.y - a.y;
    const dist = Math.max(Math.sqrt(dx * dx + dy * dy), DIST_MIN);
    // Tempered by the more-connected end's degree — a hub with 100 edges
    // cannot pull each neighbour at full strength without dragging its whole
    // neighbourhood into one clump; a leaf-to-leaf edge keeps full strength.
    const strength = LINK_STRENGTH / Math.min(a.edgeCount, b.edgeCount);
    const delta = ((dist - LINK_DISTANCE) / dist) * strength * alpha;
    const mx = dx * delta, my = dy * delta;
    if (a.fx == null) { a.vx += mx; a.vy += my; }
    if (b.fx == null) { b.vx -= mx; b.vy -= my; }
  }

  for (const node of nodes) {
    const p = layout.get(node.id);
    if (p.fx != null) { p.x = p.fx; p.y = p.fy; p.vx = 0; p.vy = 0; continue; }
    p.vx -= p.x * CENTER_STRENGTH * alpha;
    p.vy -= p.y * CENTER_STRENGTH * alpha;
    p.vx *= (1 - VELOCITY_DECAY);
    p.vy *= (1 - VELOCITY_DECAY);
    // A hard speed cap, independent of what produced vx/vy — the floor on
    // repulsion above keeps any *single* force bounded, but it is cheap
    // insurance against a chain of them stacking up on one node in one tick.
    const speed = Math.sqrt(p.vx * p.vx + p.vy * p.vy);
    if (speed > MAX_SPEED) { p.vx = (p.vx / speed) * MAX_SPEED; p.vy = (p.vy / speed) * MAX_SPEED; }
    p.x += p.vx;
    p.y += p.vy;
  }

  alpha += (0 - alpha) * ALPHA_DECAY;
  return alpha > ALPHA_MIN;
}

/* ------------------------------------------------------------- projection */

let cssWidth = 0, cssHeight = 0;

function toScreen(wx, wy) {
  return [(wx + camera.x) * camera.k + cssWidth / 2, (wy + camera.y) * camera.k + cssHeight / 2];
}
function toWorld(sx, sy) {
  return [(sx - cssWidth / 2) / camera.k - camera.x, (sy - cssHeight / 2) / camera.k - camera.y];
}

function zoomAt(sx, sy, factor) {
  autoFit = null;
  const [wx, wy] = toWorld(sx, sy);
  camera.k = clamp(camera.k * factor, MIN_K, MAX_K);
  camera.x = (sx - cssWidth / 2) / camera.k - wx;
  camera.y = (sy - cssHeight / 2) / camera.k - wy;
  needsRedraw = true;
}

/** A node and the neighbours it is currently drawn joined to — what "look at
 * this node" should frame. */
function neighbourhoodOf(node) {
  const shown = (neighbours.get(node.id) || [])
    .filter(({ edge }) => visibleEdgeSet.has(edge))
    .map(({ other }) => other);
  return [node, ...shown];
}

/** Re-frame whatever the camera has been asked to follow, once per settled tick. */
function applyAutoFit() {
  if (autoFit === 'all') { fitView(); return; }
  const node = nodeById.get(autoFit);
  if (!node) { autoFit = null; return; }
  fitView(neighbourhoodOf(node));
}

function fitView(nodesToFit) {
  // Default to the drawn graph, not the whole of it: fitting 728 nodes when 54
  // are on screen zooms out to frame mostly nothing.
  const fallback = visibleNodes.length ? visibleNodes : G.nodes;
  const pts = (nodesToFit && nodesToFit.length ? nodesToFit : fallback).map((n) => layout.get(n.id));
  if (!pts.length) return;
  let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;
  for (const p of pts) {
    minX = Math.min(minX, p.x - p.r); maxX = Math.max(maxX, p.x + p.r);
    minY = Math.min(minY, p.y - p.r); maxY = Math.max(maxY, p.y + p.r);
  }
  const w = Math.max(maxX - minX, 40), h = Math.max(maxY - minY, 40);
  const midX = (minX + maxX) / 2, midY = (minY + maxY) / 2;
  camera.k = clamp(Math.min(cssWidth / w, cssHeight / h) * 0.86, MIN_K, MAX_K);
  camera.x = -midX;
  camera.y = -midY;
  needsRedraw = true;
}

/* ---------------------------------------------------------------- theming */

function readTheme() {
  const css = getComputedStyle(document.documentElement);
  const get = (name, fallback) => (css.getPropertyValue(name) || fallback).trim() || fallback;
  theme.part = get('--node-part', '#0f5c63');
  theme.tma = get('--node-tma', '#b3752c');
  theme.tmr = get('--node-tmr', '#6f63c9');
  theme.edgeManualLaw = get('--edge-manual-law', '#9098a3');
  theme.edgeLawLaw = get('--edge-law-law', '#6f63c9');
  theme.edgeManualManual = get('--edge-manual-manual', '#0f5c63');
  theme.ink = get('--ink', '#16181c');
  theme.ink3 = get('--ink-3', '#767c86');
  theme.surface = get('--surface', '#ffffff');
  // Canvas text needs a literal font string — it does not go through CSS's
  // cascade, so `var(--sans)` is meaningless as a ctx.font value.
  theme.sansFont = get('--sans', 'sans-serif');
}

function nodeColour(node) {
  if (node.kind === 'part') return theme.part;
  return node.instrument === 'TMR1995' ? theme.tmr : theme.tma;
}

function edgeColour(kind) {
  if (kind === 'law_to_law') return theme.edgeLawLaw;
  if (kind === 'manual_to_manual') return theme.edgeManualManual;
  return theme.edgeManualLaw;
}

/* ---------------------------------------------------------------- drawing */

let canvas, ctx;

function resizeCanvas() {
  const stage = document.getElementById('graph-stage');
  const rect = stage.getBoundingClientRect();
  cssWidth = rect.width;
  cssHeight = rect.height;
  const dpr = window.devicePixelRatio || 1;
  canvas.width = Math.round(cssWidth * dpr);
  canvas.height = Math.round(cssHeight * dpr);
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  needsRedraw = true;
}

function activeSet(id) {
  if (id == null) return null;
  const set = new Set([id]);
  for (const { other } of neighbours.get(id) || []) set.add(other.id);
  return set;
}

function draw() {
  ctx.clearRect(0, 0, cssWidth, cssHeight);
  const emphasised = activeSet(focusedId != null ? focusedId : hoveredId);

  ctx.lineCap = 'round';
  for (const edge of visibleEdges) {
    const a = layout.get(edge.source), b = layout.get(edge.target);
    const related = emphasised && emphasised.has(edge.source) && emphasised.has(edge.target);
    const dim = emphasised && !related;
    const cap = maxWeight[edge.kind] || 1;
    // A kind whose weight never varies has no scale to be normalised against:
    // log(w+1)/log(cap+1) is exactly 1 for every law_to_law edge, which drew all
    // 1,312 of them at the very top of the ink scale and buried the kinds that
    // do carry a count under the one that carries only "A cites B". Draw an
    // unweighted kind at a single quiet value instead.
    const strength = cap > 1 ? Math.log(edge.weight + 1) / Math.log(cap + 1) : 0.12;
    ctx.globalAlpha = dim ? 0.05 : clamp(0.12 + strength * 0.55, 0.12, 0.75);
    ctx.strokeStyle = edgeColour(edge.kind);
    ctx.lineWidth = clamp(0.6 + strength * 2.2, 0.6, 3) / Math.sqrt(camera.k);
    const [sx, sy] = toScreen(a.x, a.y), [tx, ty] = toScreen(b.x, b.y);
    ctx.beginPath();
    ctx.moveTo(sx, sy);
    ctx.lineTo(tx, ty);
    ctx.stroke();
  }

  for (const node of visibleNodes) {
    const p = layout.get(node.id);
    const [sx, sy] = toScreen(p.x, p.y);
    if (sx < -40 || sy < -40 || sx > cssWidth + 40 || sy > cssHeight + 40) continue;
    const isFocused = node.id === focusedId;
    const isHovered = node.id === hoveredId;
    const dim = emphasised && !emphasised.has(node.id);
    const screenR = clamp(p.r * camera.k * (isFocused ? 1.25 : 1), isFocused || isHovered ? 2.4 : 1.1, 900);

    ctx.globalAlpha = dim ? 0.18 : 1;
    ctx.fillStyle = nodeColour(node);
    ctx.beginPath();
    ctx.arc(sx, sy, screenR, 0, Math.PI * 2);
    ctx.fill();
    if (isFocused || isHovered) {
      ctx.lineWidth = 2;
      ctx.strokeStyle = theme.ink;
      ctx.stroke();
    }

    const labelWanted = node.kind === 'part' ? camera.k > 0.25 : filters.labelAll || isFocused || isHovered;
    if (labelWanted && !dim) {
      ctx.globalAlpha = 1;
      ctx.fillStyle = theme.ink;
      ctx.font = (node.kind === 'part' ? '600 ' : '') + '11px ' + theme.sansFont;
      ctx.textBaseline = 'middle';
      ctx.fillText(node.label, sx + screenR + 3, sy);
    }
  }
  ctx.globalAlpha = 1;
}

function frame() {
  if (simActive) {
    const budget = performance.now() + 10;
    let ticked = false;
    while (performance.now() < budget) {
      simActive = tick();
      ticked = true;
      if (!simActive) break;
    }
    if (ticked) {
      needsRedraw = true;
      if (autoFit) applyAutoFit();
    }
  }
  if (needsRedraw) { draw(); needsRedraw = false; }
  requestAnimationFrame(frame);
}

/* ---------------------------------------------------------------- picking */

function pick(sx, sy) {
  const [wx, wy] = toWorld(sx, sy);
  let best = null, bestDist = Infinity;
  for (const node of visibleNodes) {
    const p = layout.get(node.id);
    const dx = wx - p.x, dy = wy - p.y;
    const dist = Math.sqrt(dx * dx + dy * dy);
    const tolerance = p.r + 4 / camera.k;
    if (dist <= tolerance && dist < bestDist) { best = node; bestDist = dist; }
  }
  return best;
}

/* ----------------------------------------------------------------- focus */

function routeFor(node) {
  return node.kind === 'part' ? ['part', node.part_id] : ['prov', node.ref];
}

function searchLabel(node) {
  return node.title ? `${node.label} — ${node.title}` : node.label;
}

function focusNode(node, { pan = true, moveFocus = false } = {}) {
  focusedId = node ? node.id : null;
  neighbourCap = NEIGHBOUR_CAP;
  // history.replaceState only — never assign location.hash directly, which
  // navigates and pushes a history entry of its own; clicking through a dozen
  // nodes should not fill up the back button with a dozen stops.
  const hash = node ? `#${node.kind === 'part' ? 'part' : 'prov'}:${node.kind === 'part' ? node.part_id : node.ref}` : '';
  history.replaceState(null, '', location.pathname + location.search + hash);
  // Framing a node is this call's business, and following one is over the moment
  // the focus moves or is cleared. focusFromHash re-arms it straight afterwards
  // for the one case that wants it — a deep link, still settling.
  autoFit = null;
  const hidden = noteFocusVisibility(node);
  // Panning to a node the filters have hidden lands the reader on blank canvas
  // at whatever zoom framed it — the notice above says where it went instead.
  if (node && pan && !hidden) fitView(neighbourhoodOf(node));
  renderFocusPanel(node);
  if (node && moveFocus) {
    const heading = document.querySelector('#focus-panel h3');
    if (heading) heading.focus();
  }
  needsRedraw = true;
}

function renderFocusPanel(node) {
  const panel = document.getElementById('focus-panel');
  if (!node) { panel.hidden = true; panel.replaceChildren(); return; }
  panel.hidden = false;

  const groups = new Map();  // heading -> [{label, count, node}]
  const addTo = (heading, entry) => {
    if (!groups.has(heading)) groups.set(heading, []);
    groups.get(heading).push(entry);
  };

  // Only edges that are actually on the map. The panel used to be built from
  // every edge regardless of the filters, so switching the Regulations off
  // still listed regulation neighbours — and clicking one focused a node that
  // was not drawn.
  let filteredOut = 0;
  for (const { other, edge } of neighbours.get(node.id) || []) {
    if (!visibleEdgeSet.has(edge)) { filteredOut++; continue; }
    const mine = edge.source === node.id;
    if (edge.kind === 'manual_to_law') {
      addTo(node.kind === 'part' ? 'Cites (practice → law)' : 'Cited by these Parts', { other, count: edge.weight });
    } else if (edge.kind === 'manual_to_manual') {
      addTo(mine ? 'Links to other Parts' : 'Linked from other Parts', { other, count: edge.weight });
    } else if (edge.kind === 'law_to_law') {
      addTo(mine ? 'Cites' : 'Cited by', { other, count: edge.weight });
    }
  }
  for (const list of groups.values()) list.sort((a, b) => b.count - a.count || a.other.label.localeCompare(b.other.label));

  const isPart = node.kind === 'part';
  const capped = [...groups.values()].some((entries) => entries.length > neighbourCap);
  // replaceChildren is the DOM's, not h()'s: it renders a null argument as the
  // text "null" rather than skipping it, so the conditional rows are filtered here.
  panel.replaceChildren(...[
    h('button', { class: 'link-btn close-focus', type: 'button', text: 'Close ✕', onclick: () => focusNode(null) }),
    h('h3', { tabindex: '-1', text: node.label }),
    h('p', { class: 'sub', text: isPart ? node.title : [INSTRUMENT_NAMES[node.instrument] || node.instrument, node.title].filter(Boolean).join(' — ') }),
    h('p', { class: 'sub mono', text: isPart ? `${num(node.chunks)} chunks across ${num(node.pages)} pages` : node.ref }),
    h('div', { class: 'neighbour-groups' },
      [...groups.entries()].map(([heading, entries]) => h('div', {},
        h('h4', { text: `${heading} (${entries.length})` }),
        h('ul', {}, entries.slice(0, neighbourCap).map((entry) => h('li', {},
          h('button', { class: 'ref-link', text: entry.other.label, title: entry.other.title || entry.other.ref || '', onclick: () => focusNode(entry.other) }),
          h('span', { class: 'count', text: num(entry.count) }))),
          entries.length > neighbourCap
            ? h('li', { class: 'more' }, h('span', { text: `${num(entries.length - neighbourCap)} more not listed` }))
            : null)))),
    !groups.size
      ? h('p', { class: 'hint', text: filteredOut ? `Every one of this node's ${num(filteredOut)} edges is hidden by the current filters.` : 'Nothing cites this node and it cites nothing.' })
      : null,
    filteredOut && groups.size
      ? h('p', { class: 'hint', text: `${num(filteredOut)} further edges are hidden by the current filters.` })
      : null,
    capped
      ? h('button', { class: 'link-btn', type: 'button', text: 'List every neighbour', onclick: () => { neighbourCap = Infinity; renderFocusPanel(node); } })
      : null,
    h('a', {
      class: 'link-btn open-link',
      href: `index.html#/${routeFor(node).map(encodeURIComponent).join('/')}`,
      text: 'Open in the reader →',
    }),
  ].filter(Boolean));
}

/* -------------------------------------------------------------- controls */

function updateWeightHint() {
  const hint = document.getElementById('g-weight-value');
  if (!hint) return;
  hint.textContent = filters.minWeight <= 1
    ? 'Showing every edge.'
    : `Hiding citation edges made by fewer than ${filters.minWeight} chunks. Law → law carries no `
      + 'count — the instruments only state that one provision cites another — so this never hides those.';
}

function buildControls() {
  const kindsHost = document.getElementById('g-edge-kinds');
  kindInputs.clear();
  kindsHost.replaceChildren(...EDGE_KINDS.map(([key, label, cssVar]) => {
    const count = G.edges.reduce((n, e) => n + (e.kind === key ? 1 : 0), 0);
    const input = h('input', {
      type: 'checkbox', checked: true,
      onchange: (e) => { e.target.checked ? filters.kinds.add(key) : filters.kinds.delete(key); recomputeVisibility(); },
    });
    kindInputs.set(key, input);
    return h('label', { class: 'check' },
      input,
      // The canvas draws these three in three colours and nothing said which was
      // which: EDGE_KINDS has carried the CSS variable since the view was
      // written and no control ever read it.
      h('span', { class: 'lbl' }, h('span', { class: 'line', style: `background:var(${cssVar})` }), label),
      h('span', { class: 'count', text: num(count) }));
  }));

  const instrumentsHost = document.getElementById('g-instruments');
  instrumentInputs.clear();
  instrumentsHost.replaceChildren(...[...filters.instruments].sort().map((code) => {
    const count = G.nodes.reduce((n, node) => n + (node.kind === 'provision' && node.instrument === code ? 1 : 0), 0);
    const input = h('input', {
      type: 'checkbox', checked: true,
      onchange: (e) => { e.target.checked ? filters.instruments.add(code) : filters.instruments.delete(code); recomputeVisibility(); },
    });
    instrumentInputs.set(code, input);
    return h('label', { class: 'check' },
      input,
      h('span', { class: 'lbl' }, h('span', { class: 'swatch', style: `background:var(${code === 'TMR1995' ? '--node-tmr' : '--node-tma'})` }), INSTRUMENT_NAMES[code] || code),
      h('span', { class: 'count', text: num(count) }));
  }));

  weightInput = document.getElementById('g-weight');
  // Only the weighted kinds bound the slider: law_to_law's fixed 1 would peg
  // the maximum at 1 if it were counted, and being hidden by it is exactly
  // what WEIGHTED_KINDS exists to prevent.
  weightInput.max = String(Math.max(maxWeight.manual_to_law, maxWeight.manual_to_manual, 1));
  weightInput.addEventListener('input', () => {
    filters.minWeight = Number(weightInput.value);
    updateWeightHint();
    recomputeVisibility();
  });

  document.getElementById('g-labels').addEventListener('change', (e) => { filters.labelAll = e.target.checked; needsRedraw = true; });
  document.getElementById('g-reset').addEventListener('click', () => { focusNode(null); fitView(); });

  const search = document.getElementById('g-search');
  const list = document.getElementById('g-search-list');
  search.addEventListener('input', () => {
    const q = search.value.trim().toLowerCase();
    list.replaceChildren();
    if (q.length < 2) return;
    const scored = [];
    for (const node of G.nodes) {
      const hay = (node.label + ' ' + (node.title || '') + ' ' + (node.ref || node.part_id)).toLowerCase();
      const at = hay.indexOf(q);
      if (at === -1) continue;
      scored.push({ node, rank: at });
    }
    scored.sort((a, b) => a.rank - b.rank || a.node.label.localeCompare(b.node.label));
    for (const { node } of scored.slice(0, 20)) list.append(h('option', { value: searchLabel(node) }));
  });
  // Matched fresh against the graph, not against a Map the `input` handler
  // built: selecting a datalist option re-fires `input` with the option's own
  // full text as the query first, which is a search that finds nothing (the
  // "label — title" separator isn't in any node's haystack) and would wipe a
  // Map-based lookup out from under this handler before it runs.
  search.addEventListener('change', () => {
    const value = search.value.trim();
    if (!value) return;
    const hit = G.nodes.find((node) => searchLabel(node) === value) ||
      G.nodes.find((node) => node.label.toLowerCase() === value.toLowerCase());
    if (hit) { focusNode(hit, { moveFocus: true }); search.value = ''; list.replaceChildren(); }
    else setNotice(`Nothing on this map answers to “${value}”. A provision no chunk cites and that cites nothing has no edge to draw, so it is not here.`);
  });
  // Escape in a search box means "clear the box", the browser's own convention.
  // The window-level Escape handler below would otherwise take it and close the
  // focus panel instead, leaving the half-typed query sitting there.
  search.addEventListener('keydown', (event) => {
    if (event.key === 'Escape' && search.value) {
      search.value = '';
      list.replaceChildren();
      event.stopPropagation();
    }
  });
}

/* ------------------------------------------------- keyboard traversal */

/** The drawn nodes in a stable reading order — the Manual's Parts, then the
 * provisions, each by label — so `n`/`p` walk the map the same way twice. */
function traversalOrder() {
  return visibleNodes.slice().sort((a, b) =>
    (a.kind === b.kind ? 0 : a.kind === 'part' ? -1 : 1) ||
    a.label.localeCompare(b.label, 'en-AU', { numeric: true }));
}

function nodeNearestCentre() {
  const [wx, wy] = toWorld(cssWidth / 2, cssHeight / 2);
  let best = null, bestDist = Infinity;
  for (const node of visibleNodes) {
    const p = layout.get(node.id);
    const dist = (p.x - wx) ** 2 + (p.y - wy) ** 2;
    if (dist < bestDist) { best = node; bestDist = dist; }
  }
  return best;
}

/** Announce the focused node to a screen reader. `n`/`p` stepping keeps keyboard
 * focus on the canvas so the next keystroke lands, which means nothing else in
 * the page would say what just got focused. */
function announce(text) {
  const live = document.getElementById('g-live');
  if (live) live.textContent = text;
}

/* ------------------------------------------------------------- pointing */

function wireInteraction() {
  const pointers = new Map();
  let dragNode = null, dragged = false, lastPan = null, pinchStart = null;

  canvas.addEventListener('pointerdown', (event) => {
    canvas.setPointerCapture(event.pointerId);
    autoFit = null;
    pointers.set(event.pointerId, { x: event.clientX, y: event.clientY });
    if (pointers.size === 1) {
      const rect = canvas.getBoundingClientRect();
      const sx = event.clientX - rect.left, sy = event.clientY - rect.top;
      dragNode = pick(sx, sy);
      dragged = false;
      lastPan = { x: event.clientX, y: event.clientY };
      if (dragNode) simActive = true;
    } else if (pointers.size === 2) {
      const pts = [...pointers.values()];
      pinchStart = { dist: Math.hypot(pts[0].x - pts[1].x, pts[0].y - pts[1].y), k: camera.k };
      dragNode = null;
    }
  });

  canvas.addEventListener('pointermove', (event) => {
    if (!pointers.has(event.pointerId)) {
      const rect = canvas.getBoundingClientRect();
      const hit = pick(event.clientX - rect.left, event.clientY - rect.top);
      const hitId = hit ? hit.id : null;
      if (hitId !== hoveredId) { hoveredId = hitId; needsRedraw = true; }
      showTooltip(hit, event.clientX, event.clientY, rect);
      return;
    }
    pointers.set(event.pointerId, { x: event.clientX, y: event.clientY });

    if (pointers.size === 2 && pinchStart) {
      const pts = [...pointers.values()];
      const dist = Math.hypot(pts[0].x - pts[1].x, pts[0].y - pts[1].y);
      camera.k = clamp(pinchStart.k * (dist / (pinchStart.dist || 1)), MIN_K, MAX_K);
      dragged = true;   // a pinch is not a background click; don't clear focus on release
      needsRedraw = true;
      return;
    }

    const rect = canvas.getBoundingClientRect();
    if (dragNode) {
      const [wx, wy] = toWorld(event.clientX - rect.left, event.clientY - rect.top);
      const p = layout.get(dragNode.id);
      p.fx = wx; p.fy = wy;
      dragged = true;
      needsRedraw = true;
    } else if (lastPan) {
      camera.x += (event.clientX - lastPan.x) / camera.k;
      camera.y += (event.clientY - lastPan.y) / camera.k;
      lastPan = { x: event.clientX, y: event.clientY };
      dragged = true;
      needsRedraw = true;
    }
  });

  function endPointer(event) {
    pointers.delete(event.pointerId);
    if (pointers.size < 2) pinchStart = null;
    if (pointers.size === 1) {
      // One finger lifted out of a pinch. lastPan still holds where that finger
      // went down, so the next move would pan by the whole gap between the two
      // — a jump. Re-anchor on the finger that is still down.
      const [remaining] = [...pointers.values()];
      lastPan = { x: remaining.x, y: remaining.y };
      dragNode = null;
    }
    if (pointers.size === 0) {
      if (dragNode) {
        if (!dragged) { focusNode(dragNode, { pan: false }); }
        // A dragged node stays pinned where it was dropped; double-click frees it.
      } else if (!dragged) {
        focusNode(null);
      }
      dragNode = null;
      lastPan = null;
      dragged = false;
    }
  }
  canvas.addEventListener('pointerup', endPointer);
  canvas.addEventListener('pointercancel', endPointer);

  canvas.addEventListener('dblclick', (event) => {
    const rect = canvas.getBoundingClientRect();
    const hit = pick(event.clientX - rect.left, event.clientY - rect.top);
    if (hit) {
      const p = layout.get(hit.id);
      p.fx = null; p.fy = null;
      simActive = true; alpha = Math.max(alpha, 0.25);
      needsRedraw = true;
    }
  });

  canvas.addEventListener('wheel', (event) => {
    event.preventDefault();
    const rect = canvas.getBoundingClientRect();
    const factor = Math.exp(-event.deltaY * 0.0015);
    zoomAt(event.clientX - rect.left, event.clientY - rect.top, factor);
  }, { passive: false });

  canvas.addEventListener('mouseleave', () => {
    hoveredId = null;
    document.getElementById('graph-tooltip').hidden = true;
    needsRedraw = true;
  });

  // The canvas carries tabindex="0" and, until now, no key did anything once you
  // had tabbed to it: a focus stop that could not be operated. Pan, zoom, and
  // step from node to node, so the map itself — not only the panel beside it —
  // is reachable without a pointer.
  canvas.addEventListener('keydown', (event) => {
    if (event.ctrlKey || event.metaKey || event.altKey) return;
    autoFit = null;
    const step = 70 / camera.k;
    switch (event.key) {
      case 'ArrowLeft': camera.x += step; break;
      case 'ArrowRight': camera.x -= step; break;
      case 'ArrowUp': camera.y += step; break;
      case 'ArrowDown': camera.y -= step; break;
      case '+': case '=': zoomAt(cssWidth / 2, cssHeight / 2, 1.25); break;
      case '-': case '_': zoomAt(cssWidth / 2, cssHeight / 2, 1 / 1.25); break;
      case '0': focusNode(null); fitView(); announce('View reset to the whole drawn graph.'); break;
      case 'Enter': case ' ': {
        const node = nodeNearestCentre();
        if (node) { focusNode(node); announce(`${searchLabel(node)} focused.`); }
        break;
      }
      case 'n': case 'N': case 'p': case 'P': {
        const order = traversalOrder();
        if (!order.length) break;
        const back = event.key === 'p' || event.key === 'P';
        const at = order.findIndex((node) => node.id === focusedId);
        const next = at === -1
          ? (back ? order.length - 1 : 0)
          : (at + (back ? -1 : 1) + order.length) % order.length;
        focusNode(order[next]);
        announce(`${searchLabel(order[next])}, ${next + 1} of ${order.length}.`);
        break;
      }
      case 'Escape': focusNode(null); announce('Focus cleared.'); break;
      default: return;   // Tab, and every key not listed, stays the browser's
    }
    needsRedraw = true;
    event.preventDefault();
  });

  // Escape anywhere clears the focus. The search box stops its own Escape from
  // reaching here while it still has text to clear, so the first press empties
  // the box and a second one — with nothing left to clear — falls through.
  window.addEventListener('keydown', (event) => {
    if (event.key === 'Escape') focusNode(null);
  });
}

function showTooltip(node, clientX, clientY, rect) {
  const tip = document.getElementById('graph-tooltip');
  if (!node) { tip.hidden = true; return; }
  const lines = node.kind === 'part'
    ? [h('strong', { text: node.label }), node.title, h('div', { class: 'mono', text: `${num(node.chunks)} chunks · ${num(node.pages)} pages` })]
    : [h('strong', { text: node.label }), node.title, h('div', { class: 'mono', text: `${INSTRUMENT_NAMES[node.instrument] || node.instrument} · ${num(node.manual_citations)} Manual citations` })];
  tip.replaceChildren(...lines.filter(Boolean));
  tip.hidden = false;
  const x = clientX - rect.left, y = clientY - rect.top;
  tip.style.left = clamp(x + 14, 4, rect.width - tip.offsetWidth - 4) + 'px';
  tip.style.top = clamp(y + 14, 4, rect.height - tip.offsetHeight - 4) + 'px';
}

/* ---------------------------------------------------------------- legend */

/* Appending this to the panel put it below a paragraph of prose and off the
 * bottom of a 950px-tall window, where a legend explains nothing. It now fills a
 * slot the markup reserves for it, above the fold. */
function buildLegend() {
  const host = document.getElementById('g-legend');
  if (!host) return;
  host.replaceChildren(h('div', { class: 'legend' },
    h('span', {}, h('span', { class: 'swatch', style: `background:${theme.part}` }), 'Part of the Manual'),
    h('span', {}, h('span', { class: 'swatch', style: `background:${theme.tma}` }), 'Trade Marks Act 1995'),
    h('span', {}, h('span', { class: 'swatch', style: `background:${theme.tmr}` }), 'Trade Marks Regulations 1995')));
}

/** graph.html#part:<id> / #prov:<ref> — the deep-link a click from the reader
 * lands on. Read at boot and on `hashchange`: Chrome treats a navigation that
 * only changes the fragment as same-document, so a link clicked while this
 * page is already the active tab does not reload it and boot() would never
 * run a second time. `focusNode` itself only ever calls `history.replaceState`
 * (never assigns `location.hash`), so it does not fire `hashchange` back at
 * this listener. */
function focusFromHash() {
  const match = /^#(part|prov):(.+)$/.exec(location.hash);
  if (!match) return false;
  let wanted;
  try {
    wanted = decodeURIComponent(match[2]);
  } catch {
    // A truncated or hand-edited fragment. `#prov:100%` is the one that turns
    // up, decodeURIComponent throws URIError on it, and the throw used to escape
    // boot() — taking the canvas, every listener and the animation loop with it,
    // leaving a blank stage and no message anywhere. Read it literally instead;
    // it will match no node and be reported as such below.
    wanted = match[2];
  }
  const target = G.nodes.find((node) => (match[1] === 'part' ? node.part_id === wanted : node.ref === wanted));
  if (!target) {
    setNotice(`This link names ${match[1] === 'part' ? 'a Part' : 'a provision'}, “${wanted}”, that is not on the map.`);
    return false;
  }
  focusNode(target);
  // Keep this node's neighbourhood framed while the layout settles. Landing on a
  // deep link used to leave the camera at its initial k of 1 — a zoom picked by
  // nothing, since how much room the graph needs depends on how many nodes it
  // has — with the node merely centred at whatever scale that happened to be.
  autoFit = target.id;
  simActive = true;
  alpha = Math.max(alpha, 0.35);
  return true;
}

/* ------------------------------------------------------------------- boot */

async function boot() {
  canvas = document.getElementById('graph-canvas');
  ctx = canvas.getContext('2d');

  try {
    const data = await getJSON('data/graph.json');
    G.nodes = data.nodes;
    G.edges = data.edges;
  } catch (err) {
    document.getElementById('graph-stage').replaceChildren(
      h('div', { class: 'card empty' },
        h('strong', { text: 'The graph data is missing.' }),
        h('p', { text: 'Run `python viz/build.py` and serve the output directory.' }),
        h('p', { class: 'mono', text: String(err) })));
    return;
  }

  buildIndex();
  readTheme();
  buildControls();
  buildLegend();
  recomputeVisibility();

  resizeCanvas();
  new ResizeObserver(resizeCanvas).observe(document.getElementById('graph-stage'));

  // Interaction and the draw loop go up before the deep link is read, not after.
  // Whatever a fragment does — and one of them used to throw — the map is
  // already drawn and already answers to the mouse and the keyboard.
  wireInteraction();
  requestAnimationFrame(frame);

  if (!focusFromHash()) { autoFit = 'all'; fitView(); }
  window.addEventListener('hashchange', focusFromHash);

  matchMedia('(prefers-color-scheme: dark)').addEventListener('change', () => { readTheme(); needsRedraw = true; });
}

boot();

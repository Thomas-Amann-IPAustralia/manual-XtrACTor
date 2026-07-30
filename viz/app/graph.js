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
let maxWeight = { manual_to_law: 1, law_to_law: 1, manual_to_manual: 1 };

let camera = { x: 0, y: 0, k: 1 };
let hoveredId = null;
let focusedId = null;
let followedId = null;         // camera tracks this node while the sim settles
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

  let index = 0;
  for (const node of G.nodes) {
    const seed = seedPosition(node.id, index++, G.nodes.length);
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
    if (edge.weight < filters.minWeight) return false;
    const a = nodeById.get(edge.source), b = nodeById.get(edge.target);
    if (a.kind === 'provision' && !filters.instruments.has(a.instrument)) return false;
    if (b.kind === 'provision' && !filters.instruments.has(b.instrument)) return false;
    return true;
  };
  visibleEdges = G.edges.filter(edgeOk);

  const touched = new Set();
  for (const edge of visibleEdges) { touched.add(edge.source); touched.add(edge.target); }
  visibleNodes = G.nodes.filter((node) => {
    if (node.kind === 'part') return true;
    return filters.instruments.has(node.instrument) && touched.has(node.id);
  });

  updateStatus();
  needsRedraw = true;
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

  if (followedId != null) {
    const p = layout.get(followedId);
    if (p) { camera.x = -p.x; camera.y = -p.y; }
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
  const [wx, wy] = toWorld(sx, sy);
  camera.k = clamp(camera.k * factor, MIN_K, MAX_K);
  camera.x = (sx - cssWidth / 2) / camera.k - wx;
  camera.y = (sy - cssHeight / 2) / camera.k - wy;
  needsRedraw = true;
}

function fitView(nodesToFit) {
  const pts = (nodesToFit && nodesToFit.length ? nodesToFit : G.nodes).map((n) => layout.get(n.id));
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
  theme.dim = get('--line-2', '#c6c3ba');
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
    const strength = Math.log(edge.weight + 1) / Math.log(cap + 1);
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
    if (ticked) needsRedraw = true;
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

function focusNode(node, { pan = true } = {}) {
  focusedId = node ? node.id : null;
  followedId = null;
  // history.replaceState only — never assign location.hash directly, which
  // navigates and pushes a history entry of its own; clicking through a dozen
  // nodes should not fill up the back button with a dozen stops.
  const hash = node ? `#${node.kind === 'part' ? 'part' : 'prov'}:${node.kind === 'part' ? node.part_id : node.ref}` : '';
  history.replaceState(null, '', location.pathname + location.search + hash);
  if (node && pan) fitView([node, ...(neighbours.get(node.id) || []).map((n) => n.other)]);
  renderFocusPanel(node);
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

  for (const { other, edge } of neighbours.get(node.id) || []) {
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
  panel.replaceChildren(
    h('button', { class: 'link-btn close-focus', type: 'button', text: 'Close ✕', onclick: () => focusNode(null) }),
    h('h3', { text: node.label }),
    h('p', { class: 'sub', text: isPart ? node.title : [INSTRUMENT_NAMES[node.instrument] || node.instrument, node.title].filter(Boolean).join(' — ') }),
    h('p', { class: 'sub mono', text: isPart ? `${num(node.chunks)} chunks across ${num(node.pages)} pages` : node.ref }),
    h('div', { class: 'neighbour-groups' },
      [...groups.entries()].map(([heading, entries]) => h('div', {},
        h('h4', { text: `${heading} (${entries.length})` }),
        h('ul', {}, entries.slice(0, 60).map((entry) => h('li', {},
          h('button', { class: 'ref-link', text: entry.other.label, title: entry.other.title || entry.other.ref || '', onclick: () => focusNode(entry.other) }),
          h('span', { class: 'count', text: num(entry.count) })))))),
      !groups.size ? h('p', { class: 'hint', text: 'No visible edges under the current filters.' }) : null),
    h('a', {
      class: 'link-btn open-link',
      href: `index.html#/${routeFor(node).map(encodeURIComponent).join('/')}`,
      text: 'Open in the reader →',
    }));
}

/* -------------------------------------------------------------- controls */

function buildControls() {
  const kindsHost = document.getElementById('g-edge-kinds');
  kindsHost.replaceChildren(...EDGE_KINDS.map(([key, label]) => {
    const count = G.edges.reduce((n, e) => n + (e.kind === key ? 1 : 0), 0);
    return h('label', { class: 'check' },
      h('input', {
        type: 'checkbox', checked: true,
        onchange: (e) => { e.target.checked ? filters.kinds.add(key) : filters.kinds.delete(key); recomputeVisibility(); },
      }),
      h('span', { class: 'lbl', text: label }),
      h('span', { class: 'count', text: num(count) }));
  }));

  const instrumentsHost = document.getElementById('g-instruments');
  instrumentsHost.replaceChildren(...[...filters.instruments].sort().map((code) => {
    const count = G.nodes.reduce((n, node) => n + (node.kind === 'provision' && node.instrument === code ? 1 : 0), 0);
    return h('label', { class: 'check' },
      h('input', {
        type: 'checkbox', checked: true,
        onchange: (e) => { e.target.checked ? filters.instruments.add(code) : filters.instruments.delete(code); recomputeVisibility(); },
      }),
      h('span', { class: 'lbl', text: INSTRUMENT_NAMES[code] || code }),
      h('span', { class: 'count', text: num(count) }));
  }));

  const weightInput = document.getElementById('g-weight');
  const overallMax = Math.max(maxWeight.manual_to_law, maxWeight.manual_to_manual, maxWeight.law_to_law, 1);
  weightInput.max = String(overallMax);
  weightInput.addEventListener('input', () => {
    filters.minWeight = Number(weightInput.value);
    document.getElementById('g-weight-value').textContent =
      filters.minWeight <= 1 ? 'Showing every edge.' : `Hiding edges cited fewer than ${filters.minWeight} times.`;
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
    if (hit) { focusNode(hit); search.value = ''; list.replaceChildren(); }
  });
}

/* ------------------------------------------------------------- pointing */

function wireInteraction() {
  const pointers = new Map();
  let dragNode = null, dragged = false, lastPan = null, pinchStart = null;

  canvas.addEventListener('pointerdown', (event) => {
    canvas.setPointerCapture(event.pointerId);
    pointers.set(event.pointerId, { x: event.clientX, y: event.clientY });
    followedId = null;
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
    followedId = null;
    const rect = canvas.getBoundingClientRect();
    const factor = Math.exp(-event.deltaY * 0.0015);
    zoomAt(event.clientX - rect.left, event.clientY - rect.top, factor);
  }, { passive: false });

  canvas.addEventListener('mouseleave', () => {
    hoveredId = null;
    document.getElementById('graph-tooltip').hidden = true;
    needsRedraw = true;
  });

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

function buildLegend() {
  const panel = document.getElementById('graph-panel');
  panel.append(h('div', { class: 'legend' },
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
  const wanted = decodeURIComponent(match[2]);
  const target = G.nodes.find((node) => (match[1] === 'part' ? node.part_id === wanted : node.ref === wanted));
  if (!target) return false;
  focusNode(target, { pan: false });
  followedId = target.id;   // re-assert: focusNode itself always clears it
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

  if (!focusFromHash()) fitView();
  window.addEventListener('hashchange', focusFromHash);

  wireInteraction();
  requestAnimationFrame(frame);

  matchMedia('(prefers-color-scheme: dark)').addEventListener('change', () => { readTheme(); needsRedraw = true; });
}

boot();

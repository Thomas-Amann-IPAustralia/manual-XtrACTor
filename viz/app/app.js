/* Trade Marks Manual and the legislation it is about — snapshot viewer.
 *
 * Reads the bundle built by viz/build.py. Three tiers of loading, matching the
 * three tiers of disclosure: manual.json paints the Parts, chunks.json and
 * legislation.json power the filters and the passage text, and a page's or a
 * provision's own file is fetched only when a reader opens it and wants the
 * structure inside — the paragraphs of a chunk, the subsections of a section.
 *
 * The two corpora are filtered by one set of predicates rather than two,
 * because they share one reference grammar: a Manual chunk's provisions[].id
 * and a provision's own ref are the same string, so "cites TMA1995/s41" is a
 * question both halves can answer. Where a predicate belongs to one half only
 * — Part, heading source, page metadata — choosing it excludes the other,
 * which is the honest answer to a conjunction it cannot satisfy.
 *
 * Nothing here writes anything anywhere. Every value shown is a field the
 * pipeline put in the snapshot; where this file derives something (a count, a
 * reverse index, the join between the halves) it says so on screen.
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
const plural = (n, one, many) => `${num(n)} ${n === 1 ? one : many || one + 's'}`;

/** Text with every occurrence of `needle` wrapped in <mark>. */
function marked(text, needle) {
  if (!needle) return document.createTextNode(text);
  const frag = document.createDocumentFragment();
  const hay = text.toLowerCase();
  const term = needle.toLowerCase();
  let at = 0;
  for (;;) {
    const found = hay.indexOf(term, at);
    if (found === -1) break;
    frag.append(text.slice(at, found), h('mark', { text: text.slice(found, found + term.length) }));
    at = found + term.length;
  }
  frag.append(text.slice(at));
  return frag;
}

const SOURCE_ROOT = 'https://manuals.ipaustralia.gov.au';
const SOURCE_HOST = 'manuals.ipaustralia.gov.au';

/** `fetch.normalise_url`, in the browser: the key a Manual URL is known by.
 *
 * Absolutises against the site root, drops query and fragment, lowercases the
 * host, strips a trailing slash, and forces the scheme on the Manual's own
 * host — which links to itself as `http://`, `https://` and relative paths
 * indifferently. Mirrors the pipeline because it has to agree with it: this is
 * how a link's href finds the page the snapshot filed it under.
 */
function normaliseUrl(href) {
  try {
    const url = new URL(String(href), SOURCE_ROOT);
    const host = url.hostname.toLowerCase();
    const scheme = host === SOURCE_HOST ? 'https' : url.protocol.replace(':', '');
    let path = url.pathname || '/';
    if (path.length > 1) path = path.replace(/\/+$/, '');
    return `${scheme}://${host}${url.port ? ':' + url.port : ''}${path}`;
  } catch (err) {
    return null;
  }
}

/** A link's href as something a browser can follow: absolute, fragment kept. */
function absoluteHref(href) {
  try {
    return new URL(String(href), SOURCE_ROOT).href;
  } catch (err) {
    return String(href);
  }
}

/** Where each block's text sits in `chunk.text`.
 *
 * Derived, not stored — the snapshot's own contract is that joining the
 * blocks' text with single spaces reproduces `text` exactly, so the offsets
 * follow from the lengths. Blocks with no text (images) contribute nothing and
 * no separator, which is the same step the join in `validate.py` takes.
 *
 * This is the join that lets a chunk-level link offset find the block it falls
 * in. Nothing is added to a chunk to make it work — viz/README.md.
 */
function blockStarts(chunk) {
  const starts = [];
  let at = 0;
  for (const block of chunk.blocks || []) {
    if (typeof block.text !== 'string') { starts.push(null); continue; }
    starts.push(at);
    at += block.text.length + 1;
  }
  return starts;
}

/** Text with the Manual's own hyperlinks put back, and the search term marked.
 *
 * `links` carry offsets into `chunk.text`; `offset` says where this run of
 * text starts in it. A link is drawn only where the snapshot's own words agree
 * with the text at those offsets — if a stale bundle is being served against a
 * newer snapshot, the reader gets the prose rather than a link pointing at the
 * wrong words.
 */
function linked(text, offset, links, needle) {
  const inside = (links || []).filter((link) =>
    link.end > link.start &&
    link.start >= offset &&
    link.end <= offset + text.length &&
    text.slice(link.start - offset, link.end - offset) === link.text);
  if (!inside.length) return marked(text, needle);

  const frag = document.createDocumentFragment();
  let at = 0;
  for (const link of inside) {
    const start = link.start - offset;
    if (start < at) continue;                       // overlaps the one before it
    if (start > at) frag.append(marked(text.slice(at, start), needle));
    frag.append(sourceLink(link, needle));
    at = link.end - offset;
  }
  frag.append(marked(text.slice(at), needle));
  return frag;
}

/** One anchor, as the Manual set it. Internal targets stay in the viewer. */
function sourceLink(link, needle) {
  const target = INDEX.pageByUrl.get(normaliseUrl(link.href));
  if (target) {
    return h('a', {
      class: 'src-link', href: hashFor(['page', target]),
      title: `${link.href} — in this snapshot as ${target}`,
      onclick: (e) => { e.preventDefault(); go(['page', target]); },
    }, marked(link.text, needle));
  }
  return h('a', {
    class: 'src-link out', href: absoluteHref(link.href), rel: 'noreferrer',
    title: link.href,
  }, marked(link.text, needle));
}

const AUSTLII = {
  TMA1995: 'https://www.austlii.edu.au/cgi-bin/viewdb/au/legis/cth/consol_act/tma1995121/',
  TMR1995: 'https://www.austlii.edu.au/cgi-bin/viewdb/au/legis/cth/consol_reg/tmr1995209/',
};

const INSTRUMENT_NAMES = {
  TMA1995: 'Trade Marks Act 1995',
  TMR1995: 'Trade Marks Regulations 1995',
  TMA1955: 'Trade Marks Act 1955',
  TMA1905: 'Trade Marks Act 1905',
  AIA1901: 'Acts Interpretation Act 1901',
  PBRA1994: 'Plant Breeder’s Rights Act 1994',
  DR2016: 'Designs Regulations 2016',
};

/* -------------------------------------------------------------------- state */

const DATA = { manual: null, chunks: null, law: null, ready: false, lawReady: false };
const INDEX = {
  pageByRef: new Map(),
  pageByUrl: new Map(),   // normalised url -> page_ref, so a link's href finds its page
  chunkByRef: new Map(),
  chunksByPage: new Map(),
  partByRef: new Map(),
  haystack: [],       // parallel to DATA.chunks.chunks — never merged into a chunk
  tables: {},
  citedBy: {},
  // The legislation half. Same discipline: every map here is keyed by a ref
  // and lives beside the records, never on them.
  provisionByRef: new Map(),
  provisionsByInstrument: new Map(),
  provisionsByContainer: new Map(),   // container ref -> provisions directly under it
  containerByRef: new Map(),
  containerChildren: new Map(),
  instrumentByCode: new Map(),
  lawHaystack: [],    // parallel to DATA.law.provisions
  lawUnits: {},
  lawTables: {},
  lawEdges: {},           // provision ref -> its units' provision references
  lawCites: {},
  lawCitedBy: {},
  manualCites: {},        // provision ref -> chunk refs citing it
  manualCitesUnit: {},    // unit ref -> chunk refs citing that unit exactly
  unitOwner: {},          // cited unit ref -> the provision holding it
};

const SETS = ['corpus', 'parts', 'kinds', 'headingSources', 'instruments', 'extraction', 'certainty', 'flags', 'pageflags'];
const S = {
  q: '', provision: '', caseq: '', year: '',
  corpus: new Set(),
  parts: new Set(), kinds: new Set(), headingSources: new Set(),
  instruments: new Set(), extraction: new Set(), certainty: new Set(),
  flags: new Set(), pageflags: new Set(),
};

const FLAGS = [
  ['provisions', 'cites legislation'],
  ['cases', 'cites case law'],
  ['refs', 'links to elsewhere in the Manual'],
  ['cited', 'linked to from elsewhere'],
  ['tables', 'contains a table'],
  ['fragment', 'is part of a split section'],
];
const PAGE_FLAGS = [
  ['archived', 'page carries the archived banner'],
  ['retired', 'page has left the navigation'],
  ['images', 'page contains an image'],
  ['note', 'page has an amendment note'],
];

const QUERY_KEYS = {
  q: 'q', provision: 'prov', caseq: 'case', year: 'year',
  corpus: 'in', parts: 'part', kinds: 'kind', headingSources: 'hs',
  instruments: 'inst', extraction: 'extr', certainty: 'cert',
  flags: 'has', pageflags: 'page',
};

function filtersActive() {
  return Boolean(S.q || S.provision || S.caseq || S.year) || SETS.some((k) => S[k].size);
}

/* ------------------------------------------------------------------ routing */

function readHash() {
  const raw = location.hash.replace(/^#\/?/, '');
  const [pathPart, queryPart] = raw.split('?');
  const path = pathPart ? pathPart.split('/').filter(Boolean).map(decodeURIComponent) : [];
  return { path, params: new URLSearchParams(queryPart || '') };
}

function hashFor(path) {
  const params = new URLSearchParams();
  for (const [key, qkey] of Object.entries(QUERY_KEYS)) {
    const value = S[key];
    if (value instanceof Set) { if (value.size) params.set(qkey, [...value].join(',')); }
    else if (value) params.set(qkey, value);
  }
  const query = params.toString();
  return '#/' + path.map(encodeURIComponent).join('/') + (query ? '?' + query : '');
}

function stateFromParams(params) {
  for (const [key, qkey] of Object.entries(QUERY_KEYS)) {
    const raw = params.get(qkey);
    if (S[key] instanceof Set) {
      S[key] = new Set(raw ? raw.split(',').filter(Boolean) : []);
    } else {
      S[key] = raw || '';
    }
  }
}

let currentPath = [];

/** Navigate without a round trip through hashchange. */
function go(path, replace) {
  currentPath = path;
  const url = hashFor(path);
  if (replace) history.replaceState(null, '', url);
  else history.pushState(null, '', url);
  render();
}

function syncHash() { history.replaceState(null, '', hashFor(currentPath)); }

window.addEventListener('popstate', () => {
  const { path, params } = readHash();
  stateFromParams(params);
  currentPath = path;
  syncControls();
  render();
});

window.addEventListener('hashchange', () => {
  const { path, params } = readHash();
  if (hashFor(path) === location.hash) return;
  stateFromParams(params);
  currentPath = path;
  syncControls();
  render();
});

/* --------------------------------------------------------------- data load */

async function getJSON(url) {
  const response = await fetch(url);
  if (!response.ok) throw new Error(`${url}: ${response.status}`);
  return response.json();
}

async function boot() {
  const { path, params } = readHash();
  currentPath = path;
  stateFromParams(params);

  try {
    DATA.manual = await getJSON('data/manual.json');
  } catch (err) {
    document.getElementById('view').replaceChildren(
      h('div', { class: 'card empty' },
        h('strong', { text: 'The data bundle is missing.' }),
        h('p', { text: 'Run `python viz/build.py` and serve the output directory.' }),
        h('p', { class: 'mono', text: String(err) })));
    return;
  }

  for (const page of DATA.manual.pages) {
    INDEX.pageByRef.set(page.page_ref, page);
    INDEX.partByRef.set(page.page_ref, page.part_id);
    const key = normaliseUrl(page.url);
    if (key && !INDEX.pageByUrl.has(key)) INDEX.pageByUrl.set(key, page.page_ref);
  }
  renderCorpus();
  buildControls();
  syncControls();
  render();

  // The legislation half is optional: a snapshot can hold the Manual without
  // it, and the builder then writes no legislation.json at all. A miss here is
  // that case, not a failure — the viewer carries on as the Manual's alone.
  try {
    DATA.law = await getJSON('data/legislation.json');
    indexLegislation();
  } catch (err) {
    DATA.law = null;
  }
  buildSharedControls();
  syncControls();
  renderCorpus();
  render();

  try {
    DATA.chunks = await getJSON('data/chunks.json');
  } catch (err) {
    document.getElementById('match-line').textContent = 'Chunk index failed to load.';
    return;
  }
  INDEX.tables = DATA.chunks.tables || {};
  INDEX.citedBy = DATA.chunks.cited_by || {};
  DATA.chunks.chunks.forEach((chunk, i) => {
    INDEX.chunkByRef.set(chunk.chunk_ref, chunk);
    if (!INDEX.chunksByPage.has(chunk.page_ref)) INDEX.chunksByPage.set(chunk.page_ref, []);
    INDEX.chunksByPage.get(chunk.page_ref).push(chunk);
    INDEX.haystack[i] = (chunk.heading_path.join(' ') + ' ' + chunk.text).toLowerCase();
  });
  DATA.ready = true;
  render();
}

const pageFiles = new Map();
function loadPageFile(page) {
  if (!pageFiles.has(page.page_ref)) {
    pageFiles.set(page.page_ref, getJSON('pages/' + page.file));
  }
  return pageFiles.get(page.page_ref);
}

const lawFiles = new Map();
/** A provision's own file — the units, and everything hanging off them. */
function loadProvisionFile(ref) {
  if (!lawFiles.has(ref)) {
    lawFiles.set(ref, getJSON('legislation/' + DATA.law.files[ref]));
  }
  return lawFiles.get(ref);
}

/** An instrument's contents, endnotes or record file, by convention. */
function loadInstrumentFile(code, name) {
  const key = code + '/' + name;
  if (!lawFiles.has(key)) lawFiles.set(key, getJSON('legislation/' + key));
  return lawFiles.get(key);
}

function indexLegislation() {
  const law = DATA.law;
  INDEX.lawUnits = law.units || {};
  INDEX.lawTables = law.tables || {};
  INDEX.lawEdges = law.edges || {};
  INDEX.lawCites = law.cites || {};
  INDEX.lawCitedBy = law.cited_by || {};
  INDEX.manualCites = law.cited_by_manual || {};
  INDEX.manualCitesUnit = law.cited_by_manual_units || {};
  INDEX.unitOwner = law.unit_owners || {};

  for (const instrument of law.instruments) {
    INDEX.instrumentByCode.set(instrument.code, instrument);
    INDEX.provisionsByInstrument.set(instrument.code, []);
    for (const container of (law.containers || {})[instrument.code] || []) {
      INDEX.containerByRef.set(container.ref, container);
      const parent = container.parent_ref || instrument.code;
      if (!INDEX.containerChildren.has(parent)) INDEX.containerChildren.set(parent, []);
      INDEX.containerChildren.get(parent).push(container);
    }
  }

  law.provisions.forEach((provision, i) => {
    INDEX.provisionByRef.set(provision.ref, provision);
    const list = INDEX.provisionsByInstrument.get(provision.instrument);
    if (list) list.push(provision);
    // Filed under its innermost container, or under the instrument itself
    // where it has none — front matter, and the sections before Part 1.
    const containers = provision.containers || [];
    const home = containers.length ? containers[containers.length - 1] : provision.instrument;
    if (!INDEX.provisionsByContainer.has(home)) INDEX.provisionsByContainer.set(home, []);
    INDEX.provisionsByContainer.get(home).push(provision);
    INDEX.lawHaystack[i] = (provision.heading_path.join(' ') + ' ' + provision.text).toLowerCase();
  });
  DATA.lawReady = true;
}

/** The top-level container a provision sits in, for grouping and crumbs. */
function topContainer(provision) {
  const containers = provision.containers || [];
  return containers.length ? containers[0] : null;
}

function containerLabel(container) {
  return `${container.kind} ${container.number}`;
}

/** Every provision under a container, including its Divisions and below. */
function provisionsUnder(ref) {
  const out = INDEX.provisionsByContainer.get(ref) ? [...INDEX.provisionsByContainer.get(ref)] : [];
  for (const child of INDEX.containerChildren.get(ref) || []) out.push(...provisionsUnder(child.ref));
  return out;
}

/* ---------------------------------------------------------------- matching */

function chunkMatches(chunk, i) {
  const page = INDEX.pageByRef.get(chunk.page_ref);

  if (S.corpus.size && !S.corpus.has('manual')) return false;
  if (S.parts.size && !S.parts.has(page ? page.part_id : '')) return false;
  if (S.kinds.size && !S.kinds.has(chunk.kind || 'body')) return false;
  if (S.headingSources.size && !S.headingSources.has(chunk.heading_source || 'none')) return false;

  const provisions = chunk.provisions || [];
  if (S.instruments.size && !provisions.some((p) => S.instruments.has(p.id.split('/')[0]))) return false;
  if (S.provision) {
    const needle = S.provision.toLowerCase();
    if (!provisions.some((p) => p.id.toLowerCase().includes(needle))) return false;
  }
  if (S.extraction.size && !provisions.some((p) => S.extraction.has(p.extraction))) return false;
  if (S.certainty.size && !provisions.some((p) => S.certainty.has(p.certainty || 'none'))) return false;

  if (S.caseq) {
    const needle = S.caseq.toLowerCase();
    const cases = chunk.cases || [];
    if (!cases.some((c) => c.id.toLowerCase().includes(needle) || c.citation.toLowerCase().includes(needle))) return false;
  }

  for (const flag of S.flags) {
    if (flag === 'provisions' && !provisions.length) return false;
    if (flag === 'cases' && !(chunk.cases || []).length) return false;
    if (flag === 'refs' && !(chunk.internal_refs || []).length) return false;
    if (flag === 'cited' && !INDEX.citedBy[chunk.chunk_ref]) return false;
    if (flag === 'tables' && !INDEX.tables[chunk.chunk_ref]) return false;
    if (flag === 'fragment' && !chunk.fragment) return false;
  }

  if (page) {
    if (S.year && (page.last_amended || '').slice(0, 4) !== S.year) return false;
    for (const flag of S.pageflags) {
      if (flag === 'archived' && !page.archived) return false;
      if (flag === 'retired' && !page.retired) return false;
      if (flag === 'images' && !(page.images || []).length) return false;
      if (flag === 'note' && !page.amendment_note) return false;
    }
  } else if (S.year || S.pageflags.size) {
    return false;
  }

  if (S.q && !INDEX.haystack[i].includes(S.q.toLowerCase())) return false;
  return true;
}

/** The same question, asked of a provision.
 *
 * Every predicate here is the one `chunkMatches` applies, read against the
 * field of the same name on the other corpus: `kind`, the provision edges in
 * its units, the text. The Manual-only predicates — Part, heading source, page
 * metadata, case law, and the structural flags that name a chunk's own fields
 * — are not reinterpreted to mean something else here. A provision simply does
 * not satisfy them, so choosing one filters the legislation out.
 */
function provisionMatches(provision, i) {
  if (S.corpus.size && !S.corpus.has(provision.instrument)) return false;
  if (S.parts.size || S.headingSources.size || S.pageflags.size || S.year || S.caseq) return false;
  if (S.kinds.size && !S.kinds.has(provision.kind)) return false;

  const edges = INDEX.lawEdges[provision.ref] || [];
  if (S.instruments.size && !edges.some((e) => S.instruments.has(e.id.split('/')[0]))) return false;
  if (S.extraction.size && !edges.some((e) => S.extraction.has(e.extraction))) return false;
  if (S.certainty.size && !edges.some((e) => S.certainty.has(e.certainty || 'none'))) return false;
  if (S.provision) {
    // A provision answers to its own address as well as to the ones it cites:
    // searching for TMA1995/s41 should find section 41 itself, not only the
    // passages that point at it.
    const needle = S.provision.toLowerCase();
    if (!provision.ref.toLowerCase().includes(needle) &&
        !edges.some((e) => e.id.toLowerCase().includes(needle))) return false;
  }

  for (const flag of S.flags) {
    if (flag === 'provisions' && !edges.length) return false;
    if (flag === 'cited' && !(INDEX.lawCitedBy[provision.ref] || INDEX.manualCites[provision.ref])) return false;
    if (flag === 'tables' && !INDEX.lawTables[provision.ref]) return false;
    if (flag === 'cases' || flag === 'refs' || flag === 'fragment') return false;
  }

  if (S.q && !INDEX.lawHaystack[i].includes(S.q.toLowerCase())) return false;
  return true;
}

let RESULTS = {
  refs: new Set(), byPart: new Map(), byPage: new Map(), list: [], all: false,
  lawRefs: new Set(), byInstrument: new Map(), byContainer: new Map(), lawList: [],
};

function recompute() {
  RESULTS = {
    refs: new Set(), byPart: new Map(), byPage: new Map(), list: [], all: !filtersActive(),
    lawRefs: new Set(), byInstrument: new Map(), byContainer: new Map(), lawList: [],
  };
  if (DATA.ready) {
    DATA.chunks.chunks.forEach((chunk, i) => {
      if (!chunkMatches(chunk, i)) return;
      RESULTS.refs.add(chunk.chunk_ref);
      RESULTS.list.push(chunk);
      const page = INDEX.pageByRef.get(chunk.page_ref);
      const part = page ? page.part_id : 'unknown';
      RESULTS.byPart.set(part, (RESULTS.byPart.get(part) || 0) + 1);
      RESULTS.byPage.set(chunk.page_ref, (RESULTS.byPage.get(chunk.page_ref) || 0) + 1);
    });
  }
  if (DATA.lawReady) {
    DATA.law.provisions.forEach((provision, i) => {
      if (!provisionMatches(provision, i)) return;
      RESULTS.lawRefs.add(provision.ref);
      RESULTS.lawList.push(provision);
      const code = provision.instrument;
      RESULTS.byInstrument.set(code, (RESULTS.byInstrument.get(code) || 0) + 1);
      for (const container of provision.containers || []) {
        RESULTS.byContainer.set(container, (RESULTS.byContainer.get(container) || 0) + 1);
      }
    });
  }
}

/* ------------------------------------------------------------- filter panel */

function checkboxList(container, key, options, labeller) {
  container.replaceChildren(...options.map((option) => {
    const value = String(option.value !== undefined ? option.value : option);
    const input = h('input', {
      type: 'checkbox', value, 'data-key': key,
      onchange: () => {
        if (input.checked) S[key].add(value); else S[key].delete(value);
        onFilterChange();
      },
    });
    return h('label', { class: 'check' },
      input,
      h('span', { class: 'lbl', text: labeller ? labeller(option) : value }),
      option.count !== undefined ? h('span', { class: 'count', text: num(option.count) }) : null);
  }));
}

/** Two facet vocabularies of the same name, added together.
 *
 * `kind`, `extraction`, `certainty` and the instrument of a citation are
 * fields both corpora carry, under the same names and — for kind — with
 * disjoint values, so the control that filters on one filters on both and its
 * count has to be the count of both. Nothing is invented: each side's numbers
 * are the ones its own builder counted.
 */
function mergedFacet(name) {
  const totals = new Map();
  const add = (rows) => {
    for (const row of rows || []) totals.set(row.value, (totals.get(row.value) || 0) + row.count);
  };
  add((DATA.manual.facets || {})[name]);
  if (DATA.law) add((DATA.law.facets || {})[name]);
  return [...totals.entries()]
    .map(([value, count]) => ({ value, count }))
    .sort((a, b) => b.count - a.count || a.value.localeCompare(b.value));
}

/** The controls whose vocabulary spans both halves of the snapshot. */
function buildSharedControls() {
  const group = document.getElementById('g-corpus');
  const corpus = [{ value: 'manual', count: (DATA.manual.corpus || {}).chunks, label: 'The Manual — chunks' }];
  for (const instrument of (DATA.law ? DATA.law.instruments : [])) {
    corpus.push({ value: instrument.code, count: instrument.provision_count, label: `${instrument.name} — provisions` });
  }
  group.hidden = !DATA.law;
  checkboxList(document.getElementById('f-corpus'), 'corpus', corpus, (o) => o.label);

  checkboxList(document.getElementById('f-kinds'), 'kinds', mergedFacet('kinds'));
  checkboxList(document.getElementById('f-instruments'), 'instruments', mergedFacet('instruments'),
    (o) => `${o.value}${INSTRUMENT_NAMES[o.value] ? ' — ' + INSTRUMENT_NAMES[o.value] : ''}`);
  checkboxList(document.getElementById('f-extraction'), 'extraction', mergedFacet('extraction'));
  checkboxList(document.getElementById('f-certainty'), 'certainty', mergedFacet('certainty'));

  // The suggestions are the addresses the Manual cites, then the addresses the
  // legislation snapshot holds — the same strings, from the two directions.
  const suggested = DATA.manual.facets.provisions.slice(0, 400).map((p) => p.value);
  const seen = new Set(suggested);
  if (DATA.law) {
    for (const provision of DATA.law.provisions) {
      if (!seen.has(provision.ref)) { suggested.push(provision.ref); seen.add(provision.ref); }
    }
  }
  document.getElementById('provision-list').replaceChildren(
    ...suggested.map((value) => h('option', { value })));
}

function buildControls() {
  const facets = DATA.manual.facets;

  checkboxList(document.getElementById('f-parts'),
    'parts',
    DATA.manual.parts.map((p) => ({ value: p.part_id, count: p.chunk_count, title: p.part_title })),
    (o) => o.title);

  checkboxList(document.getElementById('f-headingSources'), 'headingSources', facets.heading_sources);
  checkboxList(document.getElementById('f-flags'), 'flags',
    FLAGS.map(([value, label]) => ({ value, label })), (o) => o.label);
  checkboxList(document.getElementById('f-pageflags'), 'pageflags',
    PAGE_FLAGS.map(([value, label]) => ({ value, label })), (o) => o.label);

  document.getElementById('case-list').replaceChildren(
    ...facets.cases.slice(0, 400).map((c) => h('option', { value: c.citation })));

  buildSharedControls();

  const year = document.getElementById('year');
  const years = [...facets.amended_years].sort((a, b) => b.value.localeCompare(a.value));
  year.append(...years.map((y) => h('option', { value: y.value, text: `${y.value} (${plural(y.count, 'page')})` })));

  const debounce = (fn, ms) => {
    let timer;
    return (...args) => { clearTimeout(timer); timer = setTimeout(() => fn(...args), ms); };
  };
  const wire = (id, key) => {
    const input = document.getElementById(id);
    const commit = debounce(() => { S[key] = input.value.trim(); onFilterChange(); }, 140);
    input.addEventListener('input', commit);
  };
  wire('q', 'q');
  wire('provision', 'provision');
  wire('caseq', 'caseq');
  year.addEventListener('change', () => { S.year = year.value; onFilterChange(); });

  document.getElementById('reset').addEventListener('click', () => {
    S.q = S.provision = S.caseq = S.year = '';
    for (const key of SETS) S[key].clear();
    syncControls();
    onFilterChange();
  });
}

/** Push state into the controls — used on load and on back/forward. */
function syncControls() {
  if (!DATA.manual) return;
  document.getElementById('q').value = S.q;
  document.getElementById('provision').value = S.provision;
  document.getElementById('caseq').value = S.caseq;
  document.getElementById('year').value = S.year;
  for (const input of document.querySelectorAll('input[type=checkbox][data-key]')) {
    input.checked = S[input.dataset.key].has(input.value);
  }
  // Open any group that arrived from the URL already carrying a choice.
  const GROUP = {
    corpus: 'corpus', parts: 'parts', kinds: 'kinds', headingSources: 'headingSources',
    instruments: 'legislation', extraction: 'legislation', certainty: 'legislation',
    provision: 'legislation', caseq: 'cases', flags: 'flags', pageflags: 'page', year: 'page',
  };
  for (const [key, group] of Object.entries(GROUP)) {
    const chosen = S[key] instanceof Set ? S[key].size : Boolean(S[key]);
    if (!chosen) continue;
    const node = document.querySelector(`[data-chosen="${group}"]`);
    if (node) node.closest('details').open = true;
  }
}

function onFilterChange() {
  syncHash();
  render();
}

function renderChosen() {
  const counts = {
    corpus: S.corpus.size,
    parts: S.parts.size, kinds: S.kinds.size, headingSources: S.headingSources.size,
    legislation: S.instruments.size + S.extraction.size + S.certainty.size + (S.provision ? 1 : 0),
    cases: S.caseq ? 1 : 0,
    flags: S.flags.size,
    page: S.pageflags.size + (S.year ? 1 : 0),
  };
  for (const [key, count] of Object.entries(counts)) {
    const node = document.querySelector(`[data-chosen="${key}"]`);
    if (node) node.textContent = count ? `${count} selected` : '';
  }
  document.getElementById('reset').hidden = !filtersActive();

  const line = document.getElementById('match-line');
  if (!DATA.ready) { line.textContent = 'Loading chunks…'; return; }
  const total = DATA.chunks.chunks.length;
  const lawTotal = DATA.lawReady ? DATA.law.provisions.length : 0;
  const tail = lawTotal
    ? h('span', {}, ' · ',
      h('strong', { text: num(filtersActive() ? RESULTS.lawList.length : lawTotal) }),
      filtersActive() ? ` of ${num(lawTotal)} provisions` : ' provisions')
    : null;
  line.replaceChildren(
    filtersActive()
      ? h('span', {}, h('strong', { text: num(RESULTS.list.length) }), ` of ${num(total)} chunks match`, tail)
      : h('span', {}, h('strong', { text: num(total) }), ' chunks, no filter applied', tail));
}

/* ------------------------------------------------------------------- chrome */

function renderCorpus() {
  const corpus = DATA.manual.corpus || {};
  const stat = (label, value, sub) =>
    h('div', {}, h('dt', { text: label }), h('dd', {}, num(value), sub ? h('small', { text: sub }) : null));
  const law = DATA.law ? DATA.law.corpus || {} : null;
  document.getElementById('corpus').replaceChildren(
    stat('Parts', corpus.parts !== undefined ? corpus.parts : DATA.manual.parts.length),
    stat('Pages', corpus.pages !== undefined ? corpus.pages : DATA.manual.pages.length),
    stat('Chunks', corpus.chunks),
    law ? stat('Provisions', law.provisions, `${num(law.units)} units`) : null,
    h('div', {}, h('dt', { text: 'Crawled' }),
      h('dd', {}, (DATA.manual.crawled_at || '').slice(0, 10) || '—',
        h('small', { text: DATA.manual.extractor_version || '' }))));

  const source = (DATA.manual.source || {}).manual_root;
  document.getElementById('foot-line').replaceChildren(
    'Built from the snapshot in this repository. Sources: ',
    source ? h('a', { href: source, rel: 'noreferrer', text: source }) : 'the IP Australia website',
    DATA.law
      ? h('span', {}, ' and the compiled instruments on ',
        h('a', { href: 'https://www.legislation.gov.au', rel: 'noreferrer', text: 'legislation.gov.au' }),
        ` (${DATA.law.extractor_version || 'legislation'}, captured ${(DATA.law.captured_at || '').slice(0, 10) || '—'})`)
      : null,
    '.');
}

function crumb(label, path) {
  return h('a', { href: hashFor(path), onclick: (e) => { e.preventDefault(); go(path); }, text: label });
}

function renderCrumbs(trail) {
  const node = document.getElementById('crumbs');
  const kids = [];
  trail.forEach((item, i) => {
    if (i) kids.push(h('span', { class: 'sep', text: '/' }));
    kids.push(item.path ? crumb(item.label, item.path) : h('span', { text: item.label }));
  });
  node.replaceChildren(...kids);
}

/* -------------------------------------------------------------------- views */

function render() {
  recompute();
  renderChosen();
  const view = document.getElementById('view');
  const [head, ...rest] = currentPath;
  try {
    if (head === 'part') view.replaceChildren(viewPart(rest[0]));
    else if (head === 'page') view.replaceChildren(viewPage(rest.join('/')));
    else if (head === 'chunk') view.replaceChildren(viewChunk(rest.join('/')));
    else if (head === 'law') view.replaceChildren(viewLaw(rest.join('/')));
    else if (head === 'prov') view.replaceChildren(viewProvision(rest.join('/')));
    else if (head === 'results') view.replaceChildren(viewResults());
    else view.replaceChildren(viewParts());
  } catch (err) {
    view.replaceChildren(h('div', { class: 'card empty' },
      h('strong', { text: 'That view could not be rendered.' }),
      h('p', { class: 'mono', text: String(err && err.message || err) })));
  }
}

function viewParts() {
  renderCrumbs([{ label: 'Snapshot' }]);
  const active = filtersActive();
  const wrap = document.createDocumentFragment();

  wrap.append(h('section', { class: 'card intro' },
    h('h2', { text: 'The Manual, cut into addressable passages' }),
    h('p', { text: 'Each Part below holds pages; each page holds chunks. A chunk is normally the prose under one heading, carrying its heading ancestry, the legislation and case law cited in it, and a hash of its own text. Open a page and you can read it either as the chunks it was cut into or as a continuous page reassembled from them — the two are the same words.' }),
    h('p', {}, 'The filters on the left work on what the extractor recorded, not on the words alone: which Act a passage cites, whether the Manual hyperlinked that citation or the pipeline matched it by pattern, whether a heading was marked up or inferred. That is what the deconstruction buys you.'),
    DATA.law
      ? h('p', {}, 'And the law itself is here — ',
        h('button', { class: 'link-btn', text: 'the Act and the Regulations', onclick: () => go(['law']) }),
        ', cut the same way. A passage citing section 41 and section 41 as the drafter set it are two records with one address between them, so the filters read both.')
      : null,
    active && DATA.ready
      ? h('p', {}, h('strong', { text: `${num(RESULTS.list.length)} chunks match the current filter` }),
        ' across ', plural(RESULTS.byPage.size, 'page'),
        DATA.lawReady ? `, alongside ${plural(RESULTS.lawList.length, 'provision')}` : '', ' — ',
        h('button', { class: 'link-btn', text: 'see them as a list', onclick: () => go(['results']) }), '.')
      : null));

  const cards = DATA.manual.parts.map((part) => {
    const hits = RESULTS.byPart.get(part.part_id) || 0;
    const dim = active && DATA.ready && hits === 0;
    return h('button', {
      class: 'part-card' + (dim ? ' dim' : ''),
      onclick: () => go(['part', part.part_id]),
    },
      h('div', { class: 'pid', text: part.part_id }),
      h('div', { class: 'ptitle', text: part.part_title }),
      h('div', { class: 'meta' },
        plural(part.page_count, 'page'), ' · ', plural(part.chunk_count, 'chunk'),
        active && DATA.ready ? h('span', { class: 'hit', text: ` · ${num(hits)} matching` }) : null));
  });
  wrap.append(h('div', { class: 'grid' }, cards));
  if (DATA.law) wrap.append(h('div', { style: 'margin-top:1.6rem' }, instrumentCards()));
  return wrap;
}

/** The instruments, as cards, with the join stated under them. */
function instrumentCards() {
  const active = filtersActive() && DATA.lawReady;
  const join = DATA.law.join || {};
  return h('div', {},
    h('section', { class: 'card intro' },
      h('h2', { text: 'The law the Manual is about' }),
      h('p', { text: 'The Trade Marks Act 1995 and the Trade Marks Regulations 1995, read from the compiled Word documents the Federal Register of Legislation publishes, and cut at the boundaries the drafter set: a provision, then the numbered units inside it. No prose here is the Manual’s and none of it is this repository’s.' }),
      h('p', {},
        h('strong', { text: `${num(join.resolved)} of the Manual’s ${num(join.edges)} in-scope provision references` }),
        ` land on a provision held here, across ${plural(join.provisions, 'provision')} and ${plural(join.chunks, 'chunk')}. `,
        'That join needs no lookup table: a chunk citing section 41 carries the id ', h('code', { text: 'TMA1995/s41' }),
        ', and that is the ref of the record. The ', num(join.unresolved_edges),
        ' that do not land are a finding rather than a fault — mostly citation defects in the Manual and references to numbering the current compilation no longer has.'),
      (join.unresolved || []).length
        ? h('details', { class: 'detail' },
          h('summary', { text: `The ${plural(join.unresolved.length, 'address', 'addresses')} that do not land, most cited first` }),
          h('p', { class: 'hint', text: 'Each is an id a Manual chunk carries for one of the two instruments here, which no provision and no unit of the current compilation answers to. They are left as they were written: the Manual said it, and correcting a citation is not this snapshot’s job.' }),
          h('ul', { class: 'cite-list' }, join.unresolved.map((row) => h('li', {},
            h('span', { class: 'mono', text: row.value }),
            citingButton(row.value, `${plural(row.count, 'chunk')} →`)))))
        : null),
    h('div', { class: 'grid' }, DATA.law.instruments.map((instrument) => {
      const hits = RESULTS.byInstrument.get(instrument.code) || 0;
      return h('button', {
        class: 'part-card' + (active && !hits ? ' dim' : ''),
        onclick: () => go(['law', instrument.code]),
      },
        h('div', { class: 'pid', text: instrument.code }),
        h('div', { class: 'ptitle', text: instrument.name }),
        h('div', { class: 'meta' },
          plural(instrument.provision_count, 'provision'), ' · ', plural(instrument.unit_count, 'unit'),
          h('br'),
          `Compilation ${instrument.compilation_number}, in force ${instrument.compilation_start || '—'}`,
          instrument.has_unincorporated_amendments
            ? h('span', { class: 'badge warn', text: 'unincorporated amendments' })
            : null,
          active ? h('span', { class: 'hit', text: ` · ${num(hits)} matching` }) : null));
    })));
}

function viewPart(partId) {
  const part = DATA.manual.parts.find((p) => p.part_id === partId);
  if (!part) return notFound(`No Part called ${partId}.`);
  renderCrumbs([{ label: 'Snapshot', path: [] }, { label: part.part_id }]);

  const pages = DATA.manual.pages.filter((p) => p.part_id === partId);
  const active = filtersActive() && DATA.ready;

  const rows = pages.map((page) => {
    const hits = RESULTS.byPage.get(page.page_ref) || 0;
    return h('button', {
      class: 'row',
      onclick: () => go(['page', page.page_ref]),
      style: active && !hits ? 'opacity:.45' : null,
    },
      h('span', { class: 'ref', text: page.page_ref.split('/').slice(1).join('.') }),
      h('span', { class: 'title' },
        page.nav_title,
        h('small', { text: page.h1 && page.h1 !== page.nav_title ? page.h1 : (page.amendment_note || '') })),
      h('span', { class: 'tail' },
        pageBadges(page),
        page.last_amended || '—',
        h('span', { text: active ? `${num(hits)}/${num(page.chunk_count)}` : num(page.chunk_count) })));
  });

  return h('div', {},
    h('section', { class: 'card page-head' },
      h('h2', { text: part.part_title }),
      h('p', { class: 'sub', text: `${part.part_id} · ${plural(part.page_count, 'page')} · ${plural(part.chunk_count, 'chunk')}` }),
      active ? h('p', { class: 'hint', text: `${num(RESULTS.byPart.get(partId) || 0)} chunks in this Part match the current filter. Pages with no match are dimmed.` }) : null),
    h('div', { class: 'rows' }, rows.length ? rows : h('div', { class: 'empty', text: 'This Part has no page files in the snapshot.' })));
}

function pageBadges(page) {
  const badges = [];
  if (page.retired) badges.push(h('span', { class: 'badge warn', text: 'retired' }));
  if (page.archived) badges.push(h('span', { class: 'badge warn', text: 'archived' }));
  if ((page.images || []).length) badges.push(h('span', { class: 'badge', text: `${page.images.length} image${page.images.length > 1 ? 's' : ''}` }));
  return h('span', { class: 'badges' }, badges);
}

function viewPage(pageRef) {
  const page = INDEX.pageByRef.get(pageRef);
  if (!page) return notFound(`No page record for ${pageRef}.`);
  renderCrumbs([
    { label: 'Snapshot', path: [] },
    { label: page.part_id, path: ['part', page.part_id] },
    { label: page.page_ref.split('/').slice(1).join('.') },
  ]);

  const mode = sessionStorage.getItem('mode') || 'chunks';
  const container = h('div', {});
  const body = h('div', {});

  const setMode = (next) => {
    sessionStorage.setItem('mode', next);
    for (const button of container.querySelectorAll('.mode')) {
      button.setAttribute('aria-pressed', String(button.dataset.mode === next));
    }
    renderPageBody(body, page, next);
  };

  const modeButton = (value, label) => h('button', {
    class: 'mode', 'data-mode': value, type: 'button',
    'aria-pressed': String(mode === value),
    onclick: () => setMode(value),
  }, label);

  container.append(
    h('section', { class: 'card page-head' },
      h('h2', { text: page.h1 || page.nav_title }),
      h('p', { class: 'sub' }, page.page_ref, ' ', pageBadges(page)),
      h('dl', { class: 'meta-grid' },
        meta('Nav title', page.nav_title),
        meta('Published', page.date_published || '—'),
        meta('Last amended', page.last_amended || '—'),
        meta('IP Australia’s amendment note', page.amendment_note || '—'),
        meta('Chunks cut', num(page.chunk_count)),
        h('div', {}, h('dt', { text: 'Source page' }),
          h('dd', {}, h('a', { href: page.url, rel: 'noreferrer', text: 'open on manuals.ipaustralia.gov.au' }))),
        h('div', {}, h('dt', { text: 'Stored record' }),
          h('dd', {}, h('a', { href: 'pages/' + page.file, rel: 'noreferrer', text: page.file }))),
        meta('Content hash', (page.content_hash || '').replace('sha256:', '').slice(0, 16) + '…')),
      h('div', { class: 'modes' },
        modeButton('chunks', 'Chunks'),
        modeButton('page', 'Reassembled page'),
        modeButton('record', 'Stored record'))),
    body);

  renderPageBody(body, page, mode);
  return container;
}

function meta(label, value) {
  return h('div', {}, h('dt', { text: label }), h('dd', { text: value }));
}

function renderPageBody(host, page, mode) {
  if (mode === 'record') {
    host.replaceChildren(h('div', { class: 'card', style: 'padding:1rem' }, h('p', { class: 'busy', text: 'Loading the page file…' })));
    loadPageFile(page).then((doc) => {
      host.replaceChildren(h('section', { class: 'card', style: 'padding:1.1rem 1.25rem' },
        h('p', { class: 'hint', text: 'The page file exactly as it sits in snapshot/pages/ — the record every view above is built from.' }),
        h('div', { class: 'scroll-x' },
          h('pre', { class: 'mono', style: 'font-size:.75rem;line-height:1.5', text: JSON.stringify(doc, null, 2) }))));
    }).catch(fileError(host));
    return;
  }

  if (mode === 'page') {
    host.replaceChildren(h('div', { class: 'card', style: 'padding:1rem' }, h('p', { class: 'busy', text: 'Loading the page file…' })));
    loadPageFile(page).then((doc) => host.replaceChildren(reassembled(page, doc))).catch(fileError(host));
    return;
  }

  const chunks = INDEX.chunksByPage.get(page.page_ref);
  if (!chunks) {
    host.replaceChildren(h('div', { class: 'card empty' },
      DATA.ready
        ? h('strong', { text: 'This page yielded no chunks.' })
        : h('strong', { text: 'Loading the chunk index…' }),
      DATA.ready ? h('p', { text: page.archived ? 'The page carries the Manual’s archived banner and has no prose left.' : 'Nine pages of the Manual are only an image; those record their images and no text.' }) : null));
    return;
  }
  const active = filtersActive() && DATA.ready;
  host.replaceChildren(h('div', { class: 'rows' }, chunks.map((chunk) => {
    const hit = active && RESULTS.refs.has(chunk.chunk_ref);
    return chunkCard(chunk, { dim: active && !hit, matched: hit });
  })));
}

function fileError(host) {
  return (err) => host.replaceChildren(h('div', { class: 'card empty' },
    h('strong', { text: 'That page file could not be loaded.' }),
    h('p', { class: 'mono', text: String(err && err.message || err) })));
}

/* -------------------------------------------------------- chunk presentation */

function kindBadges(chunk) {
  const badges = [];
  if ((chunk.kind || 'body') !== 'body') badges.push(h('span', { class: 'badge', text: chunk.kind }));
  if (chunk.heading_source === 'emphasis') badges.push(h('span', { class: 'badge warn', text: 'inferred heading' }));
  if (chunk.fragment) badges.push(h('span', { class: 'badge', text: `part ${chunk.fragment.index}/${chunk.fragment.count}` }));
  if (INDEX.tables[chunk.chunk_ref]) badges.push(h('span', { class: 'badge', text: `${INDEX.tables[chunk.chunk_ref]} table${INDEX.tables[chunk.chunk_ref] > 1 ? 's' : ''}` }));
  if ((chunk.provisions || []).length) badges.push(h('span', { class: 'badge accent', text: `${chunk.provisions.length} prov` }));
  if ((chunk.cases || []).length) badges.push(h('span', { class: 'badge accent', text: `${chunk.cases.length} case${chunk.cases.length > 1 ? 's' : ''}` }));
  return h('span', { class: 'badges' }, badges);
}

function chunkCard(chunk, opts) {
  const options = opts || {};
  const leaf = chunk.heading_path[chunk.heading_path.length - 1];
  const body = h('div', { class: 'chunk-body', hidden: true });
  let filled = false;

  const head = h('button', {
    class: 'chunk-head', type: 'button', 'aria-expanded': 'false',
    onclick: () => {
      const open = body.hidden;
      body.hidden = !open;
      head.setAttribute('aria-expanded', String(open));
      if (open && !filled) { body.replaceChildren(chunkPreview(chunk)); filled = true; }
    },
  },
    h('span', { class: 'ord', text: String(chunk.ordinal) }),
    h('span', { class: 'h' },
      h('strong', {}, marked(leaf, S.q)),
      h('span', { class: 'snippet' }, marked(chunk.text.slice(0, 170), S.q))),
    kindBadges(chunk));

  return h('div', {
    class: 'chunk' + (options.matched ? ' match' : ''),
    style: options.dim ? 'opacity:.45' : null,
  }, head, body);
}

/** Second tier of disclosure: the passage and its citations, from the index. */
function chunkPreview(chunk) {
  const frag = document.createDocumentFragment();
  if (chunk.heading_path.length > 1) {
    frag.append(h('p', { class: 'hint', text: chunk.heading_path.join('  ›  ') }));
  }
  frag.append(h('div', { class: 'prose' }, h('p', {}, linked(chunk.text, 0, chunk.links, S.q))));
  frag.append(citationBlock(chunk));
  frag.append(h('p', { style: 'margin-top:.8rem' },
    h('button', { class: 'link-btn', text: 'Open this chunk in full →', onclick: () => go(['chunk', chunk.chunk_ref]) })));
  return frag;
}

/** One provisions[] edge, and where it lands.
 *
 * The id is the ref of a provision in the legislation half of the snapshot, so
 * where that half is loaded the edge is a link into it rather than a string —
 * and where the id names something the snapshot does not hold, it says so
 * instead of quietly linking to the wrong section.
 */
function provisionLine(provision) {
  const [instrument] = provision.id.split('/');
  const href = AUSTLII[instrument];
  const held = INDEX.provisionByRef.has(provision.id) || Boolean(INDEX.unitOwner[provision.id]);
  const inCorpus = INDEX.instrumentByCode.has(instrument);
  return h('li', {},
    held
      ? provisionLink(provision.id)
      : href ? h('a', { class: 'mono', href, rel: 'noreferrer', text: provision.id }) : h('span', { class: 'mono', text: provision.id }),
    h('span', { class: 'badge', text: provision.extraction }),
    provision.certainty ? h('span', { class: 'badge' + (provision.certainty === 'ambiguous' ? ' warn' : ''), text: provision.certainty }) : null,
    !held && inCorpus
      ? h('span', { class: 'badge warn', title: 'The snapshot holds the latest compilation. An address that is a citation defect, or that was renumbered by a later amendment, has nothing here to land on.', text: 'no such provision' })
      : null,
    provision.mention ? h('span', { class: 'mention', text: `“${provision.mention}”` }) : null,
    held && href ? h('a', { class: 'src-link out mention', href, rel: 'noreferrer', text: 'AustLII' }) : null);
}

/** One internal_refs entry: the target, and how the pipeline came by it. */
function internalRefLine(reference) {
  return h('li', {},
    refLink(reference.ref),
    h('span', { class: 'badge', text: reference.extraction }),
    reference.certainty ? h('span', { class: 'badge' + (reference.certainty === 'ambiguous' ? ' warn' : ''), text: reference.certainty }) : null,
    reference.mention ? h('span', { class: 'mention', text: `“${reference.mention}”` }) : null);
}

function citationBlock(chunk) {
  const frag = document.createDocumentFragment();
  const provisions = chunk.provisions || [];
  const cases = chunk.cases || [];
  const refs = chunk.internal_refs || [];
  const citedBy = INDEX.citedBy[chunk.chunk_ref] || [];

  if (provisions.length) {
    frag.append(h('details', { class: 'detail' },
      h('summary', { text: `Legislation cited (${provisions.length})` }),
      h('ul', { class: 'cite-list' }, provisions.map(provisionLine))));
  }
  if (cases.length) {
    frag.append(h('details', { class: 'detail' },
      h('summary', { text: `Case law cited (${cases.length})` }),
      h('ul', { class: 'cite-list' }, cases.map((c) =>
        h('li', {}, h('span', { class: 'mono', text: c.citation }), h('span', { class: 'mention', text: c.id }))))));
  }
  if (refs.length) {
    frag.append(h('details', { class: 'detail' },
      h('summary', { text: `Points elsewhere in the Manual (${refs.length})` }),
      h('ul', { class: 'cite-list' }, refs.map(internalRefLine))));
  }
  if (citedBy.length) {
    frag.append(h('details', { class: 'detail' },
      h('summary', { text: `Pointed to from elsewhere (${citedBy.length})` }),
      h('p', { class: 'hint', text: 'Derived by this viewer from every chunk’s internal_refs — the snapshot stores the forward direction only.' }),
      h('ul', { class: 'cite-list' }, citedBy.map((ref) => h('li', {}, refLink(ref))))));
  }
  return frag;
}

/** A chunk_ref or page_ref rendered as a link into whichever view holds it. */
function refLink(ref) {
  const chunk = INDEX.chunkByRef.get(ref);
  if (chunk) {
    return h('button', {
      class: 'ref-link', text: ref, title: chunk.heading_path.join(' › '),
      onclick: () => go(['chunk', ref]),
    });
  }
  if (INDEX.pageByRef.has(ref)) {
    const page = INDEX.pageByRef.get(ref);
    return h('button', { class: 'ref-link', text: ref, title: page.nav_title, onclick: () => go(['page', ref]) });
  }
  return h('span', { class: 'mono', text: ref });
}

/* ------------------------------------------------------- deepest disclosure */

function viewChunk(chunkRef) {
  const chunk = INDEX.chunkByRef.get(chunkRef);
  if (!chunk) {
    return notFound(DATA.ready ? `No chunk with the ref ${chunkRef}.` : 'Still loading the chunk index — try again in a moment.');
  }
  const page = INDEX.pageByRef.get(chunk.page_ref);
  renderCrumbs([
    { label: 'Snapshot', path: [] },
    { label: page ? page.part_id : '?', path: ['part', page ? page.part_id : ''] },
    { label: chunk.page_ref.split('/').slice(1).join('.'), path: ['page', chunk.page_ref] },
    { label: `chunk ${chunk.ordinal}` },
  ]);

  const siblings = INDEX.chunksByPage.get(chunk.page_ref) || [];
  const at = siblings.indexOf(chunk);

  // The index carries `text` and not `blocks`, so the flat string paints at
  // once and the structure replaces it when the page file lands. If that fetch
  // fails the reader is left with the passage rather than with a spinner.
  const prose = h('div', { class: 'prose' }, h('p', {}, linked(chunk.text, 0, chunk.links, S.q)));
  const verbatim = h('div', {});

  const container = h('div', {},
    h('section', { class: 'card page-head' },
      h('p', { class: 'hint', text: chunk.heading_path.slice(0, -1).join('  ›  ') }),
      h('h2', { text: chunk.heading_path[chunk.heading_path.length - 1] }),
      h('p', { class: 'sub' }, chunk.chunk_ref, ' ', kindBadges(chunk)),
      h('dl', { class: 'meta-grid' },
        meta('Position', `${chunk.ordinal} of ${siblings.length || page && page.chunk_count || '?'} on the page`),
        meta('Heading source', chunk.heading_source || 'none (lead-in prose)'),
        meta('Kind', chunk.kind || 'body'),
        meta('Words', num(chunk.text.split(/\s+/).filter(Boolean).length)),
        meta('Links', chunk.links && chunk.links.length ? num(chunk.links.length) : 'none'),
        meta('Content hash', (chunk.content_hash || '').replace('sha256:', '').slice(0, 16) + '…'),
        h('div', {}, h('dt', { text: 'On the page' }),
          h('dd', {}, h('a', {
            href: hashFor(['page', chunk.page_ref]), text: page ? page.nav_title : chunk.page_ref,
            onclick: (e) => { e.preventDefault(); go(['page', chunk.page_ref]); },
          })))),
      h('div', { class: 'modes' },
        at > 0 ? h('button', { class: 'mode', type: 'button', text: '← previous chunk', onclick: () => go(['chunk', siblings[at - 1].chunk_ref]) }) : null,
        at >= 0 && at < siblings.length - 1 ? h('button', { class: 'mode', type: 'button', text: 'next chunk →', onclick: () => go(['chunk', siblings[at + 1].chunk_ref]) }) : null)),
    h('section', { class: 'card', style: 'padding:1.1rem 1.25rem' },
      prose,
      verbatim,
      citationBlock(chunk)));

  if (page) {
    loadPageFile(page).then((doc) => {
      const full = doc.chunks.find((c) => c.chunk_ref === chunk.chunk_ref);
      if (!full) {
        verbatim.replaceChildren(h('p', { class: 'hint', text: 'This chunk is not in the page file, so it is shown as its flat string — the bundle is out of step with the snapshot.' }));
        return;
      }
      prose.replaceChildren(renderBlocks(full));
      verbatim.replaceChildren(h('details', { class: 'detail' },
        h('summary', { text: 'The verbatim string this was set from' }),
        h('p', { class: 'hint', text: 'Above is the chunk as the Manual set it: the paragraphs, lists and tables recorded in its blocks. The snapshot asserts the chunk as one string, and content_hash is taken over that string alone; joining the blocks with single spaces reproduces it exactly, which is what stops the two becoming differently worded copies.' }),
        h('div', { class: 'prose' }, h('p', {}, marked(full.text, S.q)))));
    }).catch((err) => {
      verbatim.replaceChildren(h('p', { class: 'hint' },
        'Shown as the chunk’s flat string: the page file holding its paragraph and list structure could not be loaded — ',
        h('span', { class: 'mono', text: String(err && err.message || err) })));
    });
  }
  return container;
}

/** Blocks → paragraphs, nested lists, tables and image notes. */
function renderBlocks(chunk) {
  const frag = document.createDocumentFragment();
  const blocks = chunk.blocks || [];
  const links = chunk.links || [];
  if (!blocks.length) return h('p', {}, linked(chunk.text, 0, links, S.q));

  const tables = chunk.tables || [];
  const starts = blockStarts(chunk);
  let tableAt = 0;
  let stack = [];   // [{depth, list}]
  let index = -1;

  const closeTo = (depth) => { while (stack.length && stack[stack.length - 1].depth > depth) stack.pop(); };
  const words = (block, i) => linked(block.text, starts[i], links, S.q);

  for (const block of blocks) {
    index += 1;
    if (block.kind === 'list_item') {
      const depth = block.depth || 1;
      closeTo(depth);
      if (!stack.length || stack[stack.length - 1].depth < depth) {
        const list = h('ul', {});
        if (stack.length) {
          const parent = stack[stack.length - 1].list;
          const host = parent.lastElementChild || parent.appendChild(h('li', {}));
          host.append(list);
        } else {
          frag.append(list);
        }
        stack.push({ depth, list });
      }
      stack[stack.length - 1].list.append(h('li', {}, words(block, index)));
      continue;
    }

    stack = [];
    if (block.kind === 'heading') {
      frag.append(h('h5', {}, words(block, index)));
    } else if (block.kind === 'table') {
      const grid = tables[tableAt++];
      frag.append(grid ? renderTable(grid, starts[index], links) : h('p', {}, words(block, index)));
    } else if (block.kind === 'image') {
      frag.append(h('p', { class: 'img-note' },
        'Image in the source at this point',
        block.alt ? ` — “${block.alt}”` : ' — the Manual gives it no alt text',
        '. The bytes are not in the snapshot: ',
        h('a', { href: SOURCE_ROOT + block.src, rel: 'noreferrer', text: block.src })));
    } else {
      frag.append(h('p', {}, words(block, index)));
    }
  }
  return frag;
}

/** The grid, with any links in its cells put back.
 *
 * A cell's place in `chunk.text` follows from the same join the blocks do: the
 * table block's text is its non-empty cells joined with single spaces, in
 * document order. `offset` is where the whole table starts; a cell holding no
 * words contributes neither text nor separator.
 */
function renderTable(grid, offset, links) {
  let at = offset === undefined || offset === null ? null : offset;
  const rows = (grid.cells || []).map((row, r) => h('tr', {}, row.map((cell) => {
    const tag = grid.header_row === r ? 'th' : 'td';
    const text = cell.text || '';
    const start = at;
    if (at !== null && text) at += text.length + 1;
    return h(tag, {
      colspan: cell.colspan || null,
      rowspan: cell.rowspan || null,
      scope: tag === 'th' ? 'col' : null,
    }, start === null ? marked(text, S.q) : linked(text, start, links, S.q));
  })));
  return h('div', { class: 'scroll-x' },
    h('table', { class: 'tm-table' },
      h('caption', { style: 'caption-side:bottom;text-align:left;font-size:.74rem;color:var(--ink-3);padding-top:.3rem',
        text: `${grid.rows} × ${grid.columns}${grid.header_row === null || grid.header_row === undefined ? ' · the markup declares no header row, so none is assumed' : ''}` }),
      h('tbody', {}, rows)));
}

/* ---------------------------------------------------------- reassembled page */

function reassembled(page, doc) {
  const chunks = [...doc.chunks].sort((a, b) => a.ordinal - b.ordinal);
  const body = h('div', { class: 'prose recon' });
  let previous = [];
  let blockCount = 0;
  let tableCount = 0;
  let linkCount = 0;

  for (const chunk of chunks) {
    blockCount += (chunk.blocks || []).length;
    tableCount += (chunk.tables || []).length;
    linkCount += (chunk.links || []).length;

    // The mark opens the chunk, so it precedes the headings: a heading in
    // heading_path is the new chunk's own, and putting the rule after it read
    // as though the heading closed the chunk above.
    body.append(h('div', { class: 'section-mark' },
      h('span', { text: `chunk ${chunk.ordinal}` }),
      refLink(chunk.chunk_ref),
      chunk.heading_source ? h('span', { class: 'badge', text: chunk.heading_source }) : h('span', { class: 'badge', text: 'no heading' }),
      chunk.fragment ? h('span', { class: 'badge', text: `part ${chunk.fragment.index}/${chunk.fragment.count}` }) : null));

    const path = chunk.heading_path;
    for (let level = 1; level < path.length; level++) {
      if (previous[level] === path[level]) continue;
      const tag = level === 1 ? 'h3' : level === 2 ? 'h4' : 'h5';
      body.append(h(tag, { text: path[level] }));
    }
    previous = path;

    body.append(renderBlocks(chunk));
  }

  return h('section', { class: 'card', style: 'padding:1.2rem 1.4rem' },
    h('p', { class: 'hint' },
      `Reassembled from ${plural(chunks.length, 'chunk')}, ${plural(blockCount, 'block')}, ${plural(tableCount, 'table')} and ${plural(linkCount, 'link')} — in ordinal order, with headings taken from each chunk's own ancestry. Nothing is added: each dashed rule opens a chunk and everything below it down to the next rule — heading included — is that chunk, and every one of them is a passage you can address, filter and cite on its own. The hyperlinks are the Manual's, drawn at the offsets each chunk's links record; one naming a page in this snapshot opens it here rather than on the live site.`),
    chunks.length ? body : h('p', { class: 'busy', text: 'This page has no chunks to reassemble.' }),
    h('p', { class: 'hint', style: 'margin-top:1.2rem' },
      'Compare with ', h('a', { href: page.url, rel: 'noreferrer', text: 'the live page' }), '.'));
}

/* -------------------------------------------------------------- legislation */

/** The address a reader would write, minus the instrument that is already known. */
function provisionLabel(provision) {
  return provision.ref.split('/').slice(1).join('/');
}

/** What to call it in a list. Front matter has no number and no title of its
 *  own — the snapshot says so by leaving both null, and this names it rather
 *  than showing the ref twice. */
function provisionTitle(provision) {
  if (provision.title) return provision.title;
  const leaf = provision.heading_path[provision.heading_path.length - 1];
  if (leaf && leaf !== provision.ref) return leaf;
  return provision.kind === 'front-matter' ? 'Front matter' : provision.ref;
}

/** As a page heading: the provision's own line in the compilation, number and
 *  all, because that is how it is printed and how it is cited. */
function provisionHeading(provision) {
  const leaf = provision.heading_path[provision.heading_path.length - 1];
  return leaf && leaf !== provision.ref ? leaf : provisionTitle(provision);
}

/** A provision ref as a link into this viewer, wherever it can be resolved.
 *
 * An id naming a unit — `TMA1995/s41(3)(a)` — opens the provision holding it,
 * because that is where the words are; the mapping comes from the bundle
 * rather than from chopping the string, which cannot be done safely.
 */
function provisionLink(id, label) {
  const target = INDEX.provisionByRef.has(id) ? id : INDEX.unitOwner[id];
  if (target) {
    const provision = INDEX.provisionByRef.get(target);
    return h('button', {
      class: 'ref-link', text: label || id,
      title: provision ? provision.heading_path.join(' › ') : target,
      onclick: () => go(['prov', target]),
    });
  }
  const href = AUSTLII[id.split('/')[0]];
  return href
    ? h('a', { class: 'mono', href, rel: 'noreferrer', text: label || id })
    : h('span', { class: 'mono', text: label || id });
}

/** Filter the whole snapshot to whatever cites this address, and show the list. */
function citingButton(id, label) {
  return h('button', {
    class: 'link-btn', text: label,
    onclick: () => {
      S.provision = id;
      const input = document.getElementById('provision');
      if (input) input.value = id;
      syncControls();
      go(['results']);
    },
  });
}

function lawBadges(provision) {
  const badges = [h('span', { class: 'badge', text: provision.kind })];
  const units = INDEX.lawUnits[provision.ref] || 0;
  if (units) badges.push(h('span', { class: 'badge', text: `${num(units)} unit${units > 1 ? 's' : ''}` }));
  const tables = INDEX.lawTables[provision.ref];
  if (tables) badges.push(h('span', { class: 'badge', text: `${tables} table${tables > 1 ? 's' : ''}` }));
  const manual = (INDEX.manualCites[provision.ref] || []).length;
  if (manual) badges.push(h('span', { class: 'badge accent', text: `${num(manual)} in the Manual` }));
  return h('span', { class: 'badges' }, badges);
}

function provisionRow(provision) {
  const active = filtersActive() && DATA.lawReady;
  const hit = RESULTS.lawRefs.has(provision.ref);
  return h('button', {
    class: 'row',
    onclick: () => go(['prov', provision.ref]),
    style: active && !hit ? 'opacity:.45' : null,
  },
    h('span', { class: 'ref', text: provisionLabel(provision) }),
    h('span', { class: 'title' },
      marked(provisionTitle(provision), S.q),
      h('small', {}, marked(provision.text.slice(0, 120), S.q))),
    h('span', { class: 'tail' }, lawBadges(provision)));
}

/** `#/law`, `#/law/TMA1995` and `#/law/TMA1995/pt4` — one entry point, three depths. */
function viewLaw(ref) {
  if (!DATA.law) {
    renderCrumbs([{ label: 'Snapshot', path: [] }, { label: 'Legislation' }]);
    return notFound(DATA.manual
      ? 'This bundle holds the Manual only — it was built from a snapshot with no legislation/ directory.'
      : 'Still loading.');
  }
  if (!ref) {
    renderCrumbs([{ label: 'Snapshot', path: [] }, { label: 'Legislation' }]);
    return instrumentCards();
  }
  if (INDEX.instrumentByCode.has(ref)) return viewInstrument(INDEX.instrumentByCode.get(ref));
  if (INDEX.containerByRef.has(ref)) return viewContainer(INDEX.containerByRef.get(ref));
  lawCrumbs([{ label: ref }]);
  return notFound(`Nothing in the legislation snapshot is addressed ${ref}.`);
}

function lawCrumbs(trail) {
  renderCrumbs([{ label: 'Snapshot', path: [] }, { label: 'Legislation', path: ['law'] }, ...trail]);
}

/** The ancestry of a container or provision, as crumbs. */
function containerTrail(refs) {
  return refs.map((containerRef) => {
    const container = INDEX.containerByRef.get(containerRef);
    return { label: container ? containerLabel(container) : containerRef, path: ['law', containerRef] };
  });
}

function viewInstrument(instrument) {
  lawCrumbs([{ label: instrument.code }]);
  const mode = sessionStorage.getItem('lawmode') || 'contents';
  const container = h('div', {});
  const body = h('div', {});

  const setMode = (next) => {
    sessionStorage.setItem('lawmode', next);
    for (const button of container.querySelectorAll('.mode')) {
      button.setAttribute('aria-pressed', String(button.dataset.mode === next));
    }
    renderInstrumentBody(body, instrument, next);
  };
  const modeButton = (value, label) => h('button', {
    class: 'mode', 'data-mode': value, type: 'button',
    'aria-pressed': String(mode === value),
    onclick: () => setMode(value),
  }, label);

  container.append(
    h('section', { class: 'card page-head' },
      h('h2', { text: instrument.name }),
      h('p', { class: 'sub' }, instrument.code, ' ',
        h('span', { class: 'badges' },
          h('span', { class: 'badge', text: instrument.status || 'status unknown' }),
          h('span', { class: 'badge', text: `compilation ${instrument.compilation_number}` }),
          instrument.has_unincorporated_amendments
            ? h('span', { class: 'badge warn', text: 'unincorporated amendments' })
            : null)),
      h('p', { class: 'hint', text: instrument.long_title || '' }),
      h('dl', { class: 'meta-grid' },
        meta('Number and year', instrument.number_and_year || '—'),
        meta('Made under', instrument.made_under || '—'),
        meta('Compilation', `No. ${instrument.compilation_number}, in force ${instrument.compilation_start || '—'}`),
        meta('Register id', instrument.register_id || '—'),
        meta('Title id', instrument.title_id || '—'),
        meta('Registered', (instrument.registered_at || '').slice(0, 10) || '—'),
        meta('Provisions', num(instrument.provision_count)),
        meta('Units', num(instrument.unit_count)),
        h('div', {}, h('dt', { text: 'On the Register' }),
          h('dd', {}, h('a', {
            href: `https://www.legislation.gov.au/${instrument.title_id}/latest/text`,
            rel: 'noreferrer', text: 'legislation.gov.au',
          }))),
        h('div', {}, h('dt', { text: 'On AustLII' }),
          h('dd', {}, AUSTLII[instrument.code]
            ? h('a', { href: AUSTLII[instrument.code], rel: 'noreferrer', text: 'austlii.edu.au' })
            : '—'))),
      instrument.has_unincorporated_amendments
        ? h('p', { class: 'hint', text: 'The Register reports amendments that have commenced and are not yet incorporated into any compilation. The text below is the latest compilation, and it is legally out of date in whatever those amendments touched.' })
        : null,
      h('div', { class: 'modes' },
        modeButton('contents', 'Contents'),
        modeButton('history', 'Amendment history'),
        modeButton('record', 'Stored record'))),
    body);

  renderInstrumentBody(body, instrument, mode);
  return container;
}

function renderInstrumentBody(host, instrument, mode) {
  if (mode === 'record') {
    host.replaceChildren(h('div', { class: 'card', style: 'padding:1rem' }, h('p', { class: 'busy', text: 'Loading the instrument file…' })));
    Promise.all([
      loadInstrumentFile(instrument.code, 'instrument.json'),
      loadInstrumentFile(instrument.code, 'contents.json'),
    ]).then(([record, contents]) => {
      host.replaceChildren(h('section', { class: 'card', style: 'padding:1.1rem 1.25rem' },
        h('p', { class: 'hint', text: 'instrument.json and contents.json exactly as they sit in snapshot/legislation/ — the compilation identity, and the document order every view above is built from.' }),
        h('div', { class: 'scroll-x' },
          h('pre', { class: 'mono', style: 'font-size:.75rem;line-height:1.5', text: JSON.stringify({ instrument: record, contents }, null, 2) }))));
    }).catch(fileError(host));
    return;
  }

  if (mode === 'history') {
    host.replaceChildren(h('div', { class: 'card', style: 'padding:1rem' }, h('p', { class: 'busy', text: 'Loading the endnotes…' })));
    if (!instrument.endnotes) {
      host.replaceChildren(h('div', { class: 'card empty' },
        h('strong', { text: 'This instrument has no endnotes file in the snapshot.' })));
      return;
    }
    loadInstrumentFile(instrument.code, 'endnotes.json')
      .then((doc) => host.replaceChildren(endnotesView(instrument, doc)))
      .catch(fileError(host));
    return;
  }

  const containers = INDEX.containerChildren.get(instrument.code) || [];
  const loose = INDEX.provisionsByContainer.get(instrument.code) || [];
  const active = filtersActive() && DATA.lawReady;

  host.replaceChildren(
    active
      ? h('p', { class: 'hint', style: 'margin:0 0 .7rem', text: `${num(RESULTS.byInstrument.get(instrument.code) || 0)} provisions of this instrument match the current filter. Anything with no match is dimmed.` })
      : h('p', { class: 'hint', style: 'margin:0 0 .7rem', text: 'The Parts, Divisions and Schedules the compilation declares, in its own order. A provision sits under the innermost one that holds it.' }),
    loose.length ? h('div', { class: 'rows', style: 'margin-bottom:1rem' }, loose.map(provisionRow)) : null,
    h('div', { class: 'grid' }, containers.map((container) => {
      const held = provisionsUnder(container.ref);
      const hits = RESULTS.byContainer.get(container.ref) || 0;
      const children = INDEX.containerChildren.get(container.ref) || [];
      return h('button', {
        class: 'part-card' + (active && !hits ? ' dim' : ''),
        onclick: () => go(['law', container.ref]),
      },
        h('div', { class: 'pid', text: containerLabel(container) }),
        h('div', { class: 'ptitle', text: container.title }),
        h('div', { class: 'meta' },
          plural(held.length, 'provision'),
          children.length ? ` · ${plural(children.length, children[0].kind.toLowerCase())}` : '',
          active ? h('span', { class: 'hit', text: ` · ${num(hits)} matching` }) : null));
    })));
}

function endnotesView(instrument, doc) {
  const endnotes = (doc.endnotes || []).map((endnote) => {
    const tables = (endnote.tables || []).map((table) => h('div', { class: 'scroll-x' },
      h('table', { class: 'tm-table' },
        h('tbody', {}, (table.rows || []).map((row, r) => h('tr', {}, row.map((cell) =>
          h(r === 0 ? 'th' : 'td', { scope: r === 0 ? 'col' : null }, marked(String(cell), S.q)))))))));
    return h('details', { class: 'detail', open: endnote.number >= 3 },
      h('summary', { text: `Endnote ${endnote.number} — ${endnote.title || ''}` }),
      h('div', { class: 'prose' }, (endnote.paragraphs || []).map((paragraph) => h('p', {}, marked(paragraph, S.q)))),
      tables);
  });

  return h('section', { class: 'card', style: 'padding:1.1rem 1.25rem' },
    h('p', { class: 'hint', text: 'The compilation’s own endnotes, verbatim. Endnote 3 is every amending law with its commencement; endnote 4 is one row per provision touched, reaching back to 1995. The provision labels in endnote 4 are deliberately not resolved to refs — the column also holds “Div 2 of Part 3” and “Reader’s Guide”, and a resolver that handled the easy rows and mangled the rest is exactly the silently-wrong record this snapshot exists to avoid.' }),
    endnotes.length ? endnotes : h('p', { class: 'busy', text: 'No endnotes were captured for this instrument.' }),
    h('p', { class: 'hint', style: 'margin-top:1rem' },
      'The amendments the Register lists against this compilation are on ',
      h('button', { class: 'link-btn', text: 'the instrument record', onclick: () => { sessionStorage.setItem('lawmode', 'record'); render(); } }), '.'));
}

function viewContainer(container) {
  const ancestry = [];
  for (let node = container; node; node = node.parent_ref ? INDEX.containerByRef.get(node.parent_ref) : null) {
    ancestry.unshift(node);
  }
  const code = container.ref.split('/')[0];
  const instrument = INDEX.instrumentByCode.get(code);
  lawCrumbs([
    { label: code, path: ['law', code] },
    ...containerTrail(ancestry.slice(0, -1).map((c) => c.ref)),
    { label: containerLabel(container) },
  ]);

  const active = filtersActive() && DATA.lawReady;
  const direct = INDEX.provisionsByContainer.get(container.ref) || [];
  const children = INDEX.containerChildren.get(container.ref) || [];
  const held = provisionsUnder(container.ref);

  return h('div', {},
    h('section', { class: 'card page-head' },
      h('p', { class: 'hint', text: instrument ? instrument.name : code }),
      h('h2', { text: `${containerLabel(container)}—${container.title}` }),
      h('p', { class: 'sub' }, container.ref, ' ',
        h('span', { class: 'badges' }, h('span', { class: 'badge', text: container.kind }))),
      active
        ? h('p', { class: 'hint', text: `${num(RESULTS.byContainer.get(container.ref) || 0)} of the ${num(held.length)} provisions here match the current filter.` })
        : null),
    direct.length ? h('div', { class: 'rows' }, direct.map(provisionRow)) : null,
    ...children.map((child) => h('div', { style: 'margin-top:1.1rem' },
      h('p', { class: 'sub-label', style: 'margin-bottom:.4rem' },
        h('button', {
          class: 'link-btn', text: `${containerLabel(child)}—${child.title}`,
          onclick: () => go(['law', child.ref]),
        })),
      h('div', { class: 'rows' }, provisionsUnder(child.ref).map(provisionRow)))),
    !direct.length && !children.length
      ? h('div', { class: 'card empty' }, h('strong', { text: 'This container holds no provisions of its own.' }))
      : null);
}

/* ------------------------------------------------------ a provision in full */

function viewProvision(ref) {
  if (!DATA.law) {
    renderCrumbs([{ label: 'Snapshot', path: [] }, { label: 'Legislation' }]);
    return notFound(DATA.manual
      ? 'This bundle holds the Manual only — it was built from a snapshot with no legislation/ directory.'
      : 'Still loading.');
  }
  const provision = INDEX.provisionByRef.get(ref);
  if (!provision) {
    const owner = INDEX.unitOwner[ref];
    if (owner) return viewProvision(owner);
    lawCrumbs([{ label: ref }]);
    return notFound(`No provision with the ref ${ref}. The snapshot holds the latest compilation, so an address that has since been renumbered, or one the Manual wrote with a defect in it, will not be here.`);
  }
  const code = provision.instrument;
  const instrument = INDEX.instrumentByCode.get(code);
  lawCrumbs([
    { label: code, path: ['law', code] },
    ...containerTrail(provision.containers || []),
    { label: provisionLabel(provision) },
  ]);

  const siblings = INDEX.provisionsByInstrument.get(code) || [];
  const at = siblings.indexOf(provision);
  const manual = INDEX.manualCites[provision.ref] || [];

  // Same bargain as a chunk: the index carries `text`, so the words paint at
  // once and the drafter's structure replaces them when the provision's own
  // file lands.
  const prose = h('div', { class: 'prose' }, h('p', {}, marked(provision.text, S.q)));
  const verbatim = h('div', {});

  const container = h('div', {},
    h('section', { class: 'card page-head' },
      h('p', { class: 'hint', text: provision.heading_path.slice(0, -1).join('  ›  ') }),
      h('h2', { text: provisionHeading(provision) }),
      h('p', { class: 'sub' }, provision.ref, ' ', lawBadges(provision)),
      h('dl', { class: 'meta-grid' },
        meta('Instrument', instrument ? instrument.name : code),
        meta('Kind', provision.kind),
        meta('Units', num(INDEX.lawUnits[provision.ref] || 0)),
        meta('Words', num(provision.text.split(/\s+/).filter(Boolean).length)),
        meta('Compilation', instrument ? `No. ${instrument.compilation_number}, in force ${instrument.compilation_start || '—'}` : '—'),
        meta('Content hash', (provision.content_hash || '').replace('sha256:', '').slice(0, 16) + '…'),
        h('div', {}, h('dt', { text: 'In' }),
          h('dd', {}, (provision.containers || []).length
            ? (provision.containers || []).map((containerRef, i) => {
              const node = INDEX.containerByRef.get(containerRef);
              return h('span', {}, i ? ' › ' : '', h('button', {
                class: 'ref-link', text: node ? containerLabel(node) : containerRef,
                onclick: () => go(['law', containerRef]),
              }));
            })
            : 'no container — it sits directly under the instrument')),
        h('div', {}, h('dt', { text: 'Stored record' }),
          h('dd', {}, h('a', {
            href: 'legislation/' + DATA.law.files[provision.ref], rel: 'noreferrer',
            text: DATA.law.files[provision.ref],
          })))),
      h('div', { class: 'modes' },
        at > 0 ? h('button', { class: 'mode', type: 'button', text: '← previous provision', onclick: () => go(['prov', siblings[at - 1].ref]) }) : null,
        at >= 0 && at < siblings.length - 1 ? h('button', { class: 'mode', type: 'button', text: 'next provision →', onclick: () => go(['prov', siblings[at + 1].ref]) }) : null)),
    h('section', { class: 'card', style: 'padding:1.1rem 1.25rem' },
      prose,
      verbatim,
      lawCitationBlock(provision, manual)));

  loadProvisionFile(provision.ref).then((doc) => {
    prose.replaceChildren(renderUnits(doc));
    verbatim.replaceChildren(h('details', { class: 'detail' },
      h('summary', { text: 'The verbatim string this was set from' }),
      h('p', { class: 'hint', text: 'Above is the provision as the drafter numbered it, from the units the Office of Parliamentary Counsel styles delimit. The snapshot also asserts the provision as one string, and content_hash is taken over that string alone; joining the units with single spaces reproduces it exactly, which is what stops the two becoming differently worded copies of the law.' }),
      h('div', { class: 'prose' }, h('p', {}, marked(doc.text, S.q)))));
  }).catch((err) => {
    verbatim.replaceChildren(h('p', { class: 'hint' },
      'Shown as the provision’s flat string: the file holding its subsection and paragraph structure could not be loaded — ',
      h('span', { class: 'mono', text: String(err && err.message || err) })));
  });

  return container;
}

/** Bold, italic and bold-italic runs put back at the offsets `emphasis` records.
 *
 * Same defensive rule as the Manual's links: a run is drawn only where the
 * snapshot's own words agree with the text at those offsets, so a stale bundle
 * shows plain prose rather than emphasis over the wrong words. It is recorded
 * and not interpreted — the leading bold-italic run of a definition is the
 * defined term, and this viewer draws it without saying so.
 */
function emphasised(text, spans, needle) {
  const inside = (spans || []).filter((span) =>
    span.end > span.start && span.start >= 0 && span.end <= text.length &&
    text.slice(span.start, span.end) === span.text);
  if (!inside.length) return marked(text, needle);

  const frag = document.createDocumentFragment();
  let at = 0;
  for (const span of [...inside].sort((a, b) => a.start - b.start)) {
    if (span.start < at) continue;                    // overlaps the one before it
    if (span.start > at) frag.append(marked(text.slice(at, span.start), needle));
    const inner = marked(span.text, needle);
    frag.append(span.weight === 'italic'
      ? h('em', {}, inner)
      : span.weight === 'bold-italic' ? h('em', {}, h('strong', {}, inner)) : h('strong', {}, inner));
    at = span.end;
  }
  frag.append(marked(text.slice(at), needle));
  return frag;
}

const UNIT_LABELS = {
  note: 'note', penalty: 'penalty', definition: 'definition',
  heading: 'run-in heading', special: 'modified text', table: 'table', text: 'unnumbered',
};

/** Units → the indented, numbered shape the compilation prints. */
function renderUnits(provision) {
  const frag = document.createDocumentFragment();
  const units = provision.units || [];
  if (!units.length) {
    return h('p', {}, provision.text
      ? marked(provision.text, S.q)
      : h('span', { class: 'hint', text: 'This provision is a heading and nothing else — the compilation retains it as repealed.' }));
  }

  for (const unit of units) {
    const depth = Math.max(0, unit.depth || 0);
    const cited = INDEX.manualCitesUnit[unit.ref] || [];
    const marks = h('span', { class: 'badges unit-marks' },
      UNIT_LABELS[unit.kind] ? h('span', { class: 'badge', text: UNIT_LABELS[unit.kind] }) : null,
      unit.number_collision ? h('span', { class: 'badge warn', text: 'number collision' }) : null,
      cited.length
        ? h('button', {
          class: 'badge accent as-btn', title: `${cited.length} Manual chunk${cited.length > 1 ? 's' : ''} cite this exact address`,
          text: `${num(cited.length)} in the Manual`,
          onclick: () => { S.provision = unit.ref; syncControls(); go(['results']); },
        })
        : null);

    const body = unit.kind === 'heading'
      ? h('h5', {}, emphasised(unit.text, unit.emphasis, S.q))
      : unit.table
        ? lawTable(unit.table)
        : h('p', {}, emphasised(unit.text, unit.emphasis, S.q));

    frag.append(h('div', {
      class: 'unit unit-' + unit.kind,
      style: depth ? `margin-left:${Math.min(depth, 5) * 1.3}rem` : null,
      id: unit.ref,
    }, body, marks.childNodes.length ? marks : null));
  }
  return frag;
}

/** The grid a unit holds, as the markup declares it — no header row is assumed. */
function lawTable(table) {
  const rows = (table.rows || []).map((row) => h('tr', {}, row.map((cell) => {
    const tag = cell.heading ? 'th' : 'td';
    return h(tag, {
      colspan: cell.colspan > 1 ? cell.colspan : null,
      scope: cell.heading ? 'col' : null,
      class: cell.continues ? 'cont' : null,
      title: cell.continues ? 'continues a vertical merge from the row above' : null,
    }, marked(cell.text || '', S.q));
  })));
  return h('div', { class: 'scroll-x' }, h('table', { class: 'tm-table' }, h('tbody', {}, rows)));
}

/** What a provision points at, what points at it, and who cites it in the Manual. */
function lawCitationBlock(provision, manual) {
  const frag = document.createDocumentFragment();
  const edges = INDEX.lawEdges[provision.ref] || [];
  const cited = INDEX.lawCitedBy[provision.ref] || [];

  if (edges.length) {
    frag.append(h('details', { class: 'detail' },
      h('summary', { text: `Legislation cited (${edges.length})` }),
      h('p', { class: 'hint', text: 'Every edge from a compiled instrument is a pattern match: the documents carry no hyperlinks at all, so there is no href evidence to be had. Because the ids are this corpus’s own refs, these double as the instrument’s internal cross-reference graph.' }),
      h('ul', { class: 'cite-list' }, edges.map((edge) => h('li', {},
        provisionLink(edge.id),
        h('span', { class: 'badge', text: edge.extraction }),
        edge.certainty ? h('span', { class: 'badge' + (edge.certainty === 'ambiguous' ? ' warn' : ''), text: edge.certainty }) : null,
        edge.unit ? h('span', { class: 'mention', text: `in ${edge.unit}` }) : null)))));
  }
  if (cited.length) {
    frag.append(h('details', { class: 'detail' },
      h('summary', { text: `Cited by other provisions (${cited.length})` }),
      h('p', { class: 'hint', text: 'Derived by this viewer by reversing every provision’s own references — the snapshot stores the forward direction only.' }),
      h('ul', { class: 'cite-list' }, cited.map((ref) => h('li', {}, provisionLink(ref))))));
  }
  if (manual.length) {
    frag.append(h('details', { class: 'detail', open: true },
      h('summary', { text: `Cited by the Manual (${manual.length} chunks)` }),
      h('p', { class: 'hint' },
        'Derived by this viewer from every chunk’s ', h('code', { text: 'provisions[].id' }),
        ' — the same string as this provision’s ref, which is the whole of the join between the two halves of the snapshot. ',
        citingButton(provision.ref, 'Filter the snapshot to these →')),
      h('ul', { class: 'cite-list' }, manual.slice(0, 60).map((ref) => h('li', {}, refLink(ref))),
        manual.length > 60 ? h('li', { class: 'mention' }, `and ${num(manual.length - 60)} more — the filtered list has all of them`) : null)));
  }
  if (!edges.length && !cited.length && !manual.length) {
    frag.append(h('p', { class: 'hint', text: 'Nothing in either corpus cites this provision, and it cites nothing itself.' }));
  }
  return frag;
}

/* ------------------------------------------------------------------ results */

function viewResults() {
  renderCrumbs([{ label: 'Snapshot', path: [] }, { label: 'Filtered passages' }]);
  if (!DATA.ready) return h('div', { class: 'card empty' }, h('strong', { text: 'Loading the chunk index…' }));
  if (!filtersActive()) {
    return h('div', { class: 'card empty' },
      h('strong', { text: 'No filter is applied.' }),
      h('p', { text: 'Choose something on the left, or browse the Parts.' }),
      h('p', {}, h('button', { class: 'link-btn', text: 'Browse Parts', onclick: () => go([]) })));
  }
  if (!RESULTS.list.length && !RESULTS.lawList.length) {
    return h('div', { class: 'card empty' },
      h('strong', { text: 'Nothing matches.' }),
      h('p', { text: 'Every filter is a conjunction — a chunk or a provision has to satisfy all of them, and some of them only one of the two corpora can satisfy at all.' }));
  }

  const byPage = new Map();
  for (const chunk of RESULTS.list) {
    if (!byPage.has(chunk.page_ref)) byPage.set(chunk.page_ref, []);
    byPage.get(chunk.page_ref).push(chunk);
  }

  const sections = [...byPage.entries()].map(([pageRef, chunks]) => {
    const page = INDEX.pageByRef.get(pageRef);
    return h('section', { class: 'card', style: 'margin-bottom:.9rem' },
      h('button', {
        class: 'row', style: 'border-bottom:1px solid var(--line)',
        onclick: () => go(['page', pageRef]),
      },
        h('span', { class: 'ref', text: page ? page.part_id : '' }),
        h('span', { class: 'title' }, page ? page.nav_title : pageRef, h('small', { text: pageRef })),
        h('span', { class: 'tail' }, `${num(chunks.length)} matching`)),
      h('div', {}, chunks.map((chunk) => chunkCard(chunk, {}))));
  });

  return h('div', {},
    h('section', { class: 'card intro' },
      h('h2', {}, RESULTS.lawList.length
        ? `${plural(RESULTS.list.length, 'chunk')} and ${plural(RESULTS.lawList.length, 'provision')} match`
        : `${plural(RESULTS.list.length, 'chunk')} match`),
      h('p', { text: `Across ${plural(byPage.size, 'page')} and ${plural(RESULTS.byPart.size, 'Part')}${RESULTS.lawList.length ? `, and ${plural(RESULTS.byInstrument.size, 'instrument')} of the legislation` : ''}. Expand a chunk to read it; open one to see the structure underneath it.` }),
      h('p', {}, activeFilterSummary())),
    RESULTS.list.length
      ? sections
      : h('div', { class: 'card empty' },
        h('strong', { text: 'No chunk of the Manual matches.' }),
        h('p', { text: 'The legislation below does.' })),
    lawResults());
}

/** The legislation side of a filtered set, grouped by instrument. */
function lawResults() {
  if (!DATA.lawReady || !RESULTS.lawList.length) return null;
  const byInstrument = new Map();
  for (const provision of RESULTS.lawList) {
    if (!byInstrument.has(provision.instrument)) byInstrument.set(provision.instrument, []);
    byInstrument.get(provision.instrument).push(provision);
  }
  return h('div', { style: 'margin-top:1.4rem' },
    h('section', { class: 'card intro' },
      h('h2', {}, `${plural(RESULTS.lawList.length, 'provision')} match`),
      h('p', { text: 'The same predicates, read against the law itself: a provision’s kind, the references its units carry, and its words. Open one to read it as the drafter numbered it.' })),
    [...byInstrument.entries()].map(([code, provisions]) => {
      const instrument = INDEX.instrumentByCode.get(code);
      return h('section', { class: 'card', style: 'margin-bottom:.9rem' },
        h('button', {
          class: 'row', style: 'border-bottom:1px solid var(--line)',
          onclick: () => go(['law', code]),
        },
          h('span', { class: 'ref', text: code }),
          h('span', { class: 'title' }, instrument ? instrument.name : code,
            h('small', { text: instrument ? `compilation ${instrument.compilation_number}, in force ${instrument.compilation_start}` : '' })),
          h('span', { class: 'tail' }, `${num(provisions.length)} matching`)),
        h('div', { class: 'rows', style: 'border:0;border-radius:0;box-shadow:none' },
          provisions.slice(0, 200).map(provisionRow)),
        provisions.length > 200
          ? h('p', { class: 'hint', style: 'padding:.6rem .9rem' }, `Showing the first 200 of ${num(provisions.length)} — narrow the filter to see the rest.`)
          : null);
    }));
}

function activeFilterSummary() {
  const bits = [];
  if (S.q) bits.push(`text contains “${S.q}”`);
  if (S.corpus.size) bits.push(`corpus in {${[...S.corpus].join(', ')}}`);
  if (S.parts.size) bits.push(`Part in {${[...S.parts].join(', ')}}`);
  if (S.kinds.size) bits.push(`kind in {${[...S.kinds].join(', ')}}`);
  if (S.headingSources.size) bits.push(`heading_source in {${[...S.headingSources].join(', ')}}`);
  if (S.instruments.size) bits.push(`cites {${[...S.instruments].join(', ')}}`);
  if (S.provision) bits.push(`provision matches “${S.provision}”`);
  if (S.extraction.size) bits.push(`extraction in {${[...S.extraction].join(', ')}}`);
  if (S.certainty.size) bits.push(`certainty in {${[...S.certainty].join(', ')}}`);
  if (S.caseq) bits.push(`case matches “${S.caseq}”`);
  for (const flag of S.flags) bits.push(FLAGS.find((f) => f[0] === flag)[1]);
  for (const flag of S.pageflags) bits.push(PAGE_FLAGS.find((f) => f[0] === flag)[1]);
  if (S.year) bits.push(`page last amended in ${S.year}`);
  return h('span', { class: 'mono', style: 'font-size:.78rem;color:var(--ink-3)', text: bits.join('  ∧  ') });
}

function notFound(message) {
  return h('div', { class: 'card empty' },
    h('strong', { text: 'Not found' }),
    h('p', { text: message }),
    h('p', {}, h('button', { class: 'link-btn', text: 'Back to the snapshot', onclick: () => go([]) })));
}

boot();

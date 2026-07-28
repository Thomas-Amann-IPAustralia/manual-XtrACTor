/* Trade Marks Manual — snapshot viewer.
 *
 * Reads the bundle built by viz/build.py. Three tiers of loading, matching the
 * three tiers of disclosure: manual.json paints the Parts, chunks.json powers
 * the filters and the passage text, and a page's own file is fetched only when
 * a reader opens it and wants the paragraph structure inside a chunk.
 *
 * Nothing here writes anything anywhere. Every value shown is a field the
 * pipeline put in the snapshot; where this file derives something (a count, a
 * reverse index) it says so on screen.
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

const DATA = { manual: null, chunks: null, ready: false };
const INDEX = {
  pageByRef: new Map(),
  chunkByRef: new Map(),
  chunksByPage: new Map(),
  partByRef: new Map(),
  haystack: [],       // parallel to DATA.chunks.chunks — never merged into a chunk
  tables: {},
  citedBy: {},
};

const SETS = ['parts', 'kinds', 'headingSources', 'instruments', 'extraction', 'certainty', 'flags', 'pageflags'];
const S = {
  q: '', provision: '', caseq: '', year: '',
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
  parts: 'part', kinds: 'kind', headingSources: 'hs',
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
  }
  renderCorpus();
  buildControls();
  syncControls();
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

/* ---------------------------------------------------------------- matching */

function chunkMatches(chunk, i) {
  const page = INDEX.pageByRef.get(chunk.page_ref);

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

let RESULTS = { refs: new Set(), byPart: new Map(), byPage: new Map(), list: [], all: false };

function recompute() {
  RESULTS = { refs: new Set(), byPart: new Map(), byPage: new Map(), list: [], all: !filtersActive() };
  if (!DATA.ready) return;
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

function buildControls() {
  const facets = DATA.manual.facets;

  checkboxList(document.getElementById('f-parts'),
    'parts',
    DATA.manual.parts.map((p) => ({ value: p.part_id, count: p.chunk_count, title: p.part_title })),
    (o) => o.title);

  checkboxList(document.getElementById('f-kinds'), 'kinds', facets.kinds);
  checkboxList(document.getElementById('f-headingSources'), 'headingSources', facets.heading_sources);
  checkboxList(document.getElementById('f-instruments'), 'instruments', facets.instruments,
    (o) => `${o.value}${INSTRUMENT_NAMES[o.value] ? ' — ' + INSTRUMENT_NAMES[o.value] : ''}`);
  checkboxList(document.getElementById('f-extraction'), 'extraction', facets.extraction);
  checkboxList(document.getElementById('f-certainty'), 'certainty', facets.certainty);
  checkboxList(document.getElementById('f-flags'), 'flags',
    FLAGS.map(([value, label]) => ({ value, label })), (o) => o.label);
  checkboxList(document.getElementById('f-pageflags'), 'pageflags',
    PAGE_FLAGS.map(([value, label]) => ({ value, label })), (o) => o.label);

  document.getElementById('provision-list').replaceChildren(
    ...facets.provisions.slice(0, 400).map((p) => h('option', { value: p.value })));
  document.getElementById('case-list').replaceChildren(
    ...facets.cases.slice(0, 400).map((c) => h('option', { value: c.citation })));

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
    parts: 'parts', kinds: 'kinds', headingSources: 'headingSources',
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
  line.replaceChildren(
    filtersActive()
      ? h('span', {}, h('strong', { text: num(RESULTS.list.length) }), ` of ${num(total)} chunks match`)
      : h('span', {}, h('strong', { text: num(total) }), ' chunks, no filter applied'));
}

/* ------------------------------------------------------------------- chrome */

function renderCorpus() {
  const corpus = DATA.manual.corpus || {};
  const stat = (label, value, sub) =>
    h('div', {}, h('dt', { text: label }), h('dd', {}, num(value), sub ? h('small', { text: sub }) : null));
  document.getElementById('corpus').replaceChildren(
    stat('Parts', corpus.parts !== undefined ? corpus.parts : DATA.manual.parts.length),
    stat('Pages', corpus.pages !== undefined ? corpus.pages : DATA.manual.pages.length),
    stat('Chunks', corpus.chunks),
    h('div', {}, h('dt', { text: 'Crawled' }),
      h('dd', {}, (DATA.manual.crawled_at || '').slice(0, 10) || '—',
        h('small', { text: DATA.manual.extractor_version || '' }))));

  const source = (DATA.manual.source || {}).manual_root;
  document.getElementById('foot-line').replaceChildren(
    'Built from the snapshot in this repository. Source: ',
    source ? h('a', { href: source, rel: 'noreferrer', text: source }) : 'the IP Australia website',
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
    else if (head === 'results') view.replaceChildren(viewResults());
    else view.replaceChildren(viewParts());
  } catch (err) {
    view.replaceChildren(h('div', { class: 'card empty' },
      h('strong', { text: 'That view could not be rendered.' }),
      h('p', { class: 'mono', text: String(err && err.message || err) })));
  }
}

function viewParts() {
  renderCrumbs([{ label: 'Manual' }]);
  const active = filtersActive();
  const wrap = document.createDocumentFragment();

  wrap.append(h('section', { class: 'card intro' },
    h('h2', { text: 'The Manual, cut into addressable passages' }),
    h('p', { text: 'Each Part below holds pages; each page holds chunks. A chunk is normally the prose under one heading, carrying its heading ancestry, the legislation and case law cited in it, and a hash of its own text. Open a page and you can read it either as the chunks it was cut into or as a continuous page reassembled from them — the two are the same words.' }),
    h('p', {}, 'The filters on the left work on what the extractor recorded, not on the words alone: which Act a passage cites, whether the Manual hyperlinked that citation or the pipeline matched it by pattern, whether a heading was marked up or inferred. That is what the deconstruction buys you.'),
    active && DATA.ready
      ? h('p', {}, h('strong', { text: `${num(RESULTS.list.length)} chunks match the current filter` }),
        ' across ', plural(RESULTS.byPage.size, 'page'), ' — ',
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
  return wrap;
}

function viewPart(partId) {
  const part = DATA.manual.parts.find((p) => p.part_id === partId);
  if (!part) return notFound(`No Part called ${partId}.`);
  renderCrumbs([{ label: 'Manual', path: [] }, { label: part.part_id }]);

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
    { label: 'Manual', path: [] },
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
  frag.append(h('div', { class: 'prose' }, h('p', {}, marked(chunk.text, S.q))));
  frag.append(citationBlock(chunk));
  frag.append(h('p', { style: 'margin-top:.8rem' },
    h('button', { class: 'link-btn', text: 'Open this chunk in full →', onclick: () => go(['chunk', chunk.chunk_ref]) })));
  return frag;
}

function provisionLine(provision) {
  const [instrument] = provision.id.split('/');
  const href = AUSTLII[instrument];
  return h('li', {},
    href ? h('a', { class: 'mono', href, rel: 'noreferrer', text: provision.id }) : h('span', { class: 'mono', text: provision.id }),
    h('span', { class: 'badge', text: provision.extraction }),
    provision.certainty ? h('span', { class: 'badge' + (provision.certainty === 'ambiguous' ? ' warn' : ''), text: provision.certainty }) : null,
    provision.mention ? h('span', { class: 'mention', text: `“${provision.mention}”` }) : null);
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
      h('ul', { class: 'cite-list' }, refs.map((ref) => h('li', {}, refLink(ref))))));
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
    { label: 'Manual', path: [] },
    { label: page ? page.part_id : '?', path: ['part', page ? page.part_id : ''] },
    { label: chunk.page_ref.split('/').slice(1).join('.'), path: ['page', chunk.page_ref] },
    { label: `chunk ${chunk.ordinal}` },
  ]);

  const siblings = INDEX.chunksByPage.get(chunk.page_ref) || [];
  const at = siblings.indexOf(chunk);

  // The index carries `text` and not `blocks`, so the flat string paints at
  // once and the structure replaces it when the page file lands. If that fetch
  // fails the reader is left with the passage rather than with a spinner.
  const prose = h('div', { class: 'prose' }, h('p', {}, marked(chunk.text, S.q)));
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
  if (!blocks.length) return h('p', {}, marked(chunk.text, S.q));

  const tables = chunk.tables || [];
  let tableAt = 0;
  let stack = [];   // [{depth, list}]

  const closeTo = (depth) => { while (stack.length && stack[stack.length - 1].depth > depth) stack.pop(); };

  for (const block of blocks) {
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
      stack[stack.length - 1].list.append(h('li', {}, marked(block.text, S.q)));
      continue;
    }

    stack = [];
    if (block.kind === 'heading') {
      frag.append(h('h5', {}, marked(block.text, S.q)));
    } else if (block.kind === 'table') {
      const grid = tables[tableAt++];
      frag.append(grid ? renderTable(grid) : h('p', {}, marked(block.text, S.q)));
    } else if (block.kind === 'image') {
      frag.append(h('p', { class: 'img-note' },
        'Image in the source at this point',
        block.alt ? ` — “${block.alt}”` : ' — the Manual gives it no alt text',
        '. The bytes are not in the snapshot: ',
        h('a', { href: SOURCE_ROOT + block.src, rel: 'noreferrer', text: block.src })));
    } else {
      frag.append(h('p', {}, marked(block.text, S.q)));
    }
  }
  return frag;
}

function renderTable(grid) {
  const rows = (grid.cells || []).map((row, r) => h('tr', {}, row.map((cell) => {
    const tag = grid.header_row === r ? 'th' : 'td';
    return h(tag, {
      colspan: cell.colspan || null,
      rowspan: cell.rowspan || null,
      scope: tag === 'th' ? 'col' : null,
    }, marked(cell.text || '', S.q));
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

  for (const chunk of chunks) {
    blockCount += (chunk.blocks || []).length;
    tableCount += (chunk.tables || []).length;

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
      `Reassembled from ${plural(chunks.length, 'chunk')}, ${plural(blockCount, 'block')} and ${plural(tableCount, 'table')} — in ordinal order, with headings taken from each chunk's own ancestry. Nothing is added: each dashed rule opens a chunk and everything below it down to the next rule — heading included — is that chunk, and every one of them is a passage you can address, filter and cite on its own.`),
    chunks.length ? body : h('p', { class: 'busy', text: 'This page has no chunks to reassemble.' }),
    h('p', { class: 'hint', style: 'margin-top:1.2rem' },
      'Compare with ', h('a', { href: page.url, rel: 'noreferrer', text: 'the live page' }), '.'));
}

/* ------------------------------------------------------------------ results */

function viewResults() {
  renderCrumbs([{ label: 'Manual', path: [] }, { label: 'Filtered chunks' }]);
  if (!DATA.ready) return h('div', { class: 'card empty' }, h('strong', { text: 'Loading the chunk index…' }));
  if (!filtersActive()) {
    return h('div', { class: 'card empty' },
      h('strong', { text: 'No filter is applied.' }),
      h('p', { text: 'Choose something on the left, or browse the Parts.' }),
      h('p', {}, h('button', { class: 'link-btn', text: 'Browse Parts', onclick: () => go([]) })));
  }
  if (!RESULTS.list.length) {
    return h('div', { class: 'card empty' },
      h('strong', { text: 'Nothing matches.' }),
      h('p', { text: 'Every filter is a conjunction — a chunk has to satisfy all of them.' }));
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
      h('h2', {}, `${num(RESULTS.list.length)} chunks match`),
      h('p', { text: `Across ${plural(byPage.size, 'page')} and ${plural(RESULTS.byPart.size, 'Part')}. Expand a chunk to read it; open one to see the structure underneath it.` }),
      h('p', {}, activeFilterSummary())),
    sections);
}

function activeFilterSummary() {
  const bits = [];
  if (S.q) bits.push(`text contains “${S.q}”`);
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
    h('p', {}, h('button', { class: 'link-btn', text: 'Back to the Manual', onclick: () => go([]) })));
}

boot();

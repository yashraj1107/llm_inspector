'use strict';

// app.js — Entry point. Owns all top-level state and wires the modules together.
//
// Load order in index.html (all plain globals, no ES module syntax):
//   api.js → json-tree.js → diff.js → replay.js → trace-list.js → app.js

// ── State ───────────────────────────────────────────────────────────────────
let _traces = [];
let _filteredTraces = [];
let _selectedId = null;
let _selectedTrace = null;
let _lastReplayedTrace = null;
let _activeTab = 'REQUEST';

let _availableProviders = new Map();  // provider → count
let _availableModels = new Map();     // model → count
let _availableTags = new Map();       // tag → count (FEATURE 6)

let _childrenMap = new Map();         // parent_id → child traces[] (FEATURE A)
let _availableEnvProviders = [];      // from /api/providers/available

let _currentNavTab = 'Traces';        // 'Traces' | 'Library'
const _markedFilters = { pinned: false, tagged: false, hasVersions: false };

const _filters = {
  status: { ok: true, fail: true },
  failureTypes: new Set(),  // FEATURE 3
  providers: new Set(),
  models: new Set(),
  tags: new Set(),           // FEATURE 6
  pinnedOnly: false,         // FEATURE 5
  timeRange: 'All-time',
  search: ''
};

// ── DOM Refs ─────────────────────────────────────────────────────────────────
const els = {
  btnToggleSidebar: document.getElementById('btn-toggle-sidebar'),
  filterSidebar: document.getElementById('filter-sidebar'),
  searchInput: document.getElementById('search-input'),
  resetFilters: document.getElementById('reset-filters'),
  tracesFilters: document.getElementById('traces-filters'),
  markedFilters: document.getElementById('marked-filters'),

  filterStatus: document.getElementById('filter-status'),
  filterProvider: document.getElementById('filter-provider'),
  filterModel: document.getElementById('filter-model'),
  filterTime: document.getElementById('filter-time'),
  filterTags: document.getElementById('filter-tags'),
  filterPinnedOnly: document.getElementById('filter-pinned-only'),

  markedFilterPinned: document.getElementById('marked-filter-pinned'),
  markedFilterTagged: document.getElementById('marked-filter-tagged'),
  markedFilterVersions: document.getElementById('marked-filter-versions'),

  listCount: document.getElementById('list-count'),
  listContainer: document.getElementById('list-container'),

  detailEmpty: document.getElementById('detail-empty'),
  detailWrap: document.getElementById('detail-content-wrap'),
  detailBadge: document.getElementById('detail-badge'),
  detailModel: document.getElementById('detail-model'),
  detailProvider: document.getElementById('detail-provider'),
  detailStats: document.getElementById('detail-stats'),
  errorStrip: document.getElementById('detail-error-strip'),
  errorMsg: document.getElementById('detail-error-msg'),

  detailTabs: document.getElementById('detail-tabs'),
  tabContent: document.getElementById('detail-tab-content'),

  btnCopyCurl: document.getElementById('btn-copy-curl'),
  btnCopyJson: document.getElementById('btn-copy-json'),
  btnActionReplay: document.getElementById('btn-action-replay'),
  btnExportTrace: document.getElementById('btn-export-trace'),
  btnPinTrace: document.getElementById('btn-pin-trace'),
  addTagInput: document.getElementById('add-tag-input'),
  detailTagsList: document.getElementById('detail-tags-list'),
};

// ── Initialization ────────────────────────────────────────────────────────────
async function init() {
  initSidebarToggle();   // trace-list.js
  attachStaticListeners();
  const providers = await apiFetchAvailableProviders();  // api.js
  _availableEnvProviders = providers;
  await fetchData();
  fetchCostStats();
}

async function fetchCostStats() {
  try {
    const stats = await apiFetchCostStats();  // api.js
    document.getElementById('nav-cost-today').textContent = '$' + stats.today.toFixed(4);
    document.getElementById('nav-cost-today').title = `Week: $${stats.week.toFixed(4)} | All-Time: $${stats.all_time.toFixed(4)}`;
  } catch (err) { console.error('Cost stats error:', err); }
}

// ── Event Wiring ─────────────────────────────────────────────────────────────
function attachStaticListeners() {
  els.searchInput.addEventListener('input', debounce(async (e) => {
    _filters.search = e.target.value.trim();
    await fetchData();
  }, 300));

  els.resetFilters.addEventListener('click', () => {
    _filters.status.ok = true;
    _filters.status.fail = true;
    _filters.failureTypes.clear();
    _filters.providers = new Set(_availableProviders.keys());
    _filters.models = new Set(_availableModels.keys());
    _filters.tags.clear();
    _filters.pinnedOnly = false;
    els.filterPinnedOnly.checked = false;
    _filters.timeRange = 'All-time';
    els.searchInput.value = '';
    _filters.search = '';
    renderSidebar();   // trace-list.js
    applyFilters();
  });

  els.filterPinnedOnly.addEventListener('change', (e) => {
    _filters.pinnedOnly = e.target.checked;
    applyFilters();
  });

  els.filterTime.addEventListener('click', (e) => {
    const btn = e.target.closest('.time-pill');
    if (!btn) return;
    _filters.timeRange = btn.dataset.val;
    renderSidebar();
    applyFilters();
  });

  els.detailTabs.addEventListener('click', (e) => {
    const btn = e.target.closest('.detail-tab');
    if (!btn) return;
    _activeTab = btn.dataset.tab;
    Array.from(els.detailTabs.children).forEach(c => c.classList.remove('active'));
    btn.classList.add('active');
    renderTabContent();
  });

  document.getElementById('nav-links').addEventListener('click', (e) => {
    const btn = e.target.closest('.nav-link');
    if (!btn) return;
    const tabName = btn.dataset.tab;
    if (tabName !== 'Traces' && tabName !== 'Library') return;

    Array.from(document.getElementById('nav-links').children).forEach(c => c.classList.remove('active'));
    btn.classList.add('active');
    _currentNavTab = tabName;

    if (tabName === 'Library') {
      els.tracesFilters.style.display = 'none';
      els.markedFilters.style.display = 'block';
    } else {
      els.tracesFilters.style.display = 'block';
      els.markedFilters.style.display = 'none';
    }
    applyFilters();
  });

  // FEATURE B: Library Filters
  els.markedFilterPinned.addEventListener('change', e => { _markedFilters.pinned = e.target.checked; applyFilters(); });
  els.markedFilterTagged.addEventListener('change', e => { _markedFilters.tagged = e.target.checked; applyFilters(); });
  els.markedFilterVersions.addEventListener('change', e => { _markedFilters.hasVersions = e.target.checked; applyFilters(); });

  els.btnActionReplay.addEventListener('click', () => {
    const tabBtn = Array.from(els.detailTabs.children).find(b => b.dataset.tab === 'REPLAY');
    if (tabBtn) tabBtn.click();
  });

  els.btnCopyCurl.addEventListener('click', handleCopyCurl);
  els.btnCopyJson.addEventListener('click', handleCopyJson);

  // FEATURE 4: Export trace
  els.btnExportTrace.addEventListener('click', () => {
    if (!_selectedTrace) return;
    const blob = new Blob([JSON.stringify(_selectedTrace, null, 2)], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `trace_${_selectedTrace.id}.json`;
    a.click();
    URL.revokeObjectURL(url);
  });

  // FEATURE 5: Pin trace
  els.btnPinTrace.addEventListener('click', async () => {
    if (!_selectedTrace) return;
    const t = _selectedTrace;
    const isPinnedNow = t.pinned === 1;
    t.pinned = isPinnedNow ? 0 : 1;

    const listRow = document.querySelector(`.trace-row[data-id="${t.id}"] .pin-icon-list`);
    if (listRow) listRow.style.fill = t.pinned ? 'currentColor' : 'none';
    const hdrIcon = document.getElementById('pin-icon-header');
    if (hdrIcon) hdrIcon.style.fill = t.pinned ? 'currentColor' : 'none';

    const cached = _traces.find(x => x.id === t.id);
    if (cached) cached.pinned = t.pinned;

    try {
      await apiPinTrace(t.id);  // api.js
    } catch (e) {
      console.error(e);
      t.pinned = isPinnedNow ? 1 : 0;
    }
  });

  // FEATURE 6: Add Tag
  els.addTagInput.addEventListener('keydown', async (e) => {
    if (e.key === 'Enter' && e.target.value.trim()) {
      if (!_selectedTrace) return;
      const newTag = e.target.value.trim();
      const currentTagsStr = _selectedTrace.tags || "";
      let tagsArr = currentTagsStr ? currentTagsStr.split(',').map(x => x.trim()) : [];
      if (!tagsArr.includes(newTag)) {
        tagsArr.push(newTag);
        const newTagsStr = tagsArr.join(',');
        _selectedTrace.tags = newTagsStr;
        const cached = _traces.find(x => x.id === _selectedTrace.id);
        if (cached) cached.tags = newTagsStr;
        e.target.value = '';
        renderTags();
        try {
          await apiSaveTags(_selectedTrace.id, newTagsStr);  // api.js
          fetchData();
        } catch (err) { console.error(err); }
      }
    }
  });
}

// ── Tags ─────────────────────────────────────────────────────────────────────
function renderTags() {
  if (!_selectedTrace) return;
  els.detailTagsList.innerHTML = '';
  const tagsStr = _selectedTrace.tags;
  if (!tagsStr) return;
  tagsStr.split(',').map(x => x.trim()).filter(x => x).forEach(t => {
    const chip = document.createElement('span');
    chip.textContent = t;
    chip.style.cssText = 'background:var(--bg-tertiary); color:var(--text-medium); font-size:10px; padding:2px 6px; border-radius:4px; border:1px solid var(--border-color);';
    els.detailTagsList.appendChild(chip);
  });
}

// ── Data Fetching & Filtering ─────────────────────────────────────────────────
async function fetchData() {
  els.listContainer.innerHTML = '<div style="padding: 20px; text-align: center; color: var(--text-light);">Loading...</div>';

  try {
    _traces = await apiFetchTraces(_filters.search);  // api.js

    const provs = new Map();
    const mods = new Map();
    const tagsMap = new Map();
    const failuresMap = new Map();

    _childrenMap.clear();

    _traces.forEach(t => {
      provs.set(t.provider, (provs.get(t.provider) || 0) + 1);
      mods.set(t.model, (mods.get(t.model) || 0) + 1);
      if (t.tags) {
        t.tags.split(',').forEach(tag => {
          const tr = tag.trim();
          if (tr) tagsMap.set(tr, (tagsMap.get(tr) || 0) + 1);
        });
      }
      if (t.status === 'error' && t.failure_type) {
        failuresMap.set(t.failure_type, (failuresMap.get(t.failure_type) || 0) + 1);
      }
      // FEATURE A: Populate _childrenMap
      if (t.parent_trace_id) {
        if (!_childrenMap.has(t.parent_trace_id)) _childrenMap.set(t.parent_trace_id, []);
        _childrenMap.get(t.parent_trace_id).push(t);
      }
    });

    if (_availableProviders.size === 0) {
      _filters.providers = new Set(provs.keys());
      _filters.models = new Set(mods.keys());
    }

    _availableProviders = provs;
    _availableModels = mods;
    _availableTags = tagsMap;
    window._currentFailuresMap = failuresMap;

    renderSidebar();  // trace-list.js
    applyFilters();
  } catch (err) {
    els.listContainer.innerHTML = `<div class="empty-msg" style="padding:20px; color:var(--accent-red)">Error loading traces: ${err.message}</div>`;
  }
}

function applyFilters() {
  const now = Date.now();
  let maxAgeMs = Infinity;
  if (_filters.timeRange === 'Last 15m') maxAgeMs = 15 * 60 * 1000;
  if (_filters.timeRange === 'Last 1h') maxAgeMs = 60 * 60 * 1000;
  if (_filters.timeRange === 'Last 6h') maxAgeMs = 6 * 60 * 60 * 1000;
  if (_filters.timeRange === '1 day') maxAgeMs = 24 * 60 * 60 * 1000;

  _filteredTraces = _traces.filter(t => {
    if (_currentNavTab === 'Library') {
      let passPinned = _markedFilters.pinned ? (t.pinned === 1) : false;
      let passTagged = _markedFilters.tagged ? (!!t.tags) : false;
      let passVersions = _markedFilters.hasVersions ? (!!t.parent_trace_id || _childrenMap.has(t.id)) : false;

      if (!_markedFilters.pinned && !_markedFilters.tagged && !_markedFilters.hasVersions) {
        return (t.pinned === 1) || (!!t.tags) || (!!t.parent_trace_id || _childrenMap.has(t.id));
      }
      if (_markedFilters.pinned && !passPinned) return false;
      if (_markedFilters.tagged && !passTagged) return false;
      if (_markedFilters.hasVersions && !passVersions) return false;
      return true;
    } else {
      // Traces tab: only root traces (or orphans)
      const isRootOrOrphan = !t.parent_trace_id || !_traces.find(x => x.id === t.parent_trace_id);
      if (!isRootOrOrphan) return false;

      const isOk = t.status === 'succeeded' || t.status === 'ok';
      if (isOk && !_filters.status.ok) return false;
      if (!isOk) {
        if (!_filters.status.fail) return false;
        if (_filters.failureTypes.size > 0 && t.failure_type && !_filters.failureTypes.has(t.failure_type)) return false;
      }

      if (!_filters.providers.has(t.provider)) return false;
      if (!_filters.models.has(t.model)) return false;
      if (_filters.pinnedOnly && t.pinned !== 1) return false;

      if (_filters.tags.size > 0) {
        if (!t.tags) return false;
        const tArr = t.tags.split(',').map(x => x.trim());
        if (!tArr.some(tag => _filters.tags.has(tag))) return false;
      }

      if (t.timestamp) {
        const traceTime = new Date(t.timestamp).getTime();
        if (now - traceTime > maxAgeMs) return false;
      }
      return true;
    }
  });

  renderList();  // trace-list.js
}

// Global toggle callbacks (used by inline onchange= handlers in sidebar HTML)
window.toggleAllStatus = (checked) => { _filters.status.ok = checked; _filters.status.fail = checked; _filters.failureTypes.clear(); applyFilters(); renderSidebar(); };
window.toggleStatus = (type, checked) => { _filters.status[type] = checked; applyFilters(); renderSidebar(); };
window.toggleFailureType = (ftype, checked) => { checked ? _filters.failureTypes.add(ftype) : _filters.failureTypes.delete(ftype); applyFilters(); };
window.toggleProvider = (p, checked) => { checked ? _filters.providers.add(p) : _filters.providers.delete(p); applyFilters(); };
window.toggleModel = (m, checked) => { checked ? _filters.models.add(m) : _filters.models.delete(m); applyFilters(); };
window.toggleTag = (t, checked) => { checked ? _filters.tags.add(t) : _filters.tags.delete(t); applyFilters(); };

// ── Trace Selection & Detail Rendering ───────────────────────────────────────
async function selectTrace(id) {
  _selectedId = id;
  _lastReplayedTrace = null;
  Array.from(els.listContainer.querySelectorAll('.trace-row')).forEach(c => c.classList.remove('active'));

  const node = els.listContainer.querySelector(`.trace-row[data-id="${id}"]`);
  if (node) node.classList.add('active');

  _selectedTrace = _traces.find(t => t.id === id);
  els.detailEmpty.style.display = 'none';
  els.detailWrap.style.display = 'flex';
  els.tabContent.innerHTML = '<div style="color:var(--text-light);">Loading trace details...</div>';

  try {
    _selectedTrace = await apiFetchTrace(id);  // api.js
    try {
      const history = await apiFetchTraceHistory(id);  // api.js
      _selectedTrace._history = history;
    } catch (e) {}

    renderDetail();
  } catch (err) {
    els.tabContent.innerHTML = `<div class="empty-msg" style="color:var(--accent-red)">${err.message}</div>`;
  }
}

function renderDetail() {
  if (!_selectedTrace) return;
  const t = _selectedTrace;
  const isOk = t.status === 'succeeded' || t.status === 'ok';

  els.detailBadge.className = `detail-badge ${isOk ? 'ok' : 'error'}`;
  els.detailBadge.textContent = isOk ? 'Succeeded' : (t.failure_type ? `Failed: ${t.failure_type}` : 'Failed');
  els.detailModel.textContent = t.model;
  els.detailProvider.textContent = t.provider;

  const hdrIcon = document.getElementById('pin-icon-header');
  if (hdrIcon) hdrIcon.style.fill = t.pinned === 1 ? 'currentColor' : 'none';

  renderTags();

  const latStr = t.latency_ms ? (t.latency_ms >= 1000 ? (t.latency_ms / 1000).toFixed(1) + 's' : t.latency_ms + 'ms') : '—';
  const timeStr = t.timestamp ? new Date(t.timestamp).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }) : '—';
  const costStr = t.cost != null ? '$' + t.cost.toFixed(4) : '—';

  els.detailStats.innerHTML = `
    <div class="stat-chip"><div class="stat-content"><span class="stat-val">${latStr}</span><span class="stat-lbl">Latency</span></div></div>
    <div class="stat-divider"></div>
    <div class="stat-chip"><div class="stat-content"><span class="stat-val">${t.prompt_tokens ?? 0}</span><span class="stat-lbl">Prompt tok.</span></div></div>
    <div class="stat-divider"></div>
    <div class="stat-chip"><div class="stat-content"><span class="stat-val">${t.completion_tokens ?? 0}</span><span class="stat-lbl">Completion tok.</span></div></div>
    <div class="stat-divider"></div>
    <div class="stat-chip"><div class="stat-content"><span class="stat-val" style="color:var(--accent-green);">${costStr}</span><span class="stat-lbl">Cost</span></div></div>
    <div class="stat-divider"></div>
    <div class="stat-chip"><div class="stat-content"><span class="stat-val">${timeStr}</span><span class="stat-lbl">Time</span></div></div>
  `;

  if (!isOk && t.error_message) {
    els.errorStrip.style.display = 'flex';
    els.errorMsg.textContent = t.error_message;
  } else {
    els.errorStrip.style.display = 'none';
  }

  renderTabContent();
}

function renderTabContent() {
  els.tabContent.innerHTML = '';
  const t = _selectedTrace;
  if (!t) return;

  // FEATURE 2: Version history strip at top of every tab
  if (t._history && t._history.length > 1) {
    els.tabContent.innerHTML += `
      <div style="background:var(--bg-secondary); border:1px solid var(--border-color); border-radius:6px; padding:12px; margin-bottom:16px;">
        <div style="font-size:10px; font-weight:700; color:var(--text-light); text-transform:uppercase; letter-spacing:0.1em; margin-bottom:8px;">Version History</div>
        <div style="display:flex; gap:8px; overflow-x:auto; padding-bottom:4px;">
          ${t._history.map((h, i) => {
            const isCurr = h.id === t.id;
            const lbl = i === 0 ? 'v1 (original)' : `v${i + 1}`;
            const timeStr = new Date(h.timestamp).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
            return `
              <div onclick="selectTrace('${h.id}')" style="cursor:pointer; flex-shrink:0; border:1px solid ${isCurr ? 'var(--accent-blue)' : 'var(--border-color)'}; background:${isCurr ? 'var(--bg-primary)' : 'transparent'}; padding:6px 12px; border-radius:4px; display:flex; flex-direction:column; gap:2px;">
                <span style="font-size:12px; font-weight:${isCurr ? '600' : '500'}; color:${isCurr ? 'var(--accent-blue)' : 'var(--text-dark)'};">${lbl}</span>
                <span style="font-size:10px; color:var(--text-light);">${h.model} • ${timeStr}</span>
              </div>
            `;
          }).join('')}
        </div>
      </div>
    `;
  }

  if (_activeTab === 'REQUEST') {
    if (!t.request_json) { els.tabContent.innerHTML += '<div class="empty-msg">(no request captured)</div>'; return; }
    els.tabContent.appendChild(createJsonTree(t.request_json));  // json-tree.js
  } else if (_activeTab === 'RESPONSE / ERROR') {
    if (!isTraceOk(t) && t.error_message) {
      els.tabContent.appendChild(createJsonTree({ error: t.error_message }));
    } else if (t.response_json) {
      els.tabContent.appendChild(createJsonTree(t.response_json));
    } else {
      els.tabContent.innerHTML += '<div class="empty-msg">(no response captured)</div>';
    }
  } else if (_activeTab === 'REPLAY') {
    renderReplayTab(t);  // replay.js
  } else if (_activeTab === 'COMPARE') {
    renderCompareTab();  // replay.js
  } else if (_activeTab === 'DIFF') {
    els.tabContent.innerHTML = `
      <div style="padding:16px;">
        <div id="diff-controls"><div style="color:var(--text-light); font-size:13px; margin-bottom:12px;">Loading version history...</div></div>
        <div id="diff-results" style="margin-top:16px; border-top:1px solid var(--border-color); padding-top:16px;"></div>
      </div>
    `;
    loadDiffHistory(t);  // diff.js
  }
}

// ── Helpers ───────────────────────────────────────────────────────────────────
function esc(str) {
  if (str == null) return '';
  return String(str).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
}

function debounce(func, wait) {
  let timeout;
  return function (...args) {
    clearTimeout(timeout);
    timeout = setTimeout(() => func.apply(this, args), wait);
  };
}

function isTraceOk(t) { return t && (t.status === 'succeeded' || t.status === 'ok'); }

function extractLastUserMessage(t) {
  if (!t || !t.request_json) return "";
  if (Array.isArray(t.request_json.messages)) {
    const msgs = t.request_json.messages;
    for (let i = msgs.length - 1; i >= 0; i--) {
      if (msgs[i].role === 'user') return msgs[i].content;
    }
  } else if (Array.isArray(t.request_json.contents)) {
    const contents = t.request_json.contents;
    for (let i = contents.length - 1; i >= 0; i--) {
      if (contents[i].role === 'user' && Array.isArray(contents[i].parts)) return contents[i].parts[0].text;
      else if (typeof contents[i] === 'string') return contents[i];
    }
  }
  return "";
}

function extractTextFromResponse(t) {
  if (!t || !t.response_json) return null;
  const r = t.response_json;
  if (typeof r.content === 'string') return r.content;
  if (Array.isArray(r.content)) { for (const b of r.content) { if (b.type === 'text' && b.text) return b.text; } }
  if (typeof r.text === 'string') return r.text;
  if (r.choices && r.choices[0] && r.choices[0].message) return r.choices[0].message.content;
  return null;
}

// ── Clipboard ─────────────────────────────────────────────────────────────────
function handleCopyJson() {
  if (!_selectedTrace || !_selectedTrace.request_json) return;
  navigator.clipboard.writeText(JSON.stringify(_selectedTrace.request_json, null, 2))
    .then(() => alert('Copied JSON to clipboard!'));
}

function handleCopyCurl() {
  if (!_selectedTrace || !_selectedTrace.request_json) return;
  const t = _selectedTrace;
  const req = t.request_json;
  let curl = '';
  if (t.provider === 'openai') {
    curl = `curl https://api.openai.com/v1/chat/completions \\\n  -H "Content-Type: application/json" \\\n  -H "Authorization: Bearer $OPENAI_API_KEY" \\\n  -d '${JSON.stringify(req)}'`;
  } else if (t.provider === 'anthropic') {
    curl = `curl https://api.anthropic.com/v1/messages \\\n  -H "x-api-key: $ANTHROPIC_API_KEY" \\\n  -H "anthropic-version: 2023-06-01" \\\n  -H "content-type: application/json" \\\n  -d '${JSON.stringify(req)}'`;
  } else if (t.provider === 'gemini') {
    curl = `curl "https://generativelanguage.googleapis.com/v1beta/models/${t.model}:generateContent?key=$GEMINI_API_KEY" \\\n  -H 'Content-Type: application/json' \\\n  -d '${JSON.stringify(req)}'`;
  } else {
    curl = `# curl generation not supported for provider ${t.provider}`;
  }
  navigator.clipboard.writeText(curl).then(() => alert('Copied cURL to clipboard!'));
}

// Kickoff
init();

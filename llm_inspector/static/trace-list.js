'use strict';

// trace-list.js — Trace list rendering, root/child grouping, sidebar rendering
// and the collapsible sidebar toggle.
//
// Depends on: _traces, _filteredTraces, _childrenMap, _filters, _markedFilters,
//             _availableProviders, _availableModels, _availableTags,
//             _currentNavTab, _selectedId, els, selectTrace, applyFilters,
//             renderSidebar, esc (app.js).

let _sidebarCollapsed = false;

function initSidebarToggle() {
  if (els.btnToggleSidebar && els.filterSidebar) {
    els.btnToggleSidebar.addEventListener('click', () => {
      _sidebarCollapsed = !_sidebarCollapsed;
      els.filterSidebar.classList.toggle('collapsed', _sidebarCollapsed);
    });
  }
  if (els.btnViewToggle) {
    els.btnViewToggle.addEventListener('click', () => {
      _viewMode = _viewMode === 'flat' ? 'tree' : 'flat';
      els.btnViewToggle.querySelector('span').textContent = `View: ${_viewMode === 'flat' ? 'Flat' : 'Tree'}`;
      renderList();
    });
  }
}

// Render the left filter sidebar controls from current filter state.
function renderSidebar() {
  let okCount = 0, failCount = 0;
  _traces.forEach(t => { (t.status === 'succeeded' || t.status === 'ok') ? okCount++ : failCount++; });
  const allStatusChecked = _filters.status.ok && _filters.status.fail;

  // FEATURE 3: Failure Type Sub-filters
  let failureHtml = '';
  if (_filters.status.fail && window._currentFailuresMap) {
    failureHtml = '<div style="margin-left:24px; margin-top:4px; margin-bottom:8px; display:flex; flex-direction:column; gap:4px;">';
    Array.from(window._currentFailuresMap.entries()).forEach(([ftype, count]) => {
      failureHtml += `
        <label class="filter-label" style="height:24px;">
          <input type="checkbox" class="filter-checkbox" ${_filters.failureTypes.has(ftype) ? 'checked' : ''} onchange="toggleFailureType('${ftype}', this.checked)">
          <span class="filter-text" style="font-size:11px; color:var(--text-medium);">${ftype}</span>
          <span class="filter-count plain">${count}</span>
        </label>
      `;
    });
    failureHtml += '</div>';
  }

  els.filterStatus.innerHTML = `
    <label class="filter-label">
      <input type="checkbox" class="filter-checkbox" ${allStatusChecked ? 'checked' : ''} onchange="toggleAllStatus(this.checked)">
      <span class="filter-text">All</span>
      <span class="filter-count">${_traces.length}</span>
    </label>
    <label class="filter-label">
      <input type="checkbox" class="filter-checkbox" ${_filters.status.ok ? 'checked' : ''} onchange="toggleStatus('ok', this.checked)">
      <span class="filter-text"><span class="status-dot ok"></span> Succeeded</span>
      <span class="filter-count">${okCount}</span>
    </label>
    <label class="filter-label">
      <input type="checkbox" class="filter-checkbox" ${_filters.status.fail ? 'checked' : ''} onchange="toggleStatus('fail', this.checked)">
      <span class="filter-text"><span class="status-dot error"></span> Failed</span>
      <span class="filter-count">${failCount}</span>
    </label>
    ${failureHtml}
  `;

  // Provider
  els.filterProvider.innerHTML = Array.from(_availableProviders.entries()).map(([p, count]) => `
    <label class="filter-label">
      <input type="checkbox" class="filter-checkbox" ${_filters.providers.has(p) ? 'checked' : ''} onchange="toggleProvider('${p}', this.checked)">
      <span class="prov-bar ${p}"></span>
      <span class="filter-text">${p}</span>
      <span class="filter-count">${count}</span>
    </label>
  `).join('');

  // Model
  els.filterModel.innerHTML = Array.from(_availableModels.entries())
    .sort((a, b) => b[1] - a[1])
    .map(([m, count]) => `
    <label class="filter-label model-label">
      <input type="checkbox" class="filter-checkbox" ${_filters.models.has(m) ? 'checked' : ''} onchange="toggleModel('${m}', this.checked)">
      <span class="filter-text-mono">${m}</span>
      <span class="filter-count plain">${count}</span>
    </label>
  `).join('');

  // FEATURE 6: Tags
  els.filterTags.innerHTML = Array.from(_availableTags.entries())
    .sort((a, b) => b[1] - a[1])
    .map(([t, count]) => `
    <label class="filter-label model-label">
      <input type="checkbox" class="filter-checkbox" ${_filters.tags.has(t) ? 'checked' : ''} onchange="toggleTag('${t}', this.checked)">
      <span class="filter-text">${t}</span>
      <span class="filter-count plain">${count}</span>
    </label>
  `).join('');

  // Time Range highlight
  Array.from(els.filterTime.children).forEach(c => {
    c.classList.toggle('active', c.dataset.val === _filters.timeRange);
  });
}

// Render the flat/grouped trace list from _filteredTraces.
function renderList() {
  if (typeof _viewMode !== 'undefined' && _viewMode === 'tree') {
    renderTreeList();
    return;
  }
  els.listCount.innerHTML = `<span class="list-count-num">${_filteredTraces.length}</span> <span class="list-count-text">Traces</span>`;

  if (_filteredTraces.length === 0) {
    els.listContainer.innerHTML = '<div class="empty-msg" style="padding: 20px; text-align: center;">No traces match the filters.</div>';
    return;
  }

  els.listContainer.innerHTML = '';

  const renderRowHtml = (t, isChild = false) => {
    const isOk = t.status === 'succeeded' || t.status === 'ok';
    const isSlow = t.latency_ms > 2000;
    const timeStr = t.timestamp ? new Date(t.timestamp).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }) : '—';
    const latStr = t.latency_ms ? (t.latency_ms >= 1000 ? (t.latency_ms / 1000).toFixed(1) + 's' : t.latency_ms + 'ms') : '—';

    // FEATURE A: Version badge
    let badgeHtml = '';
    let children = _childrenMap.get(t.id);
    if (!isChild && children && children.length > 0) {
      badgeHtml = `<div class="version-badge" style="font-size:10px; background:var(--bg-tertiary); padding:2px 6px; border-radius:12px; margin-top:4px; display:inline-flex; align-items:center; gap:2px; cursor:pointer; color:var(--text-medium); border:1px solid var(--border-color);">
         ${children.length} versions
         <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="margin-left: 2px;"><polyline points="6 9 12 15 18 9"></polyline></svg>
      </div>`;
    }

    // FEATURE 5: Pin icon
    const pinColor = t.pinned === 1 ? 'currentColor' : 'none';
    const pinHtml = `<svg class="pin-icon-list" style="position:absolute; right:8px; top:8px; width:12px; height:12px; color:var(--text-light); fill:${pinColor};" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polygon points="12 2 15.09 8.26 22 9.27 17 14.14 18.18 21.02 12 17.77 5.82 21.02 7 14.14 2 9.27 8.91 8.26 12 2"></polygon></svg>`;

    return `
      <div class="row-left-bar"></div>
      ${pinHtml}
      <div class="status-dot ${isOk ? 'ok' : 'error'}"></div>
      <div class="row-main-col">
        <div class="row-model-name">${esc(t.model)}</div>
        <div class="row-provider-name">${esc(t.provider)}</div>
        ${badgeHtml}
      </div>
      <div class="row-right-col">
        <div class="row-latency ${isSlow ? 'slow' : ''}">${latStr}</div>
        <div class="row-time">${timeStr}</div>
      </div>
    `;
  };

  _filteredTraces.sort((a, b) => {
    if (typeof _currentSort !== 'undefined') {
      if (_currentSort === 'latency') {
        return (b.latency_ms || 0) - (a.latency_ms || 0);
      }
      if (_currentSort === 'status') {
        const aErr = (a.status !== 'succeeded' && a.status !== 'ok') ? 1 : 0;
        const bErr = (b.status !== 'succeeded' && b.status !== 'ok') ? 1 : 0;
        if (aErr !== bErr) return bErr - aErr;
        return (b.timestamp || 0) - (a.timestamp || 0);
      }
    }
    return (b.timestamp || 0) - (a.timestamp || 0);
  });

  _filteredTraces.forEach(t => {
    const row = document.createElement('div');
    row.className = `trace-row ${t.status !== 'succeeded' && t.status !== 'ok' ? 'failed' : ''} ${t.id === _selectedId ? 'active' : ''}`;
    row.dataset.id = t.id;
    row.innerHTML = renderRowHtml(t, false);

    row.addEventListener('click', (e) => {
      const badge = e.target.closest('.version-badge');
      if (badge) {
        e.stopPropagation();
        const childContainer = row.nextElementSibling;
        if (childContainer && childContainer.classList.contains('child-container')) {
          const isHidden = childContainer.style.display === 'none';
          childContainer.style.display = isHidden ? 'block' : 'none';
          const svg = badge.querySelector('svg');
          if (svg) {
            svg.style.transform = isHidden ? 'rotate(180deg)' : '';
            svg.style.transition = 'transform 0.2s';
          }
        }
        return;
      }
      selectTrace(t.id);
    });

    els.listContainer.appendChild(row);

    // Child container (hidden by default)
    let children = _childrenMap.get(t.id);
    if (children && children.length > 0) {
      const childContainer = document.createElement('div');
      childContainer.className = 'child-container';
      childContainer.style.display = 'none';
      childContainer.style.borderLeft = '2px solid var(--border-color)';
      childContainer.style.marginLeft = '12px';
      childContainer.style.paddingLeft = '8px';
      childContainer.style.marginTop = '4px';
      childContainer.style.marginBottom = '8px';

      children.sort((a, b) => (b.timestamp || 0) - (a.timestamp || 0));

      children.forEach(ct => {
        const crow = document.createElement('div');
        crow.className = `trace-row ${ct.status !== 'succeeded' && ct.status !== 'ok' ? 'failed' : ''} ${ct.id === _selectedId ? 'active' : ''}`;
        crow.dataset.id = ct.id;
        crow.style.padding = '8px 12px';
        crow.innerHTML = renderRowHtml(ct, true);
        crow.addEventListener('click', () => selectTrace(ct.id));
        childContainer.appendChild(crow);
      });

      els.listContainer.appendChild(childContainer);
    }
  });
}

function renderTreeList() {
  els.listCount.innerHTML = `<span class="list-count-num">${_filteredTraces.length}</span> <span class="list-count-text">Traces</span>`;

  if (_filteredTraces.length === 0) {
    els.listContainer.innerHTML = '<div class="empty-msg" style="padding: 20px; text-align: center;">No traces match the filters.</div>';
    return;
  }

  els.listContainer.innerHTML = '';

  const traceMap = new Map(_filteredTraces.map(t => [t.id, t]));
  const childMap = new Map();
  _filteredTraces.forEach(t => {
    if (t.parent_trace_id) {
      if (!childMap.has(t.parent_trace_id)) {
        childMap.set(t.parent_trace_id, []);
      }
      childMap.get(t.parent_trace_id).push(t);
    }
  });

  // Top-level traces are those whose parent is not present in traceMap, OR who have no parent_trace_id
  const topLevel = _filteredTraces.filter(t => !t.parent_trace_id || !traceMap.has(t.parent_trace_id));

  // Sort topLevel by sort criteria (timestamp, latency, status)
  topLevel.sort((a, b) => {
    if (typeof _currentSort !== 'undefined') {
      if (_currentSort === 'latency') {
        return (b.latency_ms || 0) - (a.latency_ms || 0);
      }
      if (_currentSort === 'status') {
        const aErr = (a.status !== 'succeeded' && a.status !== 'ok') ? 1 : 0;
        const bErr = (b.status !== 'succeeded' && b.status !== 'ok') ? 1 : 0;
        if (aErr !== bErr) return bErr - aErr;
        return (b.timestamp || 0) - (a.timestamp || 0);
      }
    }
    return (b.timestamp || 0) - (a.timestamp || 0);
  });

  const renderNode = (t, depth = 0) => {
    const isOk = t.status === 'succeeded' || t.status === 'ok';
    const isSlow = t.latency_ms > 2000;
    const timeStr = t.timestamp ? new Date(t.timestamp).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }) : '—';
    const latStr = t.latency_ms ? (t.latency_ms >= 1000 ? (t.latency_ms / 1000).toFixed(1) + 's' : t.latency_ms + 'ms') : '—';

    // FEATURE 5: Pin icon
    const pinColor = t.pinned === 1 ? 'currentColor' : 'none';
    const pinHtml = `<svg class="pin-icon-list" style="position:absolute; right:8px; top:8px; width:12px; height:12px; color:var(--text-light); fill:${pinColor};" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polygon points="12 2 15.09 8.26 22 9.27 17 14.14 18.18 21.02 12 17.77 5.82 21.02 7 14.14 2 9.27 8.91 8.26 12 2"></polygon></svg>`;

    // span badge
    let spanBadgeHtml = '';
    if (t.span_type) {
      let badgeClass = 'badge-grey';
      if (t.span_type === 'llm_call') badgeClass = 'badge-blue';
      else if (t.span_type === 'custom') badgeClass = 'badge-grey';
      else if (t.span_type === 'tool_call') badgeClass = 'badge-orange';
      else if (t.span_type === 'retrieval') badgeClass = 'badge-green';

      spanBadgeHtml = `<span class="span-type-badge ${badgeClass}">${esc(t.span_type)}</span>`;
    }

    const row = document.createElement('div');
    row.className = `trace-row ${t.status !== 'succeeded' && t.status !== 'ok' ? 'failed' : ''} ${t.id === _selectedId ? 'active' : ''}`;
    row.dataset.id = t.id;
    row.style.paddingLeft = '12px';
    
    // Simple tree indent layout
    if (depth > 0) {
      row.style.marginLeft = `${depth * 16}px`;
      row.style.borderLeft = '1px solid var(--border-color)';
    }

    row.innerHTML = `
      <div class="row-left-bar"></div>
      ${pinHtml}
      <div class="status-dot ${isOk ? 'ok' : 'error'}"></div>
      <div class="row-main-col">
        <div class="row-model-name" style="display:flex; align-items:center;">
          <span>${esc(t.model || 'Span')}</span>
          ${spanBadgeHtml}
        </div>
        <div class="row-provider-name">${esc(t.provider || 'custom')}</div>
      </div>
      <div class="row-right-col">
        <div class="row-latency ${isSlow ? 'slow' : ''}">${latStr}</div>
        <div class="row-time">${timeStr}</div>
      </div>
    `;

    row.addEventListener('click', () => selectTrace(t.id));
    els.listContainer.appendChild(row);

    // Recursively render children
    const children = childMap.get(t.id) || [];
    children.sort((a, b) => (a.timestamp || 0) - (b.timestamp || 0));
    children.forEach(ct => renderNode(ct, depth + 1));
  };

  topLevel.forEach(t => renderNode(t, 0));
}

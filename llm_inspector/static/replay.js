'use strict';

// replay.js — Replay/Compare tab UI: provider dropdown, grouped model dropdown,
// custom model input, submit functions.
//
// Note: MODEL_OPTIONS must be updated manually whenever providers release new models.
// This list is NOT automatically fetched from any API.
const MODEL_OPTIONS = {
  openai: {
    "Latest": ["gpt-4o", "gpt-4o-mini", "o1-preview", "o1-mini"],
    "Other": ["gpt-3.5-turbo", "gpt-4-turbo"]
  },
  anthropic: {
    "Latest": ["claude-3-5-sonnet-20241022", "claude-3-5-haiku-20241022"],
    "Other": ["claude-3-opus-20240229", "claude-3-sonnet-20240229", "claude-3-haiku-20240307"]
  },
  gemini: {
    "Latest": ["gemini-1.5-pro", "gemini-1.5-flash", "gemini-1.5-flash-8b"],
    "Other": ["gemini-1.0-pro"]
  },
  deepseek: {
    "Latest": ["deepseek-chat", "deepseek-coder"]
  }
};

// Build a grouped <select> for a given provider. Ends with a "Custom..." option.
// selectId: the id to assign to the <select> element.
// defaultVal: pre-select this model if it's in the list.
function renderModelDropdownHtml(provider, selectId, defaultVal = '') {
  let html = `<select id="${selectId}" style="width:100%; padding:6px; border-radius:4px; border:1px solid var(--border-color); background:var(--bg-tertiary); color:var(--text-main); margin-bottom:8px;">`;

  let found = false;
  if (provider && MODEL_OPTIONS[provider]) {
    for (const [groupName, models] of Object.entries(MODEL_OPTIONS[provider])) {
      html += `<optgroup label="${groupName}">`;
      for (const m of models) {
        const selected = (m === defaultVal) ? 'selected' : '';
        if (selected) found = true;
        html += `<option value="${m}" ${selected}>${m}</option>`;
      }
      html += `</optgroup>`;
    }
  }

  const customSelected = (!found && defaultVal) ? 'selected' : '';
  html += `<option value="custom" ${customSelected}>Custom...</option>`;
  html += `</select>`;
  return html;
}

// Render the REPLAY tab contents and wire up all its event listeners.
// Depends on: _availableEnvProviders, _selectedTrace (app.js), renderModelDropdownHtml,
//             extractLastUserMessage, esc (app.js), submitReplay.
function renderReplayTab(t) {
  const lastMsg = extractLastUserMessage(t);

  const providerOpts = _availableEnvProviders.map(p => {
    const disabled = !p.available;
    const label = p.provider + (disabled ? " (No API key — add to .env)" : "");
    const selected = (p.provider === t.provider && p.available) ? "selected" : "";
    return `<option value="${p.provider}" ${disabled ? "disabled" : ""} ${selected}>${label}</option>`;
  }).join('');

  els.tabContent.innerHTML += `
    <div class="replay-container">
      <p class="replay-text">Edit the model or user message and replay this API call.</p>
      <div class="replay-form">
        <label>Provider Override</label>
        <select id="replay-provider-select" style="margin-bottom: 8px; width: 100%; padding: 6px; border-radius: 4px; border: 1px solid var(--border-color); background: var(--bg-tertiary); color: var(--text-main);">
           ${providerOpts}
        </select>

        <label style="display:flex; align-items:center; gap:6px; margin-bottom:8px; cursor:pointer;">
           <input type="checkbox" id="replay-custom-toggle">
           <span style="font-size:12px;">Use custom provider/endpoint (OpenAI SDK format)</span>
        </label>
        <input type="text" id="replay-baseurl-input" placeholder="e.g. https://api.together.xyz/v1" style="display:none; margin-bottom:8px;" />

        <label>Model Override</label>
        <div id="replay-model-dropdown-container">
           ${renderModelDropdownHtml(t.provider, 'replay-model-select', t.model)}
        </div>
        <input type="text" id="replay-model-input" value="${esc(t.model)}" placeholder="e.g. custom-model-v2" style="display:none;" />

        <label>Edit Last User Message</label>
        <textarea id="replay-msg-input">${esc(lastMsg)}</textarea>

        <div style="display:flex; align-items:center; gap:12px; margin-top:8px;">
          <button class="btn-primary" id="btn-submit-replay" style="height:34px; padding:0 16px;">Replay this call</button>
          <button class="btn-secondary" id="btn-retry-asis" style="height:34px;">Retry As-Is</button>
          <span id="replay-status-text" class="replay-text" style="display:none; color:var(--accent-blue);">Sending...</span>
        </div>
        <div id="replay-error" class="error-strip" style="display:none; margin-top:8px; border-radius:4px; border:none; height:auto; padding:10px;"></div>
      </div>
    </div>
  `;

  // Toggle custom endpoint input
  document.getElementById('replay-custom-toggle').addEventListener('change', (e) => {
    document.getElementById('replay-baseurl-input').style.display = e.target.checked ? 'block' : 'none';
    document.getElementById('replay-provider-select').disabled = e.target.checked;
  });

  document.getElementById('btn-submit-replay').addEventListener('click', () => submitReplay());
  document.getElementById('btn-retry-asis').addEventListener('click', () => submitReplay(true));

  // Model dropdown ↔ custom input visibility
  const updateReplayModelInputVisibility = () => {
    const selectEl = document.getElementById('replay-model-select');
    const inputEl = document.getElementById('replay-model-input');
    inputEl.style.display = selectEl.value === 'custom' ? 'block' : 'none';
  };

  document.getElementById('replay-provider-select').addEventListener('change', (e) => {
    const container = document.getElementById('replay-model-dropdown-container');
    container.innerHTML = renderModelDropdownHtml(e.target.value, 'replay-model-select');
    document.getElementById('replay-model-select').addEventListener('change', updateReplayModelInputVisibility);
    updateReplayModelInputVisibility();
  });

  document.getElementById('replay-model-select').addEventListener('change', updateReplayModelInputVisibility);
  updateReplayModelInputVisibility();
}

// Render the COMPARE tab contents and wire up all its event listeners.
// Depends on: _availableEnvProviders, renderModelDropdownHtml, esc (app.js), submitCompare.
function renderCompareTab() {
  const providerOpts = _availableEnvProviders.map(p => {
    const disabled = !p.available;
    const label = p.provider + (disabled ? " (No API key — add to .env)" : "");
    return `<option value="${p.provider}" ${disabled ? "disabled" : ""}>${label}</option>`;
  }).join('');

  els.tabContent.innerHTML += `
    <div class="replay-container">
      <p class="replay-text">Build a list of provider and model pairs to compare against this trace.</p>
      <div class="replay-form" style="display:flex; gap:8px; align-items:flex-end;">
        <div style="flex:1;">
           <label>Provider</label>
           <select id="compare-provider-select" style="width: 100%; padding: 6px; border-radius: 4px; border: 1px solid var(--border-color); background: var(--bg-tertiary); color: var(--text-main);">
              ${providerOpts}
           </select>
        </div>
        <div style="flex:2;">
           <label>Model</label>
           <div id="compare-model-dropdown-container">
             ${renderModelDropdownHtml(_availableEnvProviders.find(p => p.available)?.provider || 'openai', 'compare-model-select')}
           </div>
           <input type="text" id="compare-model-input" placeholder="e.g. custom-model-v2" style="display:none; margin-top:4px;" />
        </div>
        <button class="btn-secondary" id="btn-add-compare" style="height:34px;">Add</button>
      </div>

      <div id="compare-list" style="margin-top:16px; display:flex; flex-direction:column; gap:8px;"></div>

      <div style="display:flex; align-items:center; gap:12px; margin-top:16px;">
         <button class="btn-primary" id="btn-submit-compare" style="height:34px; padding:0 16px;" disabled>Compare</button>
         <span id="compare-status-text" class="replay-text" style="display:none; color:var(--accent-blue);">Sending...</span>
      </div>
      <div id="compare-error" class="error-strip" style="display:none; margin-top:8px; border-radius:4px; border:none; height:auto; padding:10px;"></div>

      <div id="compare-results-container" style="display:flex; gap:16px; overflow-x:auto; padding-top:16px;"></div>
    </div>
  `;

  window._compareCombinations = window._compareCombinations || [];

  const renderCompareList = () => {
    const listEl = document.getElementById('compare-list');
    listEl.innerHTML = window._compareCombinations.map((item, idx) => `
       <div style="display:flex; justify-content:space-between; background:var(--bg-tertiary); padding:6px 12px; border-radius:4px; border:1px solid var(--border-color);">
          <span><strong>${esc(item.provider)}</strong>: ${esc(item.model)}</span>
          <button onclick="removeCompareItem(${idx})" style="background:none; border:none; color:var(--accent-red); cursor:pointer;">&times;</button>
       </div>
    `).join('');
    document.getElementById('btn-submit-compare').disabled = window._compareCombinations.length < 1;
  };

  window.removeCompareItem = (idx) => {
    window._compareCombinations.splice(idx, 1);
    renderCompareList();
  };

  // Model dropdown ↔ custom input visibility
  const updateCompareModelInputVisibility = () => {
    const selectEl = document.getElementById('compare-model-select');
    const inputEl = document.getElementById('compare-model-input');
    inputEl.style.display = selectEl.value === 'custom' ? 'block' : 'none';
  };

  document.getElementById('compare-provider-select').addEventListener('change', (e) => {
    const container = document.getElementById('compare-model-dropdown-container');
    container.innerHTML = renderModelDropdownHtml(e.target.value, 'compare-model-select');
    document.getElementById('compare-model-select').addEventListener('change', updateCompareModelInputVisibility);
    updateCompareModelInputVisibility();
  });

  document.getElementById('compare-model-select').addEventListener('change', updateCompareModelInputVisibility);
  updateCompareModelInputVisibility();
  renderCompareList();

  document.getElementById('btn-add-compare').addEventListener('click', () => {
    const p = document.getElementById('compare-provider-select').value;
    const selectVal = document.getElementById('compare-model-select').value;
    const inputVal = document.getElementById('compare-model-input').value.trim();
    const m = selectVal === 'custom' ? inputVal : selectVal;

    if (!p || !m) return;
    if (window._compareCombinations.length >= 4) return alert("Maximum 4 models allowed for comparison.");
    window._compareCombinations.push({ provider: p, model: m });
    if (selectVal === 'custom') document.getElementById('compare-model-input').value = '';
    renderCompareList();
  });

  document.getElementById('btn-submit-compare').addEventListener('click', () => submitCompare());
}

// Submit a replay request to the backend.
// Depends on: _selectedTrace, els, apiReplay, apiFetchTrace, fetchData, esc (app.js).
async function submitReplay(asIs = false) {
  if (!_selectedTrace) return;

  const statusEl = document.getElementById('replay-status-text');
  const errEl = document.getElementById('replay-error');
  const btn = document.getElementById('btn-submit-replay');
  const asIsBtn = document.getElementById('btn-retry-asis');
  const compBtn = document.getElementById('btn-compare');

  if (btn) btn.disabled = true;
  if (asIsBtn) asIsBtn.disabled = true;
  if (compBtn) compBtn.disabled = true;
  if (statusEl) { statusEl.style.display = 'inline-block'; statusEl.textContent = 'Sending...'; }
  if (errEl) errEl.style.display = 'none';

  try {
    let payload = {};
    if (!asIs) {
      const selectVal = document.getElementById('replay-model-select').value;
      const inputVal = document.getElementById('replay-model-input').value.trim();
      const newModel = selectVal === 'custom' ? inputVal : selectVal;
      const newProvider = document.getElementById('replay-provider-select').value;
      const customToggle = document.getElementById('replay-custom-toggle').checked;
      const baseUrl = document.getElementById('replay-baseurl-input').value.trim();
      const newMsg = document.getElementById('replay-msg-input').value;
      const t = _selectedTrace;

      payload.model = newModel;
      payload.provider = newProvider;
      if (customToggle && baseUrl) {
        payload.base_url = baseUrl;
        payload.provider = 'openai';
      }

      const sourceProvider = t.provider;
      if (sourceProvider === 'openai' || sourceProvider === 'anthropic' || sourceProvider === 'deepseek') {
        const msgs = t.request_json?.messages ? JSON.parse(JSON.stringify(t.request_json.messages)) : [];
        const lastUser = [...msgs].reverse().find(m => m.role === 'user');
        if (lastUser) lastUser.content = newMsg;
        payload.messages = msgs;
      } else if (sourceProvider === 'gemini') {
        const contents = t.request_json?.contents ? JSON.parse(JSON.stringify(t.request_json.contents)) : [];
        const lastUser = [...contents].reverse().find(m => m.role === 'user');
        if (lastUser && lastUser.parts && lastUser.parts[0]) lastUser.parts[0].text = newMsg;
        payload.messages = contents;
      }
    }

    const result = await apiReplay(_selectedTrace.id, payload);
    if (statusEl) statusEl.textContent = 'Success! Fetching new trace...';

    if (result.new_trace_id) {
      const tr = await apiFetchTrace(result.new_trace_id);
      _lastReplayedTrace = tr;
      const tabBtn = Array.from(document.getElementById('detail-tabs').children).find(b => b.dataset.tab === 'DIFF');
      if (tabBtn) tabBtn.click();
      fetchData();
      return;
    }

    if (statusEl) statusEl.textContent = 'Done.';
    fetchData();
  } catch (err) {
    if (statusEl) statusEl.style.display = 'none';
    if (errEl) {
      errEl.style.display = 'flex';
      errEl.innerHTML = `<span style="color:#E8533A;font-weight:600;margin-right:8px;">Error:</span> ${esc(err.message)}`;
    }
  } finally {
    if (btn) btn.disabled = false;
    if (asIsBtn) asIsBtn.disabled = false;
    if (compBtn) compBtn.disabled = false;
  }
}

// Submit a multi-model comparison request.
// Depends on: _selectedTrace, _compareCombinations, els, apiCompare, apiFetchTrace, esc, extractTextFromResponse (app.js).
async function submitCompare() {
  if (!_selectedTrace) return;

  if (!window._compareCombinations || window._compareCombinations.length === 0) {
    alert("Please add at least one model to compare.");
    return;
  }

  const statusEl = document.getElementById('compare-status-text');
  const errEl = document.getElementById('compare-error');
  const resultsContainer = document.getElementById('compare-results-container');
  const btn = document.getElementById('btn-submit-compare');

  if (btn) btn.disabled = true;
  if (statusEl) { statusEl.style.display = 'inline-block'; statusEl.textContent = 'Comparing...'; }
  if (errEl) errEl.style.display = 'none';
  if (resultsContainer) resultsContainer.innerHTML = '';

  try {
    const results = await apiCompare(_selectedTrace.id, window._compareCombinations);
    if (statusEl) statusEl.textContent = 'Done.';

    let html = `
      <div style="flex:1; min-width:250px; background:var(--bg-secondary); border:1px solid var(--border-color); border-radius:6px; padding:12px;">
         <div style="font-weight:600; margin-bottom:8px;">Original (${esc(_selectedTrace.model)})</div>
         <div style="font-size:11px; font-family:var(--font-mono); white-space:pre-wrap; color:var(--text-medium); word-break: break-word;">
            ${esc(extractTextFromResponse(_selectedTrace) || JSON.stringify(_selectedTrace.response_json) || _selectedTrace.error_message || '')}
         </div>
      </div>
    `;

    for (let r of results) {
      let inner = '';
      if (r.success && r.new_trace_id) {
        try {
          const tr = await apiFetchTrace(r.new_trace_id);
          inner = esc(extractTextFromResponse(tr) || JSON.stringify(tr.response_json) || tr.error_message || '');
        } catch (e) { inner = 'Failed to load trace'; }
      } else {
        inner = `<span style="color:var(--accent-red);">${esc(r.error_message || 'Failed')}</span>`;
      }

      html += `
        <div style="flex:1; min-width:250px; background:var(--bg-primary); border:1px solid var(--border-color); border-radius:6px; padding:12px;">
           <div style="font-weight:600; margin-bottom:8px;">${esc(r.model)}</div>
           <div style="font-size:11px; font-family:var(--font-mono); white-space:pre-wrap; color:var(--text-medium); word-break: break-word;">
              ${inner}
           </div>
        </div>
      `;
    }

    if (resultsContainer) resultsContainer.innerHTML = html;
    fetchData();
  } catch (err) {
    if (statusEl) statusEl.style.display = 'none';
    if (errEl) {
      errEl.style.display = 'flex';
      errEl.innerHTML = `<span style="color:#E8533A;font-weight:600;margin-right:8px;">Error:</span> ${esc(err.message)}`;
    }
  } finally {
    if (btn) btn.disabled = false;
  }
}

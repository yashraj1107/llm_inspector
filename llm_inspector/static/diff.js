'use strict';

// diff.js — Word-level diff computation and multi-version diff UI rendering.

// Compute an LCS-based word diff between two strings.
// Returns an array of {type: 'same'|'added'|'removed', value: string}.
function computeWordDiff(str1, str2) {
  if (typeof str1 !== 'string') str1 = '';
  if (typeof str2 !== 'string') str2 = '';
  const words1 = str1.trim() ? str1.trim().split(/\s+/) : [];
  const words2 = str2.trim() ? str2.trim().split(/\s+/) : [];

  const n = words1.length;
  const m = words2.length;
  const dp = Array(n + 1).fill(null).map(() => Array(m + 1).fill(0));

  for (let i = 1; i <= n; i++) {
    for (let j = 1; j <= m; j++) {
      if (words1[i - 1] === words2[j - 1]) {
        dp[i][j] = dp[i - 1][j - 1] + 1;
      } else {
        dp[i][j] = Math.max(dp[i - 1][j], dp[i][j - 1]);
      }
    }
  }

  const segments = [];
  let i = n, j = m;
  while (i > 0 || j > 0) {
    if (i > 0 && j > 0 && words1[i - 1] === words2[j - 1]) {
      segments.unshift({ type: 'same', value: words1[i - 1] });
      i--; j--;
    } else if (j > 0 && (i === 0 || dp[i][j - 1] >= dp[i - 1][j])) {
      segments.unshift({ type: 'added', value: words2[j - 1] });
      j--;
    } else {
      segments.unshift({ type: 'removed', value: words1[i - 1] });
      i--;
    }
  }
  return segments;
}

// Render a two-column side-by-side diff with word-level highlights.
function renderTwoColumnDiff(origStr, newStr, isOrigOk, isNewOk) {
  const segs = computeWordDiff(origStr, newStr);

  let origHtml = '';
  let newHtml = '';

  segs.forEach(seg => {
    const val = esc(seg.value) + ' ';
    if (seg.type === 'same') {
      origHtml += val;
      newHtml += val;
    } else if (seg.type === 'removed') {
      origHtml += `<span class="diff-removed">${val}</span>`;
    } else if (seg.type === 'added') {
      newHtml += `<span class="diff-added">${val}</span>`;
    }
  });

  return `
    <div class="diff-container">
      <div class="diff-pane original">
        <div class="diff-pane-title">Original — ${isOrigOk ? 'Succeeded' : 'Failed'}</div>
        <div class="diff-content-wrapper">${origHtml || '(empty)'}</div>
      </div>
      <div class="diff-pane replay">
        <div class="diff-pane-title">Replay — ${isNewOk ? 'Succeeded' : 'Failed'}</div>
        <div class="diff-content-wrapper">${newHtml || '(empty)'}</div>
      </div>
    </div>
  `;
}

// Fetch and render the multi-version diff selector + results in the DIFF tab.
// Depends on: apiFetchTraceHistory (api.js), extractTextFromResponse, esc (app.js).
async function loadDiffHistory(trace) {
  const controlsEl = document.getElementById('diff-controls');
  const resultsEl = document.getElementById('diff-results');
  if (!controlsEl || !resultsEl) return;

  // Find root ID. If this trace has a parent, that's the root of the chain.
  const rootId = trace.parent_trace_id || trace.id;

  try {
    const history = await apiFetchTraceHistory(rootId);

    if (history.length <= 1) {
      controlsEl.innerHTML = `<div class="empty-msg">No other versions yet — replay this trace to compare.</div>`;
      return;
    }

    // Sort oldest first so v1 = original
    history.sort((a, b) => new Date(a.timestamp).getTime() - new Date(b.timestamp).getTime());

    let selectedIds = new Set();
    selectedIds.add(history[0].id);
    selectedIds.add(history[history.length - 1].id);

    const renderControls = () => {
      const limitReached = selectedIds.size >= 4;

      controlsEl.innerHTML = `
        <div style="margin-bottom:8px; font-weight:600; color:var(--text-main);">Select versions to compare (Max 4)</div>
        <div style="display:flex; flex-direction:column; gap:6px;">
          ${history.map(h => {
            const isChecked = selectedIds.has(h.id);
            const isDisabled = !isChecked && limitReached;
            const timeStr = new Date(h.timestamp).toLocaleString();
            return `
              <label style="display:flex; align-items:center; gap:8px; cursor:${isDisabled ? 'not-allowed' : 'pointer'}; opacity:${isDisabled ? 0.5 : 1};">
                <input type="checkbox" class="diff-version-cb" value="${h.id}" ${isChecked ? 'checked' : ''} ${isDisabled ? 'disabled' : ''}>
                <span style="font-family:var(--font-mono); font-size:12px;">${esc(h.model)}</span>
                <span style="color:var(--text-light); font-size:11px;">${timeStr}</span>
                ${h.status !== 'ok' && h.status !== 'succeeded' ? '<span style="color:var(--accent-red); font-size:11px;">(Failed)</span>' : ''}
              </label>
            `;
          }).join('')}
        </div>
      `;

      Array.from(controlsEl.querySelectorAll('.diff-version-cb')).forEach(cb => {
        cb.addEventListener('change', (e) => {
          if (e.target.checked) {
            if (selectedIds.size < 4) selectedIds.add(e.target.value);
          } else {
            selectedIds.delete(e.target.value);
          }
          renderControls();
          renderResults();
        });
      });
    };

    const renderResults = () => {
      if (selectedIds.size < 2) {
        resultsEl.innerHTML = `<div class="empty-msg">Select at least 2 versions to see a comparison.</div>`;
        return;
      }

      const selectedTraces = history.filter(h => selectedIds.has(h.id));

      if (selectedTraces.length === 2) {
        const t1 = selectedTraces[0];
        const t2 = selectedTraces[1];
        const txt1 = extractTextFromResponse(t1) || JSON.stringify(t1.response_json) || t1.error_message || '';
        const txt2 = extractTextFromResponse(t2) || JSON.stringify(t2.response_json) || t2.error_message || '';
        const ok1 = t1.status === 'succeeded' || t1.status === 'ok';
        const ok2 = t2.status === 'succeeded' || t2.status === 'ok';
        resultsEl.innerHTML = renderTwoColumnDiff(txt1, txt2, ok1, ok2);
      } else {
        // 3 or 4-way side-by-side columns
        let colsHtml = selectedTraces.map(t => {
          const txt = extractTextFromResponse(t) || JSON.stringify(t.response_json) || t.error_message || '';
          const isOk = t.status === 'succeeded' || t.status === 'ok';
          return `
            <div style="flex:1; min-width:200px; background:${isOk ? 'var(--bg-primary)' : 'var(--bg-secondary)'}; border:1px solid ${isOk ? 'var(--border-color)' : 'var(--accent-red)'}; border-radius:6px; padding:12px; display:flex; flex-direction:column; max-height: 600px;">
               <div style="font-weight:600; margin-bottom:4px; font-size:12px;">${esc(t.model)}</div>
               <div style="font-size:10px; color:var(--text-light); margin-bottom:8px;">${new Date(t.timestamp).toLocaleString()}</div>
               <div style="font-size:11px; font-family:var(--font-mono); white-space:pre-wrap; color:var(--text-medium); word-break: break-word; overflow-y:auto; flex:1;">
                  ${esc(txt)}
               </div>
            </div>
          `;
        }).join('');

        resultsEl.innerHTML = `
          <div style="display:flex; gap:12px; overflow-x:auto;">
             ${colsHtml}
          </div>
        `;
      }
    };

    renderControls();
    renderResults();

  } catch (err) {
    controlsEl.innerHTML = `<div class="empty-msg" style="color:var(--accent-red);">Error loading history: ${esc(err.message)}</div>`;
  }
}

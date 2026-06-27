'use strict';

// json-tree.js — Collapsible JSON tree rendering (vanilla JS, no dependencies).

function createJsonTree(obj) {
  const container = document.createElement('div');
  container.style.padding = '4px 0';

  if (typeof obj === 'object' && obj !== null) {
    Object.entries(obj).forEach(([k, v], idx, arr) => {
      container.appendChild(renderJsonNode(k, v, idx === arr.length - 1, 0));
    });
  } else {
    container.appendChild(renderJsonNode('root', obj, true, 0));
  }
  return container;
}

function renderJsonNode(label, value, isLast, depth) {
  const isObj = typeof value === 'object' && value !== null;
  const isArr = Array.isArray(value);

  const wrapper = document.createElement('div');
  wrapper.className = 'json-node';

  // Expand/collapse state — auto-open up to depth 2
  let isOpen = depth < 2;

  const row = document.createElement('div');
  row.className = `json-row ${isObj ? 'is-obj' : ''}`;

  const iconSpan = document.createElement('span');
  iconSpan.className = isObj ? 'json-toggle' : 'json-spacer';
  if (isObj) {
    iconSpan.innerHTML = isOpen ? getChevronDown() : getChevronRight();
  }

  const keySpan = document.createElement('span');
  keySpan.className = 'json-key';
  keySpan.textContent = label;

  const colonSpan = document.createElement('span');
  colonSpan.className = 'json-colon';
  colonSpan.textContent = ':';

  row.appendChild(iconSpan);
  row.appendChild(keySpan);
  row.appendChild(colonSpan);

  const valSpan = document.createElement('span');
  if (!isObj) {
    valSpan.className = `json-val-primitive ${typeof value === 'number' ? 'num' : (typeof value === 'boolean' ? 'bool' : '')}`;
    valSpan.textContent = typeof value === 'string' ? `"${value}"` : String(value);
    row.appendChild(valSpan);
    if (!isLast) {
      const comma = document.createElement('span');
      comma.className = 'json-val-comma';
      comma.textContent = ',';
      row.appendChild(comma);
    }
  } else {
    valSpan.className = `json-val-obj ${!isOpen ? 'collapsed' : ''}`;
    valSpan.innerHTML = isArr ? '[' : '{';
    if (!isOpen) {
      valSpan.innerHTML += `<span style="color:var(--text-light)"> ${isArr ? `${value.length} items` : '…'} ${isArr ? ']' : '}'}${!isLast ? ',' : ''}</span>`;
    }
    row.appendChild(valSpan);
  }

  wrapper.appendChild(row);

  const childrenDiv = document.createElement('div');
  childrenDiv.className = 'json-children';
  childrenDiv.style.display = isOpen ? 'block' : 'none';

  if (isObj) {
    const entries = Object.entries(value);
    entries.forEach(([k, v], idx) => {
      childrenDiv.appendChild(renderJsonNode(k, v, idx === entries.length - 1, depth + 1));
    });
    wrapper.appendChild(childrenDiv);

    const closeDiv = document.createElement('div');
    closeDiv.className = 'json-close';
    closeDiv.style.display = isOpen ? 'block' : 'none';
    closeDiv.innerHTML = `${isArr ? ']' : '}'}${!isLast ? '<span class="json-val-comma">,</span>' : ''}`;
    wrapper.appendChild(closeDiv);

    row.addEventListener('click', (e) => {
      e.stopPropagation();
      isOpen = !isOpen;
      iconSpan.innerHTML = isOpen ? getChevronDown() : getChevronRight();
      childrenDiv.style.display = isOpen ? 'block' : 'none';
      closeDiv.style.display = isOpen ? 'block' : 'none';

      valSpan.className = `json-val-obj ${!isOpen ? 'collapsed' : ''}`;
      valSpan.innerHTML = isArr ? '[' : '{';
      if (!isOpen) {
        valSpan.innerHTML += `<span style="color:var(--text-light)"> ${isArr ? `${value.length} items` : '…'} ${isArr ? ']' : '}'}${!isLast ? ',' : ''}</span>`;
      }
    });
  }

  return wrapper;
}

function getChevronDown() {
  return `<svg xmlns="http://www.w3.org/2000/svg" width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><polyline points="6 9 12 15 18 9"></polyline></svg>`;
}
function getChevronRight() {
  return `<svg xmlns="http://www.w3.org/2000/svg" width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><polyline points="9 18 15 12 9 6"></polyline></svg>`;
}

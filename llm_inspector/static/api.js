'use strict';

// api.js — All fetch() calls to the backend.
// No DOM manipulation here; functions return parsed JSON or throw on error.

async function apiFetchTraces(search = '') {
  let url = '/api/traces?limit=200';
  if (search) url += `&search=${encodeURIComponent(search)}`;
  const res = await fetch(url);
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return res.json();
}

async function apiFetchTrace(id) {
  const res = await fetch(`/api/traces/${encodeURIComponent(id)}`);
  if (!res.ok) throw new Error('Failed to fetch trace details');
  return res.json();
}

async function apiFetchTraceHistory(id) {
  const res = await fetch(`/api/traces/${encodeURIComponent(id)}/history`);
  if (!res.ok) throw new Error('Failed to fetch trace history');
  return res.json();
}

async function apiFetchAvailableProviders() {
  const res = await fetch('/api/providers/available');
  if (!res.ok) throw new Error('Failed to fetch providers');
  return res.json();
}

async function apiFetchCostStats() {
  const res = await fetch('/api/stats/cost');
  if (!res.ok) throw new Error('Failed to fetch cost stats');
  return res.json();
}

async function apiPinTrace(id) {
  return fetch(`/api/traces/${encodeURIComponent(id)}/pin`, { method: 'POST' });
}

async function apiSaveTags(id, tagsStr) {
  return fetch(`/api/traces/${encodeURIComponent(id)}/tags`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ tags: tagsStr })
  });
}

async function apiReplay(traceId, payload) {
  const res = await fetch(`/api/traces/${encodeURIComponent(traceId)}/replay`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload)
  });
  const result = await res.json();
  if (!res.ok || !result.success) throw new Error(result.detail || 'Replay failed');
  return result;
}

async function apiCompare(traceId, models) {
  const res = await fetch(`/api/traces/${encodeURIComponent(traceId)}/compare`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ models })
  });
  const result = await res.json();
  if (!res.ok) throw new Error(result.detail || 'Comparison request failed');
  return result;
}

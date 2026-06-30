const fs = require('fs');
const jsdom = require('jsdom');
const { JSDOM } = jsdom;
const html = fs.readFileSync('llm_inspector/static/index.html', 'utf-8');
const dom = new JSDOM(html, { url: 'http://localhost/', runScripts: "dangerously" });
global.document = dom.window.document;
global.window = dom.window;

// Mock globals
dom.window.fetch = async () => ({ ok: true, json: async () => ([]) });

// Simulate DOMContentLoaded
dom.window.document.dispatchEvent(new dom.window.Event('DOMContentLoaded'));


// Simulate DOMContentLoaded
dom.window.document.dispatchEvent(new dom.window.Event('DOMContentLoaded'));

// Find Settings button
const btn = dom.window.document.querySelector('button[data-tab="Settings"]');
console.log('Settings button:', !!btn);
if (btn) {
  btn.click();
  console.log('Clicked!');
  console.log('settings-panel display:', dom.window.document.getElementById('settings-panel').style.display);
  console.log('sidebar display:', dom.window.document.getElementById('filter-sidebar').style.display);
}

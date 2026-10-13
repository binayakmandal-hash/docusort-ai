/* DocuSort: shared helpers. */
(function () {
  'use strict';
  const DS = (window.DS = {});

  DS.el = function (tag, attrs, ...kids) {
    const n = document.createElement(tag);
    for (const [k, v] of Object.entries(attrs || {})) {
      if (v === null || v === undefined || v === false) continue;
      if (k === 'class') n.className = v;
      else if (k === 'text') n.textContent = v;
      else if (k === 'style') for (const [p, val] of Object.entries(v)) n.style.setProperty(p, val);
      else if (k.startsWith('on') && typeof v === 'function') n.addEventListener(k.slice(2), v);
      else n.setAttribute(k, v === true ? '' : v);
    }
    for (const kid of kids.flat(Infinity)) {
      if (kid === null || kid === undefined || kid === false) continue;
      n.appendChild(kid instanceof Node ? kid : document.createTextNode(String(kid)));
    }
    return n;
  };

  DS.api = async function (url, options) {
    let res;
    try { res = await fetch(url, options); } catch (e) { throw new Error('Could not reach the DocuSort server.'); }
    let data;
    try { data = await res.json(); } catch (e) { data = { ok: false, error: `Server error (${res.status}).` }; }
    if (!res.ok || data.ok === false) throw new Error(data.error || `Request failed (${res.status}).`);
    return data;
  };

  DS.reducedMotion = () => window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  DS.store = {
    get(k) { try { return localStorage.getItem(k); } catch (e) { return null; } },
    set(k, v) { try { localStorage.setItem(k, v); } catch (e) { /* storage blocked */ } },
  };

  const root = document.documentElement;
  const btn = document.getElementById('theme');
  if (btn) {
    btn.addEventListener('click', () => {
      const dark = root.dataset.theme ? root.dataset.theme === 'dark' : window.matchMedia('(prefers-color-scheme: dark)').matches;
      root.dataset.theme = dark ? 'light' : 'dark';
      DS.store.set('ds-theme', root.dataset.theme);
    });
  }
})();

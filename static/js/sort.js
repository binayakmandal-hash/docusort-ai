/* Sorting desk: upload, watch each file land in its tray, open one to see why. */
(function () {
  'use strict';
  const { el } = DS;
  const $ = (id) => document.getElementById(id);
  const LABELS = window.DS_LABELS || {};
  const SAMPLES = ['distributor-agreement.txt', 'email-meeting.txt', 'invoice.pdf', 'receipt-scan.jpg', 'resume-arjun-mehta.docx'];
  let current = { batch: null, docs: [] };

  const color = (label) => `var(--t-${label || 'unsure'})`;
  const pct = (p) => `${Math.round(p * 100)}%`;

  function showError(msg) { $('error').textContent = msg || ''; $('error').hidden = !msg; }

  function tag(text, label, delay) {
    return el('span', { class: 'tag is-printing', style: { '--c': color(label), '--d': `${delay || 0}s` }, text });
  }

  // ---------------------------------------------------------------- input
  const drop = $('drop');
  $('files').addEventListener('change', () => { if ($('files').files.length) send([...$('files').files]); $('files').value = ''; });
  ['dragenter', 'dragover'].forEach((ev) => drop.addEventListener(ev, (e) => { e.preventDefault(); drop.classList.add('is-over'); }));
  ['dragleave', 'drop'].forEach((ev) => drop.addEventListener(ev, (e) => { e.preventDefault(); drop.classList.remove('is-over'); }));
  drop.addEventListener('drop', (e) => { if (e.dataTransfer.files.length) send([...e.dataTransfer.files]); });

  $('sample').addEventListener('click', async () => {
    const btn = $('sample');
    btn.disabled = true;
    try {
      const files = await Promise.all(SAMPLES.map(async (name) => {
        const blob = await (await fetch(`/samples/${name}`)).blob();
        return new File([blob], name, { type: blob.type });
      }));
      await send(files);
    } catch (e) { showError(e.message); } finally { btn.disabled = false; }
  });

  $('paste-go').addEventListener('click', async () => {
    const text = $('pasted').value.trim();
    if (!text) return showError('Paste some text first.');
    showError(null);
    try {
      const data = await DS.api('/api/sort', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ text }) });
      render(data);
    } catch (e) { showError(e.message); }
  });

  async function send(files) {
    showError(null);
    if (files.length > 50) return showError('Sort up to 50 files at a time.');
    const fd = new FormData();
    files.forEach((f) => fd.append('files', f, f.name));
    $('sorted').hidden = false;
    $('detail-wrap').hidden = true;
    $('zip-actions').hidden = true;
    $('sorted-title').textContent = `Reading ${files.length} file${files.length > 1 ? 's' : ''}…`;
    $('trays').replaceChildren(el('div', { class: 'reading' }, files.map((f) => el('div', { class: 'reading__row', text: f.name }))));
    try {
      render(await DS.api('/api/sort', { method: 'POST', body: fd }));
    } catch (e) {
      $('sorted').hidden = true;
      showError(e.message);
    }
  }

  // ---------------------------------------------------------------- trays
  function render(data) {
    current = { batch: data.batch, docs: data.documents };
    const docs = data.documents;
    const ok = docs.filter((d) => d.ok);
    $('sorted').hidden = false;
    $('sorted-title').textContent = docs.length === 1 ? 'Sorted' : `Sorted ${ok.length} of ${docs.length} files into ${new Set(ok.map(groupOf)).size} trays`;
    $('zip-actions').hidden = !data.batch;
    updateZip();

    const groups = new Map();
    docs.forEach((d, i) => { const g = d.ok ? groupOf(d) : 'error'; if (!groups.has(g)) groups.set(g, []); groups.get(g).push([d, i]); });
    const order = [...groups.keys()].sort((a, b) => (a === 'error') - (b === 'error') || (a === 'unsure') - (b === 'unsure') || String(LABELS[a] || a).localeCompare(LABELS[b] || b));
    const trays = order.map((g, ti) => {
      const name = g === 'error' ? "Couldn't read" : g === 'unsure' ? 'Not sure' : LABELS[g];
      const list = el('div', { class: 'tray__docs' });
      groups.get(g).forEach(([d, i], k) => list.appendChild(card(d, i, 0.25 + ti * 0.08 + k * 0.06)));
      return el('section', { class: 'tray', style: { '--tray': color(g === 'error' ? null : g === 'unsure' ? null : g) } },
        el('div', { class: 'tray__head' }, tag(name, g === 'error' || g === 'unsure' ? null : g, ti * 0.08), el('span', { class: 'tray__count', text: groups.get(g).length })),
        list);
    });
    $('trays').replaceChildren(...trays);
    fly();
    if (docs.length === 1 && docs[0].ok) open(0);
  }

  function groupOf(d) { return d.sure ? d.label : 'unsure'; }

  function card(d, i, delay) {
    if (!d.ok) {
      return el('div', { class: 'doc doc--error' }, el('span', { class: 'doc__name', text: d.file }),
        el('span', { class: 'doc__meta', text: d.error }));
    }
    const pii = d.sensitive.summary.reduce((n, s) => n + s.count, 0);
    return el('button', { class: 'doc', type: 'button', 'data-i': i, onclick: () => open(i), style: { '--d': `${delay}s` } },
      el('span', { class: 'doc__name', text: d.file }),
      el('span', { class: 'doc__pct', text: pct(d.confidence) }),
      el('span', { class: 'doc__bar', 'aria-hidden': 'true' }, el('i', { style: { width: pct(d.confidence) } })),
      el('span', { class: 'doc__meta' },
        el('span', { text: d.ocr ? 'read with OCR' : d.kind.toUpperCase() }),
        pii ? el('span', { class: 'pii-badge', text: `${pii} personal number${pii > 1 ? 's' : ''}` }) : null));
  }

  // Each card starts where the drop tray is and glides into its own tray.
  function fly() {
    if (DS.reducedMotion()) return;
    const from = drop.getBoundingClientRect();
    document.querySelectorAll('#trays .doc').forEach((node, k) => {
      const to = node.getBoundingClientRect();
      const dx = from.left + from.width / 2 - (to.left + to.width / 2);
      const dy = from.top + from.height / 2 - (to.top + to.height / 2);
      node.classList.add('is-flying');
      const anim = node.animate([
        { transform: `translate(${dx}px, ${dy}px) scale(.6) rotate(-4deg)`, opacity: 0 },
        { opacity: 1, offset: 0.25 },
        { transform: 'translate(0, 0) scale(1) rotate(0)', opacity: 1 },
      ], { duration: 650, delay: 80 + k * 90, easing: 'cubic-bezier(.2,.8,.2,1)', fill: 'backwards' });
      anim.onfinish = () => node.classList.remove('is-flying');
    });
  }

  function updateZip() {
    if (current.batch) $('zip').href = `/api/batch/${current.batch}.zip${$('with-redacted').checked ? '?redacted=1' : ''}`;
  }
  $('with-redacted').addEventListener('change', updateZip);

  // ---------------------------------------------------------------- detail
  function open(i) {
    const d = current.docs[i];
    document.querySelectorAll('#trays .doc').forEach((n) => n.classList.toggle('is-open', Number(n.dataset.i) === i));
    const box = $('detail');
    box.replaceChildren(
      el('header', { class: 'detail__head' },
        el('div', null,
          el('p', { class: 'detail__file', text: `${d.file} · ${d.words.toLocaleString()} words${d.ocr ? ' · read with OCR' : ''}` }),
          tag(d.sure ? LABELS[d.label] : 'Not sure', d.sure ? d.label : null, 0.1),
          el('h2', { class: 'detail__type', text: d.sure ? `This looks like a ${LABELS[d.label].toLowerCase()}.` : `Not sure. Closest: ${LABELS[d.label].toLowerCase()}.` })),
        el('div', { class: 'detail__conf' },
          el('div', { class: 'detail__pct', 'data-count': Math.round(d.confidence * 100), text: '0%' }),
          el('p', { class: 'detail__note' }, d.sure ? `Next closest: ${d.runner_up.name.toLowerCase()} (${pct(d.runner_up.probability)}).`
            : el('span', { class: 'unsure', text: 'Below 50% confidence, so it goes in the "Not sure" folder.' })))),
      el('div', { class: 'detail__body' },
        el('div', { class: 'detail__col' },
          section('Words that decided it', words(d)),
          section('All types', el('div', { class: 'probs' }, d.probabilities.map((p, k) =>
            el('div', { class: 'prob' }, el('span', { text: p.name }),
              el('span', { class: 'prob__bar' }, el('i', { style: { width: pct(p.probability), '--c': color(p.label), '--d': `${0.1 + k * 0.05}s` } })),
              el('span', { class: 'prob__pct', text: pct(p.probability) }))))),
          section(`Key details for a ${LABELS[d.label].toLowerCase()}`, fieldsList(d))),
        el('div', { class: 'detail__col' },
          section('Personal numbers', piiBlock(d)))));
    $('detail-wrap').hidden = false;
    countUp(box.querySelector('[data-count]'));
    $('detail-wrap').scrollIntoView({ behavior: DS.reducedMotion() ? 'auto' : 'smooth', block: 'start' });
  }

  function section(title, body) { return el('section', null, el('h3', { text: title }), body); }

  function words(d) {
    const pro = d.explanation.for;
    if (!pro.length) return el('p', { class: 'clean', text: 'No single words stood out; the decision came from the overall style of the text.' });
    return el('div', null,
      el('div', { class: 'why', style: { '--c': color(d.label) } }, pro.map((t, k) => el('span', { style: { '--d': `${0.15 + k * 0.05}s` }, text: t.term }))),
      d.explanation.against.length ? el('p', { class: 'hint', style: { marginTop: '10px' } }, `Pointing towards ${d.runner_up.name.toLowerCase()} instead: `,
        d.explanation.against.map((t) => t.term).join(', '), '.') : null);
  }

  function fieldsList(d) {
    if (!d.fields.length) return el('p', { class: 'clean', text: 'No fixed details are extracted for this type.' });
    return el('dl', { class: 'fields' }, d.fields.map((f, k) => [
      el('dt', { text: f.name }),
      f.value ? el('dd', { style: { '--d': `${0.2 + k * 0.06}s` }, title: f.source || '', text: f.value })
        : el('dd', { class: 'is-empty', text: 'not found' })]));
  }

  function piiBlock(d) {
    const items = d.sensitive.items;
    const pre = el('pre', { class: 'page-text' });
    let last = 0;
    const shown = d.preview.length;
    items.filter((it) => it.end <= shown).forEach((it, k) => {
      pre.append(d.preview.slice(last, it.start), el('mark', { title: it.name, style: { '--d': `${k * 0.08}s` }, text: d.preview.slice(it.start, it.end) }));
      last = it.end;
    });
    pre.append(d.preview.slice(last) + (d.words > 0 && d.preview.length >= 4000 ? '\n…' : ''));
    if (!items.length) {
      return el('div', null, el('p', { class: 'clean', text: 'No Aadhaar, PAN, card, bank, phone, email, UPI, passport or voter ID numbers found.' }),
        el('h3', { text: 'Text read from the file', style: { marginTop: '18px' } }), pre);
    }
    const btn = el('button', { class: 'btn btn--signal', type: 'button' }, 'Black out and download a redacted copy');
    btn.addEventListener('click', async () => {
      pre.classList.add('is-redacted');
      const res = await fetch('/api/redact', { method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ text: d.text, name: d.file }) });
      const blob = await res.blob();
      const a = el('a', { href: URL.createObjectURL(blob), download: `${d.file.replace(/\.[^.]+$/, '')} (redacted).txt` });
      setTimeout(() => { document.body.appendChild(a); a.click(); a.remove(); }, DS.reducedMotion() ? 0 : 500 + items.length * 80);
    });
    return el('div', null,
      el('ul', { class: 'pii-list' }, d.sensitive.summary.map((s) =>
        el('li', null, el('strong', { text: `${s.name}${s.count > 1 ? ` × ${s.count}` : ''}` }), el('span', { text: s.why })))),
      el('div', { class: 'redact-row' }, btn, el('span', { class: 'hint', text: 'Keeps the last 4 digits so you can still tell which number it was.' })),
      el('h3', { text: 'Where they are', style: { marginTop: '18px' } }), pre);
  }

  function countUp(node) {
    const target = Number(node.dataset.count);
    if (DS.reducedMotion()) { node.textContent = `${target}%`; return; }
    const t0 = performance.now();
    const step = (t) => {
      const k = Math.min(1, (t - t0) / 700);
      node.textContent = `${Math.round(target * (1 - Math.pow(1 - k, 3)))}%`;
      if (k < 1) requestAnimationFrame(step);
    };
    requestAnimationFrame(step);
  }
})();

// RC Color Pilot — the page. Talks to server.py; every edit to the classifier is
// pushed to the Pi a few times a second, so the segmentation map repaints while you drag.

const $ = (s, r = document) => r.querySelector(s);
const $$ = (s, r = document) => [...r.querySelectorAll(s)];

const KEYS = { F: 'forward', B: 'backward', L: 'left', R: 'right', G: 'front-left', I: 'front-right', H: 'back-left', J: 'back-right', S: 'stop' };
const ACTION_TYPES = [['key', 'Car key'], ['line', 'Serial line'], ['arm', 'Arm Twin pose'], ['none', 'Nothing']];

const app = { cfg: null, st: null, sel: null, sample: null, arm: { available: false, poses: [] }, editedAt: 0, only: '', context: true };

// ---------------------------------------------------------------- plumbing

async function api(path, body) {
  const r = await fetch(path, body === undefined ? {} : { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
  const d = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(d.error || `${r.status} ${r.statusText}`);
  return d;
}
let toastTimer;
function toast(msg) {
  const t = $('#toast');
  t.textContent = msg;
  t.hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { t.hidden = true; }, 3600);
}
const store = {
  get(k, d) { try { const v = localStorage.getItem(`rcpilot.${k}`); return v === null ? d : JSON.parse(v); } catch { return d; } },
  set(k, v) { try { localStorage.setItem(`rcpilot.${k}`, JSON.stringify(v)); } catch { /* private window */ } },
};
const esc = (s) => String(s).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));

// ---------------------------------------------------------------- color math (OpenCV HSV: H 0-179, S/V 0-255)

function hsvCss(h, s, v) {
  const H = (h * 2) / 60, S = s / 255, V = v / 255, C = V * S, X = C * (1 - Math.abs((H % 2) - 1)), m = V - C;
  const [r, g, b] = H < 1 ? [C, X, 0] : H < 2 ? [X, C, 0] : H < 3 ? [0, C, X] : H < 4 ? [0, X, C] : H < 5 ? [X, 0, C] : [C, 0, X];
  return `rgb(${Math.round((r + m) * 255)} ${Math.round((g + m) * 255)} ${Math.round((b + m) * 255)})`;
}
function hexHsv(hex) {
  const r = parseInt(hex.slice(1, 3), 16) / 255, g = parseInt(hex.slice(3, 5), 16) / 255, b = parseInt(hex.slice(5, 7), 16) / 255;
  const max = Math.max(r, g, b), d = max - Math.min(r, g, b);
  let h = 0;
  if (d) h = max === r ? ((g - b) / d) % 6 : max === g ? (b - r) / d + 2 : (r - g) / d + 4;
  return [Math.round(((h * 60 + 360) % 360) / 2) % 180, Math.round(max ? (d / max) * 255 : 0), Math.round(max * 255)];
}
function rgbHex(css) {
  const m = css.match(/\d+/g).map(Number);
  return `#${m.slice(0, 3).map((x) => x.toString(16).padStart(2, '0')).join('')}`;
}
const inkOn = (hex) => {
  const c = [1, 3, 5].map((i) => parseInt(hex.slice(i, i + 2), 16) / 255).map((x) => (x <= 0.04 ? x / 12.92 : ((x + 0.055) / 1.055) ** 2.4));
  return 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2] > 0.36 ? '#111316' : '#ffffff';
};
const hueIn = (h, [lo, hi]) => (lo <= hi ? h >= lo && h <= hi : h >= lo || h <= hi);
const hueMid = ([lo, hi]) => (lo <= hi ? (lo + hi) / 2 : ((lo + hi + 180) / 2) % 180);
const wrapH = (h) => ((Math.round(h) % 180) + 180) % 180;
const range2 = (a) => (a[0] === 0 && a[1] === 255 ? 'any' : a[1] === 255 ? `≥${a[0]}` : `${a[0]}–${a[1]}`);
const hueText = ([lo, hi]) => (lo <= hi ? `${lo}–${hi}` : `${lo}→${hi}`);
const hsvShort = (c) => `H${hueText(c.h)} S${range2(c.s)} V${range2(c.v)}`;

function describe(a) {
  if (!a || a.type === 'none') return { main: '—', word: 'nothing', kind: 'text' };
  if (a.type === 'key') return { main: a.key, word: KEYS[a.key], kind: 'key' };
  if (a.type === 'line') return { main: a.text, word: 'serial line', kind: 'text' };
  return { main: 'ARM', word: a.name || a.pose, kind: 'key' };
}
const actionShort = (a) => (a.type === 'key' ? `${a.key} · ${KEYS[a.key]}` : a.type === 'line' ? a.text : a.type === 'arm' ? `arm → ${a.name}` : 'nothing');

// ---------------------------------------------------------------- config sync

let pushTimer = null, pushBusy = false, pushAgain = false;
function edited(rebuild = true) {
  app.editedAt = performance.now();
  if (rebuild) { renderChips(); renderOnly(); }
  renderWheel();
  renderCoverage();
  clearTimeout(pushTimer);
  pushTimer = setTimeout(push, 110);
}
async function push() {
  if (pushBusy) { pushAgain = true; return; }
  pushBusy = true;
  try {
    const r = await api('/api/config', { config: app.cfg });
    if (performance.now() - app.editedAt > 600) app.cfg = r.config;
  } catch (e) { toast(`Not saved: ${e.message}`); }
  pushBusy = false;
  if (pushAgain) { pushAgain = false; push(); }
}
const cls = (id) => app.cfg?.classes.find((c) => c.id === id);
const selected = () => cls(app.sel);

// ---------------------------------------------------------------- streams

function streamUrl(view) {
  if (view === 'camera') return '/stream?view=camera';
  return `/stream?view=mask&context=${app.context ? 1 : 0}${app.only ? `&only=${encodeURIComponent(app.only)}` : ''}`;
}
function setStreams(on) {
  const cam = $('#img-cam'), mask = $('#img-mask');
  if (!on) { cam.removeAttribute('src'); mask.removeAttribute('src'); return; }
  if (cam.getAttribute('src') !== streamUrl('camera')) cam.src = streamUrl('camera');
  if (mask.getAttribute('src') !== streamUrl('mask')) mask.src = streamUrl('mask');
}
for (const img of [$('#img-cam'), $('#img-mask')]) {
  img.addEventListener('error', () => setTimeout(() => { if (!document.hidden) { img.removeAttribute('src'); setStreams(true); } }, 2000));
}
document.addEventListener('visibilitychange', () => setStreams(!document.hidden));

// ---------------------------------------------------------------- one pilot at a time
// Opening this page, or coming back to its tab, wakes it and puts the other
// pilots (:8082, :8083) to sleep. A page another pilot put to sleep shows the veil.

let waking = null;
function wake() {
  if (!waking) {
    waking = api('/api/wake', {}).catch((e) => toast(`Could not wake: ${e.message}`)).finally(() => { waking = null; });
  }
  return waking;
}
document.addEventListener('visibilitychange', () => { if (!document.hidden && app.cfg) wake(); });
$('#wake-btn').addEventListener('click', () => wake());

function renderAsleep(st) {
  const asleep = !!st.asleep && !waking;
  $('#asleep').hidden = !asleep;
  if (asleep) {
    const why = st.asleep_why || 'another pilot was opened';
    $('#asleep-why').textContent = `${why.charAt(0).toUpperCase()}${why.slice(1)}.`;
  }
}

// ---------------------------------------------------------------- status loop

async function poll() {
  if (!document.hidden) {
    try {
      app.st = await api('/api/status');
      renderLive();
    } catch {
      $('#cam-text').textContent = 'Pi not answering';
      $('#lamp-cam').dataset.tone = 'bad';
    }
  }
  setTimeout(poll, 250);
}

function renderLive() {
  const st = app.st;
  if (!st || !app.cfg) return;
  renderAsleep(st);
  // health lamps
  const src = st.source;
  $('#lamp-cam').dataset.tone = src.error ? 'bad' : st.fps >= 4 ? 'ok' : 'warn';
  $('#cam-text').textContent = src.error ? 'No camera' : `${src.kind === 'testcard' ? 'Test card' : 'Camera'} · ${st.fps} fps`;
  $('#lamp-cam').title = src.error || src.name;
  const L = st.link, peer = st.peer || {};
  const withPeer = peer.up && peer.state === 'ready';
  $('#lamp-car').dataset.tone = L.state === 'ready' ? 'ok' : L.state === 'searching' ? 'warn' : 'off';
  $('#car-text').textContent = L.state === 'ready' ? `Car · ${L.port}` : L.state === 'searching' ? 'Car · looking…'
    : withPeer ? 'Car · with Zan Gesture-Car' : 'Car · free';
  $('#lamp-car').title = L.detail;
  const carBtn = $('#car-btn');
  carBtn.textContent = L.state === 'off' ? 'Take the car' : L.state === 'ready' ? 'Release the car' : 'Stop looking';
  carBtn.dataset.take = String(L.state === 'off');
  carBtn.title = L.state === 'off'
    ? (withPeer ? 'Asks the Gesture Pilot (:8083) to let go, then connects here' : 'Connect to ZAN_RC_Car over Bluetooth')
    : 'Let go of the car: it is then free for this page or the Gesture Pilot';
  $('#msg-cam').hidden = !src.error;
  $('#msg-cam').textContent = src.error ? `No picture: ${src.error}` : '';
  $$('#source button').forEach((b) => b.setAttribute('aria-pressed', String(b.dataset.source === src.kind)));

  // camera picker: shown when more than one camera answers
  const pick = $('#camera-pick');
  const cams = src.cameras || [];
  pick.hidden = cams.length < 2;
  if (!pick.hidden) {
    const val = src.camera_id || 'auto';
    const sig = `${val}|${cams.map((c) => `${c.id}:${c.name}`).join(',')}`;
    if (pick.dataset.sig !== sig) {
      pick.dataset.sig = sig;
      pick.innerHTML = `<option value="auto">Auto</option>` +
        cams.map((c) => `<option value="${c.id}" title="${c.name}">${c.name}</option>`).join('');
      pick.value = val;
    } else if (document.activeElement !== pick) pick.value = val;
  }

  // output switch
  const out = $('#output');
  out.setAttribute('aria-checked', String(st.output));
  out.toggleAttribute('data-warn', st.output && L.state !== 'ready');
  $('#output-state').textContent = st.output ? 'Live' : 'Dry run';
  $('#output-sub').textContent = !st.output ? 'nothing is sent' : L.state === 'ready' ? `to ${L.port}` : 'no car found';

  // act: the signal card
  const manual = st.mode === 'manual';
  const act = st.active ? cls(st.active) : null;
  const action = manual ? { type: 'key', key: st.held || 'S' } : act ? act.action : app.cfg.nothing;
  const d = describe(action);
  const sig = $('#signal');
  const color = !manual && act ? act.color : null;
  sig.style.setProperty('--sig', color || 'var(--well)');
  sig.style.setProperty('--on', color ? inkOn(color) : 'var(--ink)');
  sig.toggleAttribute('data-live', !!color);
  sig.dataset.kind = d.kind;
  $('#sig-main').textContent = d.main;
  $('#sig-word').textContent = d.word;

  const win = st.winner ? cls(st.winner) : null;
  let verdict;
  if (manual) verdict = st.held ? `You are holding <b>${st.held}</b> · ${KEYS[st.held]}` : 'You drive: hold a button below';
  else if (win && st.active === st.winner) verdict = `<b>${esc(win.name)}</b> is in view and has held ${st.hold} frames`;
  else if (win) verdict = `<b>${esc(win.name)}</b> is winning: ${Math.min(st.streak, st.hold)} of ${st.hold} frames`;
  else verdict = st.active ? 'Color gone: counting frames…' : 'Nothing big enough in view';
  $('#verdict').innerHTML = verdict;

  const hold = $('#hold');
  if (hold.childElementCount !== st.hold) hold.innerHTML = '<i></i>'.repeat(st.hold);
  const filled = manual ? 0 : Math.min(st.streak, st.hold);
  [...hold.children].forEach((el, i) => {
    el.classList.toggle('on', i < filled);
    el.style.background = i < filled ? (win ? win.color : 'var(--ink-3)') : '';
  });

  const what = action.type === 'key' ? `${action.key}` : action.type === 'line' ? action.text : null;
  let wire;
  if (action.type === 'arm') wire = st.output ? `Asks the Arm Twin to move to <b>${esc(action.name)}</b>` : `Dry run: would move the arm to <b>${esc(action.name)}</b>`;
  else if (!what) wire = 'No action';
  else if (!st.output) wire = `Dry run: would send <b>${esc(what)}</b> every 0.25 s`;
  else if (L.state === 'ready') wire = `Sending <b>${esc(what)}</b> to ${L.port} every 0.25 s`;
  else wire = 'Output is live, but the car is not connected';
  $('#wire').innerHTML = wire;

  // mode, pad, speed
  $$('#mode button').forEach((b) => b.setAttribute('aria-pressed', String(b.dataset.mode === st.mode)));
  $$('#pad button').forEach((b) => { b.disabled = !manual; });
  if (document.activeElement !== $('#speed')) $('#speed').value = st.speed;
  $('#speed-out').textContent = st.speed;

  // events
  const ev = $('#events');
  const sig2 = st.events.map((e) => e.t + e.text).join('|');
  if (ev.dataset.sig !== sig2) {
    ev.dataset.sig = sig2;
    ev.innerHTML = st.events.slice(0, 9).map((e) =>
      `<li><time>${e.t}</time><span>${esc(e.text)}</span><span class="tag ${e.tag}">${e.tag}</span></li>`).join('');
  }
  updateChipStats();
  renderCoverage();
}

// ---------------------------------------------------------------- coverage legend + "only" picker

function renderCoverage() {
  const ul = $('#coverage');
  if (!app.cfg) return;
  const stats = Object.fromEntries((app.st?.stats || []).map((s) => [s.id, s]));
  ul.innerHTML = app.cfg.classes.map((c) => {
    const pct = stats[c.id] ? (stats[c.id].coverage * 100).toFixed(1) : '0.0';
    return `<li class="${c.on ? '' : 'off'}"><i style="background:${c.color}"></i>${esc(c.name)} <b>${pct}%</b></li>`;
  }).join('');
}
function renderOnly() {
  const s = $('#only');
  const want = app.only;
  s.innerHTML = '<option value="">All colors</option>' + app.cfg.classes.map((c) => `<option value="${c.id}">Only ${esc(c.name)}</option>`).join('');
  s.value = cls(want) ? want : '';
  if (s.value !== want) { app.only = s.value; setStreams(true); }
}

// ---------------------------------------------------------------- chips

function renderChips() {
  const ul = $('#chips');
  ul.innerHTML = '';
  app.cfg.classes.forEach((c) => {
    const li = document.createElement('li');
    li.className = `chip${c.on ? '' : ' off'}`;
    li.dataset.id = c.id;
    li.setAttribute('role', 'option');
    li.setAttribute('aria-selected', String(c.id === app.sel));
    li.tabIndex = 0;
    li.style.setProperty('--c', c.color);
    li.style.setProperty('--on', inkOn(c.color));
    const d = describe(c.action);
    li.innerHTML = `<div class="chip-face"><span class="chip-tag" hidden></span><span class="chip-key">${esc(d.kind === 'key' ? d.main : '·')}</span></div>
      <div class="chip-body"><div class="chip-name"><span>${esc(c.name)}</span><input type="checkbox" ${c.on ? 'checked' : ''} aria-label="Use ${esc(c.name)}" title="Use this color"></div>
      <div class="chip-hsv">${hsvShort(c)}</div>
      <div class="chip-act">→ ${esc(actionShort(c.action))}</div>
      <div class="chip-meter"><span><i></i></span><b>0%</b></div></div>`;
    li.addEventListener('click', (e) => {
      if (e.target.matches('input')) return;
      select(c.id);
    });
    li.addEventListener('keydown', (e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); select(c.id); } });
    $('input', li).addEventListener('change', (e) => { c.on = e.target.checked; edited(); renderEditor(); });
    ul.appendChild(li);
  });
  const add = document.createElement('li');
  add.className = 'chip add';
  add.tabIndex = 0;
  add.textContent = '+ Add a color';
  add.addEventListener('click', () => addClass());
  ul.appendChild(add);
  updateChipStats();
}

function updateChipStats() {
  const st = app.st;
  if (!st) return;
  const stats = Object.fromEntries(st.stats.map((s) => [s.id, s]));
  for (const li of $$('#chips .chip[data-id]')) {
    const s = stats[li.dataset.id], c = cls(li.dataset.id);
    if (!c) continue;
    const pct = s ? s.coverage * 100 : 0;
    $('.chip-meter i', li).style.width = `${Math.min(100, pct * 4)}%`;
    $('.chip-meter b', li).textContent = `${pct.toFixed(1)}%`;
    const acting = st.mode === 'auto' && st.active === c.id;
    const winning = st.winner === c.id && !acting;
    const small = s && s.area > 0 && s.area < app.cfg.min_area;
    li.classList.toggle('acting', acting);
    const tag = $('.chip-tag', li);
    tag.hidden = !(acting || winning || small);
    tag.textContent = acting ? 'Acting' : winning ? 'Winning' : 'Too small';
  }
}

function select(id) {
  app.sel = id;
  store.set('sel', id);
  $$('#chips .chip[data-id]').forEach((li) => li.setAttribute('aria-selected', String(li.dataset.id === id)));
  renderWheel();
  renderEditor();
  renderSampler();
}

function newId() { return `c${Date.now().toString(36).slice(-5)}`; }
function addClass(fromSample) {
  if (app.cfg.classes.length >= 10) { toast('Ten colors is the limit — remove one first'); return; }
  const n = app.cfg.classes.length + 1;
  let c;
  if (fromSample) {
    const { h, s, v, rgb } = fromSample;
    c = { id: newId(), name: `Color ${n}`, h: [wrapH(h - 8), wrapH(h + 8)], s: [Math.max(40, s - 70), 255], v: [Math.max(40, v - 80), 255],
          color: rgb, on: true, action: { type: 'none' } };
  } else {
    c = { id: newId(), name: `Color ${n}`, h: [86, 98], s: [80, 255], v: [80, 255], color: rgbHex(hsvCss(92, 220, 220)), on: true, action: { type: 'none' } };
  }
  app.cfg.classes.push(c);
  edited();
  select(c.id);
  toast(`Added “${c.name}”: give it a name and choose what it makes the car do`);
}

// ---------------------------------------------------------------- the hue wheel

const SVGNS = 'http://www.w3.org/2000/svg';
const C = 160, R1 = 150, R0 = 132;
const pt = (deg, r) => [C + r * Math.sin((deg * Math.PI) / 180), C - r * Math.cos((deg * Math.PI) / 180)];
const trackR = (i, n) => 118 - i * Math.min(13, (118 - 56) / Math.max(1, n - 1));   // keep the middle free for the label

function arcPath(lo, hi, r) {
  const a0 = lo * 2, a1 = (hi + 1) * 2 + (lo <= hi ? 0 : 360);
  const sweep = Math.min(a1 - a0, 359.99);
  const [x0, y0] = pt(a0, r), [x1, y1] = pt(a0 + sweep, r);
  return `M${x0.toFixed(2)} ${y0.toFixed(2)} A${r} ${r} 0 ${sweep > 180 ? 1 : 0} 1 ${x1.toFixed(2)} ${y1.toFixed(2)}`;
}

function renderWheel() {
  const svg = $('#wheel');
  if (!app.cfg) return;
  const n = app.cfg.classes.length;
  let s = '';
  for (let h = 0; h < 180; h++) {     // the spectrum, one OpenCV hue per wedge
    const a = h * 2, b = a + 2.4;
    const [x0, y0] = pt(a, R1), [x1, y1] = pt(b, R1), [x2, y2] = pt(b, R0), [x3, y3] = pt(a, R0);
    s += `<path d="M${x0} ${y0}L${x1} ${y1}L${x2} ${y2}L${x3} ${y3}Z" fill="hsl(${a + 1} 100% 50%)"/>`;
  }
  for (let h = 0; h < 180; h += 30) {
    const [x, y] = pt(h * 2, R1 + 5), [tx, ty] = pt(h * 2, R1 + 13);
    s += `<line x1="${pt(h * 2, R1)[0]}" y1="${pt(h * 2, R1)[1]}" x2="${x}" y2="${y}" stroke="currentColor" stroke-width="1" opacity=".45"/>`;
    s += `<text class="spoke-label" x="${tx}" y="${ty + 3.5}" text-anchor="middle">${h}</text>`;
  }
  app.cfg.classes.forEach((c, i) => {
    const r = trackR(i, n), sel = c.id === app.sel;
    s += `<circle class="track" cx="${C}" cy="${C}" r="${r}"/>`;
    s += `<path class="arc${c.on ? '' : ' off'}" data-id="${c.id}" d="${arcPath(c.h[0], c.h[1], r)}" stroke="${c.color}" stroke-width="${sel ? 11 : 8}"/>`;
  });
  const sc = selected();
  if (sc) {
    const i = app.cfg.classes.indexOf(sc), r = trackR(i, n);
    const [ax, ay] = pt(sc.h[0] * 2, r), [bx, by] = pt((sc.h[1] + 1) * 2, r);
    s += `<circle class="handle" data-end="0" cx="${ax}" cy="${ay}" r="7.5"/><circle class="handle" data-end="1" cx="${bx}" cy="${by}" r="7.5"/>`;
    s += `<text class="center-name" x="${C}" y="${C + 2}" text-anchor="middle"${sc.name.length > 8 ? ' textLength="80" lengthAdjust="spacingAndGlyphs"' : ''}>${esc(sc.name.length > 12 ? sc.name.slice(0, 11) + '…' : sc.name)}</text>`;
    s += `<text class="center-range" x="${C}" y="${C + 18}" text-anchor="middle">H ${hueText(sc.h)}</text>`;
  }
  if (app.sample) {                    // the needle: where the sampled pixel sits on the wheel
    const a = app.sample.h * 2 + 1, [x0, y0] = pt(a, 30), [x1, y1] = pt(a, R1 + 4);
    s += `<line class="needle" x1="${x0}" y1="${y0}" x2="${x1}" y2="${y1}"/>`;
    app.cfg.classes.forEach((c, i) => {
      const [x, y] = pt(a, trackR(i, n));
      const ok = c.on && hueIn(app.sample.h, c.h);
      s += `<circle class="hit" cx="${x}" cy="${y}" r="4.5" fill="${ok ? c.color : 'var(--card)'}"/>`;
    });
  }
  svg.innerHTML = s;
  svg.style.color = 'var(--ink)';
}

function wheelAngle(ev) {
  const svg = $('#wheel'), p = svg.createSVGPoint();
  p.x = ev.clientX; p.y = ev.clientY;
  const q = p.matrixTransform(svg.getScreenCTM().inverse());
  return (Math.atan2(q.x - C, -(q.y - C)) * 180 / Math.PI + 360) % 360;
}
(() => {
  const svg = $('#wheel');
  let drag = null;
  svg.addEventListener('pointerdown', (ev) => {
    const t = ev.target;
    if (t.classList.contains('arc')) {
      if (t.dataset.id !== app.sel) { select(t.dataset.id); }
      const c = selected();
      drag = { kind: 'arc', a0: wheelAngle(ev), h0: [...c.h] };
    } else if (t.classList.contains('handle')) {
      drag = { kind: 'end', end: +t.dataset.end };
    } else return;
    svg.setPointerCapture(ev.pointerId);
    ev.preventDefault();
  });
  svg.addEventListener('pointermove', (ev) => {
    if (!drag) return;
    const c = selected(), a = wheelAngle(ev);
    if (!c) return;
    if (drag.kind === 'end') {
      if (drag.end === 0) c.h[0] = wrapH(a / 2); else c.h[1] = wrapH(a / 2 - 1);
    } else {
      let d = (a - drag.a0) / 2;
      d = ((d + 90) % 180 + 180) % 180 - 90;
      c.h = [wrapH(drag.h0[0] + d), wrapH(drag.h0[1] + d)];
    }
    edited(false);
    updateChipText(c);
    syncEditorValues();
  });
  const end = () => { if (drag) { drag = null; renderChips(); } };
  svg.addEventListener('pointerup', end);
  svg.addEventListener('pointercancel', end);
})();

function updateChipText(c) {
  const li = $(`#chips .chip[data-id="${c.id}"]`);
  if (li) $('.chip-hsv', li).textContent = hsvShort(c);
}

// ---------------------------------------------------------------- the editor

function actionPicker(host, action, onChange) {
  host.innerHTML = '';
  const type = document.createElement('select');
  type.setAttribute('aria-label', 'Action type');
  type.innerHTML = ACTION_TYPES.map(([v, l]) => `<option value="${v}">${l}</option>`).join('');
  type.value = action.type;
  host.appendChild(type);
  let detail;
  if (action.type === 'key') {
    detail = document.createElement('select');
    detail.setAttribute('aria-label', 'Key');
    detail.innerHTML = Object.entries(KEYS).map(([k, w]) => `<option value="${k}">${k} — ${w}</option>`).join('');
    detail.value = action.key;
    detail.addEventListener('change', () => onChange({ type: 'key', key: detail.value }));
  } else if (action.type === 'line') {
    detail = document.createElement('input');
    detail.type = 'text';
    detail.maxLength = 40;
    detail.placeholder = 'D,150,150';
    detail.setAttribute('aria-label', 'Serial line to send');
    detail.value = action.text || '';
    detail.addEventListener('change', () => onChange({ type: 'line', text: detail.value.trim() || 'S' }));
  } else if (action.type === 'arm') {
    detail = document.createElement('select');
    detail.setAttribute('aria-label', 'Arm pose');
    const poses = app.arm.poses;
    detail.innerHTML = poses.length ? poses.map((p) => `<option value="${esc(p.id)}">${esc(p.name)}</option>`).join('')
      : `<option value="${esc(action.pose)}">${app.arm.available ? 'No saved poses yet' : 'Arm Twin not reachable'}</option>`;
    detail.value = action.pose;
    detail.addEventListener('change', () => {
      const p = poses.find((x) => x.id === detail.value);
      if (p) onChange({ type: 'arm', pose: p.id, name: p.name });
    });
  }
  if (detail) host.appendChild(detail);
  type.addEventListener('change', () => {
    const t = type.value;
    if (t === 'key') onChange({ type: 'key', key: 'S' });
    else if (t === 'line') onChange({ type: 'line', text: 'D,150,150' });
    else if (t === 'arm') {
      const p = app.arm.poses[0];
      if (!p) { toast(app.arm.available ? 'Save a pose in the Arm Twin (Teach tab) first' : 'The Arm Twin on port 8080 is not reachable'); type.value = action.type; return; }
      onChange({ type: 'arm', pose: p.id, name: p.name });
    } else onChange({ type: 'none' });
  });
}

function dual(key, c) {
  return `<div class="dual" data-k="${key}"><div class="rail"><i class="veil lo"></i><i class="veil hi"></i></div>
    <input type="range" min="0" max="255" step="1" value="${c[key][0]}" data-i="0" aria-label="${key === 's' ? 'Saturation' : 'Brightness'} from">
    <input type="range" min="0" max="255" step="1" value="${c[key][1]}" data-i="1" aria-label="${key === 's' ? 'Saturation' : 'Brightness'} to"></div>`;
}

function renderEditor() {
  const form = $('#editor'), c = selected();
  if (!c) {
    form.innerHTML = '<h3>Selected color</h3><p class="ed-note">Pick a color class above to edit its slice of the wheel and what it makes the car do.</p>';
    return;
  }
  const idx = app.cfg.classes.indexOf(c);
  form.innerHTML = `<h3>Selected color</h3>
    <div class="ed-top">
      <input type="text" id="e-name" maxlength="24" value="${esc(c.name)}" aria-label="Color name">
      <input type="color" id="e-color" value="${c.color}" aria-label="Paint color in the map" title="Paint color in the map">
      <label class="mini-switch"><input type="checkbox" id="e-on" ${c.on ? 'checked' : ''}><span>In use</span></label>
    </div>
    <div class="field"><span>Hue</span>
      <div class="hue-inputs"><input type="number" id="e-h0" min="0" max="179" value="${c.h[0]}" aria-label="Hue from"> to
        <input type="number" id="e-h1" min="0" max="179" value="${c.h[1]}" aria-label="Hue to"></div>
      <output class="pair" id="e-hout"></output></div>
    <div class="field"><span>Saturation</span>${dual('s', c)}<output class="pair" id="e-sout"></output></div>
    <div class="field"><span>Brightness</span>${dual('v', c)}<output class="pair" id="e-vout"></output></div>
    <div class="field"><span>When it wins</span><div class="action-pick" id="e-action"></div><span></span></div>
    <div class="ed-foot">
      <button type="button" class="btn quiet" id="e-only">${app.only === c.id ? 'Show all colors in the map' : 'Show only this color in the map'}</button>
      <span class="grow"></span>
      <button type="button" class="btn quiet" id="e-up" ${idx === 0 ? 'disabled' : ''} title="Checked earlier: wins overlapping pixels">Move up</button>
      <button type="button" class="btn quiet" id="e-down" ${idx === app.cfg.classes.length - 1 ? 'disabled' : ''}>Move down</button>
      <button type="button" class="btn" id="e-del">Delete</button>
    </div>
    <p class="ed-note">Hue runs 0–179 (OpenCV's scale, degrees ÷ 2). When “from” is bigger than “to”, the slice wraps through red, like 170 to 10. Where two colors overlap, the one higher in the list wins the pixel.</p>`;

  $('#e-name').addEventListener('input', (e) => { c.name = e.target.value.slice(0, 24) || c.id; edited(false); updateChipName(c); });
  $('#e-name').addEventListener('change', () => edited());
  $('#e-color').addEventListener('input', (e) => { c.color = e.target.value; edited(); });
  $('#e-on').addEventListener('change', (e) => { c.on = e.target.checked; edited(); });
  for (const i of [0, 1]) {
    $(`#e-h${i}`).addEventListener('input', (e) => {
      if (e.target.value === '') return;
      c.h[i] = wrapH(+e.target.value);
      edited(false); updateChipText(c); syncEditorValues(false);
    });
  }
  for (const box of $$('.dual', form)) {
    const k = box.dataset.k;
    for (const inp of $$('input', box)) {
      inp.addEventListener('input', () => {
        const i = +inp.dataset.i;
        let v = +inp.value;
        if (i === 0 && v > c[k][1]) v = c[k][1];
        if (i === 1 && v < c[k][0]) v = c[k][0];
        inp.value = v;
        c[k][i] = v;
        edited(false); updateChipText(c); syncEditorValues(false);
      });
    }
  }
  actionPicker($('#e-action'), c.action, (a) => { c.action = a; edited(); renderEditor(); });
  $('#e-only').addEventListener('click', () => { setOnly(app.only === c.id ? '' : c.id); renderEditor(); });
  $('#e-up').addEventListener('click', () => move(c, -1));
  $('#e-down').addEventListener('click', () => move(c, 1));
  $('#e-del').addEventListener('click', () => {
    if (!confirm(`Delete the color “${c.name}”?`)) return;
    app.cfg.classes = app.cfg.classes.filter((x) => x !== c);
    app.sel = app.cfg.classes[0]?.id || null;
    edited();
    renderEditor();
  });
  syncEditorValues();
}

function updateChipName(c) {
  const li = $(`#chips .chip[data-id="${c.id}"]`);
  if (li) $('.chip-name span', li).textContent = c.name;
  renderWheel();
}

function syncEditorValues(inputs = true) {
  const c = selected();
  if (!c || !$('#e-hout')) return;
  if (inputs) {
    if (document.activeElement !== $('#e-h0')) $('#e-h0').value = c.h[0];
    if (document.activeElement !== $('#e-h1')) $('#e-h1').value = c.h[1];
  }
  const span = c.h[0] <= c.h[1] ? c.h[1] - c.h[0] + 1 : 180 - c.h[0] + c.h[1] + 1;
  $('#e-hout').textContent = `${span * 2}° wide`;
  const mid = hueMid(c.h);
  for (const k of ['s', 'v']) {
    const box = $(`.dual[data-k="${k}"]`);
    const rail = $('.rail', box);
    rail.style.background = k === 's'
      ? `linear-gradient(90deg, ${hsvCss(mid, 0, 230)}, ${hsvCss(mid, 255, 230)})`
      : `linear-gradient(90deg, #000, ${hsvCss(mid, Math.max(c.s[0], 160), 255)})`;
    $('.veil.lo', box).style.cssText = `left:0;width:${(c[k][0] / 255) * 100}%`;
    $('.veil.hi', box).style.cssText = `right:0;width:${100 - (c[k][1] / 255) * 100}%`;
    if (inputs) $$('input', box).forEach((inp, i) => { inp.value = c[k][i]; });
    $(`#e-${k}out`).textContent = `${c[k][0]}–${c[k][1]}`;
  }
}

function move(c, d) {
  const a = app.cfg.classes, i = a.indexOf(c), j = i + d;
  if (j < 0 || j >= a.length) return;
  [a[i], a[j]] = [a[j], a[i]];
  edited();
  renderEditor();
}

// ---------------------------------------------------------------- policy rules

const AREA_MIN = 50, AREA_MAX = 40000;
const areaFromSlider = (v) => Math.round(AREA_MIN * (AREA_MAX / AREA_MIN) ** (v / 100) / 10) * 10;
const sliderFromArea = (a) => Math.round((Math.log(a / AREA_MIN) / Math.log(AREA_MAX / AREA_MIN)) * 100);
function renderRules() {
  const c = app.cfg;
  if (document.activeElement !== $('#r-area')) $('#r-area').value = sliderFromArea(Math.max(AREA_MIN, c.min_area));
  $('#r-area-out').textContent = `${c.min_area} px`;
  if (document.activeElement !== $('#r-hold')) $('#r-hold').value = c.hold;
  $('#r-hold-out').textContent = `${c.hold} fr`;
  if (document.activeElement !== $('#r-clean')) $('#r-clean').value = c.cleanup;
  $('#r-clean-out').textContent = `${c.cleanup}×`;
  actionPicker($('#r-nothing'), c.nothing, (a) => { c.nothing = a; edited(false); renderRules(); });
}
$('#r-area').addEventListener('input', (e) => { app.cfg.min_area = areaFromSlider(+e.target.value); $('#r-area-out').textContent = `${app.cfg.min_area} px`; edited(false); });
$('#r-hold').addEventListener('input', (e) => { app.cfg.hold = +e.target.value; $('#r-hold-out').textContent = `${app.cfg.hold} fr`; edited(false); });
$('#r-clean').addEventListener('input', (e) => { app.cfg.cleanup = +e.target.value; $('#r-clean-out').textContent = `${app.cfg.cleanup}×`; edited(false); });

// ---------------------------------------------------------------- sampling a pixel

for (const frame of [$('#frame-cam'), $('#frame-mask')]) {
  frame.addEventListener('click', async (ev) => {
    const r = frame.getBoundingClientRect();
    const x = (ev.clientX - r.left) / r.width, y = (ev.clientY - r.top) / r.height;
    try {
      app.sample = { ...(await api(`/api/sample?x=${x.toFixed(4)}&y=${y.toFixed(4)}`)), fx: x, fy: y };
    } catch (e) { toast(e.message); return; }
    renderSampler();
    renderWheel();
  });
}
function renderSampler() {
  const s = app.sample, box = $('#sampler');
  for (const p of $$('.probe')) {
    p.hidden = !s;
    if (s) { p.style.left = `${s.fx * 100}%`; p.style.top = `${s.fy * 100}%`; }
  }
  box.hidden = !s;
  if (!s) return;
  $('#smp-chip').style.background = s.rgb;
  $('#smp-hsv').textContent = `H ${s.h} · S ${s.s} · V ${s.v}`;
  const names = s.classes.map((id) => cls(id)?.name).filter(Boolean);
  $('#smp-match').textContent = names.length ? `Matches ${names.join(' and ')}` : 'Matches no color class';
  const c = selected();
  const teach = $('#smp-teach');
  teach.hidden = !c;
  if (c) teach.textContent = s.classes.includes(c.id) ? `${c.name} already covers it` : `Teach ${c.name} this shade`;
  teach.disabled = !c || s.classes.includes(c.id);
}
$('#smp-close').addEventListener('click', () => { app.sample = null; renderSampler(); renderWheel(); });
$('#smp-new').addEventListener('click', () => addClass(app.sample));
$('#smp-teach').addEventListener('click', () => {
  const c = selected(), s = app.sample;
  if (!c || !s) return;
  if (!hueIn(s.h, c.h)) {            // stretch the nearer end of the slice to reach the pixel's hue
    const dLo = (c.h[0] - s.h + 180) % 180, dHi = (s.h - c.h[1] + 180) % 180;
    if (dLo <= dHi) c.h[0] = wrapH(s.h - 2); else c.h[1] = wrapH(s.h + 2);
  }
  c.s = [Math.min(c.s[0], Math.max(0, s.s - 15)), Math.max(c.s[1], Math.min(255, s.s + 15))];
  c.v = [Math.min(c.v[0], Math.max(0, s.v - 15)), Math.max(c.v[1], Math.min(255, s.v + 15))];
  edited();
  renderEditor();
  app.sample.classes = [...new Set([...app.sample.classes, c.id])];
  renderSampler();
  toast(`${c.name} now covers this shade`);
});

// ---------------------------------------------------------------- top-level controls

function setOnly(id) {
  app.only = id;
  $('#only').value = id;
  setStreams(true);
}
$('#only').addEventListener('change', (e) => { setOnly(e.target.value); renderEditor(); });
$('#context').addEventListener('change', (e) => { app.context = e.target.checked; store.set('context', app.context); setStreams(true); });

$('#output').addEventListener('click', async () => {
  const on = !(app.st && app.st.output);
  try { await api('/api/output', { on }); } catch (e) { toast(e.message); }
});
$$('#mode button').forEach((b) => b.addEventListener('click', () => api('/api/mode', { mode: b.dataset.mode }).catch((e) => toast(e.message))));
$$('#source button').forEach((b) => b.addEventListener('click', () => api('/api/source', { source: b.dataset.source }).catch((e) => toast(e.message))));
$('#camera-pick').addEventListener('change', (e) =>
  api('/api/camera', { camera: e.target.value === 'auto' ? null : e.target.value }).catch((er) => toast(er.message)));
$('#speed').addEventListener('change', (e) => api('/api/speed', { n: +e.target.value }).catch((er) => toast(er.message)));
$('#speed').addEventListener('input', (e) => { $('#speed-out').textContent = e.target.value; });

// hold-to-drive: the server stops the key if the renewals stop (dead-man)
let held = null, heldTimer = null;
function hold(key) {
  release(false);
  held = key;
  const ping = () => api('/api/drive', { key }).catch((e) => { toast(e.message); release(); });
  ping();
  heldTimer = setInterval(ping, 200);
  $$('#pad button').forEach((b) => b.classList.toggle('held', b.dataset.k === key));
}
function release(send = true) {
  clearInterval(heldTimer);
  heldTimer = null;
  $$('#pad button').forEach((b) => b.classList.remove('held'));
  if (held && send) api('/api/drive', { key: null }).catch(() => {});
  held = null;
}
for (const b of $$('#pad button')) {
  b.addEventListener('pointerdown', (e) => { if (b.disabled) return; e.preventDefault(); b.setPointerCapture(e.pointerId); if (b.dataset.k === 'S') release(); else hold(b.dataset.k); });
  b.addEventListener('pointerup', () => release());
  b.addEventListener('pointercancel', () => release());
}
const ARROWS = { ArrowUp: 'F', ArrowDown: 'B', ArrowLeft: 'L', ArrowRight: 'R', w: 'F', s: 'B', a: 'L', d: 'R' };
document.addEventListener('keydown', (e) => {
  if (e.target.closest('input, select, textarea, dialog') || e.ctrlKey || e.metaKey || e.altKey) return;
  if (e.key === ' ' || e.key === 'Escape') {
    e.preventDefault();
    release();
    if (app.st?.output) api('/api/output', { on: false }).then(() => toast('Output off: dry run')).catch(() => {});
    return;
  }
  if (ARROWS[e.key] && app.st?.mode === 'manual') {
    e.preventDefault();
    if (!e.repeat && held !== ARROWS[e.key]) hold(ARROWS[e.key]);
  }
});
document.addEventListener('keyup', (e) => { if (ARROWS[e.key] && held === ARROWS[e.key]) release(); });
window.addEventListener('blur', () => release());

$('#add').addEventListener('click', () => addClass(app.sample));
$('#reset').addEventListener('click', async () => {
  if (!confirm('Put back the six course colors and their keys? Your edits to the classes are replaced.')) return;
  try {
    const r = await api('/api/config/reset', {});
    app.cfg = r.config;
    app.sel = app.cfg.classes[0]?.id;
    renderAll();
    toast('Back to the six course colors');
  } catch (e) { toast(e.message); }
});

// code export: what to paste into the command-line scripts
$('#code').addEventListener('click', () => {
  const py = (c) => {
    const [h0, h1] = c.h, lo = (h) => `(${h}, ${c.s[0]}, ${c.v[0]})`, hi = (h) => `(${h}, ${c.s[1]}, ${c.v[1]})`;
    return h0 <= h1 ? `[(${lo(h0)}, ${hi(h1)})]` : `[(${lo(h0)}, ${hi(179)}), (${lo(0)}, ${hi(h1)})]`;
  };
  const key = (c) => c.name.toLowerCase().replace(/[^a-z0-9]+/g, '_');
  const on = app.cfg.classes.filter((c) => c.on);
  const lines = ['# 04_opencv/color_track.py — OpenCV HSV: H 0..179, S 0..255, V 0..255', 'RANGES = {',
    ...on.map((c) => `    "${key(c)}": ${py(c)},`), '}', '',
    '# 08_rc_car/vision_drive.py — the policy: color -> (key, meaning)', 'DIRECTIONS = {',
    ...on.filter((c) => c.action.type === 'key').map((c) => `    "${key(c)}": ("${c.action.key}", "${KEYS[c.action.key]}"),`), '}',
    `STABLE_FRAMES = ${app.cfg.hold}`, `MIN_AREA = ${app.cfg.min_area}`];
  const other = on.filter((c) => c.action.type !== 'key');
  if (other.length) lines.push('', `# not keys (dashboard only): ${other.map((c) => `${c.name} → ${actionShort(c.action)}`).join('; ')}`);
  $('#code-text').textContent = lines.join('\n');
  $('#code-dlg').showModal();
});
$('#code-close').addEventListener('click', () => $('#code-dlg').close());
$('#code-copy').addEventListener('click', async () => {
  try { await navigator.clipboard.writeText($('#code-text').textContent); toast('Copied'); }
  catch { toast('Select the text and copy it (the clipboard needs https or localhost)'); }
});

$('#theme').addEventListener('click', () => {
  const dark = (document.documentElement.dataset.theme || (matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light')) === 'dark';
  document.documentElement.dataset.theme = dark ? 'light' : 'dark';
  store.set('theme', dark ? 'light' : 'dark');
  try { localStorage.setItem('rcpilot.theme', dark ? 'light' : 'dark'); } catch { /* ignore */ }
});
$('#link-cam').href = `${location.protocol}//${location.hostname}:8000/`;
$('#link-arm').href = `${location.protocol}//${location.hostname}:8080/`;
$('#link-gesture').href = `${location.protocol}//${location.hostname}:8083/`;
$('#car-btn').addEventListener('click', () => {
  const take = $('#car-btn').dataset.take === 'true';
  api('/api/car', { take }).then(() => toast(take ? 'Looking for the car…' : 'Car released')).catch((e) => toast(e.message));
});

// ---------------------------------------------------------------- boot

function renderAll() {
  if (!cls(app.sel)) app.sel = app.cfg.classes[0]?.id || null;
  renderChips();
  renderOnly();
  renderWheel();
  renderEditor();
  renderRules();
  renderCoverage();
  renderSampler();
}

async function boot() {
  app.context = store.get('context', true);
  $('#context').checked = app.context;
  try {
    app.cfg = await api('/api/config');
  } catch (e) {
    toast(`The Pi did not answer: ${e.message}`);
    setTimeout(boot, 2000);
    return;
  }
  app.sel = store.get('sel', null);
  renderAll();
  if (!document.hidden) wake();            // a prerendered / background tab waits until it is shown
  setStreams(true);
  poll();
  api('/api/arm').then((a) => { app.arm = a; renderEditor(); renderRules(); }).catch(() => {});
}
boot();
window.rcPilot = app;   // handy from the browser console

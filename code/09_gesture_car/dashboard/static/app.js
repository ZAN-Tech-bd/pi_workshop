// Gesture Pilot — the page. Talks to server.py: status 4x a second, every edit to the
// gesture library pushed back within ~0.1 s. Examples are only ever added by recording.

const $ = (s, r = document) => r.querySelector(s);
const $$ = (s, r = document) => [...r.querySelectorAll(s)];

const KEYS = { F: 'forward', B: 'backward', L: 'left', R: 'right', G: 'front-left', I: 'front-right', H: 'back-left', J: 'back-right', S: 'stop' };
const SPEEDS = ['1', '2', '3', '4', '5', '6', '7', '8', '9', 'q'];
const ACTION_TYPES = [['key', 'Drive'], ['speed', 'Set speed'], ['step', 'Faster / slower'], ['none', 'Nothing']];
const FINGERS = ['Thumb', 'Index', 'Middle', 'Ring', 'Pinky'];
const BONES = [[0, 1], [1, 2], [2, 3], [3, 4], [0, 5], [5, 6], [6, 7], [7, 8], [5, 9], [9, 10], [10, 11], [11, 12],
  [9, 13], [13, 14], [14, 15], [15, 16], [13, 17], [17, 18], [18, 19], [19, 20], [0, 17]];
const PALETTE = ['#2fae4e', '#2f6df0', '#e86e4b', '#9b4dff', '#f2c418', '#ff8a2a', '#12a1a1', '#d4372c', '#c2410c', '#4d7c0f', '#0ea5e9', '#e2557a'];
const DIRS = { up: 'up', up_right: 'up-right', right: 'right', down_right: 'down-right', down: 'down', down_left: 'down-left', left: 'left', up_left: 'up-left' };

const app = { cfg: null, st: null, sel: null, builtins: {}, examples: {}, editedAt: 0, rec: null };

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
  toastTimer = setTimeout(() => { t.hidden = true; }, 3800);
}
const store = {
  get(k, d) { try { const v = localStorage.getItem(`gpilot.${k}`); return v === null ? d : JSON.parse(v); } catch { return d; } },
  set(k, v) { try { localStorage.setItem(`gpilot.${k}`, JSON.stringify(v)); } catch { /* private window */ } },
};
const esc = (s) => String(s).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const inkOn = (hex) => {
  const c = [1, 3, 5].map((i) => parseInt(hex.slice(i, i + 2), 16) / 255).map((x) => (x <= 0.04 ? x / 12.92 : ((x + 0.055) / 1.055) ** 2.4));
  return 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2] > 0.36 ? '#111316' : '#ffffff';
};
const speedText = (n) => (n === 'q' ? 'Q' : n);

function describe(a) {
  if (!a || a.type === 'none') return { main: '—', word: 'nothing', short: 'nothing' };
  if (a.type === 'key') return { main: a.key, word: KEYS[a.key], short: `${a.key} · ${KEYS[a.key]}` };
  if (a.type === 'speed') return { main: speedText(a.n), word: a.n === 'q' ? 'turbo' : `speed ${a.n}`, short: a.n === 'q' ? 'turbo' : `speed ${a.n}` };
  return { main: a.d > 0 ? '+' : '−', word: a.d > 0 ? 'faster' : 'slower', short: a.d > 0 ? 'faster' : 'slower' };
}
function ruleText(rule) {
  const m = rule.match(/^(point|thumb)_(.+)$/);
  if (m) {
    const d = DIRS[m[2]];
    return m[1] === 'point'
      ? `<code>index</code> out · <code>middle ring pinky</code> in · the index points <b>${d}</b> (±15°, gone at 45°)`
      : `<code>thumb</code> out · <code>index middle ring pinky</code> in · the thumb points <b>${d}</b> (±25°, gone at 65°)`;
  }
  return {
    open_palm: '<code>index middle ring pinky</code> out (thumb: either)',
    fist: '<code>thumb index middle ring pinky</code> in',
    victory: '<code>index middle</code> out · <code>ring pinky</code> in',
    three: '<code>index middle ring</code> out · <code>pinky</code> in',
    rock: '<code>index pinky</code> out · <code>thumb middle ring</code> in',
    love_you: '<code>thumb index pinky</code> out · <code>middle ring</code> in',
    call_me: '<code>thumb pinky</code> out · <code>index middle ring</code> in',
    ok: 'thumb tip touches the index tip · <code>middle ring pinky</code> out',
  }[rule] || rule;
}
const gest = (id) => app.cfg?.gestures.find((g) => g.id === id);
const selected = () => gest(app.sel);
// Emoji need a color-emoji font; the Pi's own browser has none (boxes), so fall back to words.
const EMOJI_OK = (() => {
  try {
    const c = document.createElement('canvas'), x = c.getContext('2d', { willReadFrequently: true });
    c.width = c.height = 24;
    x.font = '20px sans-serif';
    x.textBaseline = 'top';
    x.fillText('✋', 0, 0);
    const d = x.getImageData(0, 0, 24, 24).data;
    for (let i = 0; i < d.length; i += 4) if (d[i + 3] && Math.max(d[i], d[i + 1], d[i + 2]) - Math.min(d[i], d[i + 1], d[i + 2]) > 40) return true;
  } catch { /* no canvas */ }
  return false;
})();
const ARROW = { up: '↑', up_right: '↗', right: '→', down_right: '↘', down: '↓', down_left: '↙', left: '←', up_left: '↖' };
function glyphText(rule) {
  const m = rule.match(/^(point|thumb)_(.+)$/);
  if (m) return `${m[1] === 'point' ? 'POINT' : 'THUMB'} ${ARROW[m[2]]}`;
  return { open_palm: 'PALM', fist: 'FIST', victory: 'V', three: '3', rock: 'ROCK', love_you: 'ILY', call_me: 'CALL', ok: 'OK' }[rule] || rule;
}
const emojiOf = (g) => (g.kind !== 'builtin' ? '' : EMOJI_OK ? app.builtins[g.rule]?.emoji || '✋' : glyphText(g.rule));
const emojiHtml = (g) => (EMOJI_OK ? `<span class="emoji">${emojiOf(g)}</span>` : `<span class="glyph">${esc(emojiOf(g))}</span>`);

// a hand skeleton as SVG paths; pts are normalized (wrist 0, palm length 1)
function bones(pts, attrs = 'class="bone"') {
  return BONES.map(([a, b]) => `<line ${attrs} x1="${pts[a][0]}" y1="${pts[a][1]}" x2="${pts[b][0]}" y2="${pts[b][1]}"/>`).join('');
}
function fitBox(pts, pad = 0.35) {
  const xs = pts.map((p) => p[0]), ys = pts.map((p) => p[1]);
  const x0 = Math.min(...xs), x1 = Math.max(...xs), y0 = Math.min(...ys), y1 = Math.max(...ys);
  const s = Math.max(x1 - x0, y1 - y0) + 2 * pad;
  return `${((x0 + x1) / 2 - s / 2).toFixed(3)} ${((y0 + y1) / 2 - s / 2).toFixed(3)} ${s.toFixed(3)} ${s.toFixed(3)}`;
}

// ---------------------------------------------------------------- config sync

let pushTimer = null, pushBusy = false, pushAgain = false;
function edited(rebuild = true) {
  app.editedAt = performance.now();
  if (rebuild) renderChips();
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
async function reloadConfig() {
  try {
    app.cfg = await api('/api/config');
    renderAll();
  } catch (e) { toast(e.message); }
}

// ---------------------------------------------------------------- stream + live results
// The video is the camera's own MJPEG, passed through untouched (full camera rate);
// the skeleton is drawn here, on an SVG over it, from results the Pi pushes the
// moment each frame is analysed (/api/live, Server-Sent Events).

function setStream(on) {
  const img = $('#img-cam');
  if (!on) { img.removeAttribute('src'); return; }
  if (!img.getAttribute('src')) img.src = '/stream';
}
$('#img-cam').addEventListener('error', () => setTimeout(() => { if (!document.hidden) { $('#img-cam').removeAttribute('src'); setStream(true); } }, 2000));

let live = null, liveAt = 0, fastQueued = false;
function setLive(on) {
  if (!on) { live?.close(); live = null; return; }
  if (live) return;
  live = new EventSource('/api/live');
  live.onmessage = (ev) => {
    app.live = JSON.parse(ev.data);
    liveAt = performance.now();
    if (!app.st) return;
    Object.assign(app.st, app.live);
    if (!fastQueued) { fastQueued = true; requestAnimationFrame(() => { fastQueued = false; renderFast(); }); }
  };
  live.onerror = () => { /* EventSource reconnects by itself */ };
}
document.addEventListener('visibilitychange', () => { setStream(!document.hidden); setLive(!document.hidden); });

// ---------------------------------------------------------------- status loop (the slow part: links, events, speed)

async function poll() {
  if (!document.hidden) {
    try {
      const st = await api('/api/status');
      // the pushed results are newer than a poll's copy of them: keep those
      app.st = performance.now() - liveAt < 1000 && app.live ? { ...st, ...app.live } : st;
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
  const src = st.source, L = st.link, rc = st.rc || {};

  // health: the video runs at the camera's rate, the gestures at the engine's
  const video = src.kind === 'camera' ? st.camera_fps : st.fps;
  $('#lamp-cam').dataset.tone = src.error ? 'bad' : src.loading ? 'warn' : st.fps >= 6 ? 'ok' : 'warn';
  $('#cam-text').textContent = src.error ? 'No camera' : src.loading ? 'Loading MediaPipe…' : `${src.kind === 'demo' ? 'Demo' : 'Camera'} · ${video} fps`;
  $('#lamp-cam').title = src.error || `${src.name} · gestures analysed ${st.fps}/s · ${st.proc_ms} ms per frame`;
  $('#rates').textContent = src.error || src.loading ? '' : `video ${video} fps · gestures ${st.fps}/s`;
  $('#msg-cam').hidden = !src.error;
  $('#msg-cam').textContent = src.error ? `No picture: ${src.error}` : '';
  $$('#source button').forEach((b) => b.setAttribute('aria-pressed', String(b.dataset.source === src.kind)));
  // the camera's own frames are unmirrored: mirror them here (demo pictures already are)
  $('#img-cam').classList.toggle('mirrored', app.cfg.mirror && src.kind === 'camera');

  const withRc = rc.up && rc.state === 'ready';
  $('#lamp-car').dataset.tone = L.state === 'ready' ? 'ok' : L.state === 'searching' ? 'warn' : 'off';
  $('#car-text').textContent = L.state === 'ready' ? `Car · ${L.port}` : L.state === 'searching' ? 'Car · looking…'
    : withRc ? 'Car · with Color Pilot' : 'Car · released';
  $('#lamp-car').title = L.detail;
  const carBtn = $('#car-btn');
  carBtn.textContent = L.state === 'off' ? 'Take the car' : L.state === 'ready' ? 'Release the car' : 'Stop looking';
  carBtn.dataset.take = String(L.state === 'off');
  carBtn.title = L.state === 'off'
    ? (withRc ? 'Asks the Color Pilot (:8081) to let go, then connects here' : 'Connect to ZAN_RC_Car over Bluetooth')
    : 'Let go of the car (and hand it back to the Color Pilot)';

  const out = $('#output');
  out.setAttribute('aria-checked', String(st.output));
  out.toggleAttribute('data-warn', st.output && L.state !== 'ready');
  $('#output-state').textContent = st.output ? 'Live' : 'Dry run';
  $('#output-sub').textContent = !st.output ? 'nothing is sent' : L.state === 'ready' ? 'to the car' : 'no car connected';

  const manual = st.mode === 'manual';
  $$('#mode button').forEach((b) => b.setAttribute('aria-pressed', String(b.dataset.mode === st.mode)));
  $$('#pad button').forEach((b) => { b.disabled = !manual; });
  if (document.activeElement !== $('#speed')) $('#speed').value = SPEEDS.indexOf(st.speed);
  $('#speed-out').textContent = speedText(st.speed);

  const ev = $('#events');
  const evSig = st.events.map((e) => e.t + e.text).join('|');
  if (ev.dataset.sig !== evSig) {
    ev.dataset.sig = evSig;
    ev.innerHTML = st.events.slice(0, 9).map((e) =>
      `<li><time>${e.t}</time><span>${esc(e.text)}</span><span class="tag ${e.tag}">${e.tag}</span></li>`).join('');
  }

  renderFast();
  // examples arrived (recording) or vanished: refresh what the page shows
  for (const [id, n] of Object.entries(st.examples || {})) {
    const g2 = gest(id);
    if (g2 && g2.examples !== n && performance.now() - app.editedAt > 800 && !app.reloading) {
      app.reloading = true;
      api('/api/config').then((c) => { app.cfg = c; renderChips(); if (app.sel === id) { delete app.examples[id]; renderEditor(); } })
        .finally(() => { app.reloading = false; });
      break;
    }
  }
}

// everything that follows the hand: redrawn on every analysed frame
function renderFast() {
  const st = app.st;
  if (!st || !app.cfg) return;
  renderOverlay();
  renderAct();
  renderThink();
  updateChipStats();
  watchRecording();
}

function renderOverlay() {
  const st = app.st, h = st.hand, svg = $('#overlay');
  if (!h || st.stale) { svg.innerHTML = ''; return; }
  const p = h.pts.map(([x, y]) => [(x * 640).toFixed(1), (y * 480).toFixed(1)]);
  const col = st.color || '#ffffff';
  svg.innerHTML = `<g class="ov-shadow">${bones(p, 'class="ov-bone"')}</g><g style="stroke:${col}">${bones(p, 'class="ov-bone"')}</g>` +
    p.map(([x, y], i) => `<circle class="ov-joint" cx="${x}" cy="${y}" r="${[4, 8, 12, 16, 20].includes(i) ? 6 : 4}"/>`).join('');
}

function renderAct() {
  const st = app.st;
  const manual = st.mode === 'manual';
  const g = !manual && st.active && !st.stale ? gest(st.active) : null;
  const action = manual ? { type: 'key', key: st.held || 'S' } : g ? g.action : app.cfg.nothing;
  const d = describe(action);
  const sig = $('#signal');
  sig.style.setProperty('--sig', g ? g.color : 'var(--well)');
  sig.style.setProperty('--on', g ? inkOn(g.color) : 'var(--ink)');
  sig.toggleAttribute('data-live', !!g);
  sig.dataset.kind = action.type === 'key' || action.type === 'speed' || action.type === 'step' ? 'key' : 'text';
  $('#sig-main').textContent = d.main;
  $('#sig-word').textContent = action.type === 'step' || action.type === 'speed' ? `${d.word} · car waits` : d.word;
  $('#sig-emoji').textContent = g && EMOJI_OK ? emojiOf(g) : '';

  const win = st.winner ? gest(st.winner) : null;
  let verdict;
  if (manual) verdict = st.held ? `You are holding <b>${st.held}</b> · ${KEYS[st.held]}` : 'You drive: hold a button below (or the arrow keys)';
  else if (st.stale) verdict = 'No fresh picture: the car is told to stop';
  else if (!st.hand) verdict = 'No hand in view';
  else if (!win) verdict = 'A hand, but no gesture fits';
  else if (st.active === st.winner) verdict = `<b>${esc(win.name)}</b> is held`;
  else verdict = `<b>${esc(win.name)}</b> is winning: ${Math.min(st.streak, st.hold)} of ${st.hold} frames`;
  $('#verdict').innerHTML = verdict;

  const key = (st.would || 'S').split(' ')[0], L = st.link || {};
  $('#wire').innerHTML = !st.output ? `Dry run: would send <b>${esc(key)}</b> every 0.25 s`
    : L.state === 'ready' ? `Sending <b>${esc(key)}</b> every 0.25 s · speed ${speedText(st.speed)}` : 'Output is live, but no car is connected';

  const hold = $('#hold');
  if (hold.childElementCount !== st.hold) hold.innerHTML = '<i></i>'.repeat(st.hold);
  const filled = manual ? 0 : Math.min(st.streak, st.hold);
  [...hold.children].forEach((el, i) => {
    el.classList.toggle('on', i < filled);
    el.style.background = i < filled ? (win ? win.color : 'var(--ink-3)') : '';
  });
}

// ---------------------------------------------------------------- think panel

function renderThink() {
  const st = app.st, h = st.hand;
  // the normalized hand, with the nearest taught example as a ghost behind it
  let s = '<line class="grid" x1="-2.5" y1="0" x2="2.5" y2="0"/><line class="grid" x1="0" y1="-2.7" x2="0" y2="2.3"/>' +
    '<circle class="grid" cx="0" cy="0" r="1" fill="none"/><circle class="grid" cx="0" cy="0" r="2" fill="none"/>';
  const near = st.nearest;
  let ghostNote = '';
  if (h && near) {
    const ex = app.examples[near.id], g = gest(near.id);
    if (ex && ex.list[near.index] && g) {
      s += `<g stroke="${g.color}">${bones(ex.list[near.index].norm, 'class="ghost"')}</g>`;
      ghostNote = ` · ghost: closest example of <b>${esc(g.name)}</b>, ${near.dist} palms away`;
    } else if (g && !app.examples[near.id]?.loading) loadExamples(near.id);
  }
  if (h) {
    s += bones(h.norm) + h.norm.map((p, i) => `<circle class="${i ? 'joint' : 'wrist'}" cx="${p[0]}" cy="${p[1]}" r="${i % 4 === 0 && i ? 0.085 : 0.06}"/>`).join('');
  } else {
    s += '<text class="empty" x="0" y="-0.35" text-anchor="middle">no hand</text>';
  }
  $('#handmap').innerHTML = s;
  $('#map-caption').innerHTML = h ? `${h.handed} hand, wrist at the centre, palm length 1${ghostNote}` : 'Your hand, normalized';

  const ul = $('#fingers');
  if (!ul.childElementCount) ul.innerHTML = FINGERS.map((f) => `<li><em>${f}</em><span><i></i></span><b></b></li>`).join('');
  [...ul.children].forEach((li, i) => {
    const v = h ? h.fingers[i] : 0;
    $('i', li).style.width = `${v * 100}%`;
    $('b', li).textContent = h ? (v >= 0.5 ? 'out' : 'in') : '';
    li.classList.toggle('out', h && v >= 0.5);
  });
  $('#dirs').textContent = h ? `index points ${h.point_dir}° · thumb ${h.thumb_dir}°  (0° = up, clockwise)` : '—';
  $('#whythink').innerHTML = !h ? '' : st.why === 'taught' ? 'Decided by <b>your examples</b> (nearest neighbours)'
    : st.why === 'rule' ? 'Decided by a <b>built-in rule</b> (no taught gesture was close enough)' : 'Nothing passed its threshold';

  // scores: best first
  const rows = app.cfg.gestures.map((g) => ({ g, s: st.scores?.[g.id] ?? 0 })).sort((a, b) => b.s - a.s).slice(0, 7);
  $('#scores').innerHTML = rows.map(({ g, s: v }) => {
    const thr = g.kind === 'taught' ? 0.5 : app.cfg.rule_min;
    const cls = [g.on ? '' : 'off', st.winner === g.id ? 'win' : ''].join(' ');
    const em = g.kind === 'builtin' ? (EMOJI_OK ? emojiOf(g) : '•') : (EMOJI_OK ? '✍️' : '✎');
    return `<li class="${cls}" title="${g.kind === 'taught' ? 'taught: counts at 0.50 (= the match radius)' : `rule: counts at ${thr.toFixed(2)}`}">
      <span class="em">${em}</span><span class="nm">${esc(g.name)}</span>
      <span class="bar"><i style="width:${v * 100}%;background:${g.color}"></i><u style="left:${thr * 100}%"></u></span><b>${v.toFixed(2)}</b></li>`;
  }).join('');
}

// ---------------------------------------------------------------- library cards

function cardFace(g) {
  if (g.kind === 'builtin') return emojiHtml(g);
  if (g.preview) return `<svg viewBox="${fitBox(g.preview)}" aria-hidden="true">${bones(g.preview)}</svg>`;
  return '<span class="hint">No examples yet:<br>select it and press Record</span>';
}
function kindText(g) {
  const hand = g.hand === 'any' ? 'either hand' : `${g.hand} hand only`;
  if (g.kind === 'builtin') return `Built-in rule · ${hand}`;
  return `Taught · ${g.examples || 0} example${g.examples === 1 ? '' : 's'} · ${hand}`;
}

function renderChips() {
  const ul = $('#chips');
  ul.innerHTML = '';
  app.cfg.gestures.forEach((g) => {
    const li = document.createElement('li');
    const empty = g.kind === 'taught' && !g.examples;
    li.className = `chip${g.on ? '' : ' off'}${empty ? ' empty' : ''}`;
    li.dataset.id = g.id;
    li.setAttribute('role', 'option');
    li.setAttribute('aria-selected', String(g.id === app.sel));
    li.tabIndex = 0;
    li.style.setProperty('--c', g.color);
    li.style.setProperty('--on', inkOn(g.color));
    const d = describe(g.action);
    li.innerHTML = `<div class="chip-face"><span class="chip-tag" hidden></span>${cardFace(g)}<span class="chip-key">${esc(d.main)}</span></div>
      <div class="chip-body"><div class="chip-name"><span>${esc(g.name)}</span><input type="checkbox" ${g.on ? 'checked' : ''} aria-label="Use ${esc(g.name)}" title="Use this gesture"></div>
      <div class="chip-kind">${esc(kindText(g))}</div>
      <div class="chip-act">→ ${esc(d.short)}</div>
      <div class="chip-meter"><span><i></i></span><b>0.00</b></div></div>`;
    li.addEventListener('click', (e) => { if (!e.target.matches('input')) select(g.id); });
    li.addEventListener('keydown', (e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); select(g.id); } });
    $('input', li).addEventListener('change', (e) => { g.on = e.target.checked; edited(); renderEditor(); });
    ul.appendChild(li);
  });
  const add = document.createElement('li');
  add.className = 'chip add';
  add.tabIndex = 0;
  add.textContent = '+ Teach a new gesture';
  add.addEventListener('click', () => teachNew());
  add.addEventListener('keydown', (e) => { if (e.key === 'Enter') teachNew(); });
  ul.appendChild(add);
  updateChipStats();
}

function updateChipStats() {
  const st = app.st;
  if (!st) return;
  for (const li of $$('#chips .chip[data-id]')) {
    const g = gest(li.dataset.id);
    if (!g) continue;
    const v = st.scores?.[g.id] ?? 0;
    $('.chip-meter i', li).style.width = `${v * 100}%`;
    $('.chip-meter b', li).textContent = v.toFixed(2);
    const acting = st.mode === 'auto' && st.active === g.id;
    const winning = st.winner === g.id && !acting;
    li.classList.toggle('acting', acting);
    const tag = $('.chip-tag', li);
    tag.hidden = !(acting || winning);
    tag.textContent = acting ? 'Acting' : 'Winning';
  }
}

function select(id) {
  app.sel = id;
  store.set('sel', id);
  $$('#chips .chip[data-id]').forEach((li) => li.setAttribute('aria-selected', String(li.dataset.id === id)));
  renderEditor();
}

function newId(base) {
  let id = base, i = 2;
  while (gest(id)) id = `${base}_${i++}`;
  return id;
}
function nextColor() {
  const used = new Set(app.cfg.gestures.map((g) => g.color));
  return PALETTE.find((c) => !used.has(c)) || PALETTE[app.cfg.gestures.length % PALETTE.length];
}
function teachNew() {
  if (app.cfg.gestures.length >= 24) { toast('24 gestures is the limit: delete one first'); return; }
  const n = app.cfg.gestures.filter((g) => g.kind === 'taught').length + 1;
  const g = { id: newId(`t${Date.now().toString(36).slice(-4)}`), name: `My gesture ${n}`, kind: 'taught', hand: 'any',
    color: nextColor(), on: true, action: { type: 'none' }, examples: 0 };
  app.cfg.gestures.push(g);
  edited();
  select(g.id);
  $('#editor').scrollIntoView({ behavior: 'smooth', block: 'nearest' });
  toast('Name it, choose what it does, then hold the pose up and press Record');
}
function addBuiltin(rule) {
  if (app.cfg.gestures.length >= 24) { toast('24 gestures is the limit: delete one first'); return; }
  const b = app.builtins[rule];
  const g = { id: newId(rule), name: b.name, kind: 'builtin', rule, hand: 'any', color: nextColor(), on: true, action: { type: 'none' } };
  app.cfg.gestures.push(g);
  edited();
  select(g.id);
  $('#builtin-dlg').close();
  toast(`Added “${b.name}”: now choose what it makes the car do`);
}

// ---------------------------------------------------------------- the editor

function actionPicker(host, action, onChange, keysOnly = false) {
  host.innerHTML = '';
  const types = keysOnly ? [['key', 'Drive']] : ACTION_TYPES;
  const type = document.createElement('select');
  type.setAttribute('aria-label', 'Action type');
  type.innerHTML = types.map(([v, l]) => `<option value="${v}">${l}</option>`).join('');
  type.value = action.type;
  if (!keysOnly) host.appendChild(type);
  let detail;
  if (action.type === 'key') {
    detail = document.createElement('select');
    detail.setAttribute('aria-label', 'Key');
    detail.innerHTML = Object.entries(KEYS).map(([k, w]) => `<option value="${k}">${k} — ${w}</option>`).join('');
    detail.value = action.key;
    detail.addEventListener('change', () => onChange({ type: 'key', key: detail.value }));
  } else if (action.type === 'speed') {
    detail = document.createElement('select');
    detail.setAttribute('aria-label', 'Speed');
    detail.innerHTML = SPEEDS.map((n) => `<option value="${n}">${n === 'q' ? 'Turbo (q)' : `Speed ${n}`}</option>`).join('');
    detail.value = action.n;
    detail.addEventListener('change', () => onChange({ type: 'speed', n: detail.value }));
  } else if (action.type === 'step') {
    detail = document.createElement('select');
    detail.setAttribute('aria-label', 'Faster or slower');
    detail.innerHTML = '<option value="1">One step faster</option><option value="-1">One step slower</option>';
    detail.value = String(action.d);
    detail.addEventListener('change', () => onChange({ type: 'step', d: +detail.value }));
  }
  if (detail) host.appendChild(detail);
  type.addEventListener('change', () => {
    const t = type.value;
    onChange(t === 'key' ? { type: 'key', key: 'S' } : t === 'speed' ? { type: 'speed', n: '5' } : t === 'step' ? { type: 'step', d: 1 } : { type: 'none' });
  });
}

async function loadExamples(id) {
  app.examples[id] = { ...(app.examples[id] || {}), loading: true };
  try {
    const r = await api(`/api/examples?id=${encodeURIComponent(id)}`);
    app.examples[id] = { list: r.examples, n: r.examples.length };
  } catch { delete app.examples[id]; return; }
  if (app.sel === id) renderExamples();
}

function renderEditor() {
  const form = $('#editor'), g = selected();
  if (!g) {
    form.innerHTML = '<h3>Selected gesture</h3><p class="ed-note">Pick a gesture above to rename it, change what it does, or record its examples.</p>';
    return;
  }
  const taught = g.kind === 'taught';
  form.innerHTML = `<h3>Selected gesture · ${taught ? 'taught' : 'built-in rule'}</h3>
    <div class="ed-top">
      <input type="text" id="e-name" maxlength="28" value="${esc(g.name)}" aria-label="Gesture name">
      <input type="color" id="e-color" value="${g.color}" aria-label="Gesture color" title="Its color on this page">
      <label class="mini-switch"><input type="checkbox" id="e-on" ${g.on ? 'checked' : ''}><span>In use</span></label>
    </div>
    ${taught ? '' : `<div class="field"><span>Pose</span><select id="e-rule" aria-label="Built-in pose">${Object.entries(app.builtins)
      .map(([k, b]) => `<option value="${k}">${EMOJI_OK ? `${b.emoji}  ` : ''}${esc(b.name)}</option>`).join('')}</select></div>
    <div class="field"><span>Rule</span><p class="rulebox">${ruleText(g.rule)}</p></div>`}
    <div class="field"><span>Which hand</span><select id="e-hand" aria-label="Which hand">
      <option value="any">Either hand</option><option value="left">Left hand only</option><option value="right">Right hand only</option></select></div>
    <div class="field"><span>Makes the car</span><div class="action-pick" id="e-action"></div></div>
    ${taught ? `<div class="field"><span>Examples</span><div>
      <div class="rec-row">
        <button type="button" class="btn rec" id="e-rec">${g.examples ? 'Record again (20)' : 'Record 20 examples'}</button>
        <button type="button" class="btn quiet" id="e-more" ${g.examples ? '' : 'hidden'}>Add 10 more</button>
        <button type="button" class="btn quiet" id="e-clear" ${g.examples ? '' : 'hidden'}>Clear all</button>
      </div>
      <ul class="examples" id="e-examples"></ul></div></div>
    <p class="ed-note">Hold the pose up after the countdown and move it a little: closer, further, slightly turned. Variety makes it reliable. Record with each hand you will use. A different direction is a different gesture (point left ≠ point right).</p>` : ''}
    <div class="ed-foot">
      <span class="grow"></span>
      <button type="button" class="btn quiet" id="e-up" ${app.cfg.gestures.indexOf(g) === 0 ? 'disabled' : ''}>Move up</button>
      <button type="button" class="btn quiet" id="e-down" ${app.cfg.gestures.indexOf(g) === app.cfg.gestures.length - 1 ? 'disabled' : ''}>Move down</button>
      <button type="button" class="btn" id="e-del">Delete</button>
    </div>`;

  $('#e-name').addEventListener('input', (e) => {
    g.name = e.target.value.slice(0, 28) || g.id;
    edited(false);
    const li = $(`#chips .chip[data-id="${g.id}"] .chip-name span`);
    if (li) li.textContent = g.name;
  });
  $('#e-name').addEventListener('change', () => edited());
  $('#e-color').addEventListener('input', (e) => { g.color = e.target.value; edited(); });
  $('#e-on').addEventListener('change', (e) => { g.on = e.target.checked; edited(); });
  $('#e-hand').value = g.hand;
  $('#e-hand').addEventListener('change', (e) => { g.hand = e.target.value; edited(); });
  if (!taught) {
    $('#e-rule').value = g.rule;
    $('#e-rule').addEventListener('change', (e) => {
      const old = app.builtins[g.rule]?.name;
      g.rule = e.target.value;
      if (g.name === old) g.name = app.builtins[g.rule].name;      // keep a default name in step
      edited();
      renderEditor();
    });
  }
  actionPicker($('#e-action'), g.action, (a) => { g.action = a; edited(); renderEditor(); });
  if (taught) {
    $('#e-rec').addEventListener('click', () => record(g, 20, true));
    $('#e-more').addEventListener('click', () => record(g, 10, false));
    $('#e-clear').addEventListener('click', async () => {
      if (!confirm(`Delete all ${g.examples} examples of “${g.name}”?`)) return;
      try { await api('/api/examples/delete', { id: g.id, all: true }); } catch (e) { toast(e.message); }
    });
    if (g.examples && app.examples[g.id]?.n !== g.examples) loadExamples(g.id);
    else renderExamples();
  }
  $('#e-up').addEventListener('click', () => move(g, -1));
  $('#e-down').addEventListener('click', () => move(g, 1));
  $('#e-del').addEventListener('click', () => {
    if (!confirm(`Delete the gesture “${g.name}”${taught && g.examples ? ` and its ${g.examples} examples` : ''}?`)) return;
    app.cfg.gestures = app.cfg.gestures.filter((x) => x !== g);
    app.sel = app.cfg.gestures[0]?.id || null;
    edited();
    renderEditor();
  });
}

function renderExamples() {
  const g = selected(), ul = $('#e-examples');
  if (!g || !ul) return;
  const ex = app.examples[g.id];
  if (!g.examples) { ul.innerHTML = ''; return; }
  if (!ex?.list) { ul.innerHTML = '<li></li>'.repeat(Math.min(g.examples, 6)); return; }
  const near = app.st?.nearest?.id === g.id ? app.st.nearest.index : -1;
  ul.innerHTML = ex.list.map((e, i) => `<li class="${i === near ? 'near' : ''}" title="Example ${i + 1} · ${e.hand} hand">
    <svg viewBox="${fitBox(e.norm, 0.3)}" aria-hidden="true">${bones(e.norm)}</svg><small>${i + 1}${e.hand[0]}</small>
    <button type="button" data-i="${i}" aria-label="Delete example ${i + 1}">✕</button></li>`).join('');
  for (const b of $$('button', ul)) {
    b.addEventListener('click', async () => {
      try {
        await api('/api/examples/delete', { id: g.id, index: +b.dataset.i });
        app.examples[g.id].list.splice(+b.dataset.i, 1);
        app.examples[g.id].n -= 1;
        g.examples -= 1;
        renderExamples();
      } catch (e) { toast(e.message); }
    });
  }
}

function move(g, d) {
  const a = app.cfg.gestures, i = a.indexOf(g), j = i + d;
  if (j < 0 || j >= a.length) return;
  [a[i], a[j]] = [a[j], a[i]];
  edited();
  renderEditor();
}

// ---------------------------------------------------------------- recording

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
async function record(g, count, replace) {
  if (app.rec) return;
  if (replace && g.examples && !confirm(`Replace the ${g.examples} examples of “${g.name}” with new ones?`)) return;
  app.rec = { id: g.id, phase: 'count' };
  $('#sense').scrollIntoView({ behavior: 'smooth', block: 'nearest' });
  const box = $('#countdown');
  box.hidden = false;
  $('#count-fill').style.width = '0%';
  for (const n of [3, 2, 1]) {
    $('#count-num').textContent = n;
    $('#count-text').textContent = `Get ready: show “${g.name}”`;
    await sleep(800);
  }
  try {
    await api('/api/record', { id: g.id, count, replace });
    app.rec.phase = 'rec';
    app.rec.want = count;
    $('#count-num').textContent = '●';
    $('#count-text').textContent = 'Recording: hold it, move it a little';
  } catch (e) { toast(e.message); box.hidden = true; app.rec = null; }
}
function watchRecording() {
  const r = app.st.recording;
  if (!app.rec || app.rec.phase !== 'rec') return;
  if (r) {
    $('#count-fill').style.width = `${(r.got / r.want) * 100}%`;
    $('#count-num').textContent = `${r.got}`;
    $('#count-text').textContent = app.st.hand ? `Recording ${r.got} of ${r.want}: hold it, move it a little` : 'Show your hand to the camera…';
    return;
  }
  const g = gest(app.rec.id);
  $('#countdown').hidden = true;
  app.rec = null;
  delete app.examples[g?.id];
  reloadConfig().then(() => { if (g) toast(`“${g.name}” has ${gest(g.id)?.examples ?? 0} examples. Try it!`); });
}

// ---------------------------------------------------------------- policy rules

function renderRules() {
  const c = app.cfg;
  if (document.activeElement !== $('#r-hold')) $('#r-hold').value = c.hold;
  $('#r-hold-out').textContent = `${c.hold} fr`;
  if (document.activeElement !== $('#r-radius')) $('#r-radius').value = Math.round(c.radius * 100);
  $('#r-radius-out').textContent = c.radius.toFixed(2);
  if (document.activeElement !== $('#r-rule')) $('#r-rule').value = Math.round(c.rule_min * 100);
  $('#r-rule-out').textContent = c.rule_min.toFixed(2);
  $$('#r-model button').forEach((b) => b.setAttribute('aria-pressed', String(+b.dataset.model === c.model)));
  $$('#r-workers button').forEach((b) => b.setAttribute('aria-pressed', String(+b.dataset.workers === (c.workers || 2))));
  $('#mirror').checked = c.mirror;
  actionPicker($('#r-nothing'), c.nothing, (a) => { c.nothing = a; edited(false); renderRules(); }, true);
}
$('#r-hold').addEventListener('input', (e) => { app.cfg.hold = +e.target.value; $('#r-hold-out').textContent = `${app.cfg.hold} fr`; edited(false); });
$('#r-radius').addEventListener('input', (e) => { app.cfg.radius = +e.target.value / 100; $('#r-radius-out').textContent = app.cfg.radius.toFixed(2); edited(false); });
$('#r-rule').addEventListener('input', (e) => { app.cfg.rule_min = +e.target.value / 100; $('#r-rule-out').textContent = app.cfg.rule_min.toFixed(2); edited(false); });
$$('#r-model button').forEach((b) => b.addEventListener('click', () => { app.cfg.model = +b.dataset.model; edited(false); renderRules(); }));
$$('#r-workers button').forEach((b) => b.addEventListener('click', () => { app.cfg.workers = +b.dataset.workers; edited(false); renderRules(); }));
$('#mirror').addEventListener('change', (e) => {
  app.cfg.mirror = e.target.checked;
  app.examples = {};                         // examples are re-flipped by the Pi for the new view
  edited(false);
  renderLive();
  toast(e.target.checked ? 'Mirrored: your left is the screen\'s left' : 'Not mirrored: the camera\'s own view');
});

// ---------------------------------------------------------------- top-level controls

$('#output').addEventListener('click', async () => {
  const on = !(app.st && app.st.output);
  try { await api('/api/output', { on }); } catch (e) { toast(e.message); }
});
$('#car-btn').addEventListener('click', () => {
  const take = $('#car-btn').dataset.take === 'true';
  api('/api/car', { take }).then(() => toast(take ? 'Looking for the car…' : 'Car released')).catch((e) => toast(e.message));
});
$$('#mode button').forEach((b) => b.addEventListener('click', () => api('/api/mode', { mode: b.dataset.mode }).catch((e) => toast(e.message))));
$$('#source button').forEach((b) => b.addEventListener('click', () => api('/api/source', { source: b.dataset.source }).catch((e) => toast(e.message))));
$('#speed').addEventListener('input', (e) => { $('#speed-out').textContent = speedText(SPEEDS[+e.target.value]); });
$('#speed').addEventListener('change', (e) => api('/api/speed', { n: SPEEDS[+e.target.value] }).catch((er) => toast(er.message)));

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

$('#teach').addEventListener('click', () => teachNew());
$('#add-builtin').addEventListener('click', () => {
  const used = new Set(app.cfg.gestures.filter((g) => g.kind === 'builtin').map((g) => g.rule));
  $('#catalog').innerHTML = Object.entries(app.builtins).map(([k, b]) =>
    `<li><button type="button" data-rule="${k}" title="${used.has(k) ? 'Already in your list (adding it again lets you use a different hand)' : ''}"><span class="${EMOJI_OK ? '' : 'cat-glyph'}">${EMOJI_OK ? b.emoji : esc(glyphText(k))}</span>${esc(b.name)}${used.has(k) ? ' ✓' : ''}</button></li>`).join('');
  for (const b of $$('#catalog button')) b.addEventListener('click', () => addBuiltin(b.dataset.rule));
  $('#builtin-dlg').showModal();
});
$('#bi-close').addEventListener('click', () => $('#builtin-dlg').close());
$('#export').addEventListener('click', () => { location.href = '/api/export'; });
$('#import').addEventListener('click', () => $('#import-file').click());
$('#import-file').addEventListener('change', async (e) => {
  const f = e.target.files[0];
  e.target.value = '';
  if (!f) return;
  try {
    const d = JSON.parse(await f.text());
    if (!confirm(`Replace your ${app.cfg.gestures.length} gestures with the ${d.config?.gestures?.length ?? '?'} in “${f.name}”?`)) return;
    const r = await api('/api/import', d);
    app.cfg = r.config;
    app.examples = {};
    app.sel = app.cfg.gestures[0]?.id || null;
    renderAll();
    toast(`Imported ${app.cfg.gestures.length} gestures`);
  } catch (er) { toast(`Import failed: ${er.message}`); }
});
$('#reset').addEventListener('click', async () => {
  if (!confirm('Put back the eight starter gestures? Your taught gestures and their examples are deleted (Export first to keep them).')) return;
  try {
    const r = await api('/api/config/reset', {});
    app.cfg = r.config;
    app.examples = {};
    app.sel = app.cfg.gestures[0]?.id;
    renderAll();
    toast('Back to the starter gestures');
  } catch (e) { toast(e.message); }
});

$('#theme').addEventListener('click', () => {
  const dark = (document.documentElement.dataset.theme || (matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light')) === 'dark';
  document.documentElement.dataset.theme = dark ? 'light' : 'dark';
  store.set('theme', dark ? 'light' : 'dark');
});
$('#link-rc').href = `${location.protocol}//${location.hostname}:8081/`;
$('#link-cam').href = `${location.protocol}//${location.hostname}:8000/`;

// ---------------------------------------------------------------- boot

function renderAll() {
  if (!gest(app.sel)) app.sel = app.cfg.gestures[0]?.id || null;
  renderChips();
  renderEditor();
  renderRules();
}

async function boot() {
  try {
    const [cfg, builtins] = await Promise.all([api('/api/config'), api('/api/builtins')]);
    app.cfg = cfg;
    app.builtins = Object.fromEntries(builtins.map((b) => [b.rule, b]));
  } catch (e) {
    toast(`The Pi did not answer: ${e.message}`);
    setTimeout(boot, 2000);
    return;
  }
  app.sel = store.get('sel', null);
  renderAll();
  setStream(true);
  setLive(true);
  poll();
}
boot();
window.gesturePilot = app;   // handy from the browser console

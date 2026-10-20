/* ==========================================================================
   Seline — Voice-First UI Controller
   Mic toggle → STT → chat → TTS, orb amplitude, activity panel,
   chat sidebar, model swapper, kill switch, safety gate.
   ========================================================================== */

// ---------------------------------------------------------------------------
// State machine: idle | listening | thinking | speaking
// ---------------------------------------------------------------------------
let uiState = 'idle';
let audioCtx = null;
let micAnalyser = null;
let ttsAnalyser = null;
let nextStartTime = 0;

const HINTS = {
  idle: "Tap or say 'Hey Seline'",
  listening: 'Listening… tap to stop',
  thinking: 'Processing…',
  speaking: 'Speaking…',
};

function setUIState(state) {
  uiState = state;

  const dot = document.getElementById('status-dot');
  if (dot) {
    dot.className = 'status-dot';
    if (state === 'listening') dot.classList.add('listening');
    if (state === 'thinking') dot.classList.add('processing');
    if (state === 'speaking') dot.classList.add('speaking');
  }

  const micBtn = document.getElementById('mic-button');
  if (micBtn) micBtn.classList.toggle('listening', state === 'listening');

  const hint = document.getElementById('mic-hint');
  if (hint) hint.textContent = HINTS[state] || HINTS.idle;

  window.SelineOrb?.setState(state);
}

// Drive orb brightness from whichever audio source is live.
function brightnessLoop() {
  requestAnimationFrame(brightnessLoop);
  let v = 0;
  if (uiState === 'listening' && micAnalyser) {
    v = readRMS(micAnalyser);
  } else if (uiState === 'speaking' && ttsAnalyser) {
    v = readRMS(ttsAnalyser);
  }
  window.SelineOrb?.setBrightness(Math.min(1, v * 3.2));
}

function readRMS(analyser) {
  const buf = new Float32Array(analyser.fftSize);
  analyser.getFloatTimeDomainData(buf);
  let sum = 0;
  for (let i = 0; i < buf.length; i++) sum += buf[i] * buf[i];
  return Math.sqrt(sum / buf.length);
}

function ensureAudioCtx() {
  if (!audioCtx) {
    audioCtx = new (window.AudioContext || window.webkitAudioContext)({ sampleRate: 16000 });
    ttsAnalyser = audioCtx.createAnalyser();
    ttsAnalyser.fftSize = 512;
    ttsAnalyser.connect(audioCtx.destination);
  }
  if (audioCtx.state === 'suspended') audioCtx.resume();
}

// ---------------------------------------------------------------------------
// Microphone — click to start, click to stop
// ---------------------------------------------------------------------------
let mediaRecorder = null;
let audioChunks = [];
let micStream = null;

async function startListening() {
  try {
    micStream = await navigator.mediaDevices.getUserMedia({ audio: true });
  } catch (e) {
    showCard('error', 'Microphone access denied.', 'Mic');
    appendTranscript('error', 'Microphone access denied.');
    return;
  }

  ensureAudioCtx();
  const src = audioCtx.createMediaStreamSource(micStream);
  micAnalyser = audioCtx.createAnalyser();
  micAnalyser.fftSize = 512;
  src.connect(micAnalyser);

  mediaRecorder = new MediaRecorder(micStream);
  audioChunks = [];
  mediaRecorder.ondataavailable = (e) => audioChunks.push(e.data);
  mediaRecorder.onstop = onRecordingStopped;
  mediaRecorder.start();

  setUIState('listening');
  dispatchMicToggle(true);
}

function stopListening() {
  if (mediaRecorder && mediaRecorder.state !== 'inactive') {
    mediaRecorder.stop();
  }
  if (micStream) {
    micStream.getTracks().forEach(t => t.stop());
    micStream = null;
  }
  micAnalyser = null;
  dispatchMicToggle(false);
}

function toggleMic() {
  if (uiState === 'listening') {
    stopListening();
  } else if (uiState === 'idle') {
    startListening();
  }
}

function dispatchMicToggle(listening) {
  window.dispatchEvent(new CustomEvent('seline:mic-toggle', { detail: { listening } }));
}

async function onRecordingStopped() {
  setUIState('thinking');
  const mimeType = (mediaRecorder && mediaRecorder.mimeType) || 'audio/webm';
  const audioBlob = new Blob(audioChunks, { type: mimeType });
  const formData = new FormData();
  formData.append('file', audioBlob, `audio.${mimeType.split('/')[1] || 'webm'}`);

  try {
    const response = await fetch('/api/voice/stt', { method: 'POST', body: formData });
    const data = await response.json();
    if (data.status === 'success' && data.text) {
      await sendMessage(data.text);
    } else if (data.status === 'success') {
      showCard('error', 'Could not understand any audio.', 'STT');
      appendTranscript('error', 'Could not understand any audio.');
      setUIState('idle');
    } else {
      showCard('error', data.message || 'Could not understand audio.', 'STT');
      appendTranscript('error', data.message || 'Could not understand audio.');
      setUIState('idle');
    }
  } catch (e) {
    showCard('error', 'STT system failure.', 'STT');
    appendTranscript('error', 'STT system failure.');
    setUIState('idle');
  }
}

// ---------------------------------------------------------------------------
// Chat
// ---------------------------------------------------------------------------
async function sendMessage(text) {
  const message = (text || '').trim();
  if (!message) return;

  appendTranscript('user', message);
  setUIState('thinking');

  try {
    const response = await fetch('/api/chat', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ message }),
    });
    const data = await response.json();

    if (data.status === 'success') {
      const reply = data.reply;
      showCard('reply', reply, 'Seline');
      appendTranscript('assistant', reply);
      await playAssistantAudioStream(reply);
    } else {
      showCard('error', data.message || 'Unknown error', 'Error');
      appendTranscript('error', data.message || 'Unknown error');
    }
  } catch (e) {
    showCard('error', 'Could not connect to Jarvis Core.', 'Error');
    appendTranscript('error', 'Could not connect to Jarvis Core.');
  } finally {
    setUIState('idle');
  }
}

// ---------------------------------------------------------------------------
// TTS playback — PCM 16kHz chunked stream (proven pattern from the old dashboard)
// ---------------------------------------------------------------------------
async function playAssistantAudioStream(text) {
  if (!text) return;

  try {
    setUIState('speaking');

    const response = await fetch('/api/voice/tts', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ text }),
    });

    if (!response.ok) {
      let reason = `TTS unavailable (HTTP ${response.status})`;
      try {
        const err = await response.json();
        if (err && err.message) reason = err.message;
      } catch (e) { /* non-JSON error body */ }
      console.warn(reason);
      return;
    }

    ensureAudioCtx();
    const reader = response.body.getReader();
    nextStartTime = audioCtx.currentTime;

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;

      const int16Data = new Int16Array(value.buffer, value.byteOffset, value.byteLength / 2);
      const float32Data = new Float32Array(int16Data.length);
      for (let i = 0; i < int16Data.length; i++) {
        float32Data[i] = int16Data[i] / 32768.0;
      }

      const buffer = audioCtx.createBuffer(1, float32Data.length, 16000);
      buffer.copyToChannel(float32Data, 0);

      const source = audioCtx.createBufferSource();
      source.buffer = buffer;
      source.connect(ttsAnalyser);

      const startAt = Math.max(nextStartTime, audioCtx.currentTime);
      source.start(startAt);
      nextStartTime = startAt + buffer.duration;
    }

    await new Promise(resolve => {
      const checkEnd = setInterval(() => {
        if (audioCtx.currentTime >= nextStartTime) {
          clearInterval(checkEnd);
          resolve();
        }
      }, 100);
    });
  } catch (err) {
    console.error('Streaming audio error:', err);
  }
}

// ---------------------------------------------------------------------------
// Floating response cards
// ---------------------------------------------------------------------------
const CARD_SLOTS = [
  { left: 'calc(50% - 390px)', top: '30%' },
  { left: 'calc(50% + 150px)', top: '38%' },
  { left: 'calc(50% - 370px)', top: '56%' },
];
const activeCards = [];

function showCard(kind, text, label) {
  const layer = document.getElementById('cards-layer');
  if (!layer) return;

  const card = document.createElement('div');
  card.className = 'response-card' + (kind === 'error' ? ' error' : '');
  card.style.pointerEvents = 'auto';
  card.style.cursor = 'pointer';
  card.title = 'Click to dismiss';

  const safeLabel = document.createElement('span');
  safeLabel.className = 'card-label';
  safeLabel.textContent = label || 'Seline';

  const body = document.createElement('div');
  body.textContent = text;

  const meta = document.createElement('span');
  meta.className = 'card-meta';
  meta.textContent = monoTime();

  card.append(safeLabel, body, meta);
  card.addEventListener('click', () => dismissCard(card));

  layer.appendChild(card);
  activeCards.push(card);
  relayoutCards();

  // Notices and long replies shouldn't linger forever.
  setTimeout(() => dismissCard(card), kind === 'notice' ? 15000 : 30000);
}

function dismissCard(card) {
  const idx = activeCards.indexOf(card);
  if (idx === -1) return;
  activeCards.splice(idx, 1);
  card.classList.add('fading');
  setTimeout(() => card.remove(), 500);
  relayoutCards();
}

function relayoutCards() {
  activeCards.forEach((card, i) => {
    const slot = CARD_SLOTS[i % CARD_SLOTS.length];
    card.style.left = slot.left;
    card.style.top = slot.top;
  });
  while (activeCards.length > CARD_SLOTS.length) {
    dismissCard(activeCards[0]);
  }
}

// ---------------------------------------------------------------------------
// Chat sidebar
// ---------------------------------------------------------------------------
function appendTranscript(kind, text) {
  const box = document.getElementById('transcript-messages');
  if (!box) return;
  const div = document.createElement('div');
  div.className = `transcript-msg ${kind}`;
  div.textContent = text;
  const meta = document.createElement('span');
  meta.className = 'msg-meta';
  meta.textContent = `${kind} • ${monoTime()}`;
  div.appendChild(meta);
  box.appendChild(div);
  box.scrollTop = box.scrollHeight;
}

function toggleChatSidebar(force) {
  const sidebar = document.getElementById('chat-sidebar');
  const collapse = typeof force === 'boolean' ? !force : !sidebar.classList.contains('collapsed');
  sidebar.classList.toggle('collapsed', collapse);
  if (!collapse) document.getElementById('transcript-input')?.focus();
}

function monoTime() {
  return new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
}

// ---------------------------------------------------------------------------
// Activity panel — real Jarvis data
// ---------------------------------------------------------------------------
const noticesSeen = [];

async function loadPanelData() {
  await Promise.allSettled([loadReminders(), loadMemories(), loadAudit()]);
  renderNotices();
  updateAlertsBadge();
}

async function loadReminders() {
  try {
    const res = await fetch('/api/reminders');
    const reminders = await res.json();
    setPanelSection('reminders', reminders.length, reminders.slice(0, 4).map(r => ({
      text: r.text,
      meta: `fires ${r.trigger_at}`,
    })));
    return reminders.length;
  } catch (e) {
    setPanelSection('reminders', 0, []);
  }
}

async function loadMemories() {
  try {
    const res = await fetch('/api/memories');
    const memories = await res.json();
    setPanelSection('memories', memories.length, memories.slice(-3).reverse().map(m => ({
      text: m.content,
      meta: `#${m.id} • ${m.category} • ${String(m.created_at).substring(0, 10)}`,
    })));
  } catch (e) {
    setPanelSection('memories', 0, []);
  }
}

async function loadAudit() {
  try {
    const res = await fetch('/api/audit?limit=10');
    const data = await res.json();
    const logs = (data.logs || []).slice(0, 4);
    setPanelSection('audit', data.logs ? data.logs.length : 0, logs.map(l => ({
      text: l.length > 90 ? l.substring(0, 90) + '…' : l,
      meta: '',
    })));
  } catch (e) {
    setPanelSection('audit', 0, []);
  }
}

function renderNotices() {
  setPanelSection('notices', noticesSeen.length, noticesSeen.slice(0, 4).map(n => ({
    text: n.text,
    meta: n.time,
  })));
}

function setPanelSection(name, count, entries) {
  const countEl = document.getElementById(`panel-count-${name}`);
  const listEl = document.getElementById(`panel-list-${name}`);
  if (!countEl || !listEl) return;

  countEl.textContent = count;
  listEl.innerHTML = '';

  if (!entries.length) {
    const empty = document.createElement('div');
    empty.className = 'panel-empty';
    empty.textContent = 'Nothing yet.';
    listEl.appendChild(empty);
    return;
  }

  entries.forEach((entry, i) => {
    const div = document.createElement('div');
    div.className = 'panel-entry';
    div.style.animationDelay = `${i * 40}ms`;
    div.textContent = entry.text;
    if (entry.meta) {
      const meta = document.createElement('span');
      meta.className = 'entry-meta';
      meta.textContent = entry.meta;
      div.appendChild(meta);
    }
    listEl.appendChild(div);
  });
}

function updateAlertsBadge() {
  const badge = document.getElementById('alerts-badge');
  if (!badge) return;
  const n = noticesSeen.length;
  badge.textContent = n;
  badge.classList.toggle('hidden', n === 0);
}

// Single poller for /api/notices — the endpoint flushes on read.
async function pollNotices() {
  try {
    const res = await fetch('/api/notices');
    const data = await res.json();
    for (const notice of data.notices || []) {
      noticesSeen.unshift({ text: notice, time: monoTime() });
      if (noticesSeen.length > 10) noticesSeen.pop();
      showCard('notice', notice, 'Notice');
      appendTranscript('assistant', notice);
    }
    renderNotices();
    updateAlertsBadge();
  } catch (e) { /* server unreachable — try again next tick */ }
}

// ---------------------------------------------------------------------------
// Safety gate — dashboard parity: approve/deny pending tool confirmations
// ---------------------------------------------------------------------------
let activeConfirmationId = null;

async function pollPendingConfirmations() {
  try {
    const res = await fetch('/api/confirmation/pending');
    const data = await res.json();
    const requests = data.requests || [];
    const modal = document.getElementById('safety-modal');
    if (requests.length > 0 && modal.classList.contains('hidden')) {
      const req = requests[0];
      activeConfirmationId = req.id;
      document.getElementById('modal-action-name').textContent = req.action;
      document.getElementById('modal-reason-text').textContent = req.reason;
      document.getElementById('modal-action-args').textContent = JSON.stringify(req.args, null, 2);
      modal.classList.remove('hidden');
    }
  } catch (e) { /* try again on next tick */ }
}

async function respondConfirmation(approved) {
  document.getElementById('safety-modal').classList.add('hidden');
  if (activeConfirmationId == null) return;
  const requestId = activeConfirmationId;
  activeConfirmationId = null;
  try {
    await fetch('/api/confirmation', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ request_id: requestId, approved }),
    });
  } catch (e) {
    console.error('Failed to send confirmation', e);
  }
  pollPendingConfirmations();
}

// ---------------------------------------------------------------------------
// Model swapper + kill switch
// ---------------------------------------------------------------------------
async function toggleModelMenu(force) {
  const menu = document.getElementById('model-menu');
  const show = typeof force === 'boolean' ? force : menu.classList.contains('hidden');
  menu.classList.toggle('hidden', !show);
  if (show) await loadModelMenu();
}

async function loadModelMenu() {
  const list = document.getElementById('model-menu-list');
  list.innerHTML = '<div class="panel-empty">Loading…</div>';
  try {
    const res = await fetch('/api/models');
    const data = await res.json();
    const models = data.models || [];
    const current = data.current;
    list.innerHTML = '';
    for (const m of models) {
      const btn = document.createElement('button');
      btn.className = 'model-item' + (m === current ? ' current' : '');
      const dot = document.createElement('span');
      dot.className = 'model-dot';
      const label = document.createElement('span');
      label.textContent = m;
      btn.append(dot, label);
      btn.addEventListener('click', () => switchModel(m));
      list.appendChild(btn);
    }
    const dotEl = document.getElementById('status-dot');
    if (dotEl && current) dotEl.title = `Model: ${current}`;
  } catch (e) {
    list.innerHTML = '<div class="panel-empty">Could not load models.</div>';
  }
}

async function switchModel(name) {
  toggleModelMenu(false);
  try {
    const res = await fetch('/api/model', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ model: name }),
    });
    const data = await res.json();
    const active = data.model || name;
    showCard('notice', `Model switched to ${active}`, 'System');
    const dotEl = document.getElementById('status-dot');
    if (dotEl) dotEl.title = `Model: ${active}`;
  } catch (e) {
    showCard('error', 'Could not switch model.', 'System');
  }
}

async function initKillswitch() {
  try {
    const res = await fetch('/api/status');
    const status = await res.json();
    document.getElementById('killswitch-btn').classList.toggle('danger', !!status.killswitch_active);
    const dotEl = document.getElementById('status-dot');
    if (dotEl && status.model) dotEl.title = `Model: ${status.model}`;
  } catch (e) { /* server unreachable */ }
}

async function toggleKillswitch() {
  const btn = document.getElementById('killswitch-btn');
  const active = btn.classList.contains('danger');
  if (!confirm(active ? 'Resume the heartbeat engine?' : 'Pause the heartbeat engine (kill switch)?')) return;
  try {
    const res = await fetch('/api/killswitch', { method: 'POST' });
    const data = await res.json();
    btn.classList.toggle('danger', !!data.active);
    showCard('notice', data.active ? 'Heartbeat paused (kill switch ON).' : 'Heartbeat resumed.', 'System');
  } catch (e) {
    showCard('error', 'Kill switch toggle failed.', 'System');
  }
}

// ---------------------------------------------------------------------------
// Wiring
// ---------------------------------------------------------------------------
document.addEventListener('DOMContentLoaded', () => {
  document.getElementById('mic-button').addEventListener('click', toggleMic);

  document.getElementById('model-btn').addEventListener('click', (e) => {
    e.stopPropagation();
    toggleModelMenu();
  });
  document.getElementById('killswitch-btn').addEventListener('click', toggleKillswitch);
  document.addEventListener('click', (e) => {
    const menu = document.getElementById('model-menu');
    if (!menu.classList.contains('hidden') && !menu.contains(e.target)) {
      toggleModelMenu(false);
    }
  });
  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') toggleModelMenu(false);
  });
  initKillswitch();

  document.getElementById('chat-collapse').addEventListener('click', () => toggleChatSidebar(false));
  document.getElementById('chat-handle').addEventListener('click', () => toggleChatSidebar(true));
  document.getElementById('header-transcript-btn').addEventListener('click', () => toggleChatSidebar());

  const input = document.getElementById('transcript-input');
  const sendTyped = () => {
    const text = input.value.trim();
    if (!text) return;
    input.value = '';
    sendMessage(text);
  };
  input.addEventListener('keydown', (e) => {
    if (e.key === 'Enter') sendTyped();
  });
  document.getElementById('transcript-send').addEventListener('click', sendTyped);

  document.addEventListener('keydown', (e) => {
    if ((e.key === 't' || e.key === 'T') && document.activeElement !== input) {
      toggleChatSidebar();
    }
  });

  const panel = document.getElementById('activity-panel');
  document.getElementById('panel-toggle').addEventListener('click', () => {
    panel.classList.toggle('collapsed');
  });
  document.getElementById('alerts-btn').addEventListener('click', () => {
    panel.classList.remove('collapsed');
  });

  document.getElementById('btn-modal-approve').addEventListener('click', () => respondConfirmation(true));
  document.getElementById('btn-modal-deny').addEventListener('click', () => respondConfirmation(false));

  setUIState('idle');
  brightnessLoop();
  loadPanelData();
  pollNotices();
  setInterval(loadPanelData, 30000);
  setInterval(pollNotices, 30000);
  setInterval(pollPendingConfirmations, 2000);
});

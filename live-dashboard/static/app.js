const canvas = document.getElementById('cluster');
const ctx = canvas.getContext('2d');
const meta = document.getElementById('meta');
const statusEl = document.getElementById('ws-status');
const voiceIndicatorEl = document.getElementById('voice-indicator');
const voiceLabelEl = document.getElementById('voice-label');
const voiceDetailEl = document.getElementById('voice-detail');
const voiceLedGroups = [1, 2, 3, 4, 5, 6].map((level) => Array.from(document.querySelectorAll(`.voice-led.l${level}`)));
const voiceCoreDotEls = Array.from(document.querySelectorAll('.voice-core-dot'));
const personalityStatus = document.getElementById('personality-status');
const personalityQuiet = document.getElementById('personality-quiet');
const personalityHumor = document.getElementById('personality-humor');
let personalityRequestActive = false;
let queuedPersonalityChange = null;

async function refreshPersonality(change = null) {
  if (personalityRequestActive) {
    if (change) queuedPersonalityChange = { ...queuedPersonalityChange, ...change };
    return;
  }
  personalityRequestActive = true;
  try {
    const params = change ? `?${new URLSearchParams(change)}` : '';
    const response = await fetch(`/api/personality${params}`, {
      method: change ? 'POST' : 'GET',
      cache: 'no-store',
      signal: AbortSignal.timeout(1200),
    });
    if (!response.ok) throw new Error('speech service unavailable');
    const current = await response.json();
    const stage = current.stage == null ? '档位未就绪' : `H${current.stage}`;
    const mic = { listening: '监听中', idle: '待命' }[current.microphone] || '状态未知';
    const playback = { playing: '播报中', idle: '待命' }[current.playback] || '状态未知';
    personalityStatus.textContent = `${stage} · 麦克风${mic} · 电台${playback}`;
    personalityQuiet.checked = current.quiet;
    personalityHumor.value = current.humor;
    personalityQuiet.disabled = false;
    personalityHumor.disabled = false;
  } catch {
    personalityStatus.textContent = '人格状态未连接';
    personalityQuiet.disabled = true;
    personalityHumor.disabled = true;
  } finally {
    personalityRequestActive = false;
    if (queuedPersonalityChange) {
      const next = queuedPersonalityChange;
      queuedPersonalityChange = null;
      refreshPersonality(next);
    }
  }
}

personalityQuiet.addEventListener('change', () => refreshPersonality({ quiet: personalityQuiet.checked }));
personalityHumor.addEventListener('change', () => refreshPersonality({ humor: personalityHumor.value }));
setInterval(refreshPersonality, 1000);
refreshPersonality();

const state = {
  current: null,
  smoothSpeed: 0,
  smoothRpm: 0,
  smoothErs: 0,
  smoothFuel: 0,
  hasSeededLiveValues: false,
  boot: { active: false, progress: 1, elapsedMs: 0 },
  voiceMeterTarget: 0,
  voiceMeterPeakTarget: 0,
  voiceMeterLevel: 0,
  voiceMeterPeakLevel: 0,
  voiceBeatPulseTarget: 0,
  voiceBeatPulseLevel: 0,
  voiceBeatTriggeredAtMs: 0,
};

const demoPayload = {
  session: { track: 'Standby', lap_number: 0, total_laps: 0, position: 0, weather: 'N/A' },
  car: { speed_kph: 0, gear: 0, rpm: 0, drs_open: false, ers_pct: 0, fuel_laps_remaining: 0 },
  tyres: { wear_pct_corners: [0, 0, 0, 0], surface_temperature_c: [0, 0, 0, 0], inner_temperature_c: [0, 0, 0, 0] },
  damage: { body_damage_pct: 0, powertrain_damage_pct: 0 },
  gaps: { ahead_s: null, behind_s: null, ahead_source: 'missing', behind_source: 'missing', front_rival_name: '-', rear_rival_name: '-' },
  voice: {
    state: 'idle',
    active: false,
    pending: false,
    action_code: null,
    source_kind: null,
    llm_sidecar_used: false,
    llm_sidecar_status: null,
    amplitude_level: 0,
    amplitude_peak: 0,
    amplitude_rms: null,
    amplitude_updated_at_ms: 0,
    amplitude_source: null,
    amplitude_playback_active: false,
    beat_pulse: 0,
    beat_updated_at_ms: 0,
  },
  strategy: { primary_action: 'NONE', title: 'Standby', detail: '', priority: 0 },
};

const SPEED_SCALE_EXPONENT = 1.9;
const SPEED_SCALE_BLEND = 0.6;
const SHIFT_LIGHT_START_RPM = 10800;
const SHIFT_LIGHT_PEAK_RPM = 13400;
const SHIFT_LIGHT_PULSE_RPM = 13000;
const FEED_POLL_MS = 16;
const BOOT_DURATION_MS = 2200;
let pollTimer = null;
let ws = null;
let wsRetryTimer = null;
let lastPayloadTimestamp = 0;

function renderFeedStatus(transport, payload) {
  const source = (payload.source_status || {}).status || 'unavailable';
  statusEl.textContent = `Feed: ${transport} / ${source}`;
}

function applyIncomingPayload(payload) {
  state.current = payload;
  state.voiceMeterTarget = clamp01(Number((payload.voice || {}).amplitude_level || 0));
  state.voiceMeterPeakTarget = clamp01(Number((payload.voice || {}).amplitude_peak || 0));
  const voicePayload = payload.voice || {};
  const playbackActive = Boolean(voicePayload.amplitude_playback_active);
  const beatPulse = playbackActive ? clamp01(Number(voicePayload.beat_pulse || 0)) : 0;
  const beatUpdatedAtMs = Number((payload.voice || {}).beat_updated_at_ms || 0);
  if (beatPulse > 0 && beatUpdatedAtMs > state.voiceBeatTriggeredAtMs) {
    state.voiceBeatTriggeredAtMs = beatUpdatedAtMs;
    state.voiceBeatPulseTarget = Math.max(state.voiceBeatPulseTarget, beatPulse);
  }
  if (!playbackActive) {
    state.voiceBeatPulseTarget = 0;
  }
  if (!state.hasSeededLiveValues && Number(payload.timestamp_ms || 0) > 0) {
    state.smoothSpeed = payload.car.speed_kph || 0;
    state.smoothRpm = payload.car.rpm || 0;
    state.smoothErs = payload.car.ers_pct || 0;
    state.smoothFuel = payload.car.fuel_laps_remaining || 0;
    state.hasSeededLiveValues = true;
  }
  renderMeta();
  renderVoiceIndicator();
  const timestamp = Number(payload.timestamp_ms || 0);
  if (timestamp > 0 && timestamp !== lastPayloadTimestamp) {
    lastPayloadTimestamp = timestamp;
  }
}

async function pollLatest() {
  try {
    const response = await fetch(`/api/latest?_=${Date.now()}`, { cache: 'no-store' });
    if (!response.ok) {
      throw new Error(`HTTP ${response.status}`);
    }
    const payload = await response.json();
    applyIncomingPayload(payload);
    renderFeedStatus('http', payload);
  } catch (_err) {
    statusEl.textContent = 'Feed: reconnecting';
  } finally {
    pollTimer = setTimeout(pollLatest, FEED_POLL_MS);
  }
}

function scheduleWsReconnect() {
  if (wsRetryTimer) {
    return;
  }
  wsRetryTimer = setTimeout(() => {
    wsRetryTimer = null;
    connectDashboardSocket();
  }, 500);
}

function connectDashboardSocket() {
  if (ws && (ws.readyState === WebSocket.OPEN || ws.readyState === WebSocket.CONNECTING)) {
    return;
  }
  const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
  const port = 8765;
  ws = new WebSocket(`${protocol}//${window.location.hostname}:${port}`);
  statusEl.textContent = 'Feed: ws connecting';
  ws.onopen = () => {
    statusEl.textContent = 'Feed: ws / waiting';
    if (pollTimer) {
      clearTimeout(pollTimer);
      pollTimer = null;
    }
  };
  ws.onmessage = (event) => {
    try {
      const payload = JSON.parse(event.data);
      applyIncomingPayload(payload);
      renderFeedStatus('ws', payload);
    } catch (_err) {
      return;
    }
  };
  ws.onerror = () => {
    statusEl.textContent = 'Feed: ws error';
  };
  ws.onclose = () => {
    statusEl.textContent = 'Feed: fallback http';
    if (!pollTimer) {
      pollLatest();
    }
    scheduleWsReconnect();
  };
}

function startBootSequence() {
  state.boot = {
    active: true,
    progress: 0,
    elapsedMs: 0,
    startedAtMs: performance.now(),
  };
}

function lerp(current, target, alpha) {
  return current + (target - current) * alpha;
}

function smoothTowards(current, target, baseAlpha, boostAlpha, maxDelta) {
  const delta = Math.abs((target || 0) - (current || 0));
  const normalized = Math.max(0, Math.min(1, delta / maxDelta));
  const alpha = Math.max(0, Math.min(1, baseAlpha + normalized * boostAlpha));
  return lerp(current, target, alpha);
}

function easeOutCubic(t) {
  const clamped = Math.max(0, Math.min(1, t));
  return 1 - Math.pow(1 - clamped, 3);
}

function easeInOutCubic(t) {
  const clamped = Math.max(0, Math.min(1, t));
  return clamped < 0.5
    ? 4 * clamped * clamped * clamped
    : 1 - Math.pow(-2 * clamped + 2, 3) / 2;
}

function lerpNumber(a, b, t) {
  return a + (b - a) * t;
}

function clamp01(value) {
  return Math.max(0, Math.min(1, Number.isFinite(value) ? value : 0));
}

function lerpPoint(a, b, t) {
  return {
    x: a[0] + (b[0] - a[0]) * t,
    y: a[1] + (b[1] - a[1]) * t,
  };
}

function colorFromTemperature(tempC) {
  const normalized = Math.max(0, Math.min(1, ((tempC || 0) - 80) / 35));
  const mid = Math.max(0, Math.min(1, normalized * 1.15));
  const hot = Math.max(0, Math.min(1, (normalized - 0.45) / 0.55));
  const top = {
    r: Math.round(lerpNumber(255, 255, mid)),
    g: Math.round(lerpNumber(207, 164, mid)),
    b: Math.round(lerpNumber(71, 52, mid)),
  };
  const middle = {
    r: Math.round(lerpNumber(255, 255, normalized)),
    g: Math.round(lerpNumber(138, 98, normalized)),
    b: Math.round(lerpNumber(51, 44, normalized)),
  };
  const bottom = {
    r: Math.round(lerpNumber(255, 232, hot)),
    g: Math.round(lerpNumber(93, 55, hot)),
    b: Math.round(lerpNumber(53, 57, hot)),
  };
  return {
    top: `rgb(${top.r}, ${top.g}, ${top.b})`,
    middle: `rgb(${middle.r}, ${middle.g}, ${middle.b})`,
    bottom: `rgb(${bottom.r}, ${bottom.g}, ${bottom.b})`,
  };
}

function shearPointRightUp(point, origin, strength) {
  const [px, py] = point;
  const [ox, oy] = origin;
  const dy = oy - py;
  return [px + dy * strength, py];
}

function shearQuadRightUp(points, origin, strength) {
  return points.map((point) => shearPointRightUp(point, origin, strength));
}

function bootIndicatorAlpha(seed) {
  if (!state.boot || !state.boot.active) {
    return 1;
  }
  const t = state.boot.elapsedMs / 1000;
  const waveA = 0.35 + 0.65 * Math.max(0, Math.sin(t * 12.7 + seed * 0.91));
  const waveB = 0.3 + 0.7 * Math.max(0, Math.sin(t * 23.3 + seed * 1.73));
  return Math.max(0.18, Math.min(1, waveA * waveB));
}

function draw() {
  const sourcePayload = state.current || demoPayload;
  updateBootState();
  const p = applyBootPayload(sourcePayload);
  state.smoothSpeed = smoothTowards(state.smoothSpeed, p.car.speed_kph || 0, 0.022, 0.05, 150);
  state.smoothRpm = smoothTowards(state.smoothRpm, p.car.rpm || 0, 0.028, 0.065, 5500);
  state.smoothErs = smoothTowards(state.smoothErs, p.car.ers_pct || 0, 0.03, 0.05, 24);
  state.smoothFuel = smoothTowards(state.smoothFuel, p.car.fuel_laps_remaining || 0, 0.028, 0.04, 5);
  const voiceState = ((p.voice || {}).state || 'idle');
  const playbackActive = Boolean((p.voice || {}).amplitude_playback_active);
  const targetVoiceMeter = voiceState === 'active' ? state.voiceMeterTarget : 0;
  const targetVoicePeak = voiceState === 'active' ? state.voiceMeterPeakTarget : 0;
  state.voiceMeterLevel = targetVoiceMeter;
  state.voiceMeterPeakLevel = lerp(state.voiceMeterPeakLevel, targetVoicePeak, targetVoicePeak >= state.voiceMeterPeakLevel ? 0.92 : 0.6);
  if (voiceState !== 'active' || !playbackActive) {
    state.voiceBeatPulseTarget = 0;
    state.voiceBeatPulseLevel = lerp(state.voiceBeatPulseLevel, 0, 0.9);
  } else {
    const elapsedSinceBeatMs = state.voiceBeatTriggeredAtMs > 0 ? Date.now() - state.voiceBeatTriggeredAtMs : 9999;
    if (elapsedSinceBeatMs > 160) {
      state.voiceBeatPulseTarget = 0;
    }
    state.voiceBeatPulseLevel = lerp(
      state.voiceBeatPulseLevel,
      state.voiceBeatPulseTarget,
      state.voiceBeatPulseTarget >= state.voiceBeatPulseLevel ? 0.96 : 0.72,
    );
    state.voiceBeatPulseTarget *= 0.52;
  }

  ctx.clearRect(0, 0, canvas.width, canvas.height);
  drawBackground();
  drawOuterShell();
  drawSideDecorations();
  drawMainDial(p);
  drawWarningBars(p);
  drawWavePanels(p);
  drawTyrePanel(p);
  drawResourcePanel(p);
  drawCenterColumn(p);
  drawBottomLabels(p);
  drawBootOverlay();
  renderVoiceIndicator();
  requestAnimationFrame(draw);
}

function updateBootState() {
  if (!state.boot || !state.boot.active) {
    return;
  }
  const elapsedMs = performance.now() - state.boot.startedAtMs;
  const progress = Math.max(0, Math.min(1, elapsedMs / BOOT_DURATION_MS));
  state.boot.elapsedMs = elapsedMs;
  state.boot.progress = progress;
  if (progress >= 1) {
    state.boot.active = false;
  }
}

function applyBootPayload(payload) {
  if (!state.boot || !state.boot.active) {
    return payload;
  }
  const t = easeInOutCubic(state.boot.progress);
  const speedWave = Math.sin(t * Math.PI * 1.08);
  const ersWave = Math.sin(t * Math.PI);
  const rpmSweep = Math.sin(Math.min(1, t * 1.18) * Math.PI);
  return {
    ...payload,
    session: {
      ...payload.session,
      track: 'SYSTEM CHECK',
    },
    car: {
      ...payload.car,
      speed_kph: Math.max(payload.car.speed_kph || 0, 320 * speedWave),
      rpm: Math.max(payload.car.rpm || 0, Math.round(14500 * rpmSweep)),
      ers_pct: Math.max(payload.car.ers_pct || 0, Math.round(100 * ersWave)),
      fuel_laps_remaining: Math.max(payload.car.fuel_laps_remaining || 0, 9.9),
    },
    strategy: {
      ...payload.strategy,
      primary_action: 'SELF_TEST',
      title: 'System Check',
      detail: 'Cluster boot sequence',
    },
  };
}

function drawBackground() {
  const g = ctx.createRadialGradient(600, 520, 60, 600, 600, 560);
  g.addColorStop(0, '#18153f');
  g.addColorStop(0.36, '#0c0f2c');
  g.addColorStop(0.72, '#070917');
  g.addColorStop(1, '#010208');
  ctx.fillStyle = g;
  ctx.beginPath();
  ctx.arc(600, 600, 560, 0, Math.PI * 2);
  ctx.fill();

  const vignette = ctx.createRadialGradient(600, 600, 260, 600, 600, 620);
  vignette.addColorStop(0, 'rgba(0,0,0,0)');
  vignette.addColorStop(1, 'rgba(0,0,0,0.46)');
  ctx.fillStyle = vignette;
  ctx.beginPath();
  ctx.arc(600, 600, 560, 0, Math.PI * 2);
  ctx.fill();
}

function drawOuterShell() {
  ctx.save();
  ctx.strokeStyle = '#ece8df';
  ctx.lineWidth = 26;
  ctx.beginPath();
  ctx.arc(600, 600, 540, 0, Math.PI * 2);
  ctx.stroke();

  ctx.strokeStyle = '#352b57';
  ctx.lineWidth = 58;
  ctx.beginPath();
  ctx.arc(600, 600, 572, 0.3, Math.PI * 2 - 0.3);
  ctx.stroke();

  ctx.strokeStyle = '#090b15';
  ctx.lineWidth = 6;
  ctx.beginPath();
  ctx.arc(600, 600, 515, 0, Math.PI * 2);
  ctx.stroke();

  ctx.strokeStyle = '#f5f0e7';
  ctx.lineWidth = 10;
  ctx.beginPath();
  ctx.arc(600, 600, 500, Math.PI * 0.17, Math.PI * 0.83);
  ctx.stroke();
  ctx.restore();
}

function drawSideDecorations() {
  return;
}

function drawMainDial(p) {
  const centerX = 600;
  const centerY = 408;
  const radius = 226;
  const maxSpeedKph = 360;
  const speedKph = state.smoothSpeed || 0;
  const speedRatio = Math.max(0, Math.min(1, speedKph / maxSpeedKph));
  const rpmRatio = Math.max(0, Math.min(1, state.smoothRpm / 15000));
  const dialStart = Math.PI / 2;
  const baseDialEnd = Math.PI * 2 + Math.PI / 3;
  const baseDialSweep = baseDialEnd - dialStart;
  const dialSweep = baseDialSweep * (320 / 360);
  const dialEnd = dialStart + dialSweep;
  const speedAngle = speedToDialAngle(speedKph, maxSpeedKph, dialStart, dialSweep);
  ctx.save();

  ctx.strokeStyle = '#f7f1e5';
  ctx.lineWidth = 14;
  ctx.beginPath();
  ctx.arc(centerX, centerY, radius, dialStart, dialEnd);
  ctx.stroke();

  drawNeonArc(centerX, centerY, radius + 32, Math.PI * 0.98, Math.PI * 1.20, '#74ff4f', 4);
  drawNeonArc(centerX, centerY, radius + 32, Math.PI * 1.52, Math.PI * 1.77, '#74ff4f', 4);
  drawNeonArc(centerX, centerY, radius + 32, Math.PI * 1.95, Math.PI * 2.27, '#74ff4f', 4);
  drawNeonArc(centerX, centerY, radius + 32, Math.PI * 2.44, Math.PI * (2.44 + 0.80 * rpmRatio), '#74ff4f', 4);
  drawNeonArc(centerX, centerY, radius + 58, Math.PI * 1.48, Math.PI * 1.52, '#74ff4f', 8);
  drawDialSweepFill(centerX, centerY, 112, radius - 10, dialStart, speedAngle, speedRatio);

  for (let kph = 0; kph <= maxSpeedKph; kph += 20) {
    const angle = speedToDialAngle(kph, maxSpeedKph, dialStart, dialSweep);
    const isMajor = kph % 40 === 0;
    if (!isMajor) {
      continue;
    }
    const tickInset = 30;
    const tickOutset = -3;
    const inner = polar(centerX, centerY, radius - tickInset, angle);
    const outer = polar(centerX, centerY, radius + tickOutset, angle);
    ctx.strokeStyle = '#f7efd2';
    ctx.lineWidth = 4.5;
    ctx.beginPath();
    ctx.moveTo(inner.x, inner.y);
    ctx.lineTo(outer.x, outer.y);
    ctx.stroke();

    if (isMajor && kph !== maxSpeedKph) {
      const lp = polar(centerX, centerY, radius - 56, angle);
      ctx.fillStyle = '#efe8d8';
      ctx.font = '18px Helvetica Neue';
      ctx.textAlign = 'center';
      ctx.textBaseline = 'middle';
      ctx.fillText(String(kph), lp.x, lp.y);
    }
  }

  ctx.strokeStyle = '#ffffff';
  ctx.lineWidth = 10;
  ctx.beginPath();
  ctx.arc(centerX, centerY, 108, 0, Math.PI * 2);
  ctx.stroke();
  ctx.lineWidth = 4;
  ctx.beginPath();
  ctx.arc(centerX, centerY, 94, 0, Math.PI * 2);
  ctx.stroke();
  ctx.fillStyle = '#ffffff';
  ctx.shadowBlur = 10;
  ctx.shadowColor = '#ffffff';
  ctx.beginPath();
  ctx.arc(centerX, centerY, 14, 0, Math.PI * 2);
  ctx.fill();
  ctx.shadowBlur = 0;
  ctx.lineWidth = 3;
  ctx.beginPath();
  ctx.arc(centerX, centerY, 19, 0, Math.PI * 2);
  ctx.stroke();

  const plaqueStart = Math.PI * 0.47;
  const plaqueEnd = ((dialEnd % (Math.PI * 2)) + Math.PI * 2) % (Math.PI * 2);
  const plaqueOuter = radius;
  const plaqueInner = 38;
  drawSpeedPlaque(centerX, centerY, plaqueInner, plaqueOuter, plaqueStart, plaqueEnd);
  drawPlaqueLabel(centerX, centerY, plaqueInner, plaqueOuter, plaqueStart, plaqueEnd, 'SUGO');

  ctx.save();
  ctx.strokeStyle = '#fefbf0';
  ctx.lineWidth = 6;
  ctx.shadowBlur = 12;
  ctx.shadowColor = '#ffffff';
  ctx.beginPath();
  const needleInner = polar(centerX, centerY, 108, speedAngle);
  const needleOuter = polar(centerX, centerY, radius - 10, speedAngle);
  ctx.moveTo(needleInner.x, needleInner.y);
  ctx.lineTo(needleOuter.x, needleOuter.y);
  if (Number.isFinite(p.car.speed_kph)) ctx.stroke();
  ctx.restore();

  ctx.fillStyle = '#efe8d8';
  ctx.font = '42px Helvetica Neue';
  ctx.textAlign = 'center';
  ctx.fillText(Number.isFinite(p.car.speed_kph) ? 'KPH' : 'KPH —', centerX, centerY - 52);

  ctx.fillStyle = '#ff5a42';
  ctx.beginPath();
  ctx.moveTo(centerX - 20, centerY + 272);
  ctx.lineTo(centerX - 40, centerY + 290);
  ctx.lineTo(centerX, centerY + 290);
  ctx.closePath();
  ctx.fill();
  ctx.beginPath();
  ctx.moveTo(centerX + 20, centerY + 272);
  ctx.lineTo(centerX + 40, centerY + 290);
  ctx.lineTo(centerX, centerY + 290);
  ctx.closePath();
  ctx.fill();
  ctx.restore();
}

function speedToDialAngle(speedKph, maxSpeedKph, dialStart, dialSweep) {
  const normalized = Math.max(0, Math.min(1, speedKph / maxSpeedKph));
  const curved = Math.pow(normalized, SPEED_SCALE_EXPONENT);
  const scaled = normalized * (1 - SPEED_SCALE_BLEND) + curved * SPEED_SCALE_BLEND;
  return dialStart + dialSweep * scaled;
}

function drawWarningBars(p) {
  ctx.save();
  ctx.lineCap = 'round';
  drawTiltedGlowBar(264, 252, 74, 22, '#fff8ef', 7);
  drawStackedWarningLights(184, 292, state.smoothRpm || p.car.rpm || 0);
  drawGlowLabel(138, 444, 86, 40, 'DRS', p.car.drs_open ? '#8cff74' : '#4a5f41');
  drawAngledTrace(178, 470, '#82ff68');
  drawGlowBar(886, 395, 118, '#ff3d3d', 13);
  drawGearMarkers(p.car.gear || 0);
  ctx.restore();
}

function drawWavePanels(p) {
  drawRoundedPanel(876, 430, 132, 82, '#8dff63', p.gaps.front_rival_name || 'AHEAD', formatGap(p.gaps.ahead_s));
  drawRoundedPanel(876, 524, 132, 82, '#8dff63', p.gaps.rear_rival_name || 'BEHIND', formatGap(p.gaps.behind_s));
}

function drawTyrePanel(p) {
  const x = 350;
  const y = 790;
  const r = 140;
  const wear = p.tyres.wear_pct_corners || [0, 0, 0, 0];
  const temps = p.tyres.surface_temperature_c || [0, 0, 0, 0];
  ctx.save();
  ctx.strokeStyle = '#ffc23d';
  ctx.lineWidth = 8;
  ctx.shadowBlur = 24;
  ctx.shadowColor = '#ff8f2b';
  ctx.beginPath();
  ctx.arc(x, y, r, 0, Math.PI * 2);
  ctx.stroke();
  ctx.shadowBlur = 0;

  const segments = [
    { x: x - 72, y: y - 112 },
    { x: x + 8, y: y - 112 },
    { x: x - 72, y: y + 8 },
    { x: x + 8, y: y + 8 },
  ];
  segments.forEach((segment, idx) => {
    if (!Number.isFinite(wear[idx]) || !Number.isFinite(temps[idx])) {
      ctx.fillStyle = '#666';
      roundRect(ctx, segment.x, segment.y, 64, 104, 10, true, false);
      ctx.fillStyle = '#fff';
      ctx.font = '22px Helvetica Neue';
      ctx.textAlign = 'center';
      ctx.fillText('—', segment.x + 32, segment.y + 60);
      return;
    }
    const temp = temps[idx];
    const segmentWear = Math.max(0, Math.min(100, wear[idx] || 0));
    const maxHeight = 104;
    const fillHeight = Math.max(0, maxHeight * (1 - segmentWear / 100));
    const fillTop = segment.y + (maxHeight - fillHeight);
    const tempPalette = colorFromTemperature(temp);
    const g = ctx.createLinearGradient(segment.x, fillTop, segment.x, segment.y + maxHeight);
    g.addColorStop(0, tempPalette.top);
    g.addColorStop(0.45, tempPalette.middle);
    g.addColorStop(1, tempPalette.bottom);
    ctx.fillStyle = g;
    if (fillHeight > 0) {
      roundRect(ctx, segment.x, fillTop, 64, fillHeight, 10, true, false);
    }
  });
  drawGlowLabel(x - 54, y + 162, 108, 34, 'WEAR', '#ff9b3a', 'bold 22px Helvetica Neue');
  ctx.restore();
}

function drawResourcePanel(p) {
  const x = 830;
  const y = 790;
  const r = 136;
  ctx.save();
  ctx.strokeStyle = '#70ff54';
  ctx.lineWidth = 8;
  ctx.shadowBlur = 18;
  ctx.shadowColor = '#73ff58';
  ctx.beginPath();
  ctx.arc(x, y, r, 0, Math.PI * 2);
  ctx.stroke();
  ctx.shadowBlur = 0;

  const ersAngle = -Math.PI / 2 + Math.PI * 2 * (state.smoothErs / 100);
  const fuelAngle = Math.PI + Math.PI * Math.min((state.smoothFuel || 0) / 20, 1);
  if (Number.isFinite(p.car.ers_pct)) drawSpokeGauge(x, y, r - 12, ersAngle, '#79ff53');
  if (Number.isFinite(p.car.fuel_laps_remaining)) drawSpokeGauge(x, y, r - 48, fuelAngle, '#79ff53');
  drawSpokeGauge(x, y, r - 82, Math.PI * 1.58, '#79ff53');
  ctx.fillStyle = '#efe8d8';
  ctx.font = '18px Helvetica Neue';
  ctx.textAlign = 'left';
  ctx.fillText('E', x - 110, y + 8);
  ctx.textAlign = 'right';
  ctx.fillText('H', x + 110, y - 88);
  drawSmallLabel(x, y + 170, Number.isFinite(p.car.ers_pct) ? `ERS ${Math.round(state.smoothErs)}%` : 'ERS —');
  drawSmallLabel(x, y + 198, Number.isFinite(p.car.fuel_laps_remaining) ? `FUEL ${state.smoothFuel.toFixed(1)}LAP` : 'FUEL —');
  drawSmallLabel(x, y + 226, `${p.car.drs_open ? 'DRS OPEN' : 'DRS OFF'}`);
  ctx.restore();
}

function drawCenterColumn(p) {
  const x = 600;
  const y = 760;
  const bodyDamage = (p.damage || {}).body_damage_pct;
  const powertrainDamage = (p.damage || {}).powertrain_damage_pct;
  const damageKnown = Number.isFinite(bodyDamage) && Number.isFinite(powertrainDamage);
  const damageScore = Math.max(bodyDamage, powertrainDamage);
  const topLampColor = !damageKnown ? '#777' : damageScore >= 55 ? '#ff4343' : damageScore >= 18 ? '#ff9b3a' : '#7aff5d';
  const topLampBlink = damageScore >= 55 ? 0.7 + Math.abs(Math.sin(Date.now() / 130)) * 0.3 : 1;
  const primaryAction = (p.strategy && p.strategy.primary_action) || 'NONE';
  const mainStatus = ((p.strategy && p.strategy.title) || 'Standby').toUpperCase();
  const subStatusRaw = ((p.strategy && p.strategy.detail) || primaryAction.replaceAll('_', ' ')).toUpperCase();
  const subStatus = subStatusRaw.length > 18 ? `${subStatusRaw.slice(0, 18)}…` : subStatusRaw;
  const mainStatusColor = primaryAction === 'DYNAMICS_UNSTABLE'
    ? '#ff6e4a'
    : primaryAction === 'LOW_FUEL'
      ? '#ffb13d'
      : '#8fff68';
  const subStatusColor = primaryAction === 'DYNAMICS_UNSTABLE' ? '#ff9a7a' : '#a2ff7b';
  ctx.save();
  ctx.strokeStyle = '#ffffff';
  ctx.lineWidth = 9;
  ctx.shadowBlur = 16;
  ctx.shadowColor = '#ffffff';
  ctx.beginPath();
  ctx.moveTo(x - 28, y - 130);
  ctx.lineTo(x - 42, y - 82);
  ctx.lineTo(x - 18, y - 42);
  ctx.moveTo(x + 28, y - 130);
  ctx.lineTo(x + 42, y - 82);
  ctx.lineTo(x + 18, y - 42);
  ctx.stroke();
  ctx.shadowBlur = 0;

  ctx.save();
  ctx.globalAlpha = topLampBlink;
  drawGlowCircle(x, y - 136, 14, topLampColor);
  ctx.restore();
  drawGlowCircle(x, y - 92, 12, '#ffffff');
  const indicatorX = x - 28;
  const indicatorY = y + 18;
  const indicatorGap = 52;
  drawGlowLabel(indicatorX, indicatorY, 56, 36, 'DMG', topLampColor, 'bold 20px Helvetica Neue');
  drawGlowLabel(indicatorX, indicatorY + indicatorGap, 56, 36, `P${p.session.position}`, '#9cff8d');
  drawGlowLabel(indicatorX, indicatorY + indicatorGap * 2, 56, 36, `${p.session.lap_number}`, '#ff473d');
  const statusMainY = y + 176;
  const statusSubY = y + 222;
  drawGlowLabel(x - 86, statusMainY, 172, 32, mainStatus, mainStatusColor, 'bold 20px Helvetica Neue');
  drawGlowLabel(x - 102, statusSubY, 204, 26, subStatus, subStatusColor, 'bold 14px Helvetica Neue');
  ctx.restore();
}

function drawBottomLabels(p) {
  drawGlowLabel(244, 1030, 134, 34, `A ${formatGap(p.gaps.ahead_s)}`, '#7dff57');
  drawGlowLabel(754, 1030, 164, 34, `B ${formatGap(p.gaps.behind_s)}`, '#7dff57');
}

function drawGlowBar(x, y, width, color, thickness = 14) {
  ctx.save();
  ctx.globalAlpha = bootIndicatorAlpha((x + y + width) * 0.01);
  ctx.strokeStyle = color;
  ctx.lineWidth = thickness;
  ctx.shadowBlur = 14;
  ctx.shadowColor = color;
  ctx.beginPath();
  ctx.moveTo(x, y);
  ctx.lineTo(x + width, y);
  ctx.stroke();
  ctx.shadowBlur = 0;
  ctx.restore();
}

function drawTiltedGlowBar(x, y, length, angleDeg, color, thickness = 14) {
  const radians = (angleDeg * Math.PI) / 180;
  ctx.save();
  ctx.globalAlpha = bootIndicatorAlpha((x + y + length) * 0.01);
  ctx.strokeStyle = color;
  ctx.lineWidth = thickness;
  ctx.shadowBlur = 14;
  ctx.shadowColor = color;
  ctx.beginPath();
  ctx.moveTo(x, y);
  ctx.lineTo(x + Math.cos(radians) * length, y + Math.sin(radians) * length);
  ctx.stroke();
  ctx.shadowBlur = 0;
  ctx.restore();
}

function drawStackedWarningLights(x, y, rpm) {
  const rpmValue = Math.max(0, rpm || 0);
  const rpmRatio = Math.max(
    0,
    Math.min(1, (rpmValue - SHIFT_LIGHT_START_RPM) / (SHIFT_LIGHT_PEAK_RPM - SHIFT_LIGHT_START_RPM)),
  );
  const palette = ['#ff7c33', '#ffc33f', '#ffdd56', '#ffe970', '#f9ff8a', '#d7ff9f'];
  const warningPulse = rpmValue >= SHIFT_LIGHT_PULSE_RPM ? 0.8 + Math.abs(Math.sin(Date.now() / 85)) * 0.2 : 1;
  const clusterShiftX = -22;
  const rawBands = [
    [[x + 48, y + 20], [x + 108, y - 2], [x + 94, y + 18], [x + 56, y + 34]],
    [[x + 40, y + 36], [x + 116, y + 10], [x + 100, y + 32], [x + 48, y + 50]],
    [[x + 30, y + 52], [x + 124, y + 22], [x + 106, y + 46], [x + 40, y + 68]],
    [[x + 22, y + 68], [x + 132, y + 34], [x + 112, y + 60], [x + 34, y + 86]],
    [[x + 16, y + 84], [x + 140, y + 48], [x + 118, y + 76], [x + 30, y + 104]],
    [[x + 12, y + 100], [x + 146, y + 62], [x + 122, y + 92], [x + 28, y + 122]],
  ];
  const shiftedBands = rawBands.map((points) => points.map(([px, py]) => [px + clusterShiftX, py]));
  const bands = shiftedBands.map((points) => shearQuadRightUp(points, [x + 78 + clusterShiftX, y + 118], 0.38));
  const activationOrder = [5, 4, 3, 2, 1, 0];
  const fillLevel = rpmRatio * activationOrder.length;
  bands.forEach((points) => {
    drawFanBand(points, '#3f3518', 0.42);
  });
  activationOrder.forEach((bandIdx, orderIdx) => {
    const progress = Math.max(0, Math.min(1, fillLevel - orderIdx));
    if (progress <= 0) {
      return;
    }
    const color = palette[bandIdx];
    if (progress >= 1) {
      drawFanBand(bands[bandIdx], color, warningPulse);
      return;
    }
    drawPartialFanBand(bands[bandIdx], progress, color, warningPulse);
  });
}

function drawSkewedLightBar(x, y, width, height, skew, color) {
  ctx.save();
  ctx.fillStyle = color;
  ctx.shadowBlur = 16;
  ctx.shadowColor = color;
  ctx.beginPath();
  ctx.moveTo(x, y + height);
  ctx.lineTo(x + skew, y);
  ctx.lineTo(x + width, y);
  ctx.lineTo(x + width - skew, y + height);
  ctx.closePath();
  ctx.fill();
  ctx.restore();
}

function drawFanBand(points, color, alpha = 1) {
  ctx.save();
  const avg = points.reduce((sum, point) => sum + point[0] + point[1], 0) / (points.length * 2);
  ctx.globalAlpha = bootIndicatorAlpha(avg * 0.01);
  ctx.fillStyle = hexToRgba(color, alpha);
  ctx.shadowBlur = alpha >= 1 ? 14 : 0;
  ctx.shadowColor = color;
  ctx.beginPath();
  ctx.moveTo(points[0][0], points[0][1]);
  for (let i = 1; i < points.length; i++) {
    ctx.lineTo(points[i][0], points[i][1]);
  }
  ctx.closePath();
  ctx.fill();
  ctx.restore();
}

function drawPartialFanBand(points, progress, color, alpha = 1) {
  const topLeft = points[0];
  const topRight = points[1];
  const bottomRight = points[2];
  const bottomLeft = points[3];
  const partialTop = lerpPoint(topLeft, topRight, progress);
  const partialBottom = lerpPoint(bottomLeft, bottomRight, progress);
  drawFanBand([topLeft, partialTop, partialBottom, bottomLeft], color, alpha);
}

function drawGlowLabel(x, y, width, height, text, color, font = '22px Helvetica Neue') {
  ctx.save();
  ctx.globalAlpha = bootIndicatorAlpha((x + y + width + height) * 0.01);
  ctx.fillStyle = color;
  ctx.shadowBlur = 12;
  ctx.shadowColor = color;
  roundRect(ctx, x, y, width, height, 8, true, false);
  ctx.shadowBlur = 0;
  ctx.fillStyle = '#0b1116';
  ctx.font = font;
  ctx.textAlign = 'center';
  ctx.textBaseline = 'middle';
  ctx.fillText(text, x + width / 2, y + height / 2 + 1);
  ctx.restore();
}

function drawRoundedPanel(x, y, w, h, color, title, value) {
  ctx.save();
  ctx.globalAlpha = bootIndicatorAlpha((x + y + w + h) * 0.005);
  ctx.fillStyle = 'rgba(12, 28, 12, 0.82)';
  ctx.shadowBlur = 16;
  ctx.shadowColor = color;
  roundRect(ctx, x, y, w, h, 12, true, false);
  ctx.shadowBlur = 0;
  ctx.strokeStyle = color;
  ctx.lineWidth = 5;
  roundRect(ctx, x, y, w, h, 12, false, true);
  ctx.beginPath();
  ctx.moveTo(x + 10, y + h / 2);
  for (let i = 0; i < 5; i++) {
    const px = x + 10 + i * 20;
    const py = y + h / 2 + Math.sin(Date.now() / 250 + i) * 8;
    ctx.lineTo(px, py);
  }
  ctx.stroke();
  ctx.fillStyle = '#7dff57';
  ctx.font = '16px Helvetica Neue';
  ctx.textAlign = 'left';
  ctx.fillText(title, x + 12, y + 20);
  ctx.font = '20px Helvetica Neue';
  ctx.textAlign = 'right';
  ctx.fillText(value, x + w - 12, y + h - 12);
  ctx.restore();
}

function drawGlowCircle(x, y, r, color) {
  ctx.save();
  ctx.globalAlpha = bootIndicatorAlpha((x + y + r) * 0.02);
  ctx.fillStyle = color;
  ctx.shadowBlur = 14;
  ctx.shadowColor = color;
  ctx.beginPath();
  ctx.arc(x, y, r, 0, Math.PI * 2);
  ctx.fill();
  ctx.restore();
}

function drawSpokeGauge(x, y, r, angle, color) {
  ctx.strokeStyle = color;
  ctx.lineWidth = 8;
  ctx.beginPath();
  ctx.moveTo(x, y);
  const p = polar(x, y, r, angle);
  ctx.lineTo(p.x, p.y);
  ctx.stroke();
  for (let i = 0; i < 3; i++) {
    const a = angle + i * (Math.PI * 2 / 3);
    const pp = polar(x, y, r, a);
    ctx.beginPath();
    ctx.moveTo(x, y);
    ctx.lineTo(pp.x, pp.y);
    ctx.stroke();
  }
}

function drawSmallLabel(x, y, text) {
  ctx.save();
  ctx.fillStyle = '#efe8d8';
  ctx.font = '20px Helvetica Neue';
  ctx.textAlign = 'center';
  ctx.fillText(text, x, y);
  ctx.restore();
}

function drawNeonArc(x, y, radius, start, end, color, width) {
  ctx.save();
  ctx.strokeStyle = color;
  ctx.lineWidth = width;
  ctx.shadowBlur = 14;
  ctx.shadowColor = color;
  ctx.beginPath();
  ctx.arc(x, y, radius, start, end);
  ctx.stroke();
  ctx.restore();
}

function drawDialSweepFill(cx, cy, innerR, outerR, start, end, speedRatio) {
  if (end <= start + 0.001) {
    return;
  }
  fillRingSegment(cx, cy, innerR, outerR, start, end, '#69ff5d', 0.34);

  const yellowThreshold = 0.58;
  const orangeThreshold = 0.8;
  const redThreshold = 0.92;
  if (speedRatio > yellowThreshold) {
    const yellowStart = start + (end - start) * yellowThreshold;
    fillRingSegment(cx, cy, innerR, outerR, yellowStart, end, '#ffd85e', 0.42);
  }
  if (speedRatio > orangeThreshold) {
    const orangeStart = start + (end - start) * orangeThreshold;
    fillRingSegment(cx, cy, innerR, outerR, orangeStart, end, '#ff9c39', 0.48);
  }
  if (speedRatio > redThreshold) {
    const redStart = start + (end - start) * redThreshold;
    fillRingSegment(cx, cy, innerR, outerR, redStart, end, '#ff4a3d', 0.56);
  }
}

function drawSpeedPlaque(cx, cy, innerR, outerR, start, end) {
  const wrapClock = end < start;
  ctx.save();
  ctx.fillStyle = '#11101f';
  ctx.beginPath();
  const outerStart = polar(cx, cy, outerR, start);
  ctx.moveTo(outerStart.x, outerStart.y);
  ctx.arc(cx, cy, outerR, start, end, wrapClock);
  const innerEnd = polar(cx, cy, innerR, end);
  ctx.lineTo(innerEnd.x, innerEnd.y);
  ctx.arc(cx, cy, innerR, end, start, !wrapClock);
  ctx.closePath();
  ctx.fill();
  ctx.restore();

  ctx.save();
  ctx.strokeStyle = '#fff8ec';
  ctx.shadowBlur = 12;
  ctx.shadowColor = '#fff8ec';
  ctx.lineWidth = 10;
  ctx.beginPath();
  ctx.arc(cx, cy, outerR, start, end, wrapClock);
  ctx.stroke();
  ctx.lineWidth = 14;
  ctx.beginPath();
  ctx.arc(cx, cy, innerR, start + (wrapClock ? -0.004 : 0.004), end + (wrapClock ? 0.004 : -0.004), wrapClock);
  ctx.stroke();
  ctx.lineWidth = 9;
  const os = polar(cx, cy, outerR, start);
  const is = polar(cx, cy, innerR, start);
  const oe = polar(cx, cy, outerR, end);
  const ie = polar(cx, cy, innerR, end);
  ctx.beginPath();
  ctx.moveTo(is.x, is.y);
  ctx.lineTo(os.x, os.y);
  ctx.stroke();
  ctx.beginPath();
  ctx.moveTo(ie.x, ie.y);
  ctx.lineTo(oe.x, oe.y);
  ctx.stroke();
  ctx.restore();

  const bandColors = ['#69ff5d', '#ffd85e', '#ff9c39', '#ff5b49', '#fff7ee'];
  const plaqueDepth = outerR - innerR;
  const bandInnerR = innerR + plaqueDepth * 0.08;
  const bandOuterR = bandInnerR + (plaqueDepth * (0.56 - 0.08) * 4.6) / 7;
  const bandInset = 0.022;
  const bandSpan = wrapClock ? start - end : end - start;
  const centeredSpan = Math.max(0, (bandSpan - bandInset * 2) * 0.72);
  const centeredOffset = bandInset + (bandSpan - bandInset * 2 - centeredSpan) / 2;
  const bandCount = bandColors.length;
  const bandWidth = centeredSpan / bandCount;
  bandColors.forEach((color, idx) => {
    const bandStart = wrapClock
      ? start - centeredOffset - bandWidth * idx
      : start + centeredOffset + bandWidth * idx;
    const bandEnd = wrapClock
      ? bandStart - bandWidth * 0.82
      : bandStart + bandWidth * 0.82;
    ctx.save();
    ctx.fillStyle = color;
    ctx.beginPath();
    const o0 = polar(cx, cy, bandOuterR, bandStart);
    ctx.moveTo(o0.x, o0.y);
    ctx.arc(cx, cy, bandOuterR, bandStart, bandEnd, wrapClock);
    const i1 = polar(cx, cy, bandInnerR, bandEnd);
    ctx.lineTo(i1.x, i1.y);
    ctx.arc(cx, cy, bandInnerR, bandEnd, bandStart, !wrapClock);
    ctx.closePath();
    ctx.fill();
    ctx.restore();
  });
}

function drawPlaqueLabel(cx, cy, innerR, outerR, start, end, text) {
  const wrapClock = end < start;
  const span = wrapClock ? start - end : end - start;
  const mid = wrapClock ? start - span / 2 : start + span / 2;
  const plaqueDepth = outerR - innerR;
  const bandInnerR = innerR + plaqueDepth * 0.08;
  const bandOuterR = bandInnerR + (plaqueDepth * (0.56 - 0.08) * 4.6) / 7;
  const labelRadius = bandOuterR + (outerR - bandOuterR) * 0.44;
  const anchor = polar(cx, cy, labelRadius, mid);
  ctx.save();
  ctx.translate(anchor.x, anchor.y);
  ctx.rotate(mid - Math.PI / 2);
  ctx.fillStyle = '#b9332e';
  ctx.font = '700 30px Helvetica Neue';
  ctx.textAlign = 'center';
  ctx.textBaseline = 'middle';
  ctx.shadowBlur = 8;
  ctx.shadowColor = '#ff9c39';
  ctx.fillText(text, 0, 0);
  ctx.shadowBlur = 0;
  ctx.restore();
}

function drawAngledTrace(x, y, color) {
  const centerX = 600;
  const centerY = 408;
  const radius = 226;
  const dialStart = Math.PI / 2;
  const baseDialEnd = Math.PI * 2 + Math.PI / 3;
  const baseDialSweep = baseDialEnd - dialStart;
  const dialSweep = baseDialSweep * (320 / 360);
  const traceAngle = speedToDialAngle(160, 360, dialStart, dialSweep);
  const traceTarget = polar(centerX, centerY, radius - 30, traceAngle);
  const upperY = traceTarget.y;
  const lowerY = y + 34;
  const baseGlow = hexToRgba(color, 0.28);
  ctx.save();
  ctx.strokeStyle = baseGlow;
  ctx.lineWidth = 12;
  ctx.shadowBlur = 18;
  ctx.shadowColor = color;
  ctx.beginPath();
  ctx.moveTo(x - 52, lowerY);
  ctx.lineTo(x + 54, lowerY);
  ctx.lineTo(x + 84, upperY);
  ctx.lineTo(x + 142, upperY);
  ctx.stroke();
  ctx.strokeStyle = color;
  ctx.lineWidth = 8;
  ctx.shadowBlur = 12;
  ctx.shadowColor = color;
  ctx.beginPath();
  ctx.moveTo(x - 52, lowerY);
  ctx.lineTo(x + 54, lowerY);
  ctx.lineTo(x + 84, upperY);
  ctx.lineTo(x + 142, upperY);
  ctx.stroke();
  ctx.restore();
}

function drawGearMarkers(gear) {
  const gearValue = typeof gear === 'number' ? gear : parseInt(gear, 10) || 0;
  const bandIndex = gearValue > 0 ? Math.max(1, Math.min(4, Math.ceil(gearValue / 2))) : 0;
  const labels = ['1', '2', '3', '4'];
  for (let i = 0; i < 4; i++) {
    const x = 136 + i * 56;
    const y = 638 - i * 30;
    const active = bandIndex === i + 1;
    const passed = bandIndex > i + 1;
    drawIndexedMarker(x, y, labels[i], active, passed);
  }
}

function drawIndexedMarker(x, y, text, active = false, passed = false) {
  ctx.save();
  ctx.strokeStyle = active ? '#ffd166' : '#1a1414';
  ctx.lineWidth = 4;
  ctx.beginPath();
  ctx.moveTo(x, y);
  ctx.lineTo(x + 8, y + 82);
  ctx.stroke();
  const lampColor = active ? '#ffb347' : (passed ? '#ff7a2e' : '#ff8a33');
  drawGlowCircle(x, y, active ? 26 : 22, lampColor);
  ctx.strokeStyle = hexToRgba('#fff1ba', active ? 0.72 : 0.46);
  ctx.lineWidth = active ? 3.5 : 2.5;
  ctx.shadowBlur = active ? 10 : 6;
  ctx.shadowColor = '#fff1ba';
  ctx.beginPath();
  ctx.arc(x, y, active ? 17 : 14, 0, Math.PI * 2);
  ctx.stroke();
  ctx.fillStyle = hexToRgba('#ffe7a0', active ? 0.42 : 0.28);
  ctx.shadowBlur = active ? 12 : 8;
  ctx.shadowColor = lampColor;
  ctx.beginPath();
  ctx.arc(x - 5, y - 5, active ? 4.5 : 3.5, 0, Math.PI * 2);
  ctx.fill();
  ctx.shadowBlur = 0;
  ctx.fillStyle = active ? '#130600' : '#2a0e04';
  ctx.font = '22px Helvetica Neue';
  ctx.textAlign = 'center';
  ctx.textBaseline = 'middle';
  ctx.fillText(text, x, y + 1);
  ctx.restore();
}

function fillRingSegment(cx, cy, innerR, outerR, start, end, hex, alpha) {
  ctx.save();
  ctx.fillStyle = hexToRgba(hex, alpha);
  ctx.beginPath();
  const outerStart = polar(cx, cy, outerR, start);
  ctx.moveTo(outerStart.x, outerStart.y);
  ctx.arc(cx, cy, outerR, start, end);
  const innerEnd = polar(cx, cy, innerR, end);
  ctx.lineTo(innerEnd.x, innerEnd.y);
  ctx.arc(cx, cy, innerR, end, start, true);
  ctx.closePath();
  ctx.fill();
  ctx.restore();
}

function hexToRgba(hex, alpha) {
  const normalized = hex.replace('#', '');
  const value = normalized.length === 3
    ? normalized.split('').map((ch) => ch + ch).join('')
    : normalized;
  const intValue = parseInt(value, 16);
  const r = (intValue >> 16) & 255;
  const g = (intValue >> 8) & 255;
  const b = intValue & 255;
  return `rgba(${r}, ${g}, ${b}, ${alpha})`;
}

function roundRect(ctx, x, y, width, height, radius, fill, stroke) {
  ctx.beginPath();
  ctx.moveTo(x + radius, y);
  ctx.arcTo(x + width, y, x + width, y + height, radius);
  ctx.arcTo(x + width, y + height, x, y + height, radius);
  ctx.arcTo(x, y + height, x, y, radius);
  ctx.arcTo(x, y, x + width, y, radius);
  ctx.closePath();
  if (fill) ctx.fill();
  if (stroke) ctx.stroke();
}

function polar(cx, cy, r, a) {
  return { x: cx + Math.cos(a) * r, y: cy + Math.sin(a) * r };
}

function formatGap(value) {
  return value == null ? '-' : `${value.toFixed(3)}s`;
}

function renderMeta() {
  const p = state.current || demoPayload;
  const voice = p.voice || demoPayload.voice;
  const voiceState = voice.state || 'idle';
  const voiceAction = voice.action_code || '-';
  const bootLine = state.boot && state.boot.active
    ? `<div>Boot: ${Math.round((state.boot.progress || 0) * 100)}%</div>`
    : '';
  meta.innerHTML = `
    <div>Track: ${p.session.track}</div>
    <div>Lap: ${p.session.lap_number} / ${p.session.total_laps}</div>
    <div>Pos: P${p.session.position}</div>
    <div>Strategy: ${p.strategy.primary_action}</div>
    <div>Weather: ${p.session.weather ?? '-'}</div>
    <div>Voice: ${voiceState.toUpperCase()} / ${voiceAction}</div>
    ${bootLine}
    <div>Feed Ts: ${p.timestamp_ms || 0}</div>
    <div>Temps: ${(p.tyres.surface_temperature_c || []).map(value => value ?? '-').join(' / ') || '-'}</div>
    <div>Damage: body ${p.damage.body_damage_pct ?? '-'} / power ${p.damage.powertrain_damage_pct ?? '-'}</div>
  `;
  const grid = p.strategy.starting_grid;
  if (grid) {
    for (const [stops, route] of Object.entries(grid.routes)) {
      const line = document.createElement('div');
      line.textContent = `${stops} 停　${route.stints.map(s => s.compound + ' × ' + s.laps + '圈').join(' → ')}`;
      meta.appendChild(line);
    }
    if (grid.if_start_can_change) {
      const free = grid.if_start_can_change;
      for (const [stops, route] of Object.entries(free.routes)) {
        if (grid.routes[stops]?.stints[0].compound === route.stints[0].compound) continue;
        const line = document.createElement('div');
        line.textContent = `可重选起步胎 · ${stops} 停　${route.stints.map(s => s.compound + ' × ' + s.laps + '圈').join(' → ')}`;
        meta.appendChild(line);
      }
    }
    if (Number.isFinite(grid.one_two_break_even_s)) {
      const line = document.createElement('div');
      line.textContent = grid.one_two_break_even_s > 0
        ? `保持起步胎 · 两停回本上限 ${grid.one_two_break_even_s.toFixed(2)} 秒（当前天气持续）`
        : '保持起步胎 · 额外停车代价为正时，一停快于两停';
      meta.appendChild(line);
    }
  }
}

function renderVoiceIndicator() {
  const p = state.current || demoPayload;
  const voice = p.voice || demoPayload.voice;
  const hasAudioMeter = voice.amplitude_playback_active === true;
  const hasVisibleAudioEnergy = hasAudioMeter && (
    Number(voice.amplitude_level || 0) >= 0.11
    || Number(voice.amplitude_peak || 0) >= 0.16
    || state.voiceBeatPulseLevel >= 0.16
  );
  const stateName = hasVisibleAudioEnergy ? 'active' : (voice.pending ? 'pending' : 'idle');
  if (state.boot && state.boot.active) {
    voiceIndicatorEl.classList.remove('active', 'pending', 'idle');
    voiceIndicatorEl.classList.remove('audio-reactive');
    voiceIndicatorEl.classList.add('boot');
    voiceLabelEl.textContent = 'VOICE CHECK';
    voiceDetailEl.textContent = `boot ${(Math.max(0, Math.min(1, state.boot.progress || 0)) * 100).toFixed(0)}%`;
    voiceIndicatorEl.title = 'voice self-test active';
    resetVoiceMeterStyles();
    return;
  }

  const stateClass = ['active', 'pending'].includes(stateName) ? stateName : 'idle';
  const actionCode = voice.action_code || '';
  const sourceKind = voice.source_kind || '';
  const llmStatus = voice.llm_sidecar_status || '';

  voiceIndicatorEl.classList.remove('boot', 'active', 'pending', 'idle');
  voiceIndicatorEl.classList.add(stateClass);

  if (stateClass === 'active') {
    const meterLevel = clamp01(Math.max(state.voiceMeterLevel, state.voiceMeterPeakLevel * 0.2));
    if (hasVisibleAudioEnergy) {
      voiceIndicatorEl.classList.add('audio-reactive');
      applyVoiceMeter(meterLevel);
    } else {
      voiceIndicatorEl.classList.remove('audio-reactive');
      resetVoiceMeterStyles();
    }
    voiceLabelEl.textContent = 'VOICE LIVE';
    voiceDetailEl.textContent = actionCode || sourceKind || 'output active';
    voiceIndicatorEl.title = sourceKind ? `source=${sourceKind}` : 'voice output active';
    return;
  }

  voiceIndicatorEl.classList.remove('audio-reactive');
  resetVoiceMeterStyles();
  if (stateClass === 'pending') {
    voiceLabelEl.textContent = 'VOICE QUEUED';
    voiceDetailEl.textContent = actionCode || sourceKind || 'output queued';
    voiceIndicatorEl.title = sourceKind ? `source=${sourceKind}` : 'voice output queued';
    return;
  }

  voiceLabelEl.textContent = 'VOICE IDLE';
  voiceDetailEl.textContent = llmStatus || 'standby';
  voiceIndicatorEl.title = 'voice output idle';
}

function applyVoiceMeter(level) {
  const shaped = 0.08 + Math.pow(clamp01(level), 0.48) * 0.92;
  const stepped = shaped * (voiceLedGroups.length + 0.55);
  const solidCount = Math.floor(stepped);
  const fractional = clamp01(stepped - solidCount);
  const beatPulse = clamp01(state.voiceBeatPulseLevel);
  const beatElapsedMs = state.voiceBeatTriggeredAtMs > 0 ? Date.now() - state.voiceBeatTriggeredAtMs : 9999;
  const beatProgress = clamp01(beatElapsedMs / 280);
  const beatHead = beatProgress * (voiceLedGroups.length - 0.15);
  voiceLedGroups.forEach((group, index) => {
    let local = 0;
    if (index < solidCount) {
      local = 1;
    } else if (index === solidCount) {
      local = 0.22 + fractional * 0.78;
    } else if (index === solidCount + 1 && fractional > 0.62) {
      local = 0.16 + (fractional - 0.62) * 0.9;
    }
    let beatBoost = 0;
    if (beatPulse > 0.01) {
      const distance = Math.abs(index - beatHead);
      if (distance < 0.95) {
        beatBoost = (1 - distance / 0.95) * beatPulse;
      }
    }
    const ringBias = 1 - index / Math.max(voiceLedGroups.length - 1, 1);
    const combined = clamp01(local + beatBoost * 0.95);
    const opacity = 0.08 + combined * (0.84 + ringBias * 0.08);
    const blurPx = 7 + combined * (18 + ringBias * 8);
    const glowAlpha = 0.18 + combined * (0.7 + ringBias * 0.1);
    const baseFill = combined > 0.02 ? '#ff474b' : '#541015';
    group.forEach((el) => {
      el.style.opacity = opacity.toFixed(3);
      el.style.fill = baseFill;
      el.style.filter = combined > 0.03
        ? `drop-shadow(0 0 ${blurPx.toFixed(1)}px rgba(255, 78, 82, ${glowAlpha.toFixed(3)}))`
        : 'none';
    });
  });
  const coreLevel = 0.68 + shaped * 0.32;
  voiceCoreDotEls.forEach((el) => {
    el.style.opacity = coreLevel.toFixed(3);
    el.style.fill = `rgba(143, 255, 104, ${(0.72 + shaped * 0.24).toFixed(3)})`;
    el.style.filter = `drop-shadow(0 0 ${(14 + shaped * 20).toFixed(1)}px rgba(143, 255, 104, ${(0.44 + shaped * 0.36).toFixed(3)}))`;
  });
}

function resetVoiceMeterStyles() {
  voiceLedGroups.flat().forEach((el) => {
    el.style.opacity = '';
    el.style.fill = '';
    el.style.filter = '';
  });
  voiceCoreDotEls.forEach((el) => {
    el.style.opacity = '';
    el.style.fill = '';
    el.style.filter = '';
  });
}

function drawBootOverlay() {
  if (!state.boot || !state.boot.active) {
    return;
  }
  const progress = Math.max(0, Math.min(1, state.boot.progress || 0));
  const width = 320;
  const height = 88;
  const x = 600 - width / 2;
  const y = 126;
  const alpha = 0.7 + (1 - progress) * 0.25;

  ctx.save();
  ctx.globalAlpha = alpha;
  ctx.fillStyle = 'rgba(5, 8, 20, 0.88)';
  ctx.strokeStyle = 'rgba(245, 240, 224, 0.42)';
  ctx.lineWidth = 2;
  roundRect(ctx, x, y, width, height, 14, true, true);

  ctx.fillStyle = '#f7f1dc';
  ctx.font = 'bold 24px Helvetica Neue';
  ctx.textAlign = 'center';
  ctx.textBaseline = 'middle';
  ctx.fillText('SYSTEM CHECK', 600, y + 26);

  ctx.fillStyle = '#b5ff71';
  ctx.font = '14px Helvetica Neue';
  ctx.fillText(`BOOT ${(progress * 100).toFixed(0)}%`, 600, y + 50);

  ctx.fillStyle = 'rgba(255,255,255,0.08)';
  roundRect(ctx, x + 28, y + 60, width - 56, 10, 5, true, false);
  ctx.fillStyle = '#8eff64';
  roundRect(ctx, x + 28, y + 60, (width - 56) * progress, 10, 5, true, false);
  ctx.restore();
}

connectDashboardSocket();
pollLatest();
startBootSequence();
renderMeta();
renderVoiceIndicator();
draw();

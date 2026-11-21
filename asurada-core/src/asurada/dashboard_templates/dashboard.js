
    const payload = __EMBEDDED_PAYLOAD__;
    const latest = payload.latest || {};
    const timingSummary = payload.timing_summary || {};
    const trackProfile = payload.track_profile || {};
    const frames = payload.frames || [];
    const laps = payload.laps || [];

    const metaStrip = document.getElementById('meta-strip');
    const lapFilter = document.getElementById('lap-filter');
    const slider = document.getElementById('frame-slider');
    const playToggle = document.getElementById('play-toggle');
    const prevFrameButton = document.getElementById('prev-frame');
    const nextFrameButton = document.getElementById('next-frame');
    const frameIndex = document.getElementById('frame-index');
    const timelineFrame = document.getElementById('timeline-frame');
    const timelineTime = document.getElementById('timeline-time');
    const timelineTrack = document.getElementById('timeline-track');
    const timelineUsage = document.getElementById('timeline-usage');
    const timelineMessage = document.getElementById('timeline-message');
    const timelinePriority = document.getElementById('timeline-priority');
    const currentFrameGrid = document.getElementById('current-frame-grid');
    const rivalGrid = document.getElementById('rival-grid');
    const decisionTrace = document.getElementById('decision-trace');
    const modelSignals = document.getElementById('model-signals');
    const neighborRows = document.getElementById('neighbor-rows');
    const debugJson = document.getElementById('debug-json');
    const trackSegments = document.getElementById('track-segments');
    const trackMarker = document.getElementById('track-marker');
    const trajectoryMeta = document.getElementById('trajectory-meta');
    const trackContextGrid = document.getElementById('track-context-grid');

    let filteredFrames = frames.slice();
    let playbackIndex = Math.max(filteredFrames.length - 1, 0);
    let playbackTimer = null;
    let isPlaying = false;

    function num(value, digits = 1) {
      if (value === null || value === undefined || value === '') return '-';
      const parsed = Number(value);
      if (Number.isNaN(parsed)) return '-';
      return parsed.toFixed(digits);
    }

    function gap(value) {
      if (value === null || value === undefined || value === '') return '-';
      const parsed = Number(value);
      if (Number.isNaN(parsed)) return '-';
      return `${parsed.toFixed(3)}s`;
    }

    function gapWithSource(officialValue, estimatedValue) {
      if (officialValue !== null && officialValue !== undefined && officialValue !== '') {
        return { value: gap(officialValue), detail: 'official' };
      }
      if (estimatedValue !== null && estimatedValue !== undefined && estimatedValue !== '') {
        return { value: gap(estimatedValue), detail: 'estimated' };
      }
      return { value: '-', detail: 'missing' };
    }

    function pct(value) {
      if (value === null || value === undefined || value === '') return '-';
      const parsed = Number(value);
      if (Number.isNaN(parsed)) return '-';
      return `${parsed.toFixed(1)}%`;
    }

    function listCodes(items) {
      if (!Array.isArray(items) || !items.length) return ['-'];
      return items.map((item) => item.code || item.title || '-');
    }

    function chip(text, muted = false) {
      return `<span class="pill${muted ? ' muted' : ''}">${text}</span>`;
    }

    function toneClassForAction(code) {
      if (code === 'LOW_FUEL') return 'tone-warn';
      if (code === 'DYNAMICS_UNSTABLE' || code === 'SAFETY_CAR') return 'tone-bad';
      if (code && code !== 'NONE') return 'tone-good';
      return '';
    }

    function kvCell(label, value, detail = '') {
      return `<div class="kv"><small>${label}</small><strong>${value}</strong><div class="subtext">${detail || '&nbsp;'}</div></div>`;
    }

    function renderMeta() {
      const chips = [
        `赛道 ${latest.track || '-'}`,
        `天气 ${latest.weather || '-'}`,
        `采样时长 ${timingSummary.capture_wall_label || '-'}`,
        `会话跨度 ${timingSummary.session_span_label || '-'}`,
        `总帧数 ${frames.length}`,
      ];
      metaStrip.innerHTML = chips.map((item) => `<div class="meta-chip">${item}</div>`).join('');
      lapFilter.innerHTML = `<option value="all">全部圈数</option>` + laps.map((lap) => `<option value="${lap}">Lap ${lap}</option>`).join('');
    }

    function renderCurrentFrame(frame) {
      const gapAhead = gapWithSource(frame.official_gap_ahead_s, frame.estimated_gap_ahead_s);
      const gapBehind = gapWithSource(frame.official_gap_behind_s, frame.estimated_gap_behind_s);
      currentFrameGrid.innerHTML = [
        kvCell('Top Message', `<span class="${toneClassForAction(frame.top_message)}">${frame.top_message || 'NONE'}</span>`, frame.top_detail || '无额外说明'),
        kvCell('Lap / Total', `${frame.lap || '-'} / ${frame.total_laps || '-'}`, `frame=${frame.frame}`),
        kvCell('Position / Speed', `P${frame.position || '-'} / ${num(frame.speed)} km/h`, frame.track || '-'),
        kvCell('Track Context', `${frame.track_segment || '-'} / ${frame.track_usage || '-'}`, frame.track_zone || '-'),
        kvCell('Gap Ahead', gapAhead.value, `玩家与前车 · ${gapAhead.detail}`),
        kvCell('Gap Behind', gapBehind.value, `玩家与后车 · ${gapBehind.detail}`),
        kvCell('Fuel / ERS', `${num(frame.fuel_laps_remaining, 2)} laps / ${pct(frame.ers_pct)}`, `wear=${pct(frame.tyre_wear_pct)}`),
        kvCell('Controls', `T${num(frame.throttle, 2)} B${num(frame.brake, 2)} S${num(frame.steer, 2)}`, `G${frame.gear ?? '-'} / ${frame.rpm ?? '-'} rpm`),
      ].join('');
    }

    function renderRivals(frame) {
      const rivals = [
        ['前车', frame.front_rival],
        ['后车', frame.rear_rival],
      ];
      rivalGrid.innerHTML = rivals.map(([label, rival]) => `
        <div class="rival-card">
          <h3>${label} · ${rival?.name || '-'}</h3>
          <div class="rival-stats">
            <div><small>位置</small><strong>${rival?.position ? `P${rival.position}` : '-'}</strong></div>
            <div><small>与前车差距</small><strong>${gap(rival?.display_gap_ahead_s)}</strong><div class="subtext">${rival?.official_gap_ahead_s != null ? 'official' : (rival?.estimated_gap_ahead_s != null ? 'estimated' : 'missing')}</div></div>
            <div><small>与后车差距</small><strong>${gap(rival?.display_gap_behind_s)}</strong><div class="subtext">${rival?.official_gap_behind_s != null ? 'official' : (rival?.estimated_gap_behind_s != null ? 'estimated' : 'missing')}</div></div>
            <div><small>速度</small><strong>${rival?.speed_kph != null ? `${num(rival.speed_kph)} km/h` : '-'}</strong></div>
            <div><small>ERS</small><strong>${pct(rival?.ers_pct)}</strong></div>
            <div><small>DRS</small><strong>${rival?.drs_available ? 'OPEN' : 'OFF'}</strong></div>
          </div>
        </div>
      `).join('');
    }

    function renderDecisionTrace(frame) {
      const modelDebug = frame.stage_two_model_debug || {};
      const arbiterInput = modelDebug.arbiter_input || {};
      const arbiterOutput = modelDebug.arbiter_output || {};
      const tactical = arbiterInput.tactical_context || {};
      const confidence = arbiterInput.confidence_context || {};
      const fallback = arbiterInput.fallback_context || {};
      const outputControl = arbiterInput.output_control || {};
      const traces = [
        {
          title: 'Messages',
          value: listCodes(frame.messages || []).join(' / '),
          detail: frame.top_detail || '当前帧输出栈。',
          pills: (frame.messages || []).map((item) => chip(`${item.code || item.title || '-'}@${item.priority ?? '-'}`)),
        },
        {
          title: 'Arbiter',
          value: `${arbiterOutput.final_hud_action?.code || '-'} / ${arbiterOutput.final_voice_action?.code || '-'}`,
          detail: `ordered=${listCodes(arbiterOutput.ordered_actions || []).join(' / ')} | suppressed=${listCodes(arbiterOutput.suppressed_actions || []).join(' / ')}`,
          pills: [
            chip(`rules ${listCodes(arbiterInput.rule_candidates || []).join(' / ')}`, true),
            chip(`models ${listCodes(arbiterInput.model_candidates || []).join(' / ')}`, true),
          ],
        },
        {
          title: 'Tactical State',
          value: tactical.tactical_state || '-',
          detail: `transition=${tactical.state_transition || '-'} | lock=${tactical.state_lock ? 'yes' : 'no'} | priority=${tactical.state_priority_hint || '-'}`,
          pills: [
            chip(`recommended ${tactical.recommended_action || '-'}`),
            chip(`history-hold ${tactical.history_hold_applied ? 'yes' : 'no'}`, true),
          ],
        },
        {
          title: 'Confidence / Fallback',
          value: `${confidence.confidence_level || '-'} / ${fallback.fallback_mode || '-'}`,
          detail: `score=${num(confidence.confidence_score, 2)} | mainline=${fallback.mainline_allowed ? 'yes' : 'no'} | voice=${outputControl.voice_allowed === false ? 'muted' : 'open'}`,
          pills: [
            chip(`hud-only ${outputControl.hud_only ? 'yes' : 'no'}`, true),
            chip(`voice priority floor ${outputControl.voice_priority_floor || '-'}`, true),
          ],
        },
      ];
      decisionTrace.innerHTML = traces.map((item) => `
        <div class="trace-row">
          <header><strong>${item.title}</strong><span>${item.value}</span></header>
          <p>${item.detail}</p>
          <div class="pill-list">${item.pills.join('')}</div>
        </div>
      `).join('');
    }

    function renderModelSignals(frame) {
      const modelDebug = frame.stage_two_model_debug || {};
      const resource = modelDebug.resource_models || {};
      const pressure = modelDebug.rival_pressure_models || {};
      const quality = modelDebug.driving_quality_models || {};
      const tyreTrend = modelDebug.tyre_degradation_trend_models || {};
      const defence = modelDebug.defence_cost_model || {};
      const rows = [
        ['Fuel Risk', num(resource.fuel_risk?.score, 1), '参与 LOW_FUEL 偏置'],
        ['Dynamics Risk', num(resource.dynamics_risk?.score, 1), '参与 DYNAMICS_UNSTABLE 偏置'],
        ['Rear Pressure', num(pressure.rear_pressure?.score, 1), '参与 DEFEND_WINDOW 偏置'],
        ['Defence Cost', num(defence.score, 1), '防守代价侧信号'],
        ['Entry / Apex / Exit', `${num(quality.entry_quality?.score, 1)} / ${num(quality.apex_quality?.score, 1)} / ${num(quality.exit_traction?.score, 1)}`, '驾驶质量分数'],
        ['Tyre / Grip Trend', `${num(tyreTrend.future_tyre_wear_delta?.score, 1)} / ${num(tyreTrend.future_grip_drop_score?.score, 1)}`, '轮胎趋势分数'],
        ['Strategy Candidates', String((modelDebug.strategy_action_model?.model_candidates || []).length), listCodes(modelDebug.strategy_action_model?.model_candidates || []).join(' / ')],
      ];
      modelSignals.innerHTML = rows.map(([label, value, detail]) => `
        <div class="signal-row">
          <header><strong>${label}</strong><span>${value}</span></header>
          <p>${detail}</p>
        </div>
      `).join('');
    }

    function renderNeighbors(index) {
      const rows = [
        ['上一帧', filteredFrames[index - 1]],
        ['当前帧', filteredFrames[index]],
        ['下一帧', filteredFrames[index + 1]],
      ];
      neighborRows.innerHTML = rows.map(([label, item]) => {
        if (!item) {
          return `<tr><td>${label}</td><td colspan="5" class="tone-warn">无数据</td></tr>`;
        }
        return `
          <tr>
            <td>${label}</td>
            <td>${item.frame}</td>
            <td>${num(item.session_time_s, 3)}s</td>
            <td>${item.top_message || 'NONE'}</td>
            <td>${num(item.speed, 1)} km/h</td>
            <td>${gap(item.gap_behind_s)}</td>
          </tr>
        `;
      }).join('');
    }

    function segmentColor(zoneType) {
      if ((zoneType || '').includes('braking')) return '#b33d3f';
      if ((zoneType || '').includes('corner')) return '#a45a00';
      if ((zoneType || '').includes('deployment')) return '#117a5a';
      return '#0b63ce';
    }

    function renderTrackContext(frame) {
      const lapLength = Number(trackProfile.lap_length_m || 0);
      const segments = Array.isArray(trackProfile.semantic_segments) ? trackProfile.semantic_segments : [];
      const lapDistance = Number(frame.lap_distance_m);
      if (!lapLength || Number.isNaN(lapDistance) || !segments.length || !trackSegments || !trackMarker) {
        trajectoryMeta.textContent = '当前样本没有可用的赛道语义分段。';
        if (trackSegments) trackSegments.innerHTML = '';
        if (trackContextGrid) trackContextGrid.innerHTML = '';
        return;
      }

      const currentSegment = segments.find((segment) => lapDistance >= Number(segment.start_m || 0) && lapDistance <= Number(segment.end_m || 0));
      const currentIndex = currentSegment ? segments.findIndex((segment) => segment.name === currentSegment.name) : -1;
      const previousSegment = currentIndex > 0 ? segments[currentIndex - 1] : null;
      const nextSegment = currentIndex >= 0 && currentIndex < segments.length - 1 ? segments[currentIndex + 1] : null;
      const nearestApexes = (Array.isArray(trackProfile.corner_apexes) ? trackProfile.corner_apexes : [])
        .map((apex) => ({ ...apex, delta: Math.abs(Number(apex.distance_m || 0) - lapDistance) }))
        .sort((a, b) => a.delta - b.delta);
      const nearestApex = nearestApexes[0] || null;
      const activeBrakingZone = (Array.isArray(trackProfile.braking_zones) ? trackProfile.braking_zones : []).find((zone) => {
        const start = Number(zone.start_m || 0);
        const end = Number(zone.end_m || 0);
        return lapDistance >= start && lapDistance <= end;
      });

      trackSegments.innerHTML = segments.map((segment) => {
        const start = Number(segment.start_m || 0);
        const end = Number(segment.end_m || 0);
        const left = (start / lapLength) * 100;
        const width = Math.max(((end - start) / lapLength) * 100, 0.35);
        const active = currentSegment && currentSegment.name === segment.name;
        return `<div class="track-segment" style="left:${left}%;width:${width}%;background:${segmentColor(segment.zone_type)};opacity:${active ? '1' : '0.72'}"></div>`;
      }).join('');

      const playerLeft = (Math.max(Math.min(lapDistance, lapLength), 0) / lapLength) * 100;
      trackMarker.style.left = `${playerLeft}%`;

      trajectoryMeta.innerHTML = [
        `当前落点 ${lapDistance.toFixed(0)}m / ${lapLength.toFixed(0)}m`,
        `Lap ${frame.lap || '-'} / ${frame.total_laps || '-'}`,
        `当前位置 ${currentSegment ? currentSegment.name : '-'}`,
        `Usage ${currentSegment?.usage || frame.track_usage || '-'}`,
        `P${frame.position || '-'} · ${num(frame.speed, 1)} km/h`,
      ].map((item) => `<span>${item}</span>`).join('');

      trackContextGrid.innerHTML = [
        ['当前赛段', currentSegment?.name || '-', currentSegment?.zone_type || '-'],
        ['上一赛段', previousSegment?.name || '-', previousSegment?.usage || '-'],
        ['下一赛段', nextSegment?.name || '-', nextSegment?.usage || '-'],
        ['最近 Apex', nearestApex?.name || '-', nearestApex ? `距离 ${nearestApex.delta.toFixed(0)}m` : '-'],
        ['Braking Zone', activeBrakingZone?.name || '当前不在制动区', activeBrakingZone ? `${activeBrakingZone.start_m.toFixed(0)}m - ${activeBrakingZone.end_m.toFixed(0)}m` : '-'],
        ['前后车判断', `前车 ${gap(frame.gap_ahead_s)} / 后车 ${gap(frame.gap_behind_s)}`, '这里统一用时间差，不再显示圈内米数'],
      ].map(([label, value, detail]) => `
        <div class="track-context-card">
          <small>${label}</small>
          <strong>${value}</strong>
          <div class="subtext">${detail}</div>
        </div>
      `).join('');
    }

    function renderDebug(frame) {
      debugJson.textContent = JSON.stringify({
        frame: frame.frame,
        lap: frame.lap,
        messages: frame.messages,
        runtime_timing: frame.runtime_timing,
        stage_two_model_debug: frame.stage_two_model_debug,
      }, null, 2);
    }

    function renderFrame(index) {
      if (!filteredFrames.length) return;
      playbackIndex = Math.min(Math.max(index, 0), filteredFrames.length - 1);
      const frame = filteredFrames[playbackIndex];
      frameIndex.textContent = `${playbackIndex + 1} / ${filteredFrames.length}`;
      timelineFrame.textContent = `#${frame.frame}`;
      timelineTime.textContent = `Lap ${frame.lap || '-'} · ${num(frame.session_time_s, 3)}s`;
      timelineTrack.textContent = frame.track_segment || '-';
      timelineUsage.textContent = `${frame.track_usage || '-'} / ${frame.track_zone || '-'}`;
      timelineMessage.innerHTML = `<span class="${toneClassForAction(frame.top_message)}">${frame.top_message || 'NONE'}</span>`;
      timelinePriority.textContent = `priority=${frame.top_priority || 0}`;
      slider.value = String(playbackIndex);
      renderCurrentFrame(frame);
      renderRivals(frame);
      renderDecisionTrace(frame);
      renderModelSignals(frame);
      renderNeighbors(playbackIndex);
      renderTrackContext(frame);
      renderDebug(frame);
    }

    function clearPlayback() {
      if (playbackTimer !== null) {
        clearInterval(playbackTimer);
        playbackTimer = null;
      }
    }

    function updatePlayLabel() {
      playToggle.textContent = isPlaying ? '暂停' : '播放';
    }

    function applyLapFilter() {
      clearPlayback();
      isPlaying = false;
      updatePlayLabel();
      const selectedLap = lapFilter.value;
      filteredFrames = selectedLap === 'all' ? frames.slice() : frames.filter((frame) => String(frame.lap) === selectedLap);
      slider.min = 0;
      slider.max = String(Math.max(filteredFrames.length - 1, 0));
      playbackIndex = Math.max(filteredFrames.length - 1, 0);
      renderFrame(playbackIndex);
    }

    function step(delta) {
      if (!filteredFrames.length) return;
      clearPlayback();
      isPlaying = false;
      updatePlayLabel();
      renderFrame(Math.min(Math.max(playbackIndex + delta, 0), filteredFrames.length - 1));
    }

    lapFilter.addEventListener('change', applyLapFilter);
    slider.addEventListener('input', () => {
      clearPlayback();
      isPlaying = false;
      updatePlayLabel();
      renderFrame(Number(slider.value || 0));
    });
    prevFrameButton.addEventListener('click', () => step(-1));
    nextFrameButton.addEventListener('click', () => step(1));
    playToggle.addEventListener('click', () => {
      isPlaying = !isPlaying;
      updatePlayLabel();
      clearPlayback();
      if (!isPlaying) return;
      playbackTimer = setInterval(() => {
        if (playbackIndex >= filteredFrames.length - 1) {
          clearPlayback();
          isPlaying = false;
          updatePlayLabel();
          return;
        }
        renderFrame(playbackIndex + 1);
      }, 120);
    });

    renderMeta();
    updatePlayLabel();
    applyLapFilter();
  
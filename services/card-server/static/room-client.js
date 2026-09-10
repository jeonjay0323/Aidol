/**
 * 멀티콜 클라이언트.
 *
 * 마이크는 하나지만 아바타는 여럿이다. 서버가 매 턴 화자를 정해 알려주므로,
 * 응답 오디오에 실린 cardId를 보고 해당 아바타의 Simli 세션으로만 흘려보낸다.
 */
window.AidolRoom = (() => {
  let ws = null, micCtx = null, playCtx = null, processor = null, micStream = null;
  let members = {};           // cardId -> {pc, ws, buffer, videoEl}
  let nextPlayTime = 0, activeSources = 0, muted = false, active = false;
  let hooks = {};
  const SIMLI_CHUNK = 3200;

  async function initSimli(cardId, faceId, videoEl) {
    const { session_token } = await (await fetch('/api/simli/token', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ faceId })
    })).json();

    let iceServers = [{ urls: 'stun:stun.l.google.com:19302' }];
    try { const r = await fetch('/api/simli/ice'); if (r.ok) iceServers = await r.json(); } catch (_) {}

    const pc = new RTCPeerConnection({ iceServers });
    pc.addTransceiver('audio', { direction: 'recvonly' });
    pc.addTransceiver('video', { direction: 'recvonly' });
    pc.ontrack = (e) => {
      if (e.track.kind === 'video' && videoEl) {
        videoEl.srcObject = e.streams[0];
        videoEl.style.display = 'block';
        videoEl.play().catch(() => {});
        hooks.onVideo && hooks.onVideo(cardId);
      }
    };
    const offer = await pc.createOffer();
    await pc.setLocalDescription(offer);
    await waitForIce(pc);

    const sws = new WebSocket(
      `wss://api.simli.ai/compose/webrtc/p2p?session_token=${session_token}&enableSFU=true`);
    sws.onopen = () => sws.send(JSON.stringify(pc.localDescription));
    sws.onmessage = async (e) => {
      if (e.data.toUpperCase().split(' ')[0].includes('SDP'))
        await pc.setRemoteDescription(new RTCSessionDescription(JSON.parse(e.data)));
    };
    members[cardId] = { pc, ws: sws, buffer: new Int16Array(0), videoEl };
  }

  function waitForIce(pc) {
    return new Promise((resolve) => {
      if (pc.iceGatheringState === 'complete') return resolve();
      let prev = 0, count = 0;
      pc.onicecandidate = () => count++;
      const check = () => {
        if (pc.iceGatheringState === 'complete' || count === prev) resolve();
        else { prev = count; setTimeout(check, 150); }
      };
      setTimeout(check, 150);
    });
  }

  function toSimli(cardId, bytes) {
    const m = members[cardId];
    if (!m || !m.ws || m.ws.readyState !== WebSocket.OPEN) return;
    const re = resample24to16(new Int16Array(bytes));
    const merged = new Int16Array(m.buffer.length + re.length);
    merged.set(m.buffer); merged.set(re, m.buffer.length);
    m.buffer = merged;
    while (m.buffer.length >= SIMLI_CHUNK) {
      m.ws.send(new Uint8Array(m.buffer.slice(0, SIMLI_CHUNK).buffer));
      m.buffer = m.buffer.slice(SIMLI_CHUNK);
    }
  }
  function flushSimli(cardId) {
    const m = members[cardId];
    if (m && m.ws && m.ws.readyState === WebSocket.OPEN && m.buffer.length)
      m.ws.send(new Uint8Array(m.buffer.buffer));
    if (m) m.buffer = new Int16Array(0);
  }
  function resample24to16(input) {
    const outLen = Math.floor(input.length * 2 / 3), out = new Int16Array(outLen);
    for (let i = 0; i < outLen; i++) {
      const src = i * 1.5, lo = Math.floor(src), hi = Math.min(lo + 1, input.length - 1);
      out[i] = Math.round(input[lo] * (1 - (src - lo)) + input[hi] * (src - lo));
    }
    return out;
  }

  async function startMic() {
    micCtx = new AudioContext({ sampleRate: 16000 });
    micStream = await navigator.mediaDevices.getUserMedia({
      audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true } });
    await micCtx.audioWorklet.addModule('/static/pcm-processor.js');
    const source = micCtx.createMediaStreamSource(micStream);
    processor = new AudioWorkletNode(micCtx, 'pcm-processor');

    const THRESH = 0.02, SILENCE_MS = 1000, MIN_CHUNKS = 15, PREROLL = 5;
    let state = 'silent', timer = null, count = 0, preroll = [];

    processor.port.onmessage = (e) => {
      if (!ws || ws.readyState !== WebSocket.OPEN || activeSources > 0 || muted) return;
      const samples = e.data, b64 = toBase64(float32ToPCM16(samples));
      let rms = 0;
      for (let i = 0; i < samples.length; i++) rms += samples[i] * samples[i];
      rms = Math.sqrt(rms / samples.length);

      if (rms > THRESH) {
        if (state === 'silent') {
          state = 'speaking'; count = 0;
          ws.send(JSON.stringify({ type: 'activity_start' }));
          preroll.forEach(b => ws.send(JSON.stringify({ type: 'audio', data: b })));
          preroll = [];
          hooks.onUserSpeaking && hooks.onUserSpeaking(true);
        }
        count++;
        clearTimeout(timer);
        timer = setTimeout(() => {
          if (count >= MIN_CHUNKS) ws.send(JSON.stringify({ type: 'activity_end' }));
          state = 'silent'; count = 0;
          hooks.onUserSpeaking && hooks.onUserSpeaking(false);
        }, SILENCE_MS);
        ws.send(JSON.stringify({ type: 'audio', data: b64 }));
      } else if (state === 'silent') {
        preroll.push(b64);
        if (preroll.length > PREROLL) preroll.shift();
      } else {
        ws.send(JSON.stringify({ type: 'audio', data: b64 }));
      }
    };
    source.connect(processor);
    processor.connect(micCtx.destination);
  }

  function schedule(pcm) {
    if (!playCtx) return;
    activeSources++;
    const samples = pcmToFloat32(pcm);
    const buf = playCtx.createBuffer(1, samples.length, 24000);
    buf.copyToChannel(samples, 0);
    const src = playCtx.createBufferSource();
    src.buffer = buf; src.connect(playCtx.destination);
    const at = Math.max(playCtx.currentTime, nextPlayTime);
    src.start(at);
    nextPlayTime = at + buf.duration;
    src.onended = () => { activeSources--; };
  }

  /* ── 공개 API ── */
  async function start(cardIds, getVideoEl, cb = {}) {
    hooks = cb; active = true;
    playCtx = new AudioContext({ sampleRate: 24000 });
    nextPlayTime = 0; activeSources = 0; muted = false; members = {};

    const proto = location.protocol === 'https:' ? 'wss' : 'ws';
    ws = new WebSocket(`${proto}://${location.host}/ws/room`);
    ws.onopen = () => ws.send(JSON.stringify({ cardIds }));

    ws.onmessage = async (e) => {
      const msg = JSON.parse(e.data);
      if (msg.type === 'joined') {
        hooks.onJoined && hooks.onJoined(msg.members);
        for (const m of msg.members) {
          if (!m.faceId) continue;
          try { await initSimli(m.cardId, m.faceId, getVideoEl(m.cardId)); }
          catch (err) { console.warn('Simli 실패', m.name, err); }
        }
        try { await startMic(); hooks.onMicReady && hooks.onMicReady(); }
        catch (err) { hooks.onMicDenied && hooks.onMicDenied(err); }
      } else if (msg.type === 'turn_start') {
        hooks.onTurn && hooks.onTurn(msg.cardId);
      } else if (msg.type === 'audio') {
        const bytes = fromBase64(msg.data);
        schedule(bytes);
        toSimli(msg.cardId, bytes);
      } else if (msg.type === 'turn_complete') {
        flushSimli(msg.cardId);
        hooks.onSaid && hooks.onSaid(msg.cardId, msg.text);
      } else if (msg.type === 'error') {
        hooks.onError && hooks.onError(msg.data);
      }
    };
    ws.onclose = () => { if (active) end(); };
  }

  function target(cardId) {
    if (ws && ws.readyState === WebSocket.OPEN)
      ws.send(JSON.stringify({ type: 'target', cardId }));
  }

  function end() {
    if (!active && !ws && !playCtx) return;
    active = false;
    if (ws) { ws.close(); ws = null; }
    Object.values(members).forEach(m => { m.ws && m.ws.close(); m.pc && m.pc.close(); });
    members = {};
    if (processor) { processor.disconnect(); processor = null; }
    if (micStream) { micStream.getTracks().forEach(t => t.stop()); micStream = null; }
    if (micCtx) { micCtx.close(); micCtx = null; }
    if (playCtx) { playCtx.close(); playCtx = null; }
    hooks.onEnd && hooks.onEnd();
  }

  function toggleMute() { muted = !muted; return muted; }

  function float32ToPCM16(f32) {
    const buf = new ArrayBuffer(f32.length * 2), view = new DataView(buf);
    for (let i = 0; i < f32.length; i++) {
      const s = Math.max(-1, Math.min(1, f32[i]));
      view.setInt16(i * 2, s < 0 ? s * 0x8000 : s * 0x7FFF, true);
    }
    return buf;
  }
  function pcmToFloat32(buf) {
    const view = new DataView(buf), out = new Float32Array(buf.byteLength / 2);
    for (let i = 0; i < out.length; i++) out[i] = view.getInt16(i * 2, true) / 0x8000;
    return out;
  }
  function toBase64(buf) { let b = ''; new Uint8Array(buf).forEach(x => b += String.fromCharCode(x)); return btoa(b); }
  function fromBase64(b64) {
    const bin = atob(b64), buf = new ArrayBuffer(bin.length), v = new Uint8Array(buf);
    for (let i = 0; i < bin.length; i++) v[i] = bin.charCodeAt(i);
    return buf;
  }

  return { start, end, target, toggleMute };
})();

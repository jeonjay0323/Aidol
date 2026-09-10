/**
 * 카드 통화 클라이언트.
 *
 * 오디오가 두 갈래로 흐른다:
 *   Gemini Live 응답(24kHz) → 스피커
 *                           → 16kHz 리샘플 → Simli WebRTC → 립싱크 영상
 * 얼굴이 아직 준비되지 않은 카드는 Simli 없이 음성만 흐른다.
 */
window.AidolCall = (() => {
  let ws = null, micCtx = null, playCtx = null, processor = null, micStream = null;
  let simliWs = null, simliPc = null, simliBuffer = new Int16Array(0);
  let nextPlayTime = 0, activeSources = 0, muted = false, active = false;
  let hooks = {};

  const SIMLI_CHUNK = 3200;

  /* ── Simli ── */
  let t0 = 0;
  async function initSimli(faceId, videoEl) {
    t0 = performance.now();
    const { session_token } = await (await fetch('/api/simli/token', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ faceId })
    })).json();

    let iceServers = [{ urls: 'stun:stun.l.google.com:19302' }];
    try {
      const r = await fetch('/api/simli/ice');
      if (r.ok) iceServers = await r.json();
    } catch (_) {}

    simliPc = new RTCPeerConnection({ iceServers });
    simliPc.addTransceiver('audio', { direction: 'recvonly' });
    simliPc.addTransceiver('video', { direction: 'recvonly' });
    simliPc.ontrack = (e) => {
      if (e.track.kind === 'video' && videoEl) {
        console.log('[Simli] 영상 도착', Math.round(performance.now() - t0), 'ms');
        videoEl.srcObject = e.streams[0];
        videoEl.style.display = 'block';
        videoEl.play().catch(() => {});
        hooks.onVideo && hooks.onVideo();
      }
    };

    const offer = await simliPc.createOffer();
    await simliPc.setLocalDescription(offer);
    await waitForIce(simliPc);

    simliWs = new WebSocket(
      `wss://api.simli.ai/compose/webrtc/p2p?session_token=${session_token}&enableSFU=true`);
    simliWs.onopen = () => {
      console.log('[Simli] WS 연결', Math.round(performance.now() - t0), 'ms');
      simliWs.send(JSON.stringify(simliPc.localDescription));
    };
    simliWs.onmessage = async (e) => {
      if (e.data.toUpperCase().split(' ')[0].includes('SDP')) {
        await simliPc.setRemoteDescription(new RTCSessionDescription(JSON.parse(e.data)));
      }
    };
  }

  // ICE 수집은 최대 2초만 기다린다. 상한이 없으면 후보가 계속 들어올 때
  // 연결이 시작조차 못 한다 (얼굴이 안 뜨는 주된 원인).
  function waitForIce(pc, timeoutMs = 2000) {
    return new Promise((resolve) => {
      if (pc.iceGatheringState === 'complete') return resolve();
      let done = false;
      const finish = () => { if (!done) { done = true; resolve(); } };
      const timer = setTimeout(finish, timeoutMs);
      pc.addEventListener('icegatheringstatechange', () => {
        if (pc.iceGatheringState === 'complete') { clearTimeout(timer); finish(); }
      });
    });
  }

  function sendToSimli(bytes) {
    if (!simliWs || simliWs.readyState !== WebSocket.OPEN) return;
    const re = resample24to16(new Int16Array(bytes));
    const merged = new Int16Array(simliBuffer.length + re.length);
    merged.set(simliBuffer); merged.set(re, simliBuffer.length);
    simliBuffer = merged;
    while (simliBuffer.length >= SIMLI_CHUNK) {
      simliWs.send(new Uint8Array(simliBuffer.slice(0, SIMLI_CHUNK).buffer));
      simliBuffer = simliBuffer.slice(SIMLI_CHUNK);
    }
  }
  function flushSimli() {
    if (simliWs && simliWs.readyState === WebSocket.OPEN && simliBuffer.length)
      simliWs.send(new Uint8Array(simliBuffer.buffer));
    simliBuffer = new Int16Array(0);
  }
  function resample24to16(input) {
    const outLen = Math.floor(input.length * 2 / 3);
    const out = new Int16Array(outLen);
    for (let i = 0; i < outLen; i++) {
      const src = i * 1.5, lo = Math.floor(src), hi = Math.min(lo + 1, input.length - 1);
      out[i] = Math.round(input[lo] * (1 - (src - lo)) + input[hi] * (src - lo));
    }
    return out;
  }

  /* ── 마이크 · VAD ── */
  async function startMic() {
    micCtx = new AudioContext({ sampleRate: 16000 });
    micStream = await navigator.mediaDevices.getUserMedia({
      audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true }
    });
    await micCtx.audioWorklet.addModule('/static/pcm-processor.js');
    const source = micCtx.createMediaStreamSource(micStream);
    processor = new AudioWorkletNode(micCtx, 'pcm-processor');

    // 임계값 직전 청크를 들고 있다가 발화 시작 때 함께 보낸다 → 첫 음절 잘림 방지
    const THRESH = 0.02, SILENCE_MS = 1000, MIN_CHUNKS = 15, PREROLL = 5;
    let state = 'silent', timer = null, count = 0, preroll = [];

    processor.port.onmessage = (e) => {
      if (!ws || ws.readyState !== WebSocket.OPEN || activeSources > 0 || muted) return;
      const samples = e.data;
      const b64 = toBase64(float32ToPCM16(samples));
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

  /* ── 재생 ── */
  function schedule(pcm) {
    if (!playCtx) return;
    activeSources++;
    hooks.onSpeaking && hooks.onSpeaking(true);
    const samples = pcmToFloat32(pcm);
    const buf = playCtx.createBuffer(1, samples.length, 24000);
    buf.copyToChannel(samples, 0);
    const src = playCtx.createBufferSource();
    src.buffer = buf;
    src.connect(playCtx.destination);
    const at = Math.max(playCtx.currentTime, nextPlayTime);
    src.start(at);
    nextPlayTime = at + buf.duration;
    src.onended = () => {
      activeSources--;
      if (activeSources === 0) hooks.onSpeaking && hooks.onSpeaking(false);
    };
  }

  /* ── 공개 API ── */
  async function start(cardId, videoEl, cb = {}) {
    hooks = cb;
    active = true;
    playCtx = new AudioContext({ sampleRate: 24000 });
    nextPlayTime = 0; activeSources = 0; muted = false;

    const proto = location.protocol === 'https:' ? 'wss' : 'ws';
    ws = new WebSocket(`${proto}://${location.host}/ws/call/${cardId}`);

    ws.onmessage = async (e) => {
      const msg = JSON.parse(e.data);
      if (msg.type === 'connected') {
        // 화면을 먼저 연다. 마이크 권한 대기 때문에 로딩에 갇히지 않도록.
        hooks.onConnected && hooks.onConnected(msg);
        if (msg.faceId) {
          try { await initSimli(msg.faceId, videoEl); }
          catch (err) { console.warn('Simli 연결 실패, 음성으로 진행:', err); }
        }
        try {
          await startMic();
          hooks.onMicReady && hooks.onMicReady();
        } catch (err) {
          console.warn('마이크 실패:', err);
          hooks.onMicDenied && hooks.onMicDenied(err);
        }
      } else if (msg.type === 'audio') {
        const bytes = fromBase64(msg.data);
        schedule(bytes);
        sendToSimli(bytes);
      } else if (msg.type === 'turn_complete') {
        flushSimli();
      } else if (msg.type === 'error') {
        hooks.onError && hooks.onError(msg.data);
      }
    };
    ws.onclose = () => { if (active) end(); };
    ws.onerror = () => hooks.onError && hooks.onError('연결 오류');
  }

  function end() {
    // endCall() ↔ onEnd() 상호 호출이 무한 루프가 되지 않도록 막는다
    if (!active && !ws && !playCtx) return;
    active = false;
    if (ws) { ws.close(); ws = null; }
    if (simliWs) { simliWs.close(); simliWs = null; }
    pending = [];
    if (simliPc) { simliPc.close(); simliPc = null; }
    if (processor) { processor.disconnect(); processor = null; }
    if (micStream) { micStream.getTracks().forEach(t => t.stop()); micStream = null; }
    if (micCtx) { micCtx.close(); micCtx = null; }
    if (playCtx) { playCtx.close(); playCtx = null; }
    simliBuffer = new Int16Array(0);
    hooks.onEnd && hooks.onEnd();
  }

  function toggleMute() { muted = !muted; return muted; }

  /* ── 유틸 ── */
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
  function toBase64(buf) {
    let b = ''; new Uint8Array(buf).forEach(x => b += String.fromCharCode(x));
    return btoa(b);
  }
  function fromBase64(b64) {
    const bin = atob(b64), buf = new ArrayBuffer(bin.length), v = new Uint8Array(buf);
    for (let i = 0; i < bin.length; i++) v[i] = bin.charCodeAt(i);
    return buf;
  }

  return { start, end, toggleMute };
})();

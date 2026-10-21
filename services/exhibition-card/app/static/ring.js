/* 아이돌이 먼저 거는 전화 — 수신 화면.
   기획의 핵심 훅("선택하는 게 아니라 선택받는 경험")을 웹 안에서 보여준다.
   만들기 직후(create.js)와 카드 화면 ?ring=1 이 같이 쓴다. 스타일은 scan.css 의 .ring.

   AidolRing.show({ name, image, label, onAccept, onDecline })
   벨소리는 WebAudio 로 직접 만든다. 사용자가 이 페이지를 한 번도 누르지 않았으면
   브라우저가 소리를 막는데, 그때는 화면만 울린다. */
window.AidolRing = (() => {
  let el = null, ctx = null, timer = null, stopTimer = null;

  function tone() {
    try {
      ctx = ctx || new AudioContext();
      if (ctx.state === 'suspended') ctx.resume();
      // 두 음을 짧게 두 번 — 폰 벨소리처럼 들리되 거슬리지 않게
      const t0 = ctx.currentTime;
      [[0, 784], [0.18, 988], [0.5, 784], [0.68, 988]].forEach(([at, f]) => {
        const o = ctx.createOscillator(), g = ctx.createGain();
        o.type = 'sine'; o.frequency.value = f;
        g.gain.setValueAtTime(0, t0 + at);
        g.gain.linearRampToValueAtTime(0.18, t0 + at + 0.02);
        g.gain.exponentialRampToValueAtTime(0.001, t0 + at + 0.16);
        o.connect(g).connect(ctx.destination);
        o.start(t0 + at); o.stop(t0 + at + 0.18);
      });
    } catch {}
    try { navigator.vibrate && navigator.vibrate([400, 200, 400]); } catch {}
  }

  function stop() {
    clearInterval(timer); clearTimeout(stopTimer);
    try { navigator.vibrate && navigator.vibrate(0); } catch {}
    if (el) { el.remove(); el = null; }
  }

  const esc = (s) => String(s ?? '').replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));

  function show({ name, image, label = '음성통화', onAccept, onDecline, timeout = 30000 }) {
    stop();
    el = document.createElement('div');
    el.className = 'ring';
    el.setAttribute('role', 'alertdialog');
    el.setAttribute('aria-label', `${name}에게서 전화가 왔어요`);
    el.innerHTML = `
      <div class="ring-bg" ${image ? `style="background-image:url('${esc(image)}')"` : ''}></div>
      <div class="ring-top">
        <div class="ring-app"><i></i>LUKIDS ${esc(label)}</div>
        <div class="ring-face">${image ? `<img src="${esc(image)}" alt="">` : ''}</div>
        <div class="ring-name">${esc(name)}</div>
        <div class="ring-sub">전화가 왔어요</div>
      </div>
      <div class="ring-acts">
        <button class="ring-btn no" type="button"><span><svg viewBox="0 0 24 24"><path d="M3.5 13.6c4.9-4.3 12.1-4.3 17 0l-1.9 2.6-3.4-1.2v-2.4a12 12 0 0 0-6.4 0V15l-3.4 1.2Z" fill="currentColor"/></svg></span>거절</button>
        <button class="ring-btn yes" type="button"><span><svg viewBox="0 0 24 24"><path d="M6.2 3.5h3l1.5 3.8-1.9 1.4a12 12 0 0 0 5.5 5.5l1.4-1.9 3.8 1.5v3a1.8 1.8 0 0 1-2 1.8A16.5 16.5 0 0 1 4.4 5.5a1.8 1.8 0 0 1 1.8-2Z" fill="currentColor"/></svg></span>받기</button>
      </div>`;
    document.body.appendChild(el);
    el.querySelector('.yes').onclick = () => { stop(); onAccept && onAccept(); };
    el.querySelector('.no').onclick = () => { stop(); onDecline && onDecline('declined'); };
    el.querySelector('.yes').focus();
    tone();
    timer = setInterval(tone, 2200);
    // 아무도 안 받으면 부재중
    stopTimer = setTimeout(() => { stop(); onDecline && onDecline('missed'); }, timeout);
  }

  // 사용자가 누른 순간(발급 버튼)에 불러 둔다. iOS 는 탭 밖에서 처음 만든 소리를 막는다
  function unlock() {
    try {
      ctx = ctx || new AudioContext();
      if (ctx.state === 'suspended') ctx.resume();
      const b = ctx.createBuffer(1, 1, 22050), s = ctx.createBufferSource();
      s.buffer = b; s.connect(ctx.destination); s.start(0);
    } catch {}
  }

  return { show, stop, unlock };
})();

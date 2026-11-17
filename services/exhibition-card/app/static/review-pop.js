/* 후기 팝업 — 모든 페이지에서 일정 시간이 지나면 한 번 뜬다(app/review.py 로 보내고 메일로 간다).
   통화 중이거나 채팅을 치는 중, 사진을 만드는 중이면 끝날 때까지 미룬다.
   한 번 보냈으면 그 기기에서는 하루 동안 다시 뜨지 않는다. 닫으면 몇 분 뒤 한 번 더 묻는다. */
(() => {
  const FIRST_SEC = 120;      // 처음 들어온 뒤 이만큼 머물면
  const AGAIN_SEC = 300;      // 닫았으면 이만큼 뒤 한 번 더
  const MAX_ASK = 2;          // 한 세션에 최대 몇 번 묻는지
  const S = (k, v) => { try { if (v === undefined) return sessionStorage.getItem(k); sessionStorage.setItem(k, v); } catch {} };
  const L = (k, v) => { try { if (v === undefined) return localStorage.getItem(k); localStorage.setItem(k, v); } catch {} };

  if (L('lukids.reviewedAt') && Date.now() - +L('lukids.reviewedAt') < 24 * 3600e3) return;
  if (!S('lukids.since')) S('lukids.since', Date.now());
  const asked = () => +(S('lukids.asked') || 0);

  // 지금 쓰고 있는 기능
  function feature(){
    const p = location.pathname;
    if (p === '/') return '홈';
    if (p.startsWith('/gallery')) return '전시';
    if (p.startsWith('/make')) return '제작';
    if (p.startsWith('/c/')) {
      const on = id => document.getElementById(id)?.classList.contains('on');
      if (on('c-solo') || on('c-multi')) return '통화';
      if (on('s-chat')) return '채팅';
      if (document.querySelector('.screen.on[id^="s-create"]')) return '제작';
      return '카드 화면';
    }
    return p;
  }
  // 방해하면 안 되는 순간
  function busy(){
    const on = id => document.getElementById(id)?.classList.contains('on');
    if (on('c-solo') || on('c-multi')) return true;
    const a = document.activeElement;
    if (a && (a.tagName === 'INPUT' || a.tagName === 'TEXTAREA') && a.value) return true;
    const gen = document.getElementById('gen-wait');
    if (gen && gen.offsetParent) return true;
    return document.querySelector('.site-sheet.on, .invite-sheet:not([hidden]), #rp-box.on');
  }

  const css = `
  #rp-box{position:fixed;inset:0;z-index:100;display:none;align-items:flex-end;justify-content:center;font-family:inherit}
  #rp-box.on{display:flex}
  #rp-box .rp-dim{position:absolute;inset:0;background:rgba(0,0,0,.6)}
  #rp-box .rp-card{position:relative;width:100%;max-width:440px;background:var(--bg-elevated,#1f1f22);color:var(--label-normal,#fff);
    border-radius:20px 20px 0 0;padding:22px 18px calc(18px + env(safe-area-inset-bottom));animation:rpUp .3s cubic-bezier(.2,.8,.3,1)}
  @media (min-width:600px){ #rp-box{align-items:center} #rp-box .rp-card{border-radius:20px} }
  @keyframes rpUp{from{transform:translateY(24px);opacity:0}to{transform:none;opacity:1}}
  #rp-box h3{font-size:19px;font-weight:800;margin:0 0 4px;line-height:26px}
  #rp-box p{font-size:13px;color:var(--label-alt,#aaa);margin:0 0 14px}
  #rp-box .rp-stars{display:flex;gap:6px;margin-bottom:14px}
  #rp-box .rp-stars button{flex:1;aspect-ratio:1;max-width:56px;border-radius:12px;cursor:pointer;font-size:26px;line-height:1;
    background:var(--fill-alt,#2a2a2e);border:1px solid var(--line-normal,#444);color:var(--label-assistive,#666)}
  #rp-box .rp-stars button.on{color:var(--primary-normal,#e63bc0);border-color:var(--primary-normal,#e63bc0)}
  #rp-box textarea,#rp-box input{width:100%;box-sizing:border-box;padding:12px;border-radius:12px;font:inherit;font-size:16px;margin-bottom:10px;
    background:var(--fill-alt,#2a2a2e);border:1px solid var(--line-normal,#444);color:var(--label-normal,#fff);resize:none}
  #rp-box .rp-acts{display:flex;gap:8px;margin-top:4px}
  #rp-box .rp-acts button{flex:1;padding:14px;border-radius:12px;border:none;cursor:pointer;font:inherit;font-weight:800;font-size:15px}
  #rp-box .rp-send{background:var(--primary-normal,#e63bc0);color:var(--static-black,#000)}
  #rp-box .rp-later{background:var(--fill-normal,#333);color:var(--label-normal,#fff)}
  #rp-box .rp-msg{font-size:13px;color:var(--status-negative,#f55);min-height:18px;margin:-4px 0 6px}`;

  let box, stars = 0, shownFeature = '';
  function build(){
    const st = document.createElement('style'); st.textContent = css; document.head.appendChild(st);
    box = document.createElement('div'); box.id = 'rp-box';
    box.setAttribute('role', 'dialog'); box.setAttribute('aria-modal', 'true'); box.setAttribute('aria-labelledby', 'rp-h');
    box.innerHTML = `<div class="rp-dim"></div><div class="rp-card">
      <h3 id="rp-h">루키즈 어때요?</h3><p id="rp-sub"></p>
      <div class="rp-stars">${[1,2,3,4,5].map(n => `<button type="button" data-n="${n}" aria-label="${n}점">★</button>`).join('')}</div>
      <textarea id="rp-text" rows="3" maxlength="1000" placeholder="재미있었던 점, 아쉬웠던 점을 자유롭게 써 주세요"></textarea>
      <input id="rp-name" maxlength="20" placeholder="닉네임 (안 써도 돼요)" autocomplete="off">
      <div class="rp-msg" id="rp-msg" role="status"></div>
      <div class="rp-acts"><button type="button" class="rp-later">나중에</button><button type="button" class="rp-send">보내기</button></div>
    </div>`;
    document.body.appendChild(box);
    box.querySelectorAll('.rp-stars button').forEach(b => b.onclick = () => {
      stars = +b.dataset.n;
      box.querySelectorAll('.rp-stars button').forEach(x => x.classList.toggle('on', +x.dataset.n <= stars));
    });
    box.querySelector('.rp-dim').onclick = close;
    box.querySelector('.rp-later').onclick = close;
    box.querySelector('.rp-send').onclick = send;
  }
  function open(){
    if (!box) build();
    shownFeature = feature();
    box.querySelector('#rp-sub').textContent = `지금 쓰고 있던 ‘${shownFeature}’에 대해 별점과 한마디를 남겨 주세요.`;
    box.querySelector('#rp-msg').textContent = '';
    box.classList.add('on');
    S('lukids.asked', asked() + 1);
  }
  function close(){
    box.classList.remove('on');
    if (asked() < MAX_ASK) schedule(AGAIN_SEC);
  }
  async function send(){
    const text = box.querySelector('#rp-text').value.trim();
    const msg = box.querySelector('#rp-msg');
    if (!stars && !text) { msg.textContent = '별점이나 하고 싶은 말을 남겨 주세요.'; return; }
    // CARD(카드 화면) · CREATE(만들기)는 페이지 스크립트의 전역 상수라 typeof 로 본다
    const card = typeof CARD !== 'undefined' ? CARD.card_id : (typeof CREATE !== 'undefined' && CREATE.cardId) || null;
    try {
      const r = await fetch('/api/review', { method:'POST', headers:{'Content-Type':'application/json'},
        body: JSON.stringify({ cardId: card, stars, text, name: box.querySelector('#rp-name').value.trim(),
                               feature: shownFeature, page: location.pathname }) });
      if (!r.ok) throw 0;
      L('lukids.reviewedAt', Date.now());
      box.querySelector('.rp-card').innerHTML = '<h3>고마워요!</h3><p>남겨 준 후기는 루키즈를 더 재미있게 만드는 데 쓸게요.</p>' +
        '<div class="rp-acts"><button type="button" class="rp-later">닫기</button></div>';
      box.querySelector('.rp-later').onclick = () => box.classList.remove('on');
    } catch { msg.textContent = '보내지 못했어요. 잠시 뒤 다시 눌러 주세요.'; }
  }

  let timer = null;
  function schedule(sec){
    clearTimeout(timer);
    timer = setTimeout(function tick(){
      if (L('lukids.reviewedAt') || asked() >= MAX_ASK) return;
      if (busy()) { timer = setTimeout(tick, 15000); return; }   // 끝날 때까지 미룬다
      open();
    }, sec * 1000);
  }
  // 페이지를 옮겨 다녀도 처음 들어온 때부터 센다
  const left = Math.max(5, FIRST_SEC - (Date.now() - +S('lukids.since')) / 1000);
  if (asked() < MAX_ASK) schedule(asked() ? Math.max(left, 30) : left);
  window.LukidsReview = { open };   // 다른 화면에서 직접 열 때
})();

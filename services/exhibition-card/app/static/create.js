/* 내 아이돌 만들기 — 카드 화면(scan.html)과 제작 페이지(make.html)가 같이 쓴다.
   화면 마크업은 templates/_create_screens.html.
   두 페이지가 먼저 정의해야 하는 것: go(id) · pick(btn) · CREATE_HOME(만들기를 닫을 때) */

// 이 기기에서 만든 카드. 인쇄 페이지와 전시의 "내가 만든" 필터가 읽는다.
function rememberMine(id){
  try {
    const a = JSON.parse(localStorage.getItem('lukids.mine') || '[]').filter(x => x !== id);
    a.unshift(id);
    localStorage.setItem('lukids.mine', JSON.stringify(a.slice(0, 50)));
  } catch {}
}

/* ───────── 카드 만들기 ─────────
   실물: normal.py PRESETS / epic.py SPECIES 의 키를 그대로 서버에 넘긴다.
   버추얼: imagegen.py MOODS / HAIR 의 키. 조립은 서버가 한다. */

const PRESETS = [
  { k:'cat',  label:'고양이상', mood:'시크'  },
  { k:'dog',  label:'강아지상', mood:'청량'  },
  { k:'wolf', label:'늑대상',   mood:'다크'  },
  { k:'fox',  label:'여우상',   mood:'무드'  },
  { k:'deer', label:'사슴상',   mood:'몽환'  },
];
const SPECIES = [
  { k:'ninetail', label:'구미호', note:'여우 귀 · 금색 눈'   },
  { k:'cat',      label:'묘인',   note:'고양이 귀 · 수염점'  },
  { k:'devil',    label:'악마',   note:'램혼 · 진홍 눈'      },
  { k:'angel',    label:'천사',   note:'광륜 · 백금 눈'      },
  { k:'fairy',    label:'요정',   note:'뾰족귀 · 연두 눈'    },
  { k:'mermaid',  label:'인어',   note:'지느러미 귀 · 비늘'  },
];
const MOODS = [
  { k:'fresh',  label:'청량', note:'맑은 하늘 · 활짝 웃음' },
  { k:'dreamy', label:'몽환', note:'반짝이 · 옅은 미소'    },
  { k:'dark',   label:'다크', note:'네온 · 날카로운 눈빛'  },
  { k:'cute',   label:'큐트', note:'윙크 · 발랄한 포즈'    },
  { k:'chic',   label:'시크', note:'차분 · 미니멀'         },
];
const HAIRS = [
  { k:'pink',   label:'핑크',   c:'#F4A7C0' }, { k:'lilac', label:'라일락', c:'#B9A6F2' },
  { k:'sky',    label:'하늘',   c:'#9CC9F5' }, { k:'blonde', label:'금발',  c:'#E8C77A' },
  { k:'black',  label:'흑발',   c:'#2E2A33' }, { k:'silver', label:'은발',  c:'#E4E4EC' },
];
// docs/features 에 적힌 매핑. Zephyr 는 하늘 카드가 쓰는 들뜬 톤.
const VOICES = {
  m: [ { k:'Puck', label:'밝고 활기찬' }, { k:'Charon', label:'차분하고 낮은' },
       { k:'Fenrir', label:'유쾌한' },    { k:'Orus', label:'감성적인' } ],
  f: [ { k:'Leda', label:'맑고 또렷한' }, { k:'Zephyr', label:'들뜨고 밝은' } ],
};

const CREATE = { kind:null, gender:null, grade:'normal', look:null, hair:null, prompt:'',
                 voice:null, name:'', persona:'', image:null, tries:0, cardId:null,
                 depth:null, startedAt:0 };

// A조건은 이름도 안 짓는다. 고르는 노동만 남기려면 이름이 자동이어야 한다.
const AUTO_NAMES = ['하루','시온','유나','재이','린','도하','서우','노아'];

function logStep(step){
  fetch('/api/step', { method:'POST', headers:{'Content-Type':'application/json'},
    body: JSON.stringify({ step, depth: CREATE.depth,
                           ms: CREATE.startedAt ? Date.now() - CREATE.startedAt : null }) })
    .catch(()=>{});
}

// 만들기에 들어올 때 조건을 받는다. 참가자가 고르면 자기선택 편향이 생긴다.
async function startCreate(){
  CREATE.startedAt = Date.now();
  if (!CREATE.depth) {
    try {
      const r = await fetch('/api/condition').then(r => r.json());
      CREATE.depth = r.depth;
    } catch { CREATE.depth = 'C'; }   // 서버가 못 주면 가장 깊은 조건으로 둔다
  }
  logStep('open');
  go('s-create');
}

function hint(id, msg){
  const el = document.getElementById(id);
  if (!msg) { el.hidden = true; return; }
  el.textContent = msg; el.hidden = false;
  el.scrollIntoView({ behavior:'smooth', block:'nearest' });
}

function pickKind(btn){
  document.querySelectorAll('#kinds .grade').forEach(b => b.classList.remove('sel'));
  btn.classList.add('sel');
  CREATE.kind = btn.dataset.kind;
  CREATE.look = null;               // 실물과 버추얼은 고르는 축이 다르다
  hint('create-hint', '');
}
function pickGender(btn){
  document.querySelectorAll('#gender button').forEach(b => b.classList.remove('sel'));
  btn.classList.add('sel');
  CREATE.gender = btn.dataset.gender;
  CREATE.voice = null;              // 목소리 풀이 성별마다 다르다
  hint('create-hint', '');
}
function pickGrade(btn){
  CREATE.grade = btn.dataset.grade;
  CREATE.look = null;               // 등급이 바뀌면 고른 얼굴상·종족은 뜻을 잃는다
  renderLook();
}

function lookPool(){
  if (CREATE.kind === 'virtual') return MOODS;
  return CREATE.grade === 'epic' ? SPECIES : PRESETS;
}

function renderLook(){
  const virtual = CREATE.kind === 'virtual', epic = CREATE.grade === 'epic';
  document.getElementById('look-real').hidden = virtual;
  document.getElementById('hair-field').hidden = !virtual;
  document.querySelectorAll('#grade button')
    .forEach(b => b.classList.toggle('sel', b.dataset.grade === CREATE.grade));
  document.getElementById('look-q').textContent =
    virtual ? '어떤 분위기인가요?' : epic ? '어떤 종족인가요?' : '어떤 얼굴인가요?';
  document.getElementById('look-sub').textContent =
    virtual ? '표정 · 조명 · 배경이 함께 정해집니다'
    : epic ? '종족마다 귀 · 눈 · 표식과 배경이 함께 정해집니다'
    : '동물상이 얼굴 생김새와 표정을 정합니다';

  const box = document.getElementById('look-opts');
  box.innerHTML = '';
  lookPool().forEach(o => {
    const b = document.createElement('button');
    b.className = 'opt two' + (CREATE.look === o.k ? ' sel' : '');
    b.innerHTML = `<b>${o.label}</b><small>${o.note || o.mood}</small>`;
    b.onclick = () => { pick(b); CREATE.look = o.k; hint('look-hint', ''); };
    box.appendChild(b);
  });

  const hb = document.getElementById('hair-opts');
  hb.innerHTML = '';
  HAIRS.forEach(h => {
    const b = document.createElement('button');
    b.className = 'opt hair' + (CREATE.hair === h.k ? ' sel' : '');
    b.innerHTML = `<i style="background:${h.c}"></i>${h.label}`;
    b.onclick = () => { pick(b); CREATE.hair = h.k; hint('look-hint', ''); };
    hb.appendChild(b);
  });
}

function toLook(){
  if (!CREATE.kind || !CREATE.gender) {
    return hint('create-hint', '아이돌 종류와 성별을 모두 골라주세요.');
  }
  // A조건은 고르기만 한다 — 직접 쓰는 칸을 열면 조건이 섞인다
  document.getElementById('prompt-field').hidden = CREATE.depth === 'A';
  renderLook();
  logStep('look');
  go('s-create-look');
}

function syncPrompt(){
  const el = document.getElementById('c-prompt');
  CREATE.prompt = el.value.trim();
  document.getElementById('prompt-count').textContent = el.value.length;
}

function toName(){
  const virtual = CREATE.kind === 'virtual';
  if (!CREATE.look) {
    return hint('look-hint', virtual ? '분위기를 골라주세요.'
                : CREATE.grade === 'epic' ? '종족을 골라주세요.' : '얼굴상을 골라주세요.');
  }
  if (virtual && !CREATE.hair) return hint('look-hint', '머리색을 골라주세요.');
  if (CREATE.depth === 'A') CREATE.prompt = '';

  const box = document.getElementById('voice-opts');
  box.innerHTML = '';
  VOICES[CREATE.gender].forEach(v => {
    const b = document.createElement('button');
    b.className = 'opt two' + (CREATE.voice === v.k ? ' sel' : '');
    b.innerHTML = `<b>${v.label}</b><small>${v.k}</small>`;
    b.onclick = () => { pick(b); CREATE.voice = v.k; hint('name-hint', ''); syncReview(); };
    box.appendChild(b);
  });
  // A조건은 이름도 성격도 받지 않는다 — 고르는 노동만 남긴다
  if (CREATE.depth === 'A') {
    CREATE.name = AUTO_NAMES[Math.floor(Math.random() * AUTO_NAMES.length)];
    CREATE.voice = VOICES[CREATE.gender][0].k;
    logStep('skip-name');
    return toResult();
  }
  document.getElementById('persona-field').hidden = CREATE.depth !== 'C';
  syncReview();
  logStep('name');
  go('s-create-name');
}

function lookLabel(){
  return (lookPool().find(o => o.k === CREATE.look) || {}).label || '—';
}
function hairLabel(){
  return (HAIRS.find(h => h.k === CREATE.hair) || {}).label || '—';
}

function syncReview(){
  if (CREATE.depth !== 'A') CREATE.name = document.getElementById('c-name').value.trim();
  const pv = document.getElementById('c-persona');
  CREATE.persona = CREATE.depth === 'C' ? pv.value.trim() : '';
  document.getElementById('persona-count').textContent = pv.value.length;
  const virtual = CREATE.kind === 'virtual', epic = CREATE.grade === 'epic';
  const rows = [
    ['이름',   CREATE.name || '—'],
    ['종류',   virtual ? '버추얼' : epic ? '실물 · 에픽' : '실물 · 일상'],
    ['성별',   CREATE.gender === 'f' ? '여자' : '남자'],
    [virtual ? '분위기' : epic ? '종족' : '얼굴상', lookLabel()],
    ...(virtual ? [['머리색', hairLabel()]] : []),
    ...(CREATE.prompt ? [['직접 쓴 모습', CREATE.prompt]] : []),
    ['목소리', CREATE.voice || '—'],
    ...(CREATE.depth === 'C' ? [['성격', CREATE.persona || '—']] : []),
  ];
  const esc = s => String(s).replace(/[&<>"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
  document.getElementById('review').innerHTML =
    rows.map(([k, v]) => `<div><span>${k}</span><b>${esc(v)}</b></div>`).join('');
}

function toResult(){
  syncReview();
  if (!CREATE.name)  return hint('name-hint', '이름을 입력해주세요.');
  if (!CREATE.voice) return hint('name-hint', '목소리를 골라주세요.');
  CREATE.image = null; CREATE.tries = 0; CREATE.cardId = null;
  rang = false; clearTimeout(ringTimer);
  document.getElementById('result-pick').hidden = false;
  document.getElementById('result-done').hidden = true;
  go('s-create-result');
  generate();
}

function backFromResult(){
  if (CREATE.cardId) return CREATE_HOME();
  go(CREATE.depth === 'A' ? 's-create-look' : 's-create-name');
}

function setBusy(busy){
  document.getElementById('gen-wait').hidden = !busy;
  document.getElementById('gen-img').hidden = busy || !CREATE.image;
  document.getElementById('issue-btn').disabled = busy || !CREATE.image;
  document.getElementById('regen-btn').disabled = busy;
}

async function generate(){
  CREATE.tries += 1;
  hint('result-hint', '');
  document.getElementById('result-q').textContent = CREATE.name + '을(를) 그리는 중';
  document.getElementById('result-sub').textContent = '20초쯤 걸려요';
  setBusy(true);
  logStep('generate');
  try {
    const r = await fetch('/api/generate', {
      method:'POST', headers:{'Content-Type':'application/json'},
      body: JSON.stringify({ kind:CREATE.kind, gender:CREATE.gender, grade:CREATE.grade,
                             look:CREATE.look, mood:CREATE.look, hair:CREATE.hair,
                             prompt:CREATE.prompt, depth:CREATE.depth, try:CREATE.tries }),
    });
    const j = await r.json();
    if (!r.ok) throw new Error(j.detail || '생성 실패');
    CREATE.image = j.image;
    document.getElementById('gen-img').src = j.image;
    document.getElementById('result-q').textContent = '이 모습 어때요?';
    document.getElementById('result-sub').textContent = '마음에 안 들면 다시 만들 수 있어요';
  } catch (e) {
    document.getElementById('result-q').textContent = '사진을 만들지 못했어요';
    document.getElementById('result-sub').textContent = '';
    hint('result-hint', e.message);
  }
  setBusy(false);
}

// 통화 페르소나. tools/virtual_card.py 프리셋과 같은 틀로 맞춘다.
function buildPersona(){
  const virtual = CREATE.kind === 'virtual';
  const who = virtual ? '버추얼 아이돌' : '아이돌 연습생';
  const look = virtual ? `${lookLabel()} 분위기에 ${hairLabel()} 머리`
             : CREATE.grade === 'epic' ? `${lookLabel()} 컨셉` : `${lookLabel()} 얼굴`;
  return [
    `너는 ${who} '${CREATE.name}'이야. ${CREATE.gender === 'f' ? '여자' : '남자'}야.`,
    `외모: ${look}.`,
    CREATE.prompt ? `생김새: ${CREATE.prompt}` : '',
    CREATE.persona ? `성격: ${CREATE.persona}` : '밝고 다정하고, 상대 이야기에 리액션이 커.',
    '너를 만든 사람과 지금 처음 영상통화를 하는 중이야. 한 번에 한두 문장으로 짧게 말하고, '
    + '질문을 하나씩 던져서 대화를 이어가. 너 자신이 AI라는 말은 먼저 꺼내지 마.',
  ].filter(Boolean).join('\n');
}

function buildTags(){
  if (CREATE.kind === 'virtual') return ['버추얼', lookLabel(), hairLabel() + ' 머리'];
  return [CREATE.grade === 'epic' ? '에픽' : '일상', lookLabel()];
}

// 카드 하단 게이지. 8칸 중 3~8칸.
function rollStats(){
  const s = {};
  ['보컬', '댄스', '비주얼', '매력'].forEach(k => { s[k] = 3 + Math.floor(Math.random() * 6); });
  return s;
}

async function issueCard(){
  if (!CREATE.image) return;
  window.AidolRing && AidolRing.unlock();
  document.getElementById('issue-btn').disabled = true;
  document.getElementById('regen-btn').disabled = true;
  hint('result-hint', '');
  try {
    const blob = await fetch(CREATE.image).then(r => r.blob());
    const fd = new FormData();
    fd.append('name', CREATE.name);
    fd.append('persona', buildPersona());
    fd.append('voice', CREATE.voice);
    fd.append('tags', JSON.stringify(buildTags()));
    fd.append('stats', JSON.stringify(rollStats()));
    fd.append('source', 'user');
    fd.append('register_face', 'false');
    fd.append('image', blob, 'card.jpg');
    const r = await fetch('/api/cards', { method:'POST', body:fd });
    const j = await r.json();
    if (!r.ok) throw new Error(j.detail || '발급 실패');
    CREATE.cardId = j.cardId;
    rememberMine(j.cardId);
    logStep('issued');
    document.getElementById('result-q').textContent = CREATE.name + ' 카드가 나왔어요';
    document.getElementById('result-sub').textContent = '카드 번호 ' + j.cardId;
    document.getElementById('result-pick').hidden = true;
    document.getElementById('result-done').hidden = false;
    // (2026-10-07) 발급 뒤 아이돌이 먼저 거는 전화는 껐다 — 시연에서 인쇄 흐름을 끊는다.
    // 다시 켜려면 여기서 scheduleRing(j.cardId, RING_DELAY) 를 부른다.
  } catch (e) {
    hint('result-hint', '카드를 만들지 못했어요. ' + e.message);
    document.getElementById('issue-btn').disabled = false;
    document.getElementById('regen-btn').disabled = false;
  }
}

// 인쇄용 카드 페이지를 새 창으로 열면 사진이 다 뜬 뒤 인쇄 창이 뜬다.
// 발급 직후 자동으로 열지 않는 건, await 뒤의 window.open 을 사파리가 팝업으로 막기 때문.
function printCard(){
  window.open(`/label/${CREATE.cardId}?print=1`, '_blank');
}


/* ───────── 아이돌이 먼저 거는 전화 ─────────
   기획의 핵심 훅 — 고르는 게 아니라 선택받는 경험. 발급 몇 초 뒤 수신 화면이 뜬다.
   받으면 그 카드 화면으로 넘어가 바로 통화한다(?answer=1). */
const RING_DELAY = 6000;      // 발급 뒤 인쇄 버튼을 누를 여유
const RING_AFTER_PRINT = 2500; // 라벨 탭에서 돌아온 뒤
let ringTimer = null, rang = false;

function scheduleRing(cardId, ms){
  clearTimeout(ringTimer);
  ringTimer = setTimeout(() => ringFromIdol(cardId), ms);
}

function holdRingUntilBack(cardId){
  if (rang) return;
  clearTimeout(ringTimer);
  const back = () => {
    if (document.visibilityState !== 'visible') return;
    document.removeEventListener('visibilitychange', back);
    window.removeEventListener('focus', back);
    scheduleRing(cardId, RING_AFTER_PRINT);
  };
  // 새 탭이 열리면 이 탭이 가려졌다가 돌아올 때 visible 이 된다
  setTimeout(() => {
    document.addEventListener('visibilitychange', back);
    window.addEventListener('focus', back);
  }, 800);
  // 같은 탭에서 인쇄 창만 떴다 닫힌 경우를 대비한 안전장치
  scheduleRing(cardId, 40000);
}

function ringFromIdol(cardId){
  if (rang || CREATE.cardId !== cardId || !window.AidolRing) return;
  rang = true; clearTimeout(ringTimer);
  logStep('ring');
  AidolRing.show({
    name: CREATE.name, image: CREATE.image, label: '음성통화',
    onAccept(){ logStep('ring-answer'); location.href = `/c/${cardId}?answer=1`; },
    onDecline(why){
      logStep('ring-' + why);
      document.getElementById('result-sub').textContent =
        `${CREATE.name}에게서 부재중 전화 1통 · 아래 통화하기로 다시 걸 수 있어요`;
    },
  });
}

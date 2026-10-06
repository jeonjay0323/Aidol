/* 블루투스 라벨 프린터로 바로 인쇄 (Web Bluetooth).
 *
 * 아이패드 사파리는 Web Bluetooth 가 없어서 Bluefy 같은 브라우저 앱에서 연다.
 * Aiyin 계열 라벨 프린터는 대개 TSPL 을 쓰고, BLE 는 ISSC 투명 UART 서비스(49535343-…)로 받는다.
 * 기종마다 달라서 설정(언어 · 해상도 · 방향 · 간격)을 바꿔 가며 맞출 수 있게 했다 — /printer.
 *
 *   await LukidsBT.connect()              프린터 고르기(브라우저 선택 창)
 *   await LukidsBT.printCard(cardId)      /label/{id}.png?mono=1&dpi=… 을 받아 비트맵으로 보낸다
 *   LukidsBT.settings / save(patch)       localStorage 'lukids.printer'
 */
window.LukidsBT = (() => {
  // 흔한 BLE 프린터 서비스. acceptAllDevices 로 고를 때 여기 없는 서비스는 열 수 없다
  const SERVICES = [
    '49535343-fe7d-4ae5-8fa9-9fafd205e455',   // ISSC 투명 UART — Aiyin · Feasycom
    '0000ff00-0000-1000-8000-00805f9b34fb',
    '000018f0-0000-1000-8000-00805f9b34fb',
    '0000ae30-0000-1000-8000-00805f9b34fb',
    '0000fee7-0000-1000-8000-00805f9b34fb',
    'e7810a71-73ae-499d-8c15-faa9aef0c3f2',
    '0000ffe0-0000-1000-8000-00805f9b34fb',
    '0000ff80-0000-1000-8000-00805f9b34fb',
  ];
  const DEFAULTS = { char: '', bmode: 4, lang: 'tspl', dpi: 203, w: 60, h: 40, gap: 2, direction: 1, density: 8,
                     invert: false, chunk: 180, delay: 20 };
  const KEY = 'lukids.printer';
  let settings = { ...DEFAULTS };
  try { Object.assign(settings, JSON.parse(localStorage.getItem(KEY) || '{}')); } catch {}

  let device = null, ch = null, writable = [];
  // 데이터를 받는 통로로 흔한 것들(앞이 우선). 6DAA 같은 ISSC 의 다른 쓰기 특성은 인쇄를 안 받는다
  // FF02 = 이 계열(Aimo · Quyin OEM, labelife 문서)의 BLE 인쇄 통로. 실물 DPP-Ai01W 에도 있다
  const PREFER = ['0000ff02', '49535343-8841', '00002af1', '0000fff2', '0000ff82', '0000ff12', '0000ff11', '0000fec7'];
  const logs = [];
  // 아이패드 화면의 로그를 서버에도 남긴다 — 실물 프린터 문제를 원격으로 보기 위해 (Cloud Run 로그 'btlog')
  const sid = Math.random().toString(36).slice(2, 8);
  function log(m) {
    logs.push(m); console.log('[bt]', m); LukidsBT.onlog && LukidsBT.onlog(m);
    try { navigator.sendBeacon('/api/btlog', JSON.stringify({ sid, m: String(m).slice(0, 300) })); } catch {}
  }

  const supported = () => !!(navigator.bluetooth && navigator.bluetooth.requestDevice);

  async function connect() {
    if (!supported()) throw new Error('이 브라우저는 블루투스를 지원하지 않아요. 아이패드는 Bluefy 앱에서 여세요.');
    if (ch && device && device.gatt.connected) return device.name;
    device = await navigator.bluetooth.requestDevice({ acceptAllDevices: true, optionalServices: SERVICES });
    log(`선택: ${device.name || '(이름 없음)'}`);
    device.addEventListener('gattserverdisconnected', () => { ch = null; log('연결 끊김'); });
    const server = await device.gatt.connect();
    const services = await server.getPrimaryServices();
    writable = [];
    for (const sv of services) {
      let chars = [];
      try { chars = await sv.getCharacteristics(); } catch { continue; }
      for (const c of chars) {
        const p = c.properties;
        log(`특성 ${c.uuid} ${p.write ? 'W' : ''}${p.writeWithoutResponse ? 'w' : ''}${p.notify ? 'N' : ''}`);
        if (p.writeWithoutResponse || p.write) writable.push(c);
      }
    }
    if (!writable.length) throw new Error('쓸 수 있는 특성을 못 찾았어요. 로그를 확인해 주세요.');
    // 설정에 고른 통로가 있으면 그것, 없으면 알려진 데이터 통로 순서대로
    const want = (settings.char || '').toLowerCase();
    const rank = (c) => { const u = full(c.uuid); const i = PREFER.findIndex(k => u.startsWith(k));
                          return i < 0 ? 99 : i; };
    ch = (want && writable.find(c => full(c.uuid) === full(want)))
         || writable.slice().sort((a, b) => rank(a) - rank(b))[0];
    LukidsBT.channels = writable.map(c => c.uuid);
    log(`서비스 ${services.length}개 · 쓸 수 있는 통로 ${writable.length}개 · ${navigator.userAgent.slice(-40)}`);
    log(`보낼 곳: ${ch.uuid}`);
    return device.name;
  }

  const sleep = (ms) => new Promise(r => setTimeout(r, ms));
  // Bluefy 는 16비트 UUID 를 'FF02' 처럼 짧게 준다. 비교할 때는 긴 형식으로 맞춘다
  const full = (u) => { u = String(u).toLowerCase(); return u.length === 4 ? `0000${u}-0000-1000-8000-00805f9b34fb` : u; };

  async function send(bytes) {
    const n = settings.chunk;
    for (let i = 0; i < bytes.length; i += n) {
      const part = bytes.slice(i, i + n);
      const withResp = ch.properties.write && (settings.resp ?? full(ch.uuid).startsWith('0000ff02'));
      if (withResp || !ch.properties.writeWithoutResponse) {
        await (ch.writeValueWithResponse ? ch.writeValueWithResponse(part) : ch.writeValue(part));
      } else await ch.writeValueWithoutResponse(part);
      if (settings.delay) await sleep(settings.delay);
    }
  }

  const ascii = (s) => new TextEncoder().encode(s);
  function concat(parts) {
    const len = parts.reduce((a, p) => a + p.length, 0);
    const out = new Uint8Array(len); let o = 0;
    for (const p of parts) { out.set(p, o); o += p.length; }
    return out;
  }

  /* LZO1X-1 — 압축하지 않고 리터럴로만 싸서 끝 표시를 붙인다. 펌웨어의 일반 LZO 해제기가 그대로 푼다.
     thermal-label/labelife packages/core/src/lzo.ts (MIT, Mannes Brak) 를 옮김 */
  function lzo(input) {
    const N = input.length, EOS = [0x11, 0x00, 0x00];
    if (N === 0) return new Uint8Array(EOS);
    if (N <= 238) { const o = new Uint8Array(N + 4); o[0] = N + 17; o.set(input, 1); o.set(EOS, N + 1); return o; }
    const t = N - 18, zeros = Math.floor((t - 1) / 255), nz = t - zeros * 255;
    const o = new Uint8Array(2 + zeros + N + 3); let i = 0;
    o[i++] = 0; for (let z = 0; z < zeros; z++) o[i++] = 0; o[i++] = nz;
    o.set(input, i); o.set(EOS, i + N); return o;
  }
  const u32 = (v) => new Uint8Array([v & 255, (v >>> 8) & 255, (v >>> 16) & 255, (v >>> 24) & 255]);
  function lzoChunked4(raw, size = 4096) {     // BITMAP 모드 4 — 4KiB 마다 [u32 길이][LZO], 끝에 0
    const parts = [];
    for (let o = 0; o < raw.length; o += size) { const c = lzo(raw.subarray(o, o + size)); parts.push(u32(c.length), c); }
    parts.push(u32(0)); return concat(parts);
  }

  // 이미지 → 1비트 줄 단위 바이트 (1 = 검정)
  async function bitmap(url) {
    const img = await new Promise((res, rej) => {
      const i = new Image(); i.crossOrigin = 'anonymous';
      i.onload = () => res(i); i.onerror = () => rej(new Error('라벨 이미지를 못 받았어요'));
      i.src = url;
    });
    const w = img.naturalWidth, h = img.naturalHeight;
    const cv = Object.assign(document.createElement('canvas'), { width: w, height: h });
    const g = cv.getContext('2d'); g.fillStyle = '#fff'; g.fillRect(0, 0, w, h); g.drawImage(img, 0, 0);
    const px = g.getImageData(0, 0, w, h).data;
    const wb = Math.ceil(w / 8), bits = new Uint8Array(wb * h);
    for (let y = 0; y < h; y++) for (let x = 0; x < w; x++) {
      const i = (y * w + x) * 4;
      if (px[i] < 128) bits[y * wb + (x >> 3)] |= 0x80 >> (x & 7);
    }
    return { w, h, wb, bits };
  }

  function tspl({ wb, h, bits }) {
    const s = settings, mode = Number(s.bmode);
    // 이 계열 펌웨어는 1 = 검정(labelife). 표준 TSPL(0 = 검정)이면 '흑백 뒤집기'를 켠다
    const raw = s.invert ? bits.map(b => b ^ 0xff) : bits;
    let body;
    if (mode === 4) body = [ascii(`BITMAP 0,0,${wb},${h},4,`), lzoChunked4(raw)];
    else if (mode === 3) { const c = lzo(raw); body = [ascii(`BITMAP 0,0,${wb},${h},3,${c.length},`), c]; }
    else body = [ascii(`BITMAP 0,0,${wb},${h},0,`), raw];
    return concat([
      ascii(`\r\nDENSITY ${s.density}\r\nREFERENCE 0,0\r\nOFFSET 0 mm\r\nSIZE ${s.w} mm,${s.h} mm\r\n` +
            `GAP ${s.gap} mm,0 mm\r\nDIRECTION ${s.direction},0\r\nCLS\r\n`),
      ...body, ascii('\r\nPRINT 1,1\r\n'),
    ]);
  }

  function escpos({ wb, h, bits }) {
    const data = settings.invert ? bits.map(b => b ^ 0xff) : bits;
    // ESC @ 초기화 → GS v 0 래스터 → 줄 바꿈(종이 밀기). 라벨 끝 맞춤은 GS FF(지원 시)
    return concat([
      new Uint8Array([0x1b, 0x40]),
      new Uint8Array([0x1d, 0x76, 0x30, 0x00, wb & 0xff, wb >> 8, h & 0xff, h >> 8]), data,
      new Uint8Array([0x1d, 0x0c]),
    ]);
  }

  async function printCard(cardId) {
    try { return await _print(cardId); }
    catch (e) { log('오류: ' + (e && e.name ? e.name + ' ' + e.message : String(e))); throw e; }
  }

  async function _print(cardId) {
    log(`설정 ${JSON.stringify(settings)}`);
    if (!ch || !device || !device.gatt.connected) await connect();
    const s = settings;
    const url = `/label/${encodeURIComponent(cardId)}.png?mono=1&dpi=${s.dpi}`;
    const bm = await bitmap(url);
    log(`이미지 ${bm.w}×${bm.h} (${s.dpi}dpi) · ${s.lang.toUpperCase()} · BITMAP ${s.bmode} · 통로 ${full(ch.uuid).slice(4, 8)}`);
    const bytes = s.lang === 'escpos' ? escpos(bm) : tspl(bm);
    log(`보내는 중 ${bytes.length} 바이트`);
    await send(bytes);
    log('보냄 — 다 보냈어요');
  }

  // 통로 찾기: 쓸 수 있는 통로마다 "번호 + 언어" 를 찍는 작은 시험 라벨을 보낸다.
  // 나온 라벨의 번호가 맞는 통로다. TSPL 로 먼저 다 돌고, 아무것도 안 나오면 ESC/POS 로.
  async function probe(lang) {
    if (!ch || !device || !device.gatt.connected) await connect();
    const s = settings;
    for (let i = 0; i < writable.length; i++) {
      const c = writable[i], n = i + 1;
      const job = lang === 'escpos'
        ? concat([new Uint8Array([0x1b, 0x40, 0x1d, 0x21, 0x11]), ascii(`\n  ${n} ESC\n\n\n\n`), new Uint8Array([0x0c])])
        : ascii(`SIZE ${s.w} mm,${s.h} mm\r\nGAP ${s.gap} mm,0 mm\r\nCLS\r\n` +
                `TEXT 60,100,"5",0,1,1,"${n} TSPL"\r\nPRINT 1,1\r\n`);
      log(`시험 ${n}/${writable.length} · ${lang} → ${c.uuid}`);
      try {
        ch = c; await send(job);
      } catch (e) { log(`  실패: ${e.name} ${e.message}`); }
      await sleep(2500);
    }
    log('통로 찾기 끝 — 나온 라벨의 번호를 /printer 의 "통로"에서 고르세요');
  }

  function save(patch) {
    Object.assign(settings, patch);
    try { localStorage.setItem(KEY, JSON.stringify(settings)); } catch {}
  }
  function reset() { settings = { ...DEFAULTS }; LukidsBT.settings = settings; save({}); }

  const LukidsBT = { supported, connect, printCard, probe, save, reset, settings, logs, onlog: null, channels: [],
                     get connected() { return !!(ch && device && device.gatt.connected); },
                     get name() { return device && device.name; } };
  return LukidsBT;
})();

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
  const DEFAULTS = { lang: 'tspl', dpi: 203, w: 60, h: 40, gap: 2, direction: 1, density: 8,
                     invert: false, chunk: 180, delay: 20 };
  const KEY = 'lukids.printer';
  let settings = { ...DEFAULTS };
  try { Object.assign(settings, JSON.parse(localStorage.getItem(KEY) || '{}')); } catch {}

  let device = null, ch = null;
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
    ch = null;
    for (const s of services) {
      let chars = [];
      try { chars = await s.getCharacteristics(); } catch { continue; }
      for (const c of chars) {
        const p = c.properties;
        log(`서비스 ${s.uuid.slice(0, 8)} · 특성 ${c.uuid.slice(0, 8)} ${p.write ? 'W' : ''}${p.writeWithoutResponse ? 'w' : ''}${p.notify ? 'N' : ''}`);
        if (!ch && (p.writeWithoutResponse || p.write)) ch = c;
      }
    }
    if (!ch) throw new Error('쓸 수 있는 특성을 못 찾았어요. 로그를 확인해 주세요.');
    log(`서비스 ${services.length}개 · ${navigator.userAgent.slice(-40)}`);
    log(`보낼 곳: ${ch.uuid}`);
    return device.name;
  }

  const sleep = (ms) => new Promise(r => setTimeout(r, ms));

  async function send(bytes) {
    const n = settings.chunk;
    for (let i = 0; i < bytes.length; i += n) {
      const part = bytes.slice(i, i + n);
      if (ch.properties.writeWithoutResponse) await ch.writeValueWithoutResponse(part);
      else await ch.writeValue(part);
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
    const s = settings;
    // TSPL 비트맵은 0 이 검정이다 — 뒤집어 보낸다 (invert 로 되돌릴 수 있다)
    const data = s.invert ? bits : bits.map(b => b ^ 0xff);
    return concat([
      ascii(`SIZE ${s.w} mm,${s.h} mm\r\nGAP ${s.gap} mm,0 mm\r\nDIRECTION ${s.direction},0\r\n` +
            `DENSITY ${s.density}\r\nCLS\r\nBITMAP 0,0,${wb},${h},0,`),
      data, ascii('\r\nPRINT 1,1\r\n'),
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
    catch (e) { log('오류: ' + (e && (e.name + ' ' + e.message))); throw e; }
  }

  async function _print(cardId) {
    log(`설정 ${JSON.stringify(settings)}`);
    if (!ch || !device || !device.gatt.connected) await connect();
    const s = settings;
    const url = `/label/${encodeURIComponent(cardId)}.png?mono=1&dpi=${s.dpi}`;
    const bm = await bitmap(url);
    log(`이미지 ${bm.w}×${bm.h} (${s.dpi}dpi) · ${s.lang.toUpperCase()}`);
    const bytes = s.lang === 'escpos' ? escpos(bm) : tspl(bm);
    log(`보내는 중 ${bytes.length} 바이트`);
    await send(bytes);
    log('보냄 — 다 보냈어요');
  }

  function save(patch) {
    Object.assign(settings, patch);
    try { localStorage.setItem(KEY, JSON.stringify(settings)); } catch {}
  }
  function reset() { settings = { ...DEFAULTS }; LukidsBT.settings = settings; save({}); }

  const LukidsBT = { supported, connect, printCard, save, reset, settings, logs, onlog: null,
                     get connected() { return !!(ch && device && device.gatt.connected); },
                     get name() { return device && device.name; } };
  return LukidsBT;
})();

// 기기 현황 — 이 기기가 지금 어떤 화면인지 서버에 알린다. /devices 에서 본다.
// 15초마다, 그리고 화면(.screen.on 등)이 바뀌면 바로 보낸다.
(() => {
  if (location.pathname.startsWith('/devices')) return;
  const KEY = 'lukids-device';
  let dev = localStorage.getItem(KEY);
  if (!dev) {
    dev = (crypto.randomUUID ? crypto.randomUUID() : String(Math.random()).slice(2) + Date.now()).replace(/[^A-Za-z0-9]/g, '').slice(0, 16);
    localStorage.setItem(KEY, dev);
  }

  const ua = navigator.userAgent;
  const kind = /iPad/.test(ua) || (/Macintosh/.test(ua) && navigator.maxTouchPoints > 1) ? 'iPad'
    : /iPhone/.test(ua) ? 'iPhone' : /Android/.test(ua) ? 'Android'
    : /Macintosh/.test(ua) ? 'Mac' : /Windows/.test(ua) ? 'Windows' : 'etc';

  const SEL = '.screen.on, .call.on, .call-again.on, .survey.on';
  const screen = () => [...document.querySelectorAll(SEL)].map(e => e.id).filter(Boolean).join(',');

  function payload(hidden) {
    return JSON.stringify({
      device: dev, path: location.pathname + location.search, title: document.title,
      screen: screen(), kind, size: innerWidth + '×' + innerHeight,
      hidden: hidden ?? document.hidden,
    });
  }
  function beat() {
    fetch('/api/presence', { method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: payload(), keepalive: true }).catch(() => {});
  }

  let last = '', t = null;
  const watch = new MutationObserver(() => {
    clearTimeout(t);
    t = setTimeout(() => { const s = screen(); if (s !== last) { last = s; beat(); } }, 400);
  });
  function start() {
    last = screen();
    watch.observe(document.body, { subtree: true, attributes: true, attributeFilter: ['class'] });
    beat();
    setInterval(beat, 15000);
  }
  document.addEventListener('visibilitychange', beat);
  addEventListener('pagehide', () => {
    navigator.sendBeacon && navigator.sendBeacon('/api/presence', new Blob([payload(true)], { type: 'application/json' }));
  });
  if (document.body) start(); else addEventListener('DOMContentLoaded', start);
})();

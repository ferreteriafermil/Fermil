// Graba el recorrido del cliente en la página real (pantalla de teléfono 1080x1920).
const { chromium } = require('playwright');
const fs = require('fs');
const CODE = process.env.CODIGO;
const OUT = 'video/out';
fs.mkdirSync(OUT + '/frames', { recursive: true });
const marks = [];
const sleep = ms => new Promise(r => setTimeout(r, ms));
(async () => {
  const browser = await chromium.launch();
  const ctx = await browser.newContext({ viewport: { width: 360, height: 640 }, deviceScaleFactor: 3, isMobile: true, hasTouch: true, locale: 'es-VE', timezoneId: 'America/Caracas', acceptDownloads: true,
    userAgent: 'Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Mobile Safari/537.36' });
  await ctx.route(/wa\.me|api\.whatsapp\.com/, r => r.abort());
  const page = await ctx.newPage();
  ctx.on('page', p => { if (p !== page) p.close().catch(() => {}); });
  page.on('console', m => m.type() === 'error' && console.log('consola:', m.text().slice(0, 160)));
  const cdp = await ctx.newCDPSession(page);
  let n = 0, t0 = 0, rec = false;
  const frames = [];
  cdp.on('Page.screencastFrame', async f => {
    cdp.send('Page.screencastFrameAck', { sessionId: f.sessionId }).catch(() => {});
    if (!rec) return;
    const ts = f.metadata.timestamp;
    if (!t0) t0 = ts;
    const name = `f${String(n++).padStart(5, '0')}.jpg`;
    fs.writeFileSync(`${OUT}/frames/${name}`, Buffer.from(f.data, 'base64'));
    frames.push({ name, t: ts - t0 });
  });
  const mark = (id) => { const t = frames.length ? frames[frames.length - 1].t : 0; marks.push({ id, t: Date.now() }); console.log('paso', id); };
  const shot = async id => page.screenshot({ path: `${OUT}/paso-${id}.jpg`, type: 'jpeg', quality: 80 }).catch(() => {});
  const css = `#__ptr{position:fixed;left:0;top:0;width:0;height:0;z-index:2147483647;pointer-events:none}
#__ptr .g{position:absolute;left:-26px;top:-26px;width:52px;height:52px;border-radius:50%;background:radial-gradient(circle,rgba(34,197,94,.55) 0%,rgba(34,197,94,.28) 45%,rgba(34,197,94,0) 72%);transition:transform .18s}
#__ptr svg{position:absolute;left:-3px;top:-2px;width:30px;height:30px;filter:drop-shadow(0 2px 3px rgba(0,0,0,.45));transition:transform .15s;transform-origin:3px 2px}
#__ptr.down svg{transform:scale(.82)} #__ptr.down .g{transform:scale(1.35)}
.__rip{position:fixed;width:20px;height:20px;margin:-10px 0 0 -10px;border-radius:50%;border:4px solid #22c55e;background:rgba(34,197,94,.25);z-index:2147483647;pointer-events:none;animation:__r .65s ease-out forwards}
@keyframes __r{0%{transform:scale(.6);opacity:1}100%{transform:scale(3.4);opacity:0}}`;
  const prep = async () => page.evaluate(c => {
    if (!document.getElementById('__tapcss')) { const s = document.createElement('style'); s.id = '__tapcss'; s.textContent = c; document.head.appendChild(s); }
    if (!document.getElementById('__ptr')) {
      const d = document.createElement('div'); d.id = '__ptr';
      d.innerHTML = '<div class="g"></div><svg viewBox="0 0 24 24"><path d="M3 2 L3 20 L8 15.5 L11.5 22.5 L14.6 21 L11.2 14.2 L18 14 Z" fill="#fff" stroke="#0b3d12" stroke-width="1.6" stroke-linejoin="round"/></svg>';
      document.body.appendChild(d); window.__px = 250; window.__py = 520;
    }
    const top = l => { const ds = [...document.querySelectorAll('dialog[open]')]; return ds.length ? ds[ds.length - 1] : document.body; };
    window.__place = (el, x, y) => { const host = top(); if (el.parentNode !== host) host.appendChild(el); el.style.left = x + 'px'; el.style.top = y + 'px'; const r = el.getBoundingClientRect(); const dx = r.left - x, dy = r.top - y; if (Math.abs(dx) > .5 || Math.abs(dy) > .5) { el.style.left = (x - dx) + 'px'; el.style.top = (y - dy) + 'px'; } };
    window.__move = (x, y, ms) => new Promise(res => { const el = document.getElementById('__ptr'), sx = window.__px, sy = window.__py, t = performance.now(); const f = now => { const k = Math.min(1, (now - t) / ms), e = k < .5 ? 4 * k * k * k : 1 - Math.pow(-2 * k + 2, 3) / 2; const cx = sx + (x - sx) * e, cy = sy + (y - sy) * e - Math.sin(Math.PI * k) * 18; window.__place(el, cx, cy); k < 1 ? requestAnimationFrame(f) : (window.__px = x, window.__py = y, res()); }; requestAnimationFrame(f); });
    window.__press = () => { const el = document.getElementById('__ptr'); el.classList.add('down'); const r = document.createElement('div'); r.className = '__rip'; document.body.appendChild(r); window.__place(r, window.__px, window.__py); el.parentNode.appendChild(el); setTimeout(() => r.remove(), 700); setTimeout(() => el.classList.remove('down'), 220); };
    window.__place(document.getElementById('__ptr'), window.__px, window.__py);
  }, css);
  async function tap(loc, { click = true, wait = 700 } = {}) {
    loc = typeof loc === 'string' ? page.locator(loc).first() : loc;
    await loc.scrollIntoViewIfNeeded({ timeout: 8000 }).catch(() => {});
    await sleep(120);
    await prep();
    const b = await loc.boundingBox();
    if (b) {
      const x = b.x + Math.min(b.width / 2, 140), y = b.y + b.height / 2;
      const dist = await page.evaluate(([x, y]) => Math.hypot(x - window.__px, y - window.__py), [x, y]);
      await page.evaluate(([x, y, ms]) => window.__move(x, y, ms), [x, y, Math.round(Math.min(900, Math.max(380, dist * 1.6)))]);
      await sleep(140);
      await page.evaluate(() => window.__press());
      await sleep(180);
    }
    if (click) await loc.click({ timeout: 8000 });
    await prep();
    await sleep(wait);
  }
  async function scroll(px, ms = 1200) {
    await prep();
    await page.evaluate(([px, ms]) => new Promise(res => { const el = document.querySelector('dialog[open] .drawer-body') || document.scrollingElement; const s = el.scrollTop, t = performance.now(); const f = now => { const k = Math.min(1, (now - t) / ms), e = k < .5 ? 2 * k * k : 1 - Math.pow(-2 * k + 2, 2) / 2; el.scrollTop = s + px * e; k < 1 ? requestAnimationFrame(f) : res(); }; requestAnimationFrame(f); }), [px, ms]);
    await sleep(250);
  }
  const slowType = async (loc, txt) => { await page.locator(loc).first().pressSequentially(txt, { delay: 110 }); };
  const closeExtras = async () => { for (const s of ['[data-act="cambiosok"]']) { const l = page.locator(s); if (await l.count() && await l.first().isVisible()) { await l.first().click().catch(() => {}); await sleep(400); } } };
  async function buscar(){
    const b = page.locator('#searchForm button[type="submit"], #searchForm .btn').first();
    if (await b.count()) await tap(b, { wait: 300 }); else await page.keyboard.press('Enter');
    await page.keyboard.press('Escape').catch(() => {});
    await page.evaluate(() => { document.activeElement && document.activeElement.blur(); const s = document.getElementById('sugg'); if (s) s.hidden = true; });
    await sleep(1500);
  }
  const sec = {};
  const at = id => { sec[id] = frames.length ? frames[frames.length - 1].t : 0; console.log('paso', id, sec[id].toFixed(2)); };
  try {
    await page.goto('https://ferreteria-fermil.pages.dev/', { waitUntil: 'networkidle', timeout: 60000 });
    await prep(); await sleep(1500);
    await cdp.send('Page.startScreencast', { format: 'jpeg', quality: 92, maxWidth: 1080, maxHeight: 1920, everyNthFrame: 1 });
    rec = true; await sleep(300);
    // keep frames flowing while static: tiny invisible animation
    await page.evaluate(() => { const d = document.createElement('div'); d.style.cssText = 'position:fixed;left:0;top:0;width:1px;height:1px;z-index:2147483647;pointer-events:none'; document.body.appendChild(d); let i = 0; (function f(){ d.style.background = (i++ % 2) ? 'rgba(0,0,0,.01)' : 'rgba(0,0,0,.02)'; requestAnimationFrame(f); })(); });
    at('inicio'); await sleep(3200); await scroll(560, 2600); await sleep(1100); await scroll(700, 2600); await sleep(1100); await scroll(-1260, 2200); await sleep(1300); await shot('1-inicio');
    at('login'); await tap('#btnLogin'); await sleep(400);
    await tap('#cCode', { wait: 300 }); await slowType('#cCode', CODE); await sleep(500);
    await page.keyboard.press('Enter'); await sleep(2600); await closeExtras(); await prep(); await shot('2-dentro');
    at('dentro'); await sleep(1200); await scroll(520, 1500); await sleep(900); await shot('3-precios');
    at('buscar'); await page.evaluate(() => window.scrollTo({ top: 0 })); await sleep(400);
    await tap('#q', { wait: 300 }); await slowType('#q', 'cemento'); await sleep(400); await buscar();
    await scroll(300, 1000); await sleep(800); await shot('4-busqueda');
    at('agregar'); await tap(page.locator('[data-act="add"]:visible').first(), { wait: 900 });
    const inc = page.locator('[data-act="inc"]:visible').first();
    if (await inc.count()) { await tap(inc, { wait: 450 }); await tap(inc, { wait: 700 }); }
    await page.evaluate(() => window.scrollTo({ top: 0, behavior: 'smooth' })); await sleep(700);
    await page.locator('#q').fill(''); await tap('#q', { wait: 200 }); await slowType('#q', 'cabilla'); await sleep(300); await buscar();
    await tap(page.locator('[data-act="add"]:visible').first(), { wait: 1100 }).catch(e => console.log('aviso agregar 2', e.message.slice(0,80))); await shot('5-agregado');
    at('carrito'); await tap(page.locator('[data-act="cart"]:visible').first(), { wait: 1300 }); await shot('6-carrito');
    at('pedido'); await tap('[data-act="type"][data-type="pedido"]', { wait: 900 });
    await scroll(420, 1300); await sleep(300);
    const nom = page.locator('#fNombre'); if (await nom.isVisible().catch(() => false)) { await nom.fill(''); await tap(nom, { wait: 200 }); await slowType('#fNombre', 'Ferretería Javier'); await sleep(500); }
    await scroll(500, 1300); await sleep(500);
    await tap('[data-act="wa"]', { click: false, wait: 1200 }); await shot('7-pedido');
    at('presupuesto'); await page.evaluate(() => { const el = document.querySelector('dialog[open] .drawer-body'); if (el) el.scrollTop = 0; }); await sleep(500);
    await tap('[data-act="type"][data-type="presupuesto"]', { wait: 1100 }); await shot('8-presupuesto');
    await tap('[data-act="quote"]', { wait: 1800 }); await shot('9-ver');
    at('verpres'); await page.evaluate(() => { const q = document.querySelector('#dlgQuote'); if (q) q.scrollTop = 0; }); await sleep(600);
    await page.evaluate(() => new Promise(res => { const el = document.querySelector('#dlgQuote'); if (!el) return res(); const s = el.scrollTop, t = performance.now(); const f = now => { const k = Math.min(1, (now - t) / 2200); el.scrollTop = s + 600 * k; k < 1 ? requestAnimationFrame(f) : res(); }; requestAnimationFrame(f); }));
    await sleep(900);
    const closeQ = page.locator('#dlgQuote [data-act="close"]').first(); if (await closeQ.count()) await tap(closeQ, { wait: 700 }); else await page.keyboard.press('Escape');
    at('pdf'); const dl = page.waitForEvent('download', { timeout: 30000 }).catch(() => null);
    await tap(page.locator('dialog[open] [data-act="pdf"]').first(), { wait: 600 });
    const d = await dl; if (d) { await d.saveAs(`${OUT}/presupuesto.pdf`); console.log('pdf ok'); }
    await sleep(2500); await shot('10-pdf');
    at('fin'); await page.keyboard.press('Escape'); await sleep(600); await page.evaluate(() => window.scrollTo({ top: 0, behavior: 'smooth' })); await sleep(2200);
  } catch (e) { console.log('ERROR', e.message); await shot('error'); }
  rec = false; await cdp.send('Page.stopScreencast').catch(() => {});
  await sleep(300);
  // constant 30 fps list for ffmpeg
  const lines = ['ffconcat version 1.0'];
  for (let i = 0; i < frames.length; i++) { const dur = i + 1 < frames.length ? frames[i + 1].t - frames[i].t : 0.5; lines.push(`file frames/${frames[i].name}`, `duration ${Math.max(dur, 0.001).toFixed(4)}`); }
  lines.push(`file frames/${frames[frames.length - 1].name}`);
  fs.writeFileSync(`${OUT}/lista.txt`, lines.join('\n'));
  fs.writeFileSync(`${OUT}/pasos.json`, JSON.stringify(sec, null, 1));
  console.log('frames', frames.length, 'dur', frames.length ? frames[frames.length - 1].t.toFixed(1) : 0);
  await browser.close();
})();

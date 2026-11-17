/* ===================== Panel de tabulaciones (administración) =====================
   Entra con el código de administración (tabla tabulador_admins en Supabase). Calcula fletes
   con la misma lógica del Excel "SISTEMA ERP FERMIL TABULACIONES": costo por km de cada camión,
   nómina, viáticos, hotel, peajes, topografía, utilidad y venta mínima (tope del flete).
   Los km salen de una matriz entre todos los lugares; un lugar nuevo se mide solo por
   carretera (OpenStreetMap/OSRM) a partir de sus coordenadas. */
const TAB = (() => {
  const TAMANOS = ['PEQUEÑO', 'MEDIANO', 'GRANDE'];
  const TOPE = {'PEQUEÑO': 'tope_pequeno', 'MEDIANO': 'tope_mediano', 'GRANDE': 'tope_grande'};
  const PARAMS = [
    ['origen', 'Origen de todos los viajes', 'txt'], ['gasoil', 'Precio del gasoil ($/litro)', 'usd'],
    ['bcv', 'Tasa BCV manual (Bs/$)', 'num'], ['viatico_camion', 'Viático diario camión ($)', 'usd'],
    ['viatico_gandola', 'Viático diario gandola ($)', 'usd'], ['hospedaje', 'Hospedaje por noche ($)', 'usd'],
    ['tope_pequeno', 'Tope del flete · PEQUEÑO', 'pct'], ['tope_mediano', 'Tope del flete · MEDIANO', 'pct'],
    ['tope_grande', 'Tope del flete · GRANDE', 'pct'], ['ocupacion_min', 'Ocupación mínima de carga', 'pct'],
    ['costo_parada', 'Costo operativo por parada ($)', 'usd'], ['utilidad', 'Utilidad del transporte', 'pct'],
    ['km_dia', 'Km máximos por día', 'num'], ['paradas_2dias', 'Paradas que obligan a 2 días', 'num'],
    ['km_min', 'Km mínimo por viaje', 'num'], ['diario_pesado', 'Pago diario extra chofer de gandola ($)', 'usd'],
    ['km_cambio_aceite', 'Km entre cambios de aceite', 'num'], ['litros_extra', 'Litros extra por cambio de aceite', 'num'],
  ];
  const FLOTA_COLS = [['modelo', 'Vehículo', 'txt'], ['tamano', 'Tamaño', 'tam'], ['tipo', 'Tipo', 'tipo'], ['capacidad', 'Capacidad kg', 'num'],
    ['ejes', 'Ejes', 'num'], ['cat_peaje', 'Peaje', 'peaje'], ['n_cauchos', 'N° cauchos', 'num'], ['precio_caucho', 'Caucho c/u $', 'num'],
    ['vida_cauchos', 'Vida cauchos km', 'num'], ['precio_paila', 'Paila $', 'num'], ['litros_paila', 'Litros paila', 'num'],
    ['litros_motor', 'Litros motor', 'num'], ['rend', 'Rend. km/L', 'num'], ['mant', '% mant.', 'pct'], ['factor', 'Factor peso', 'num']];
  const CHOF_COLS = [['nombre', 'Chofer', 'txt'], ['tipo', 'Tipo', 'chof'], ['mensual', 'Mensual + cesta $', 'num'], ['bonos', 'Bonos $', 'num'],
    ['parafiscales', 'Parafiscales $', 'num'], ['prestaciones', 'Prestaciones $', 'num'], ['por_viaje', 'Pago por viaje $ (pesados)', 'num']];

  let D = null, CODE = '', NOMBRE = '', ACT = '', PREC = new Map(), dirty = false, vista = 'viaje', filtroTab = '', vendTab = '', sugerir = false;
  let V = sess.get('fermil_tab_viaje', null) || {vendedor: '', vehiculo: '', chofer: '', paradas: []};

  const dlg = document.createElement('dialog');
  dlg.id = 'dlgTab'; dlg.className = 'panel tab-panel'; dlg.setAttribute('aria-labelledby', 'tabTitle');
  document.body.appendChild(dlg);
  const fab = document.createElement('button');
  fab.type = 'button'; fab.className = 'tab-fab'; fab.hidden = true; fab.textContent = '📊 Tabulaciones';
  fab.addEventListener('click', () => abrir());
  document.body.appendChild(fab);
  const hojaImp = document.createElement('div');
  hojaImp.id = 'tabPrint'; document.body.appendChild(hojaImp);

  /* ---------- números ---------- */
  const n = v => { const x = Number(String(v ?? '').replace(',', '.')); return isFinite(x) ? x : 0; };
  const r1 = v => Math.round(v * 10) / 10;
  const pct = v => fmt0.format(r1(v * 100)) + ' %';
  const km_ = v => isFinite(v) ? fmt0.format(r1(v)) + ' km' : '—';
  const kg = v => fmt0.format(Math.round(v)) + ' kg';
  const P = () => D.parametros;
  const bcv = () => (P().bcv_auto !== false && CONFIG.tasaBs > 0) ? CONFIG.tasaBs : (n(P().bcv) || 1);
  const guardarViaje = () => sess.set('fermil_tab_viaje', V);
  const idx = nom => D.lugares.findIndex(l => l.nombre === nom);
  const lug = nom => D.lugares[idx(nom)];
  const veh = mod => D.flota.find(v => v.modelo === mod);
  const chof = nom => D.choferes.find(c => c.nombre === nom);
  const corredores = () => [...new Set(D.lugares.map(l => l.corredor).filter(Boolean))];

  /* ---------- cálculo (igual que el Excel) ---------- */
  function vehCostos(v){
    const p = P();
    const cpk_c = n(v.n_cauchos) * n(v.precio_caucho) / (n(v.vida_cauchos) || 1);
    const cpk_a = n(v.precio_paila) / (n(v.litros_paila) || 1) * (n(v.litros_motor) + n(p.litros_extra)) / (n(p.km_cambio_aceite) || 1);
    const cpk_g = n(p.gasoil) / (n(v.rend) || 1);
    return {cpk_c, cpk_a, cpk_g, costo_km: (cpk_c + cpk_a + cpk_g) * (1 + n(v.mant)) * (n(v.factor) || 1), peaje: n(D.peajes[v.cat_peaje]) / bcv()};
  }
  const diarioChofer = c => (n(c.mensual) + n(c.bonos) + n(c.parafiscales) + n(c.prestaciones)) / 30;
  const choferCosto = (c, dias) => c.tipo === 'Pesado' ? n(c.por_viaje) + n(P().diario_pesado) * dias : diarioChofer(c) * dias;
  const km = (a, b) => { const i = idx(a), j = idx(b); return (i < 0 || j < 0 || !D.matriz[i]) ? NaN : n(D.matriz[i][j]); };
  const tope = t => n(P()[TOPE[t]]) || 0.03;
  const promChofer = tipo => { const cs = D.choferes.filter(c => c.tipo === tipo); return cs.length ? cs.reduce((s, c) => s + choferCosto(c, 1) - (tipo === 'Pesado' ? n(P().diario_pesado) : 0), 0) / cs.length : 0; };

  function calcular(paradas, modelo, chofer){
    const p = P(), v = veh(modelo);
    const ps = paradas.filter(x => x.lugar && idx(x.lugar) >= 0);
    if (!v || !ps.length) return null;
    const vc = vehCostos(v);
    const ruta = [p.origen, ...ps.map(x => x.lugar), p.origen];
    let kms = 0, falta = false;
    for (let i = 1; i < ruta.length; i++){ const d = km(ruta[i - 1], ruta[i]); if (!isFinite(d)) falta = true; else kms += d; }
    const kmTot = Math.max(n(p.km_min), kms);
    const np = ps.length;
    const dias = Math.max(np >= n(p.paradas_2dias) ? 2 : 1, Math.ceil(kmTot / (n(p.km_dia) || 400)));
    const venta = ps.reduce((s, x) => s + n(x.venta), 0), peso = ps.reduce((s, x) => s + n(x.peso), 0);
    const ls = ps.map(x => lug(x.lugar));
    const rod = kmTot * vc.costo_km, topo = rod * Math.max(...ls.map(l => n(l.topo))), par = np * n(p.costo_parada);
    const subV = rod + topo + par;
    const corr = {};
    ls.forEach(l => { corr[l.corredor] = Math.max(corr[l.corredor] || 0, n(l.peajes)); });
    const nPeajes = Object.values(corr).reduce((s, x) => s + x, 0) * 2;
    const peajes = nPeajes * vc.peaje;
    const c = chof(chofer);
    const tipoC = c ? c.tipo : (v.tipo === 'Gandola' ? 'Pesado' : 'Liviano');
    const nomina = c ? choferCosto(c, dias) : (tipoC === 'Pesado' ? promChofer('Pesado') + n(p.diario_pesado) * dias : promChofer('Liviano') * dias);
    const viat = (v.tipo === 'Gandola' ? n(p.viatico_gandola) : n(p.viatico_camion)) * dias;
    const hosp = n(p.hospedaje) * Math.max(0, dias - 1);
    const subO = peajes + nomina + viat + hosp;
    const util = (subV + subO) * n(p.utilidad);
    const total = subV + subO + util;
    const t = tope(v.tamano), ocup = peso / (n(v.capacidad) || 1), vmin = total / t;
    const estado = ocup > 1 ? 'exceso' : (ocup < n(p.ocupacion_min) ? 'vacio' : (venta < vmin ? 'flete' : 'ok'));
    return {v, kmTot, dias, np, venta, peso, ocup, rod, topo, par, subV, nPeajes, peajes, nomina, viat, hosp, subO, util, total, tope: t,
            vmin, incid: venta ? total / venta : 0, estado, falta, tipoC, chofer: c ? c.nombre : `Promedio ${tipoC.toLowerCase()}`};
  }

  function tabulador(nom, tam){
    const p = P(), l = lug(nom), vs = D.flota.filter(v => v.tamano === tam);
    if (!l || !vs.length) return null;
    const ck = vs.reduce((s, v) => s + vehCostos(v).costo_km, 0) / vs.length;
    const pj = vs.reduce((s, v) => s + vehCostos(v).peaje, 0) / vs.length;
    const kmTot = Math.max(n(p.km_min), km(p.origen, nom) + km(nom, p.origen));
    const dias = Math.max(1, Math.ceil(kmTot / (n(p.km_dia) || 400)));
    const veh_ = kmTot * ck * (1 + n(l.topo)) + n(p.costo_parada);
    const peajes = n(l.peajes) * 2 * pj;
    const nom_ = tam === 'GRANDE' ? promChofer('Pesado') + n(p.diario_pesado) * dias : promChofer('Liviano') * dias;
    const viat = (tam === 'GRANDE' ? n(p.viatico_gandola) : n(p.viatico_camion)) * dias;
    const costo = (veh_ + peajes + nom_ + viat + n(p.hospedaje) * (dias - 1)) * (1 + n(p.utilidad));
    return {kmTot, dias, costo, minimo: costo / tope(tam)};
  }

  /* ---------- productos de cada parada ---------- */
  function precioDe(cod){
    const x = PREC.get(cod), pr = byRef[cod];
    const pesoPlade = x ? n(x.peso) : 0, pesoMan = n((D.pesos_manual || {})[cod]);
    return {cod, nombre: pr ? pr.nombre : '', unidad: pr ? pr.unidad : '', mayor: x ? n(x.mayor) : (pr ? n(pr.mayor) : 0),
            stock: x ? n(x.stock) : null, peso: pesoPlade || pesoMan, pesoOrigen: pesoPlade ? 'PLADE' : (pesoMan ? 'manual' : ''), existe: !!(x || pr)};
  }
  function totParada(pa){
    if (!pa.items || !pa.items.length) return {venta: n(pa.venta), peso: n(pa.peso), sinPeso: 0};
    let venta = 0, peso = 0, sinPeso = 0;
    pa.items.forEach(it => { const q = precioDe(it.cod); venta += q.mayor * n(it.cant); peso += q.peso * n(it.cant); if (!q.peso && n(it.cant)) sinPeso++; });
    return {venta: venta + n(pa.ventaExtra), peso: peso + n(pa.pesoExtra), sinPeso};
  }
  const paradasCalc = () => V.paradas.map(pa => Object.assign({lugar: pa.lugar}, totParada(pa)));

  /* ---------- sesión ---------- */
  function cargar(r, code){
    CODE = code; NOMBRE = r.nombre || 'Administración'; ACT = r.actualizado || '';
    D = r.datos || {};
    ['parametros', 'peajes', 'pesos_manual'].forEach(k => { if (!D[k] || typeof D[k] !== 'object') D[k] = {}; });
    ['flota', 'choferes', 'lugares', 'matriz', 'vendedores'].forEach(k => { if (!Array.isArray(D[k])) D[k] = []; });
    if (P().bcv_auto == null) P().bcv_auto = true;
    PREC = new Map((r.precios || []).map(x => [String(x[0]), {mayor: x[1], stock: x[2], peso: x[3]}]));
    dirty = false;
    if (!V.paradas.length) V.paradas = [{lugar: '', items: [], venta: '', peso: ''}];
    fab.hidden = false;
  }
  function salir(){
    if (dirty && !confirmar('Tienes cambios sin guardar. ¿Salir igual?')) return;
    CODE = ''; D = null; PREC = new Map(); fab.hidden = true;
    sess.set('fermil_code', null); recordar.set(null);
    if (dlg.open) dlg.close();
    toast('Saliste del panel de tabulaciones');
  }
  function confirmar(msg){ return window.confirm(msg); }
  function abrir(v){ if (!D) return; if (v) vista = v; pintar(); if (!dlg.open) dlg.showModal(); }

  async function guardar(){
    const b = dlg.querySelector('[data-t="guardar"]');
    if (b){ b.disabled = true; b.textContent = 'Guardando…'; }
    try {
      const r = await rpc('fermil_guardar_tabulador', {p_codigo: CODE, p_datos: D});
      if (!r) throw new Error('El código ya no es válido. Vuelve a entrar.');
      ACT = r; dirty = false; toast('Cambios guardados');
    } catch (e){ toast(e.message || 'No se pudo guardar'); }
    pintar();
  }

  /* ---------- medir km por carretera (OpenStreetMap / OSRM) ---------- */
  async function osrm(qs){
    const coords = D.lugares.map(l => `${n(l.lon).toFixed(5)},${n(l.lat).toFixed(5)}`).join(';');
    const r = await fetch(`https://router.project-osrm.org/table/v1/driving/${coords}?annotations=distance${qs}`);
    const j = await r.json();
    if (j.code !== 'Ok') throw new Error('El servicio de mapas no respondió (' + (j.message || j.code) + '). Intenta en un rato.');
    return j;
  }
  async function medirLugar(i){
    const N = D.lugares.length;
    for (let a = 0; a < N; a++){ if (!D.matriz[a]) D.matriz[a] = []; while (D.matriz[a].length < N) D.matriz[a].push(null); }
    const [fila, col] = await Promise.all([osrm(`&sources=${i}`), osrm(`&destinations=${i}`)]);
    for (let j = 0; j < N; j++){
      D.matriz[i][j] = fila.distances[0][j] == null ? null : r1(fila.distances[0][j] / 1000);
      D.matriz[j][i] = col.distances[j][0] == null ? null : r1(col.distances[j][0] / 1000);
    }
    D.matriz[i][i] = 0;
    return Math.round(fila.sources[0].distance || 0);
  }
  async function medirTodo(){
    const j = await osrm('');
    D.matriz = j.distances.map(f => f.map(x => x == null ? null : r1(x / 1000)));
  }
  function leerCoords(t){
    t = String(t || '').trim();
    let m = t.match(/!3d(-?\d+\.\d+)!4d(-?\d+\.\d+)/) || t.match(/@(-?\d+\.\d+),\s*(-?\d+\.\d+)/) || t.match(/(-?\d{1,2}\.\d+)\s*[,; ]\s*(-?\d{1,3}\.\d+)/);
    if (!m) return null;
    const lat = Number(m[1]), lon = Number(m[2]);
    if (!(lat > -5 && lat < 16 && lon > -75 && lon < -58)) return null;  // dentro de Venezuela
    return {lat, lon};
  }

  /* ---------- pintar ---------- */
  const opt = (lista, sel, vacio) => (vacio != null ? `<option value="">${esc(vacio)}</option>` : '') + lista.map(x => `<option${x === sel ? ' selected' : ''}>${esc(x)}</option>`).join('');
  const ESTADO = {ok: ['✅ VIAJE APROBADO', 'ok'], exceso: ['❌ RECHAZADO: la carga pasa la capacidad del camión', 'no'], vacio: ['❌ RECHAZADO: el camión va muy vacío', 'no'], flete: ['❌ RECHAZADO: el flete es muy alto para esta venta', 'no']};

  function pintar(){
    const tabs = [['viaje', '🧮 Calcular viaje'], ['tabulador', '📊 Tabulador'], ['lugares', '🗺️ Lugares y km'], ['ajustes', '⚙️ Costos y flota']];
    dlg.innerHTML = `<div class="pn-head"><div><span class="eyebrow">Panel administrativo · ${esc(NOMBRE)}</span><h2 id="tabTitle">Tabulaciones</h2></div>
      <div class="pn-nav">${dirty ? '<button type="button" class="btn accent" data-t="guardar">Guardar cambios</button>' : ''}<button type="button" class="btn pn-back" data-t="salir">Salir</button><button type="button" class="x" data-act="close" aria-label="Cerrar">×</button></div></div>
      <div class="seg pn-tabs tab-tabs" role="tablist">${tabs.map(([k, t]) => `<button type="button" role="tab" data-t="vista" data-v="${k}" aria-pressed="${vista === k}">${t}</button>`).join('')}</div>
      <div class="pn-body">${dirty ? '<p class="tab-aviso">Tienes cambios sin guardar. Toca <b>Guardar cambios</b> para que queden para todos.</p>' : ''}${({viaje: pViaje, tabulador: pTabulador, lugares: pLugares, ajustes: pAjustes}[vista])()}</div>`;
  }

  function pViaje(){
    const ps = paradasCalc();
    const r = calcular(ps, V.vehiculo, V.chofer);
    const lugaresOpt = (sel) => {
      const grupos = D.vendedores.map(vd => [vd, D.lugares.filter(l => l.vendedor === vd)]).concat([['Otros', D.lugares.filter(l => !D.vendedores.includes(l.vendedor))]]);
      return '<option value="">Escoge el lugar…</option>' + grupos.filter(g => g[1].length && (!V.vendedor || g[0] === V.vendedor || sel)).map(([vd, ls]) =>
        `<optgroup label="${esc(vd)}">${ls.map(l => `<option${l.nombre === sel ? ' selected' : ''}>${esc(l.nombre)}</option>`).join('')}</optgroup>`).join('');
    };
    const paradas = V.paradas.map((pa, i) => {
      const t = totParada(pa), items = pa.items || [];
      const tramo = pa.lugar ? km(i === 0 ? P().origen : (V.paradas[i - 1].lugar || P().origen), pa.lugar) : NaN;
      return `<div class="tab-parada">
        <div class="tab-ph"><b>Parada ${i + 1}</b><select data-f="parada" data-i="${i}" aria-label="Lugar de la parada ${i + 1}">${lugaresOpt(pa.lugar)}</select>
          <span class="tab-muted">${pa.lugar ? `${esc(lug(pa.lugar)?.estado || '')} · ${km_(tramo)} desde la anterior` : ''}</span>
          <button type="button" class="btn link" data-t="quitar" data-i="${i}">Quitar</button></div>
        <div class="tab-items">
          ${items.map((it, k) => { const q = precioDe(it.cod); return `<div class="tab-item">
            <span class="tab-cod">${esc(it.cod)}</span><span class="tab-nom">${q.existe ? esc(q.nombre) : '<em>Código no encontrado</em>'}${q.stock != null ? ` <small>· existencia ${fmt0.format(q.stock)}</small>` : ''}</span>
            <label>Cant. <input type="number" min="0" step="any" value="${esc(it.cant)}" data-f="cant" data-i="${i}" data-k="${k}"></label>
            <span>${usd(q.mayor)} c/u</span>
            ${q.peso ? `<span>${fmt0.format(q.peso)} kg c/u <small>(${q.pesoOrigen})</small></span>` : `<label class="tab-falta">Peso kg c/u <input type="number" min="0" step="any" placeholder="falta" data-f="pesoman" data-cod="${esc(it.cod)}"></label>`}
            <b>${usd(q.mayor * n(it.cant))}</b><button type="button" class="x tab-xs" data-t="qitem" data-i="${i}" data-k="${k}" aria-label="Quitar producto">×</button></div>`; }).join('')}
          <form class="tab-add" data-i="${i}"><input name="cod" list="tabCodigos" placeholder="Código o nombre del producto" autocomplete="off"><input name="cant" type="number" min="0" step="any" placeholder="Cant." value="1"><button class="btn ghost">Agregar</button></form>
        </div>
        <div class="tab-pt">${items.length
          ? `<span>Venta: <b>${usd(t.venta)}</b></span><span>Peso: <b>${kg(t.peso)}</b></span>${t.sinPeso ? `<span class="tab-falta">${t.sinPeso} producto(s) sin peso</span>` : ''}`
          : `<label>Venta $ <input type="number" min="0" step="any" value="${esc(pa.venta)}" data-f="venta" data-i="${i}"></label><label>Peso kg <input type="number" min="0" step="any" value="${esc(pa.peso)}" data-f="peso" data-i="${i}"></label><span class="tab-muted">o agrega los productos por código y se calcula solo</span>`}</div>
      </div>`;
    }).join('');
    const vehs = D.flota.map(v => v.modelo), chofs = D.choferes.filter(c => { const v = veh(V.vehiculo); return !v || (v.tipo === 'Gandola') === (c.tipo === 'Pesado'); }).map(c => c.nombre);
    const det = r ? `
      <div class="tab-res">
        <div class="tab-kpis">
          <div><span>Km del viaje</span><b>${km_(r.kmTot)}</b></div><div><span>Días</span><b>${r.dias}${r.dias > 1 ? ` · ${r.dias - 1} noche(s)` : ''}</b></div>
          <div><span>Ocupación</span><b>${pct(r.ocup)}</b><small>${kg(r.peso)} de ${kg(n(r.v.capacidad))}</small></div>
          <div><span>Venta total</span><b>${usd(r.venta)}</b></div>
          <div class="tab-big"><span>Costo del flete</span><b>${usd(r.total)}</b><small>Incidencia ${pct(r.incid)}</small></div>
          <div class="tab-big"><span>Venta mínima (tope ${pct(r.tope)})</span><b>${usd(r.vmin)}</b></div>
        </div>
        <p class="tab-estado ${ESTADO[r.estado][1]}">${ESTADO[r.estado][0]}${r.estado === 'vacio' ? ` (mínimo ${pct(n(P().ocupacion_min))})` : ''}${r.estado === 'exceso' ? ` (sobran ${kg(r.peso - n(r.v.capacidad))}): usa un camión más grande o divide el viaje` : ''}${r.estado === 'flete' ? ` · faltan ${usd(r.vmin - r.venta)} de venta` : ''}</p>
        ${r.falta ? '<p class="tab-falta">Algún tramo no tiene km en la matriz: revisa la pestaña Lugares y km.</p>' : ''}
        <table class="tab-tbl tab-desg"><tbody>
          <tr><td>Rodamiento (gasoil, cauchos y aceite)</td><td>${usd(r.rod)}</td></tr><tr><td>Topografía</td><td>${usd(r.topo)}</td></tr>
          <tr><td>Costo por ${r.np} parada(s)</td><td>${usd(r.par)}</td></tr><tr class="sub"><td>Subtotal vehículo</td><td>${usd(r.subV)}</td></tr>
          <tr><td>Peajes (${r.nPeajes} pasos · ${usd(vehCostos(r.v).peaje)} c/u)</td><td>${usd(r.peajes)}</td></tr><tr><td>Nómina chofer (${esc(r.chofer)})</td><td>${usd(r.nomina)}</td></tr>
          <tr><td>Viáticos</td><td>${usd(r.viat)}</td></tr><tr><td>Hospedaje</td><td>${usd(r.hosp)}</td></tr><tr class="sub"><td>Subtotal operativo</td><td>${usd(r.subO)}</td></tr>
          <tr><td>Utilidad del transporte (${pct(n(P().utilidad))})</td><td>${usd(r.util)}</td></tr><tr class="tot"><td>COSTO LOGÍSTICO TOTAL</td><td>${usd(r.total)}</td></tr>
        </tbody></table>
        <div class="tab-acts"><button type="button" class="btn accent" data-t="imprimir">🖨️ Imprimir / PDF (blanco y negro)</button><button type="button" class="btn ghost" data-t="sugerir">${sugerir ? 'Ocultar comparación' : '🚛 Comparar todos los camiones'}</button></div>
        ${sugerir ? pSugerencia(ps) : ''}
      </div>` : '<p class="tab-muted">Escoge un vehículo y al menos una parada para ver el cálculo.</p>';
    codigosLista();
    return `<section class="pn-card"><h3>1. Vendedor, vehículo y chofer</h3>
        <div class="tab-grid3">
          <label>Vendedor<select data-f="vendedor">${opt(D.vendedores, V.vendedor, 'Todos')}</select></label>
          <label>Vehículo<select data-f="vehiculo">${opt(vehs, V.vehiculo, 'Escoge…')}</select></label>
          <label>Chofer<select data-f="chofer">${opt(chofs, V.chofer, 'Promedio del tipo')}</select></label>
        </div>
        <p class="tab-muted">Tasa BCV usada: <b>${fmt2.format(bcv())}</b> Bs/$ ${P().bcv_auto !== false && CONFIG.tasaBs > 0 ? '(la del día, de PLADE)' : '(manual)'} · Origen y regreso: <b>${esc(P().origen)}</b></p>
      </section>
      <section class="pn-card"><h3>2. Paradas en orden</h3>${paradas}
        <div class="tab-acts"><button type="button" class="btn ghost" data-t="parada">+ Agregar parada</button><button type="button" class="btn link" data-t="limpiar">Empezar un viaje nuevo</button></div>
      </section>
      <section class="pn-card"><h3>3. Resultado</h3>${det}</section>`;
  }
  /* La lista de códigos (miles de productos) se arma una sola vez fuera del panel, para no redibujarla en cada cambio */
  function codigosLista(){
    if (document.getElementById('tabCodigos')) return;
    const dl = document.createElement('datalist');
    dl.id = 'tabCodigos';
    dl.innerHTML = PRODUCTS.map(p => `<option value="${esc(p.ref)}">${esc(p.nombre)}</option>`).join('');
    document.body.appendChild(dl);
  }
  function pSugerencia(ps){
    const filas = D.flota.map(v => calcular(ps, v.modelo, '')).filter(Boolean);
    const ok = filas.filter(r => r.estado === 'ok').sort((a, b) => a.total - b.total);
    const mejor = ok[0];
    return `<div class="tab-scroll"><table class="tab-tbl"><thead><tr><th>Vehículo</th><th>Tamaño</th><th>Ocupación</th><th>Costo flete</th><th>Venta mínima</th><th>Resultado</th></tr></thead><tbody>
      ${filas.map(r => `<tr class="${r === mejor ? 'mejor' : ''}"><td>${esc(r.v.modelo)}${r === mejor ? ' ⭐' : ''}</td><td>${esc(r.v.tamano)}</td><td>${pct(r.ocup)}</td><td>${usd(r.total)}</td><td>${usd(r.vmin)}</td><td>${({ok: '✅', exceso: '❌ no cabe', vacio: '❌ muy vacío', flete: '❌ flete alto'})[r.estado]}</td></tr>`).join('')}
      </tbody></table></div><p class="tab-muted">${mejor ? `⭐ El camión aprobado más barato para este viaje es el <b>${esc(mejor.v.modelo)}</b>.` : 'Ningún camión aprueba este viaje: hace falta más carga o más venta.'} La comparación usa el chofer promedio de cada tipo.</p>`;
  }

  function pTabulador(){
    const f = norm(filtroTab);
    const ls = D.lugares.filter(l => (!vendTab || l.vendedor === vendTab) && (!f || norm(l.nombre + ' ' + l.estado + ' ' + l.corredor).includes(f)))
      .sort((a, b) => (a.vendedor || '').localeCompare(b.vendedor || '') || km(P().origen, a.nombre) - km(P().origen, b.nombre));
    return `<section class="pn-card"><h3>Venta mínima por destino (viaje directo ida y vuelta)</h3>
      <div class="tab-grid3"><label>Vendedor<select data-f="vendtab">${opt(D.vendedores, vendTab, 'Todos')}</select></label><label>Buscar<input data-f="filtrotab" value="${esc(filtroTab)}" placeholder="Pueblo, estado o corredor"></label>
      <div class="tab-acts"><button type="button" class="btn ghost" data-t="imprimirtab">🖨️ Imprimir tabulador</button></div></div>
      <div class="tab-scroll"><table class="tab-tbl"><thead><tr><th>Vendedor</th><th>Lugar</th><th>Estado</th><th>Km ida y vuelta</th><th>Peajes ida</th><th>Días</th>${TAMANOS.map(t => `<th>Mínimo ${t}</th>`).join('')}</tr></thead><tbody>
      ${ls.map(l => { const rs = TAMANOS.map(t => tabulador(l.nombre, t)); return `<tr><td>${esc(l.vendedor || '')}</td><td><b>${esc(l.nombre)}</b></td><td>${esc(l.estado || '')}</td><td>${km_(rs[0]?.kmTot)}</td><td>${n(l.peajes)}</td><td>${rs[0]?.dias || ''}</td>${rs.map(x => `<td class="num"><b>${x ? usd(x.minimo) : '—'}</b></td>`).join('')}</tr>`; }).join('')}
      </tbody></table></div>
      <p class="tab-muted">Cada tamaño usa el promedio de sus camiones: ${TAMANOS.map(t => `<b>${t}</b>: ${D.flota.filter(v => v.tamano === t).map(v => esc(v.modelo)).join(', ')}`).join(' · ')}. Tope del flete ${pct(tope('PEQUEÑO'))}.</p></section>`;
  }

  function pLugares(){
    const corr = corredores();
    return `<section class="pn-card"><h3>Agregar un lugar nuevo</h3>
      <p>Busca el pueblo en Google Maps, deja el dedo sobre el punto (o clic derecho en la computadora) y copia las coordenadas, por ejemplo <code>9.0408, -69.7413</code>. También sirve pegar el enlace de Google Maps. Los km por carretera hasta todos los demás lugares se calculan solos.</p>
      <form class="tab-nuevo tab-grid3" id="tabNuevo">
        <label>Nombre<input name="nombre" required></label><label>Estado<input name="estado" required></label>
        <label>Vendedor<select name="vendedor">${opt(D.vendedores, '', null)}</select></label>
        <label>Corredor (para los peajes)<input name="corredor" list="tabCorr" required placeholder="Ej: Troncal 5 (Sur-Occidente)"></label>
        <label>Peajes en la ida<input name="peajes" type="number" min="0" step="1" value="0"></label>
        <label>% topografía<input name="topo" type="number" min="0" max="100" step="any" value="10"></label>
        <label class="tab-span2">Coordenadas o enlace de Google Maps<input name="coords" required placeholder="9.0408, -69.7413"></label>
        <div class="tab-acts"><button class="btn accent">Agregar y medir km</button></div>
      </form><datalist id="tabCorr">${corr.map(c => `<option>${esc(c)}</option>`).join('')}</datalist></section>
      <section class="pn-card"><h3>Lugares (${D.lugares.length})</h3>
      <p class="tab-muted">Peajes = cuántos peajes hay en la ida. En un viaje con varias paradas, por cada corredor se cobra el pueblo con más peajes (ida y vuelta).</p>
      <div class="tab-scroll"><table class="tab-tbl tab-edit"><thead><tr><th>Lugar</th><th>Estado</th><th>Vendedor</th><th>Corredor</th><th>Peajes ida</th><th>% topo.</th><th>Km desde ${esc(P().origen)}</th><th>Coordenadas</th><th></th></tr></thead><tbody>
      ${D.lugares.map((l, i) => `<tr><td><input value="${esc(l.nombre)}" data-p="lugares.${i}.nombre" data-tipo="txt" readonly title="El nombre no se cambia para no dañar la matriz"></td><td><input value="${esc(l.estado || '')}" data-p="lugares.${i}.estado" data-tipo="txt"></td>
        <td><select data-p="lugares.${i}.vendedor" data-tipo="txt">${opt(D.vendedores, l.vendedor, '—')}</select></td><td><input value="${esc(l.corredor || '')}" list="tabCorr" data-p="lugares.${i}.corredor" data-tipo="txt"></td>
        <td><input type="number" min="0" step="1" value="${n(l.peajes)}" data-p="lugares.${i}.peajes"></td><td><input type="number" step="any" value="${r1(n(l.topo) * 100)}" data-p="lugares.${i}.topo" data-tipo="pct"></td>
        <td class="num">${km_(km(P().origen, l.nombre))}</td><td class="tab-muted">${n(l.lat).toFixed(4)}, ${n(l.lon).toFixed(4)}</td>
        <td><button type="button" class="btn link" data-t="borrarlugar" data-i="${i}">Borrar</button></td></tr>`).join('')}
      </tbody></table></div>
      <div class="tab-acts"><button type="button" class="btn ghost" data-t="medirtodo">Volver a medir toda la matriz</button></div>
      <p class="tab-muted">Km por carretera de OpenStreetMap (OSRM). Pueden variar unos km con lo que diga Google Maps.</p></section>`;
  }

  function campo(path, val, tipo){
    if (tipo === 'tam') return `<select data-p="${path}" data-tipo="txt">${opt(TAMANOS, val, null)}</select>`;
    if (tipo === 'tipo') return `<select data-p="${path}" data-tipo="txt">${opt(['Camion', 'Gandola'], val, null)}</select>`;
    if (tipo === 'chof') return `<select data-p="${path}" data-tipo="txt">${opt(['Liviano', 'Pesado'], val, null)}</select>`;
    if (tipo === 'peaje') return `<select data-p="${path}" data-tipo="txt">${opt(Object.keys(D.peajes), val, null)}</select>`;
    if (tipo === 'txt') return `<input value="${esc(val ?? '')}" data-p="${path}" data-tipo="txt">`;
    if (tipo === 'pct') return `<input type="number" step="any" value="${r1(n(val) * 100)}" data-p="${path}" data-tipo="pct">`;
    return `<input type="number" step="any" value="${esc(val ?? '')}" data-p="${path}">`;
  }
  function pAjustes(){
    const p = P();
    return `<section class="pn-card"><h3>Costos generales</h3>
      <label class="tab-check"><input type="checkbox" data-p="parametros.bcv_auto" data-tipo="bool"${p.bcv_auto !== false ? ' checked' : ''}> Usar la tasa BCV del día que trae PLADE (${CONFIG.tasaBs > 0 ? fmt2.format(CONFIG.tasaBs) : 'no disponible'})</label>
      <div class="tab-grid3">${PARAMS.map(([k, t, tipo]) => `<label>${esc(t)}${tipo === 'pct' ? ' (%)' : ''}${campo('parametros.' + k, p[k], tipo)}</label>`).join('')}</div></section>
      <section class="pn-card"><h3>Peajes (Bs por peaje)</h3><div class="tab-grid3">${Object.keys(D.peajes).map(k => `<label>${esc(k)}${campo('peajes.' + k, D.peajes[k], 'num')}<small>${usd(n(D.peajes[k]) / bcv())}</small></label>`).join('')}</div></section>
      <section class="pn-card"><h3>Flota</h3><div class="tab-scroll"><table class="tab-tbl tab-edit"><thead><tr>${FLOTA_COLS.map(c => `<th>${c[1]}</th>`).join('')}<th>Costo por km</th><th></th></tr></thead><tbody>
      ${D.flota.map((v, i) => `<tr>${FLOTA_COLS.map(([k, , t]) => `<td>${campo(`flota.${i}.${k}`, v[k], t)}</td>`).join('')}<td class="num"><b>${usd(vehCostos(v).costo_km)}</b></td><td><button type="button" class="btn link" data-t="borrar" data-l="flota" data-i="${i}">Borrar</button></td></tr>`).join('')}
      </tbody></table></div><div class="tab-acts"><button type="button" class="btn ghost" data-t="nuevo" data-l="flota">+ Agregar camión</button></div></section>
      <section class="pn-card"><h3>Choferes</h3><div class="tab-scroll"><table class="tab-tbl tab-edit"><thead><tr>${CHOF_COLS.map(c => `<th>${c[1]}</th>`).join('')}<th>Costo diario</th><th></th></tr></thead><tbody>
      ${D.choferes.map((c, i) => `<tr>${CHOF_COLS.map(([k, , t]) => `<td>${campo(`choferes.${i}.${k}`, c[k], t)}</td>`).join('')}<td class="num">${c.tipo === 'Pesado' ? usd(n(p.diario_pesado)) + ' + viaje' : usd(diarioChofer(c))}</td><td><button type="button" class="btn link" data-t="borrar" data-l="choferes" data-i="${i}">Borrar</button></td></tr>`).join('')}
      </tbody></table></div><div class="tab-acts"><button type="button" class="btn ghost" data-t="nuevo" data-l="choferes">+ Agregar chofer</button></div></section>
      <section class="pn-card"><h3>Vendedores mayoristas</h3><p class="tab-muted">${D.vendedores.map(esc).join(' · ')}</p></section>`;
  }

  /* ---------- imprimir en blanco y negro ---------- */
  function imprimir(html){
    hojaImp.innerHTML = `<div class="tp-head"><b>FERRETERÍA FERMIL</b><span>${new Date().toLocaleDateString('es-VE')} · Tasa BCV ${fmt2.format(bcv())}</span></div>` + html;
    document.body.classList.add('tab-printing');
    const fin = () => { document.body.classList.remove('tab-printing'); window.removeEventListener('afterprint', fin); };
    window.addEventListener('afterprint', fin);
    setTimeout(() => window.print(), 50);
  }
  function imprimirViaje(){
    const ps = paradasCalc(), r = calcular(ps, V.vehiculo, V.chofer);
    if (!r) return;
    const filas = V.paradas.filter(pa => pa.lugar).map((pa, i) => { const t = totParada(pa); return `<tr><td>${i + 1}</td><td>${esc(pa.lugar)}</td><td>${esc(lug(pa.lugar)?.estado || '')}</td><td>${usd(t.venta)}</td><td>${kg(t.peso)}</td><td></td></tr>`; }).join('');
    const prods = V.paradas.filter(pa => pa.lugar && pa.items && pa.items.length).map((pa, i) => `<p><b>${esc(pa.lugar)}:</b> ${pa.items.map(it => { const q = precioDe(it.cod); return `${esc(it.cod)} ${esc(q.nombre)} × ${fmt0.format(n(it.cant))}`; }).join(' · ')}</p>`).join('');
    imprimir(`<h1>Orden de despacho</h1><p>Vendedor: <b>${esc(V.vendedor || '—')}</b> · Vehículo: <b>${esc(r.v.modelo)}</b> · Chofer: <b>${esc(r.chofer)}</b></p>
      <table><thead><tr><th>#</th><th>Lugar</th><th>Estado</th><th>Venta</th><th>Peso</th><th>Firma / recibido</th></tr></thead><tbody>${filas}</tbody></table>${prods}
      <table class="tp-res"><tbody><tr><td>Km del viaje</td><td>${km_(r.kmTot)}</td><td>Días</td><td>${r.dias}</td></tr><tr><td>Ocupación</td><td>${pct(r.ocup)}</td><td>Venta total</td><td>${usd(r.venta)}</td></tr>
      <tr><td>Subtotal vehículo</td><td>${usd(r.subV)}</td><td>Peajes</td><td>${usd(r.peajes)}</td></tr><tr><td>Nómina chofer</td><td>${usd(r.nomina)}</td><td>Viáticos + hotel</td><td>${usd(r.viat + r.hosp)}</td></tr>
      <tr><td>Utilidad transporte</td><td>${usd(r.util)}</td><td><b>COSTO TOTAL</b></td><td><b>${usd(r.total)}</b></td></tr><tr><td>Venta mínima</td><td>${usd(r.vmin)}</td><td>Incidencia</td><td>${pct(r.incid)}</td></tr></tbody></table>
      <p class="tp-estado">${ESTADO[r.estado][0].replace(/[✅❌] /, '')}</p><p class="tp-firmas">Elaborado: __________________ &nbsp; Chofer: __________________ &nbsp; Autorizado: __________________</p>`);
  }
  function imprimirTab(){
    const ls = D.lugares.filter(l => !vendTab || l.vendedor === vendTab);
    imprimir(`<h1>Tabulador de ventas mínimas${vendTab ? ' · ' + esc(vendTab) : ''}</h1><table><thead><tr><th>Vendedor</th><th>Lugar</th><th>Km i/v</th><th>Peajes</th>${TAMANOS.map(t => `<th>Mín. ${t}</th>`).join('')}</tr></thead><tbody>
      ${ls.map(l => `<tr><td>${esc(l.vendedor || '')}</td><td>${esc(l.nombre)}</td><td>${km_(tabulador(l.nombre, 'PEQUEÑO')?.kmTot)}</td><td>${n(l.peajes)}</td>${TAMANOS.map(t => `<td>${usd(tabulador(l.nombre, t)?.minimo || 0)}</td>`).join('')}</tr>`).join('')}</tbody></table>`);
  }

  /* ---------- eventos ---------- */
  function setPath(path, raw, tipo){
    const ks = path.split('.');
    let o = D;
    for (let i = 0; i < ks.length - 1; i++) o = o[ks[i]];
    const k = ks[ks.length - 1];
    o[k] = tipo === 'txt' ? raw : (tipo === 'bool' ? !!raw : (tipo === 'pct' ? n(raw) / 100 : n(raw)));
    dirty = true;
  }
  dlg.addEventListener('click', async e => {
    const b = e.target.closest('[data-t]');
    if (!b) return;
    const t = b.dataset.t, i = Number(b.dataset.i);
    if (t === 'vista'){ vista = b.dataset.v; pintar(); }
    else if (t === 'guardar') guardar();
    else if (t === 'salir') salir();
    else if (t === 'parada'){ V.paradas.push({lugar: '', items: [], venta: '', peso: ''}); guardarViaje(); pintar(); }
    else if (t === 'quitar'){ V.paradas.splice(i, 1); if (!V.paradas.length) V.paradas.push({lugar: '', items: [], venta: '', peso: ''}); guardarViaje(); pintar(); }
    else if (t === 'qitem'){ V.paradas[i].items.splice(Number(b.dataset.k), 1); guardarViaje(); pintar(); }
    else if (t === 'limpiar'){ if (confirmar('¿Borrar las paradas y empezar un viaje nuevo?')){ V.paradas = [{lugar: '', items: [], venta: '', peso: ''}]; guardarViaje(); pintar(); } }
    else if (t === 'sugerir'){ sugerir = !sugerir; pintar(); }
    else if (t === 'imprimir') imprimirViaje();
    else if (t === 'imprimirtab') imprimirTab();
    else if (t === 'borrar'){ if (confirmar('¿Borrar este renglón?')){ D[b.dataset.l].splice(i, 1); dirty = true; pintar(); } }
    else if (t === 'nuevo'){
      if (b.dataset.l === 'flota') D.flota.push({modelo: 'NUEVO', desc: '', tamano: 'MEDIANO', tipo: 'Camion', capacidad: 8000, ejes: 2, cat_peaje: '2 ejes', n_cauchos: 6, precio_caucho: 310, vida_cauchos: 50000, precio_paila: 115.45, litros_paila: 19, litros_motor: 15, rend: 4.5, mant: 0.15, factor: 1.5});
      else D.choferes.push({nombre: 'NUEVO CHOFER', tipo: 'Liviano', mensual: 0, bonos: 0, parafiscales: 0, prestaciones: 0, por_viaje: 0});
      dirty = true; pintar();
    }
    else if (t === 'borrarlugar'){
      if (!confirmar(`¿Borrar ${D.lugares[i].nombre}? Se quita también de la matriz de km.`)) return;
      D.lugares.splice(i, 1); D.matriz.splice(i, 1); D.matriz.forEach(f => f.splice(i, 1)); dirty = true; pintar();
    }
    else if (t === 'medirtodo'){
      b.disabled = true; b.textContent = 'Midiendo…';
      try { await medirTodo(); dirty = true; toast('Matriz medida de nuevo. Toca Guardar cambios.'); } catch (err){ toast(err.message); }
      pintar();
    }
  });
  dlg.addEventListener('change', e => {
    const el = e.target, f = el.dataset.f;
    if (el.dataset.p){ setPath(el.dataset.p, el.type === 'checkbox' ? el.checked : el.value, el.dataset.tipo); pintar(); return; }
    if (!f) return;
    const i = Number(el.dataset.i);
    if (f === 'vendedor'){ V.vendedor = el.value; }
    else if (f === 'vehiculo'){ V.vehiculo = el.value; const v = veh(V.vehiculo), c = chof(V.chofer); if (v && c && (v.tipo === 'Gandola') !== (c.tipo === 'Pesado')) V.chofer = ''; }
    else if (f === 'chofer') V.chofer = el.value;
    else if (f === 'parada') V.paradas[i].lugar = el.value;
    else if (f === 'venta' || f === 'peso') V.paradas[i][f] = el.value;
    else if (f === 'cant') V.paradas[i].items[Number(el.dataset.k)].cant = el.value;
    else if (f === 'pesoman'){ D.pesos_manual[el.dataset.cod] = n(el.value); dirty = true; }
    else if (f === 'vendtab') vendTab = el.value;
    else if (f === 'filtrotab') filtroTab = el.value;
    guardarViaje(); pintar();
  });
  dlg.addEventListener('input', e => {
    if (e.target.dataset.f === 'filtrotab'){ filtroTab = e.target.value; const pos = e.target.selectionStart; pintar(); const q = dlg.querySelector('[data-f="filtrotab"]'); if (q){ q.focus(); q.setSelectionRange(pos, pos); } }
  });
  dlg.addEventListener('submit', async e => {
    e.preventDefault();
    const fm = e.target;
    if (fm.classList.contains('tab-add')){
      const i = Number(fm.dataset.i);
      let cod = String(fm.cod.value || '').trim().toUpperCase();
      if (!cod) return;
      if (!byRef[cod] && !PREC.has(cod)){
        const q = norm(fm.cod.value), hit = PRODUCTS.find(p => p._name.includes(q));
        if (hit) cod = hit.ref; else { toast('No encontré ese código'); return; }
      }
      const pa = V.paradas[i]; pa.items = pa.items || [];
      const ya = pa.items.find(it => it.cod === cod);
      if (ya) ya.cant = n(ya.cant) + (n(fm.cant.value) || 1); else pa.items.push({cod, cant: n(fm.cant.value) || 1});
      guardarViaje(); pintar();
      const nuevo = dlg.querySelectorAll('.tab-add')[i]; if (nuevo) nuevo.cod.focus();
    } else if (fm.id === 'tabNuevo'){
      const nombre = fm.nombre.value.trim(), c = leerCoords(fm.coords.value);
      if (idx(nombre) >= 0){ toast('Ya existe un lugar con ese nombre'); return; }
      if (!c){ toast('No entendí las coordenadas. Pega algo como 9.0408, -69.7413'); return; }
      const b = fm.querySelector('button'); b.disabled = true; b.textContent = 'Midiendo km por carretera…';
      D.lugares.push({nombre, estado: fm.estado.value.trim(), vendedor: fm.vendedor.value, corredor: fm.corredor.value.trim(), peajes: n(fm.peajes.value), topo: n(fm.topo.value) / 100, lat: c.lat, lon: c.lon});
      D.matriz.push([]);
      try {
        const lejos = await medirLugar(D.lugares.length - 1);
        dirty = true;
        toast(`${nombre} agregado: ${km_(km(P().origen, nombre))} desde ${P().origen}. Toca Guardar cambios.`);
        if (lejos > 2000) toast(`Ojo: el punto quedó a ${fmt0.format(lejos / 1000)} km de la carretera más cercana; revisa las coordenadas.`);
      } catch (err){ D.lugares.pop(); D.matriz.pop(); D.matriz.forEach(f => f.length = D.lugares.length); toast(err.message || 'No se pudo medir'); }
      pintar();
    }
  });

  return {cargar, abrir, salir, activo: () => !!D, _calc: {calcular, tabulador}};
})();

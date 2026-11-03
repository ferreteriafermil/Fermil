"""
Robot Fermil: sincroniza PLADE -> página web.

En cada corrida:
  1. Entra a PLADE con el usuario y la clave guardados como secretos de GitHub.
  2. Lee la tasa del día.
  3. Descarga el inventario en Excel de cada almacén y categoría (venta, mayor y menor).
  4. Quita costos y utilidades, suma el IVA de cada producto (el reporte de PLADE viene sin IVA) y arma dos cosas:
       - salida/catalogo.json (público): nombre, precio de venta con IVA, existencias por
         sucursal y si aplica oferta en divisas (sin decir cuánto).
       - precios al mayor (privado): se suben a Supabase, que solo los entrega con un código válido.
  5. (python robot/sync.py fotos) Busca la foto de los productos nuevos, la achica y la guarda en fotos/.

Secretos (variables de entorno):
  PLADE_URL, PLADE_USUARIO, PLADE_CLAVE, SUPABASE_URL, SUPABASE_SECRET
Opcionales: SALIDA (salida), FOTOS_MINUTOS (150), MINIMO_PRODUCTOS (1000),
            FOTOS_REVISAR_TODO=1 para volver a buscar fotos de productos que antes no tenían
"""
import io
import json
import os
import re
import sys
import time
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).parent))
from parse_plade import construir  # noqa: E402

RAIZ = Path(__file__).resolve().parent.parent
from urllib.parse import urljoin, urlsplit


def solo_sitio(url, defecto):
    """Deja solo https://servidor, aunque el secreto traiga /panel, /rest/v1 u otra ruta pegada."""
    u = urlsplit((url or '').strip() or defecto)
    if not u.scheme:
        u = urlsplit('https://' + (url or '').strip())
    return f'{u.scheme}://{u.netloc}'


BASE = solo_sitio(os.environ.get('PLADE_URL'), 'https://fermil.pladesoftware.com')
USUARIO = os.environ.get('PLADE_USUARIO', '').strip()
CLAVE = os.environ.get('PLADE_CLAVE', '')
SALIDA = RAIZ / os.environ.get('SALIDA', 'salida')
FOTOS = RAIZ / 'fotos'
CACHE_FOTOS = RAIZ / 'fotos_cache.json'
CACHE_IDS = RAIZ / 'ids_plade.json'   # id interno de PLADE de cada código (no cambia)
IDS_MINUTOS = float(os.environ.get('IDS_MINUTOS', '30'))
FOTOS_MINUTOS = float(os.environ.get('FOTOS_MINUTOS', '150'))
MINIMO_PRODUCTOS = int(os.environ.get('MINIMO_PRODUCTOS', '1000'))

# Almacén de PLADE -> sucursal de la página
ALMACENES = [
    (1, 'unda'),        # Inversiones Fermil Centro, C.A. (Fermil La Unda)
    (7, 'quinta'),      # Inversiones La Esquina del Constructor, C.A. (Fermil La Quinta)
    (5, 'colonia'),     # Inversiones Fermil, C.A. (Fermil La Colonia)
    (6, 'biscucuy'),    # Ferreagro Fermil Biscucuy, C.A.
    (11, 'ingco'),      # Ingco Biscucuy
    # Lo que ven los mayoristas: Almacén Principal y Almacén Unda por separado; sus clientes ven la suma.
    # El 15 (Venta Mayorista) no tiene existencias y no se usa.
    (9, 'principal'),   # Almacén Principal
    (17, 'almunda'),    # Almacén Unda
]
ALM_MAYOR = ('principal', 'almunda')
# Categorías de PLADE: se piden por separado para que cada reporte sea rápido
CATEGORIAS_PLADE = [1, 2, 6, 11, 14, 15, 17, 18, 19, 20, 21, 22, 23, 27, 40]

HEADERS = {'User-Agent': 'Mozilla/5.0 (RobotFermil; catalogo web)'}


def log(*a):
    print(time.strftime('%H:%M:%S'), *a, flush=True)


def aviso(nivel, msg):
    """Mensaje que se ve en GitHub sin abrir el registro (nivel: notice, warning o error)."""
    print(f'::{nivel} title=Robot Fermil::{msg}', flush=True)


def falla(msg):
    aviso('error', msg)
    sys.exit(1)


def pistas(r):
    """Datos de una respuesta de PLADE para diagnosticar, sin copiar su contenido."""
    t = (r.text[:20000] if 'text' in r.headers.get('Content-Type', '') or r.content[:1] == b'<' else '').lower()
    claves = [k for k in ('login.php', 'name="pas"', 'sesion', 'sesión', 'duplic', 'incorrect', 'cerrar', 'expir', 'permiso', 'reporte_inventario') if k in t]
    return f'HTTP {r.status_code} · {r.headers.get("Content-Type", "?")} · {len(r.content)} bytes · {r.url.split("?")[0].replace(BASE, "")} · pistas: {", ".join(claves) or "ninguna"}'


def entrar():
    if not USUARIO or not CLAVE:
        falla('Faltan los secretos PLADE_USUARIO y PLADE_CLAVE.')
    s = requests.Session()
    s.headers.update(HEADERS)
    s.get(f'{BASE}/panel/login.php', timeout=60)
    r0 = s.post(f'{BASE}/panel/login.php', data={'pc': '', 'cor': USUARIO, 'pas': CLAVE, 'bti': ''}, timeout=60)
    r = s.get(f'{BASE}/panel/index.php?op=inicio', timeout=60)
    aviso('notice', f'Entrada a PLADE · login: {pistas(r0)} · inicio: {pistas(r)}')
    dentro = ('op=reporte_inventario' in r.text or 'Buscar sub' in r.text) and 'name="pas"' not in r.text.lower()
    if not dentro:
        falla('No se pudo entrar a PLADE: revisa PLADE_USUARIO y PLADE_CLAVE, o cierra tu sesión de PLADE en el navegador y vuelve a correr.')
    log('Sesión iniciada en PLADE')
    return s, r.text


NUM = r'(\d{1,3}(?:\.\d{3})+,\d+|\d+,\d+|\d+\.\d+|\d+)'
PATRONES_TASA = [
    r'1\s*(?:\$|US\$|USD|&#36;|&dollar;)\s*(?:<[^>]+>\s*)*=\s*(?:<[^>]+>\s*)*(?:Bs\.?S?\.?\s*)?' + NUM,
    r'(?:\$|USD)\s*1\s*=\s*(?:Bs\.?\s*)?' + NUM,
    r'tasa[\w\s.:]{0,40}?(?:<[^>]+>\s*)*(?:Bs\.?\s*)?' + NUM,
    r'(?:tasa|cambio|dolar|d[oó]lar)\w*["\']?\s*[:=]\s*["\']?' + NUM,
]


def a_numero(t):
    if ',' in t:
        t = t.replace('.', '').replace(',', '.')
    try:
        return float(t)
    except ValueError:
        return None


def leer_tasa(html):
    html = html.replace('&nbsp;', ' ').replace('\xa0', ' ')
    for pat in PATRONES_TASA:
        for m in re.finditer(pat, html, re.I):
            v = a_numero(m.group(1))
            if v and 50 < v < 1_000_000:
                return v
    return None


def pistas_tasa(html):
    """Fragmentos cortos alrededor de 'tasa' o '$ =' para ver cómo la muestra PLADE."""
    trozos = []
    for m in re.finditer(r'tasa|\$\s*=|=\s*bs', html, re.I):
        t = re.sub(r'\s+', ' ', html[max(0, m.start() - 70): m.end() + 90])
        t = re.sub(r'[\w.+-]+@[\w-]+\.[\w.]+', '[correo]', t)
        trozos.append(t)
        if len(trozos) >= 6:
            break
    return ' ¦ '.join(trozos) or 'no aparece la palabra tasa'


def buscar_tasa(s, inicio):
    tasa = leer_tasa(inicio)
    if tasa:
        return tasa
    for ruta in ('/panel/index.php', '/panel/index.php?op=tasa_cambio', '/panel/index.php?op=monedas'):
        try:
            r = s.get(BASE + ruta, timeout=60)
            tasa = leer_tasa(r.text)
            if tasa:
                aviso('notice', f'Tasa encontrada en {ruta}')
                return tasa
        except requests.RequestException:
            pass
    aviso('warning', 'Tasa: ' + pistas_tasa(inicio)[:900])
    return None


def url_excel(almacen, categoria):
    return (f'{BASE}/reportes/spreadsheets/reporte_inventario.php?estatus=1&id_almacen={almacen}'
            f'&cate={categoria}&id_tipo_rotacion=&consignacion=&id_clasificacion_inventario=&linea=&costo='
            f'&mostrar_exi=on&solo_exi=on&orden=V.cod_inv&multi_moneda=1&solo_sin_exi=&letra_desde=&letra_hasta='
            f'&precio_utilidad[]=venta&precio_utilidad[]=1&precio_utilidad[]=2')


def descargar_reportes(s, carpeta):
    carpeta.mkdir(parents=True, exist_ok=True)
    archivos = []
    fallos_seguidos = 0
    primer_fallo = None
    for alm, suc in ALMACENES:
        for cat in CATEGORIAS_PLADE:
            if fallos_seguidos >= 3 and not archivos:
                falla(f'PLADE no entrega los reportes en Excel. Primera respuesta: {primer_fallo}')
            destino = carpeta / f'inv_{alm}_{cat}.xlsx'
            bajado = False
            for intento in range(3):
                try:
                    t0 = time.time()
                    r = s.get(url_excel(alm, cat), timeout=900)
                    if r.status_code == 200 and r.content[:2] == b'PK':
                        destino.write_bytes(r.content)
                        archivos.append((str(destino), suc))
                        log(f'almacén {alm} categoría {cat}: {len(r.content)//1024} KB en {time.time()-t0:.0f}s')
                        bajado = True
                        break
                    if primer_fallo is None:
                        primer_fallo = f'almacén {alm} categoría {cat}: {pistas(r)} en {time.time()-t0:.0f}s'
                        aviso('warning', primer_fallo)
                    log(f'almacén {alm} categoría {cat}: respuesta inesperada ({r.status_code}); intento {intento + 1}')
                except requests.RequestException as e:
                    if primer_fallo is None:
                        primer_fallo = f'almacén {alm} categoría {cat}: {type(e).__name__}'
                        aviso('warning', primer_fallo)
                    log(f'almacén {alm} categoría {cat}: error {e}; intento {intento + 1}')
                time.sleep(5)
            fallos_seguidos = 0 if bajado else fallos_seguidos + 1
    aviso('notice', f'Reportes de PLADE descargados: {len(archivos)} de {len(ALMACENES) * len(CATEGORIAS_PLADE)}')
    return archivos


def url_reporte(almacen, cate):
    return (f'{BASE}/panel/index.php?op=reporte_inventario&id_almacen%5B%5D={almacen}&cate={cate}&orden=V.cod_inv'
            f'&precio_utilidad%5B%5D=venta&estatus=1&mostrar_exi=on&solo_exi=on&bt_filtrar=1')


def leer_ids(html):
    """Cada producto del reporte tiene una etiqueta con la clase bt_resumen_producto, su id interno
    y el código como texto. Se aceptan los atributos en cualquier orden y con o sin comillas."""
    ids = {}
    for m in re.finditer(r'<(?:a|span|button|td|div)\b([^>]*bt_resumen_producto[^>]*)>\s*(?:<[^>]+>\s*)*([^<]+?)\s*<', html, re.I):
        attrs, texto = m.group(1), m.group(2)
        num = re.search(r'''(?:\bid|data-id|data-idc|idc)\s*=\s*['"]?(\d+)''', attrs, re.I)
        if num and texto.strip():
            ids.setdefault(texto.strip(), num.group(1))
    return ids


def ids_por_codigo(s, almacen, cate):
    """El reporte en pantalla trae el id interno de cada producto (hace falta para pedir su foto).
    Se pide por categoría, igual que los Excel, porque el reporte completo tarda demasiado."""
    return leer_ids(s.get(url_reporte(almacen, cate), timeout=300).text)


def tapar(t):
    """Quita montos (números con coma o punto decimal) antes de mostrar un pedazo de HTML en GitHub."""
    return re.sub(r'\d+(?:[.,]\d+)+', '#', re.sub(r'\s+', ' ', t))


def diagnostico_fotos():
    """Prueba corta (1-3 minutos) de cómo trae PLADE los ids y las fotos, para no esperar una corrida completa."""
    s, _ = entrar()
    for alm, cate in ((1, 6), (1, 1)):
        t0 = time.time()
        try:
            r = s.get(url_reporte(alm, cate), timeout=300)
        except requests.RequestException as e:
            aviso('warning', f'Reporte almacén {alm} categoría {cate}: {type(e).__name__} a los {time.time() - t0:.0f}s')
            continue
        h = r.text
        ids = leer_ids(h)
        i = h.find('bt_resumen_producto')
        etiqueta = tapar(h[max(0, h.rfind('<', 0, i)):h.find('<', h.find('>', i) + 1) + 1]) if i >= 0 else '-'
        m = re.search(r'>\s*([A-Z]{3,5}\d{3,5})\s*<', h)
        cerca = tapar(h[max(0, m.start() - 260):m.end() + 20]) if m else '-'
        aviso('notice', f'Reporte almacén {alm} categoría {cate}: {pistas(r)} · {time.time() - t0:.0f}s · '
                        f'bt_resumen_producto: {h.count("bt_resumen_producto")} · ids leídos: {len(ids)} · '
                        f'ejemplo: {list(ids.items())[:3]} · etiqueta: {etiqueta[:300]}')
        aviso('notice', f'Junto al primer código: {cerca[:400]}')
        scripts = sorted(set(re.findall(r'''(?:url|load|ajax|post|get)\s*[:(]\s*['"]([^'"]{4,80}\.php[^'"]{0,60})''', h, re.I)))[:12]
        aviso('notice', f'Direcciones que usa la página del reporte: {scripts}')
        if ids:
            cod, idc = next(iter(ids.items()))
            try:
                rr = s.post(f'{BASE}/panel/ajax_php.php', data={'modulo': 'productos', 'tipo': 'buscarProducto', 'por_id': 1,
                                                               'idc': idc, 'solo_modal_resumen': 1}, timeout=60)
                try:
                    j = rr.json()
                    prod = j.get('producto') or {}
                    aviso('notice', f'Foto de {cod}: claves {sorted(j)[:15]} · producto {sorted(prod)[:25]} · img_inv: {"sí" if prod.get("img_inv") else "no"}')
                except ValueError:
                    aviso('warning', f'Foto de {cod}: no llegó JSON · {pistas(rr)} · {tapar(rr.text[:200])}')
            except requests.RequestException as e:
                aviso('warning', f'Foto de {cod}: {type(e).__name__}')
            break


def minutos_para_fotos():
    """De día cada corrida dedica FOTOS_MINUTOS a fotos. De noche (7 p. m. a 7 a. m. en Venezuela) no hay corridas
    programadas, así que se aprovecha hasta las 6:40 a. m. (máximo 4 horas) para no atrasar los precios de las 7."""
    ahora = time.gmtime()
    hora = ahora.tm_hour + ahora.tm_min / 60
    if hora >= 23 or hora < 10.5:
        hasta = (10 + 40 / 60) - hora + (24 if hora >= 23 else 0)
        return max(FOTOS_MINUTOS, min(240, hasta * 60))
    return FOTOS_MINUTOS


def nombre_almacen(path):
    """Valor de la columna ALMACÉN de un Excel de PLADE."""
    import openpyxl
    ws = openpyxl.load_workbook(path, read_only=True, data_only=True).worksheets[0]
    col = None
    for row in ws.iter_rows(values_only=True):
        if col is None:
            hdr = [str(c or '').upper() for c in (row or [])]
            col = next((i for i, c in enumerate(hdr) if 'ALMAC' in c), None)
            continue
        if row and len(row) > col and row[col]:
            return ' '.join(str(row[col]).split())
    return ''


def diagnostico_almacenes():
    """Prueba corta: lista los almacenes que tiene PLADE y cuántos productos con existencia trae cada uno."""
    s, inicio = entrar()
    vistos = {}
    for html in (inicio, s.get(f'{BASE}/panel/index.php?op=reporte_inventario', timeout=120).text):
        for m in re.finditer(r'<select[^>]*id_almacen[^>]*>(.*?)</select>', html, re.S | re.I):
            for o in re.finditer(r'<option[^>]*value=["\']?(\d+)["\']?[^>]*>([^<]*)<', m.group(1), re.I):
                vistos[o.group(1)] = ' '.join(o.group(2).split())
    aviso('notice', 'Almacenes en PLADE: ' + (' · '.join(f'{k} = {v}' for k, v in sorted(vistos.items(), key=lambda x: int(x[0]))) or 'no se encontró la lista'))
    from parse_plade import leer_excel
    for alm in (9, 17):
        total = con = 0
        nombre = ''
        for cate in CATEGORIAS_PLADE:
            try:
                r = s.get(url_excel(alm, cate), timeout=600)
                if r.status_code != 200 or r.content[:2] != b'PK':
                    continue
                f = Path(f'/tmp/alm{alm}_{cate}.xlsx'); f.write_bytes(r.content)
                filas = leer_excel(f)
                total += len(filas); con += sum(1 for x in filas if x['disp'] > 0)
                if not nombre:
                    nombre = nombre_almacen(f)
            except Exception as e:
                aviso('warning', f'Almacén {alm} categoría {cate}: {type(e).__name__}')
        aviso('notice', f'Almacén {alm} ({nombre or "?"}): {total} productos en los reportes, {con} con existencia')


def actualizar_fotos(s, productos):
    from PIL import Image
    FOTOS.mkdir(parents=True, exist_ok=True)
    cache = json.loads(CACHE_FOTOS.read_text()) if CACHE_FOTOS.exists() else {}
    if os.environ.get('FOTOS_REVISAR_TODO') == '1':  # vuelve a buscar los que antes no tenían foto
        cache = {k: v for k, v in cache.items() if v}
    pendientes = [p['c'] for p in productos if p['c'] not in cache]
    log(f'Fotos: {len(cache)} revisadas antes, {len(pendientes)} por revisar')
    if not pendientes:
        return cache
    guardado = json.loads(CACHE_IDS.read_text()) if CACHE_IDS.exists() else {}
    ids, leidos = guardado.get('ids', {}), set(guardado.get('leidos', []))
    reportes = [(alm, cate) for alm, _ in ALMACENES for cate in CATEGORIAS_PLADE]
    t_ids = time.time()
    n = 0
    for alm, cate in reportes:
        if all(c in ids for c in pendientes) or time.time() - t_ids > IDS_MINUTOS * 60:
            break
        if f'{alm}-{cate}' in leidos:
            continue
        try:
            t0 = time.time()
            nuevos = ids_por_codigo(s, alm, cate)
            ids.update({k: v for k, v in nuevos.items() if k not in ids})
            leidos.add(f'{alm}-{cate}')
            n += 1
            log(f'ids almacén {alm} categoría {cate}: {len(nuevos)} en {time.time() - t0:.0f}s')
        except requests.RequestException as e:
            log(f'ids almacén {alm} categoría {cate}: {e}')
        CACHE_IDS.write_text(json.dumps({'ids': ids, 'leidos': sorted(leidos)}, sort_keys=True))
    vuelta_completa = len(leidos) >= len(reportes)
    completo = vuelta_completa or all(c in ids for c in pendientes)
    if vuelta_completa:  # la próxima vez que aparezcan productos nuevos se vuelve a revisar todo
        leidos = set()
    CACHE_IDS.write_text(json.dumps({'ids': ids, 'leidos': sorted(leidos)}, sort_keys=True))
    aviso('notice', f'Fotos: {len(ids)} ids de productos conocidos · {n} reportes leídos en {time.time() - t_ids:.0f}s'
                    + ('' if completo else f' (faltan {len(reportes) - len(leidos)} reportes; siguen en la próxima corrida)'))
    if completo:
        for cod in pendientes:
            if cod not in ids:
                cache[cod] = ''  # no aparece en los reportes de las tiendas: sin foto por ahora
    limite = time.time() + minutos_para_fotos() * 60
    hechas = errores = 0
    primer_error = ''
    for cod in pendientes:
        if time.time() > limite:
            log(f'Se acabó el tiempo para fotos en esta corrida; siguen en la próxima ({hechas} hechas)')
            break
        if cod not in ids:
            continue
        try:
            r = s.post(f'{BASE}/panel/ajax_php.php', data={'modulo': 'productos', 'tipo': 'buscarProducto', 'por_id': 1,
                                                          'idc': ids[cod], 'solo_modal_resumen': 1}, timeout=60)
            url = (r.json().get('producto') or {}).get('img_inv')
            if not url:
                cache[cod] = ''
                continue
            img = s.get(urljoin(f'{BASE}/panel/', url), timeout=60)
            img.raise_for_status()
            im = Image.open(io.BytesIO(img.content)).convert('RGB')
            im.thumbnail((360, 360))
            nombre = re.sub(r'[^A-Za-z0-9_-]', '_', cod) + '.jpg'
            im.save(FOTOS / nombre, 'JPEG', quality=78, optimize=True)
            cache[cod] = 'fotos/' + nombre
            hechas += 1
        except Exception as e:  # una foto que falla no detiene el robot; se reintenta en la próxima corrida
            errores += 1
            primer_error = primer_error or f'{cod}: {type(e).__name__}: {tapar(str(e))[:160]}'
            log(f'foto {cod}: {e}')
        if hechas and hechas % 200 == 0:
            CACHE_FOTOS.write_text(json.dumps(cache, sort_keys=True))
            log(f'{hechas} fotos nuevas hasta ahora')
    CACHE_FOTOS.write_text(json.dumps(cache, sort_keys=True))
    log(f'Fotos: {hechas} nuevas en esta corrida, {sum(1 for v in cache.values() if v)} con foto en total')
    faltan = sum(1 for p in productos if p['c'] not in cache)
    aviso('notice', f'Fotos: {hechas} nuevas en esta corrida · {sum(1 for v in cache.values() if v)} productos con foto · '
                    f'{sum(1 for v in cache.values() if v == "")} sin foto en PLADE · faltan por revisar {faltan}'
                    + (' · FOTOS COMPLETAS' if not faltan else ''))
    if errores:
        aviso('warning', f'Fotos: {errores} no se pudieron bajar (se reintentan en la próxima corrida). Primera: {primer_error}')
    return cache


def _sb_headers(key, extra=None):
    h = {'apikey': key, 'Content-Type': 'application/json'}
    if not key.startswith('sb_'):
        h['Authorization'] = f'Bearer {key}'  # clave antigua (service_role)
    h.update(extra or {})
    return h


def precios_guardados(url, key):
    """Lo que tiene Supabase ahora (para saber qué precios cambiaron). None si falta la actualización SQL."""
    out, desde = {}, 0
    while True:
        r = requests.get(f'{url}/rest/v1/precios_mayor?select=cod,mayor,mayor_anterior,cambio&order=cod&limit=1000&offset={desde}',
                         headers=_sb_headers(key), timeout=120)
        if r.status_code >= 300:
            return None
        lote = r.json()
        out.update({x['cod']: x for x in lote})
        if len(lote) < 1000:
            return out
        desde += 1000


def subir_supabase(filas):
    """Sube precios y existencias de los mayoristas. Devuelve los precios que cambiaron: [(cod, antes, ahora)]."""
    cambios = []
    url = solo_sitio(os.environ.get('SUPABASE_URL'), '') if os.environ.get('SUPABASE_URL', '').strip() else ''
    key = os.environ.get('SUPABASE_SECRET', '').strip()
    if not url or not key:
        log('Supabase no configurado: no se suben los precios al mayor')
        return cambios
    antes = precios_guardados(url, key)
    if antes is None:
        aviso('warning', 'Supabase todavía no tiene las columnas nuevas (falta correr supabase-actualizacion-1.sql): '
                         'se suben precios y existencia total, sin desglose por almacén ni aviso de cambios.')
        filas = [{k: f[k] for k in ('cod', 'mayor', 'stock_mayorista')} for f in filas]
    else:
        ahora = time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())
        suben = bajan = 0
        for f in filas:
            v = antes.get(f['cod'])
            if v and v.get('mayor') is not None and abs(float(v['mayor']) - f['mayor']) >= 0.005:
                f['mayor_anterior'], f['cambio'] = float(v['mayor']), ahora
                cambios.append((f['cod'], float(v['mayor']), f['mayor']))
                if f['mayor'] > float(v['mayor']): suben += 1
                else: bajan += 1
            else:
                f['mayor_anterior'], f['cambio'] = (v or {}).get('mayor_anterior'), (v or {}).get('cambio')
        aviso('notice', f'Precios al mayor: {suben} subieron y {bajan} bajaron desde la corrida anterior')
    h = _sb_headers(key, {'Prefer': 'resolution=merge-duplicates,return=minimal'})
    for i in range(0, len(filas), 1000):
        r = requests.post(f'{url}/rest/v1/precios_mayor?on_conflict=cod', headers=h, data=json.dumps(filas[i:i+1000]), timeout=120)
        if r.status_code >= 300:
            # La página pública se publica igual; solo los mayoristas se quedan sin precio nuevo
            print(f'::error title=Supabase::No se pudieron subir los precios al mayor ({r.status_code}): {r.text[:300]}', flush=True)
            return []
    log(f'Supabase: {len(filas)} precios al mayor actualizados')
    return cambios


def avisar_por_correo(cambios, productos):
    """Correo a cada mayorista cuando sube algún precio al mayor.
    Secretos: CORREO_USUARIO y CORREO_CLAVE (cuenta de Gmail que envía, con clave de aplicación)
    y CORREOS_MAYORISTAS: 'Nombre <correo>, Nombre <correo>'."""
    import smtplib
    from email.message import EmailMessage
    from email.utils import getaddresses
    suben = [c for c in cambios if c[2] > c[1]]
    if not suben:
        return
    usuario, clave = os.environ.get('CORREO_USUARIO', '').strip(), os.environ.get('CORREO_CLAVE', '').replace(' ', '').strip()
    destinos = [(n, c) for n, c in getaddresses([os.environ.get('CORREOS_MAYORISTAS', '')]) if '@' in c]
    if not usuario or not clave or not destinos:
        aviso('notice', f'{len(suben)} precios al mayor subieron; el aviso por correo no está configurado todavía')
        return
    nombre = {p['c']: p['n'] for p in productos}
    orden = sorted(cambios, key=lambda c: -(c[2] / c[1] if c[1] else 0))
    fmt = lambda v: f'${v:,.2f}'.replace(',', 'X').replace('.', ',').replace('X', '.')
    filas = ''.join(
        f'<tr><td style="padding:6px 8px;border-top:1px solid #e3e8e3">{nombre.get(cod, cod)}<br><span style="color:#6b7a6e;font-size:12px">{cod}</span></td>'
        f'<td style="padding:6px 8px;border-top:1px solid #e3e8e3;text-align:right">{fmt(a)}</td>'
        f'<td style="padding:6px 8px;border-top:1px solid #e3e8e3;text-align:right"><b>{fmt(n)}</b></td>'
        f'<td style="padding:6px 8px;border-top:1px solid #e3e8e3;text-align:right;color:{"#c62828" if n > a else "#006300"};font-weight:bold">'
        f'{"▲ +" if n > a else "▼ "}{f"{(n / a - 1) * 100:.1f}".replace(".", ",")} %</td></tr>'
        for cod, a, n in orden[:300])
    bajan = len(cambios) - len(suben)
    extra = f' y {bajan} {"bajó" if bajan == 1 else "bajaron"}' if bajan else ''
    html = (f'<div style="font-family:Arial,sans-serif;color:#17241c;max-width:640px">'
            f'<h2 style="color:#c62828;margin:0 0 6px">Actualización de precios al mayor</h2>'
            f'<p style="margin:0 0 12px">{len(suben)} {"producto subió" if len(suben) == 1 else "productos subieron"} de precio'
            f'{extra}. Son precios al mayor sin IVA; '
            f'tus descuentos se aplican encima. Revisa antes de cotizar.</p>'
            f'<table style="border-collapse:collapse;width:100%;font-size:14px"><tr style="background:#eef3ee;color:#5a6b60;font-size:12px">'
            f'<th style="padding:6px 8px;text-align:left">Producto</th><th style="padding:6px 8px;text-align:right">Antes</th>'
            f'<th style="padding:6px 8px;text-align:right">Ahora</th><th style="padding:6px 8px;text-align:right">Cambio</th></tr>{filas}</table>'
            f'{"<p>Y otros más: míralos en tu panel.</p>" if len(orden) > 300 else ""}'
            f'<p style="margin-top:16px"><a href="https://ferreteria-fermil.pages.dev" style="background:#006300;color:#fff;padding:10px 16px;border-radius:8px;text-decoration:none">Abrir el catálogo</a></p>'
            f'<p style="color:#6b7a6e;font-size:12px">Ferretería Fermil · aviso automático del robot de precios</p></div>')
    enviados = 0
    try:
        with smtplib.SMTP_SSL('smtp.gmail.com', 465, timeout=60) as smtp:
            smtp.login(usuario, clave)
            for n, c in destinos:
                m = EmailMessage()
                m['Subject'] = f'Fermil · Actualización de precios al mayor ({len(suben)} {"subió" if len(suben) == 1 else "subieron"})'
                m['From'] = f'Ferretería Fermil <{usuario}>'
                m['To'] = f'{n} <{c}>' if n else c
                m.set_content(f'{len(suben)} productos subieron de precio al mayor. Míralos en tu panel: https://ferreteria-fermil.pages.dev')
                m.add_alternative(html, subtype='html')
                smtp.send_message(m)
                enviados += 1
        aviso('notice', f'Aviso de precios enviado por correo a {enviados} mayoristas')
    except Exception as e:
        aviso('warning', f'No se pudo enviar el aviso por correo: {type(e).__name__}')


def main():
    s, inicio = entrar()
    tasa = buscar_tasa(s, inicio)
    log(f'Tasa del día: {tasa}')
    if not tasa:
        falla('No se encontró la tasa del día en PLADE: no se publica.')
    archivos = descargar_reportes(s, RAIZ / 'reportes')
    if not archivos:
        falla('No se descargó ningún reporte de PLADE.')
    data = construir(archivos, tasa=tasa)
    productos = data['productos']
    if len(productos) < MINIMO_PRODUCTOS:
        falla(f'Solo llegaron {len(productos)} productos: no se publica para no dañar la página.')
    privados = []
    for p in productos:
        if not p.get('y'):
            continue
        pr, un = p['e'].get('principal', 0), p['e'].get('almunda', 0)
        privados.append({'cod': p['c'], 'mayor': p['y'], 'stock_mayorista': round(pr + un, 2),
                         'stock_principal': pr, 'stock_unda': un})
    publico = []
    for p in productos:
        q = {k: v for k, v in p.items() if k != 'y'}
        q['e'] = {k: v for k, v in p['e'].items() if k not in ALM_MAYOR}  # lo de los mayoristas no va en la página pública
        publico.append(q)
    SALIDA.mkdir(parents=True, exist_ok=True)
    (SALIDA / 'catalogo.json').write_text(json.dumps({**data, 'productos': publico}, ensure_ascii=False, separators=(',', ':')), encoding='utf-8')
    log(f'Catálogo público: {len(publico)} productos · actualizado {data["generado"]}')
    aviso('notice', f'Catálogo listo: {len(publico)} productos · tasa {tasa} · {data["generado"]}')
    cambios = subir_supabase(privados)
    avisar_por_correo(cambios, productos)


def solo_fotos():
    """Segunda parte de la corrida: busca fotos nuevas con el catálogo que ya se publicó."""
    productos = json.loads((SALIDA / 'catalogo.json').read_text(encoding='utf-8'))['productos']
    antes = json.loads(CACHE_FOTOS.read_text()) if CACHE_FOTOS.exists() else {}
    s, _ = entrar()
    cache = actualizar_fotos(s, productos)
    nuevas = sum(1 for k, v in cache.items() if v and not antes.get(k))
    if nuevas:
        (SALIDA / 'fotos_nuevas').write_text(str(nuevas))


if __name__ == '__main__':
    if 'almacenes' in sys.argv[1:]:
        diagnostico_almacenes()
    elif 'diagnostico' in sys.argv[1:]:
        diagnostico_fotos()
    elif 'fotos' in sys.argv[1:]:
        try:
            solo_fotos()
        except SystemExit:
            raise
        except Exception as e:  # que se vea en GitHub qué pasó, sin abrir el registro
            aviso('warning', f'Fotos: se detuvo por {type(e).__name__}: {tapar(str(e))[:300]}')
            raise
    else:
        main()

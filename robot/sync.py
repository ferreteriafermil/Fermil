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
from urllib.parse import urlsplit


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
FOTOS_MINUTOS = float(os.environ.get('FOTOS_MINUTOS', '150'))
MINIMO_PRODUCTOS = int(os.environ.get('MINIMO_PRODUCTOS', '1000'))

# Almacén de PLADE -> sucursal de la página
ALMACENES = [
    (1, 'unda'),        # Inversiones Fermil Centro, C.A. (Fermil La Unda). El almacén "Unda 17" es depósito: no se usa.
    (7, 'quinta'),      # Inversiones La Esquina del Constructor, C.A. (Fermil La Quinta)
    (5, 'colonia'),     # Inversiones Fermil, C.A. (Fermil La Colonia)
    (6, 'biscucuy'),    # Ferreagro Fermil Biscucuy, C.A. (no INGCO Biscucuy)
    (15, 'mayorista'),  # Venta Mayorista
]
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


def ids_por_codigo(s, almacen):
    """El reporte en pantalla trae el id interno de cada producto (hace falta para pedir su foto)."""
    url = (f'{BASE}/panel/index.php?op=reporte_inventario&id_almacen%5B%5D={almacen}&orden=V.cod_inv'
           f'&precio_utilidad%5B%5D=venta&estatus=1&mostrar_exi=on&solo_exi=on&bt_filtrar=1')
    html = s.get(url, timeout=900).text
    return {m.group(2).strip(): m.group(1)
            for m in re.finditer(r"id=['\"](\d+)['\"][^>]*class=['\"]bt_resumen_producto['\"][^>]*>([^<]+)<", html)}


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
    ids = {}
    for alm, suc in ALMACENES:
        if suc == 'mayorista' or all(c in ids for c in pendientes):
            continue
        try:
            t0 = time.time()
            ids.update({k: v for k, v in ids_por_codigo(s, alm).items() if k not in ids})
            log(f'ids de productos tras almacén {alm}: {len(ids)}')
            aviso('notice', f'Fotos: ids del almacén {alm} leídos en {time.time() - t0:.0f}s ({len(ids)} en total)')
        except requests.RequestException as e:
            log(f'no se pudo leer los ids del almacén {alm}: {e}')
    for cod in pendientes:
        if cod not in ids:
            cache[cod] = ''  # no aparece en los reportes de las tiendas: sin foto por ahora
    limite = time.time() + FOTOS_MINUTOS * 60
    hechas = 0
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
            img = requests.get(url, timeout=60, headers=HEADERS)
            im = Image.open(io.BytesIO(img.content)).convert('RGB')
            im.thumbnail((360, 360))
            nombre = re.sub(r'[^A-Za-z0-9_-]', '_', cod) + '.jpg'
            im.save(FOTOS / nombre, 'JPEG', quality=78, optimize=True)
            cache[cod] = 'fotos/' + nombre
            hechas += 1
        except Exception as e:  # una foto que falla no detiene el robot; se reintenta en la próxima corrida
            log(f'foto {cod}: {e}')
        if hechas and hechas % 200 == 0:
            CACHE_FOTOS.write_text(json.dumps(cache, sort_keys=True))
            log(f'{hechas} fotos nuevas hasta ahora')
    CACHE_FOTOS.write_text(json.dumps(cache, sort_keys=True))
    log(f'Fotos: {hechas} nuevas en esta corrida, {sum(1 for v in cache.values() if v)} con foto en total')
    aviso('notice', f'Fotos: {hechas} nuevas en esta corrida, {sum(1 for v in cache.values() if v)} productos con foto en total')
    return cache


def subir_supabase(filas):
    url = solo_sitio(os.environ.get('SUPABASE_URL'), '') if os.environ.get('SUPABASE_URL', '').strip() else ''
    key = os.environ.get('SUPABASE_SECRET', '').strip()
    if not url or not key:
        log('Supabase no configurado: no se suben los precios al mayor')
        return
    h = {'apikey': key, 'Content-Type': 'application/json', 'Prefer': 'resolution=merge-duplicates,return=minimal'}
    if not key.startswith('sb_'):
        h['Authorization'] = f'Bearer {key}'  # clave antigua (service_role)
    for i in range(0, len(filas), 1000):
        r = requests.post(f'{url}/rest/v1/precios_mayor?on_conflict=cod', headers=h, data=json.dumps(filas[i:i+1000]), timeout=120)
        if r.status_code >= 300:
            # La página pública se publica igual; solo los mayoristas se quedan sin precio nuevo
            print(f'::error title=Supabase::No se pudieron subir los precios al mayor ({r.status_code}): {r.text[:300]}', flush=True)
            return
    log(f'Supabase: {len(filas)} precios al mayor actualizados')


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
    privados = [{'cod': p['c'], 'mayor': p['y'], 'stock_mayorista': p['e'].get('mayorista')}
                for p in productos if p.get('y')]
    publico = []
    for p in productos:
        q = {k: v for k, v in p.items() if k != 'y'}
        q['e'] = {k: v for k, v in p['e'].items() if k != 'mayorista'}
        publico.append(q)
    SALIDA.mkdir(parents=True, exist_ok=True)
    (SALIDA / 'catalogo.json').write_text(json.dumps({**data, 'productos': publico}, ensure_ascii=False, separators=(',', ':')), encoding='utf-8')
    log(f'Catálogo público: {len(publico)} productos · actualizado {data["generado"]}')
    aviso('notice', f'Catálogo listo: {len(publico)} productos · tasa {tasa} · {data["generado"]}')
    subir_supabase(privados)


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
    solo_fotos() if 'fotos' in sys.argv[1:] else main()

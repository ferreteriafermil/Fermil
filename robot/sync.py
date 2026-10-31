"""
Robot Fermil: sincroniza PLADE -> página web.

En cada corrida:
  1. Entra a PLADE con el usuario y la clave guardados como secretos de GitHub.
  2. Lee la tasa del día.
  3. Descarga el inventario en Excel de cada almacén y categoría (venta, mayor y menor).
  4. Quita costos y utilidades y arma dos cosas:
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


def entrar():
    if not USUARIO or not CLAVE:
        sys.exit('Faltan los secretos PLADE_USUARIO y PLADE_CLAVE.')
    s = requests.Session()
    s.headers.update(HEADERS)
    s.get(f'{BASE}/panel/login.php', timeout=60)
    s.post(f'{BASE}/panel/login.php', data={'pc': '', 'cor': USUARIO, 'pas': CLAVE, 'bti': ''}, timeout=60)
    r = s.get(f'{BASE}/panel/index.php?op=inicio', timeout=60)
    if 'op=reporte_inventario' not in r.text and 'Buscar sub' not in r.text:
        sys.exit('No se pudo entrar a PLADE: revisa los secretos PLADE_USUARIO y PLADE_CLAVE.')
    log('Sesión iniciada en PLADE')
    return s, r.text


def leer_tasa(html):
    m = re.search(r'1\$\s*=\s*(?:<[^>]+>\s*)*([\d.]+,\d+|[\d,]+\.\d+|\d+)', html)
    if not m:
        return None
    t = m.group(1)
    t = t.replace('.', '').replace(',', '.') if ',' in t else t
    try:
        return float(t)
    except ValueError:
        return None


def url_excel(almacen, categoria):
    return (f'{BASE}/reportes/spreadsheets/reporte_inventario.php?estatus=1&id_almacen={almacen}'
            f'&cate={categoria}&id_tipo_rotacion=&consignacion=&id_clasificacion_inventario=&linea=&costo='
            f'&mostrar_exi=on&solo_exi=on&orden=V.cod_inv&multi_moneda=1&solo_sin_exi=&letra_desde=&letra_hasta='
            f'&precio_utilidad[]=venta&precio_utilidad[]=1&precio_utilidad[]=2')


def descargar_reportes(s, carpeta):
    carpeta.mkdir(parents=True, exist_ok=True)
    archivos = []
    for alm, suc in ALMACENES:
        for cat in CATEGORIAS_PLADE:
            destino = carpeta / f'inv_{alm}_{cat}.xlsx'
            for intento in range(3):
                try:
                    t0 = time.time()
                    r = s.get(url_excel(alm, cat), timeout=900)
                    if r.status_code == 200 and r.content[:2] == b'PK':
                        destino.write_bytes(r.content)
                        archivos.append((str(destino), suc))
                        log(f'almacén {alm} categoría {cat}: {len(r.content)//1024} KB en {time.time()-t0:.0f}s')
                        break
                    log(f'almacén {alm} categoría {cat}: respuesta inesperada ({r.status_code}); intento {intento + 1}')
                except requests.RequestException as e:
                    log(f'almacén {alm} categoría {cat}: error {e}; intento {intento + 1}')
                time.sleep(5)
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
            ids.update({k: v for k, v in ids_por_codigo(s, alm).items() if k not in ids})
            log(f'ids de productos tras almacén {alm}: {len(ids)}')
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
    tasa = leer_tasa(inicio)
    log(f'Tasa del día: {tasa}')
    archivos = descargar_reportes(s, RAIZ / 'reportes')
    if not archivos:
        sys.exit('No se descargó ningún reporte de PLADE.')
    data = construir(archivos, tasa=tasa)
    productos = data['productos']
    if len(productos) < MINIMO_PRODUCTOS:
        sys.exit(f'Solo llegaron {len(productos)} productos: no se publica para no dañar la página.')
    if not tasa:
        sys.exit('No se encontró la tasa del día en PLADE: no se publica.')
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

"""
Convierte los reportes de inventario de PLADE (Excel) en el catálogo que usa la app.

- Lee un Excel por almacén (reporte_inventario con precios VENTA, MAYOR y MENOR).
- NUNCA copia costos ni utilidades: solo nombre, categoría, marca, precios de venta y mayor,
  disponibilidad por sucursal y una marca de "aplica oferta en divisas" (sin el precio menor).
- Uso: python parse_plade.py salida.json archivo1.xlsx:unda archivo2.xlsx:quinta ...
"""
import json
import sys
import unicodedata
from decimal import Decimal, ROUND_CEILING
from datetime import datetime, timedelta, timezone

VET = timezone(timedelta(hours=-4))  # hora de Venezuela


def ahora_vet():
    t = datetime.now(VET)
    h = t.hour % 12 or 12
    return f"{t:%d/%m/%Y} {h}:{t:%M} {'a. m.' if t.hour < 12 else 'p. m.'}"

import openpyxl

# Categorías de PLADE -> (clave, nombre que ve el cliente)
CATEGORIAS = {
    'FERRETERIA': ('ferreteria', 'Ferretería'),
    'PINTURA': ('pintura', 'Pintura'),
    'ELECTRICIDAD': ('electricidad', 'Electricidad'),
    'PLOMERIA': ('plomeria', 'Plomería'),
    'MANGUERA': ('manguera', 'Mangueras'),
    'CONEXION DE RIEGO': ('riego', 'Conexiones de riego'),
    'CONSTRUCCION (HIERRO, POLVO)': ('construccion', 'Construcción: hierro y polvos'),
    'HERRAMIENTA': ('herramienta', 'Herramientas'),
    'HERRERIA': ('herreria', 'Herrería'),
    'HOGAR': ('hogar', 'Hogar'),
    'SEGURIDAD': ('seguridad', 'Seguridad'),
    'GENERICA': ('generica', 'Genéricos'),
    'HOTEL': ('hotel', 'Hotel'),
    'BAÑO': ('bano', 'Baño'),
    'BANO': ('bano', 'Baño'),
    'ILUMINACION': ('iluminacion', 'Iluminación'),
}


def norm(s):
    s = '' if s is None else str(s)
    s = unicodedata.normalize('NFD', s.upper().strip())
    return ''.join(c for c in s if unicodedata.category(c) != 'Mn')


def num(v):
    if v is None or v == '':
        return 0.0
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).replace('$', '').replace(' ', '')
    if s.count(',') == 1 and s.count('.') == 0:
        s = s.replace(',', '.')
    try:
        return float(s)
    except ValueError:
        return 0.0


def detectar_sucursal(path):
    """Lee la columna ALMACÉN del Excel y dice a qué sucursal pertenece."""
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    ws = wb.worksheets[0]
    col = None
    for row in ws.iter_rows(values_only=True):
        if col is None:
            if row and row[0] is not None and norm(row[0]) in ('CODIGO', 'CÓDIGO'):
                hdr = [norm(h) for h in row]
                col = hdr.index('ALMACEN') if 'ALMACEN' in hdr else -1
            continue
        if col is not None and col >= 0 and len(row) > col and row[col]:
            a = norm(row[col])
            wb.close()
            if 'VENTA MAYORISTA' in a: return 'mayorista'
            if 'ESQUINA' in a: return 'quinta'
            if 'BISCUCUY' in a and 'INGCO' not in a: return 'biscucuy'
            if 'CENTRO' in a: return 'unda'
            if 'INVERSIONES FERMIL' in a: return 'colonia'
            return None
    wb.close()
    return None


def leer_excel(path):
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    ws = wb.worksheets[0]
    cols = None
    filas = []
    for row in ws.iter_rows(values_only=True):
        if cols is None:
            if row and row[0] is not None and norm(row[0]) in ('CODIGO', 'CÓDIGO'):
                cols = {norm(h): i for i, h in enumerate(row) if h is not None}
            continue
        cod = row[cols['CODIGO']] if 'CODIGO' in cols else row[0]
        if cod is None or str(cod).strip() == '' or norm(cod).startswith('TOTAL') or norm(cod).startswith('UTILIDAD') or norm(cod).startswith('%'):
            continue
        g = lambda name: row[cols[name]] if name in cols and cols[name] < len(row) else None
        filas.append({
            'cod': str(cod).strip(),
            'nom': ' '.join(str(g('PRODUCTO') or '').split()),
            'cat': norm(g('CATEGORIA')),
            'sub': ' '.join(str(g('SUB CATEGORIA') or '').split()),
            'marca': ' '.join(str(g('LINEA') or '').split()),
            'und': ' '.join(str(g('PRESENTACION') or g('PRESENTACIÓN') or '').split()).lower(),
            'estatus': norm(g('ESTATUS')),
            'bloq': norm(g('BLOQUEAR PARA VENTA')),
            'disp': num(g('DISPONIBILIDAD')),
            'venta': num(g('TOTAL EN VENTA (PRECIO DE VENTA)')) or num(g('PRECIO UNI.')),
            'mayor': num(g('TOTAL EN VENTA (MAYOR)')),
            'menor': num(g('TOTAL EN VENTA (MENOR)')),
            'iva': num(g('IVA')),
        })
    wb.close()
    return filas


def con_iva(precio, iva):
    """PLADE da los precios del reporte SIN IVA; la página los muestra con IVA, redondeando
    al céntimo hacia arriba como lo muestra PLADE (98,34 + 16 % = 114,08)."""
    if not precio:
        return 0
    total = Decimal(str(precio)) * (Decimal(1) + Decimal(str(iva or 0)) / Decimal(100))
    return float(total.quantize(Decimal('0.01'), rounding=ROUND_CEILING))


def construir(archivos, tasa=None):
    productos = {}
    sucursales = []
    for path, suc in archivos:
        if suc not in sucursales:
            sucursales.append(suc)
        for f in leer_excel(path):
            if f['estatus'] and f['estatus'] != 'ACTIVO':
                continue
            if f['bloq'] in ('SI', 'SÍ'):
                continue
            cat = CATEGORIAS.get(f['cat'])
            if not cat:
                continue
            p = productos.get(f['cod'])
            if p is None:
                p = productos[f['cod']] = {
                    'c': f['cod'], 'n': f['nom'], 'k': cat[0], 's': f['sub'].title() if f['sub'] else '',
                    'm': f['marca'], 'u': f['und'] or 'unidad',
                    'v': con_iva(f['venta'], f['iva']), 'y': con_iva(f['mayor'], f['iva']),
                    'd': 1 if (f['menor'] > 0 and f['venta'] > 0 and f['menor'] < f['venta'] * 0.995) else 0,
                    'e': {},
                }
            # si una sucursal trae precio y otra no, se completa
            if not p['v'] and f['venta']:
                p['v'] = con_iva(f['venta'], f['iva'])
            if not p['y'] and f['mayor']:
                p['y'] = con_iva(f['mayor'], f['iva'])
            if f['disp'] > 0:
                p['e'][suc] = round(f['disp'], 2)
    lista = [p for p in productos.values() if p['v'] > 0]
    lista.sort(key=lambda p: (p['k'], p['n']))
    cats = {}
    for p in lista:
        cats[p['k']] = cats.get(p['k'], 0) + 1
    return {
        'generado': ahora_vet(),
        'tasa': tasa,
        'sucursales': sucursales,
        'categorias': cats,
        'productos': lista,
    }


if __name__ == '__main__':
    salida = sys.argv[1]
    archivos = [tuple(a.rsplit(':', 1)) for a in sys.argv[2:]]
    data = construir(archivos)
    with open(salida, 'w', encoding='utf-8') as fh:
        json.dump(data, fh, ensure_ascii=False, separators=(',', ':'))
    print(len(data['productos']), 'productos ->', salida, data['categorias'])

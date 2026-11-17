"""Junta las memorias del robot de esta corrida (carpeta que se pasa como argumento) con las que ya
están en main, para que dos corridas seguidas nunca choquen ni se pierda trabajo.
Uso (desde la raíz del repositorio, ya parado en origin/main): python robot/unir_caches.py /tmp/robot"""
import json
import sys
from pathlib import Path

local = Path(sys.argv[1])


def leer(p):
    try:
        return json.loads(Path(p).read_text())
    except (OSError, ValueError):
        return None


def guardar(nombre, datos):
    Path(nombre).write_text(json.dumps(datos, sort_keys=True))


# Fotos: gana la que tenga foto
a, b = leer('fotos_cache.json') or {}, leer(local / 'fotos_cache.json') or {}
if a or b:
    guardar('fotos_cache.json', {k: (b.get(k) or a.get(k) or '') for k in set(a) | set(b)})

# Ids de PLADE: unión; los reportes leídos son los de esta corrida
a, b = leer('ids_plade.json') or {}, leer(local / 'ids_plade.json') or {}
if a or b:
    guardar('ids_plade.json', {'ids': {**a.get('ids', {}), **b.get('ids', {})}, 'leidos': b.get('leidos', a.get('leidos', []))})

# Pesos: gana la revisión más reciente de cada producto
a, b = leer('pesos_plade.json') or {}, leer(local / 'pesos_plade.json') or {}
if a or b:
    guardar('pesos_plade.json', {k: max([x for x in (a.get(k), b.get(k)) if x], key=lambda x: x[1]) for k in set(a) | set(b)})

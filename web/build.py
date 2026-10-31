"""Arma index.html a partir de la plantilla, los estilos, el catálogo y las fotos.

Versión de prueba (todo dentro de un solo archivo):
    python build.py data/catalogo.json data/fotos.json index.html

Versión para la nube (la usa el robot en GitHub):
    python build.py --nube nube.json --catalogo salida/catalogo.json \
        --fotos-cache fotos_cache.json --fotos-dir fotos --salida _site
"""
import argparse
import json
import re
import shutil
import sys
from pathlib import Path

base = Path(__file__).parent
CSS_EXTRA = ['extra.css', 'v4.css', 'v5.css']


def safe(obj):
    # JSON dentro de <script>: evitar que "</script>" cierre la etiqueta
    return json.dumps(obj, ensure_ascii=False, separators=(',', ':')).replace('</', '<\\/')


def armar(catalogo, fotos, nube=None):
    tpl = (base / 'app.template.html').read_text(encoding='utf-8')
    css = (base / 'base.css').read_text(encoding='utf-8')
    extra = '\n'.join((base / f).read_text(encoding='utf-8') for f in CSS_EXTRA)
    nube_js = ''
    if nube:
        # En la nube los códigos de mayoristas viven en Supabase, nunca dentro de la página
        tpl = re.sub(r"codigo:'[^']*'", "codigo:''", tpl)
        tpl = re.sub(r'<!--PRUEBA-->.*?<!--/PRUEBA-->', '<p class="hint">Tu código te lo da Ferretería Fermil o tu vendedor mayorista.</p>', tpl, flags=re.S)
        nube_js = 'window.FERMIL_NUBE = ' + safe({'url': nube['supabase_url'].rstrip('/'), 'key': nube['supabase_key']}) + ';'
    return (tpl.replace('/*__BASECSS__*/', css)
               .replace('/*__EXTRACSS__*/', extra)
               .replace('/*__NUBE__*/', nube_js)
               .replace('__CATALOGO__', safe(catalogo))
               .replace('__FOTOS__', safe(fotos)))


def prueba(argv):
    cat_path = Path(argv[0]) if len(argv) > 0 else base / 'data' / 'catalogo.json'
    fotos_path = Path(argv[1]) if len(argv) > 1 else base / 'data' / 'fotos.json'
    out_path = Path(argv[2]) if len(argv) > 2 else base / 'index.html'
    catalogo = json.loads(cat_path.read_text(encoding='utf-8'))
    fotos = json.loads(fotos_path.read_text(encoding='utf-8')) if fotos_path.exists() else {}
    html = armar(catalogo, fotos)
    out_path.write_text(html, encoding='utf-8')
    print(f'{out_path} · {len(html)/1024:.0f} KB · {len(catalogo["productos"])} productos · {len(fotos)} fotos')


def nube(args):
    cfg = json.loads(Path(args.nube).read_text(encoding='utf-8'))
    if not cfg.get('supabase_url') or not cfg.get('supabase_key'):
        sys.exit('Falta supabase_url o supabase_key en ' + args.nube)
    catalogo = json.loads(Path(args.catalogo).read_text(encoding='utf-8'))
    for p in catalogo['productos']:
        p.pop('y', None)  # el precio al mayor nunca va en la página pública
        p.get('e', {}).pop('mayorista', None)
    cache = json.loads(Path(args.fotos_cache).read_text(encoding='utf-8')) if Path(args.fotos_cache).exists() else {}
    fotos_dir = Path(args.fotos_dir)
    salida = Path(args.salida)
    if salida.exists():
        shutil.rmtree(salida)
    (salida / 'fotos').mkdir(parents=True)
    codigos = {p['c'] for p in catalogo['productos']}
    fotos = {}
    for cod, ruta in cache.items():
        if not ruta or cod not in codigos:
            continue
        archivo = fotos_dir / Path(ruta).name
        if archivo.exists():
            shutil.copy2(archivo, salida / 'fotos' / archivo.name)
            fotos[cod] = 'fotos/' + archivo.name
    if (base / 'media').exists():
        shutil.copytree(base / 'media', salida / 'media')
    html = armar(catalogo, fotos, cfg)
    (salida / 'index.html').write_text(html, encoding='utf-8')
    (salida / '_headers').write_text('/fotos/*\n  Cache-Control: public, max-age=604800\n/media/*\n  Cache-Control: public, max-age=86400\n/index.html\n  Cache-Control: no-cache\n', encoding='utf-8')
    print(f'{salida} · index {len(html)/1024:.0f} KB · {len(catalogo["productos"])} productos · {len(fotos)} fotos')


if __name__ == '__main__':
    if len(sys.argv) > 1 and sys.argv[1].startswith('--'):
        ap = argparse.ArgumentParser()
        ap.add_argument('--nube', required=True)
        ap.add_argument('--catalogo', required=True)
        ap.add_argument('--fotos-cache', default='fotos_cache.json')
        ap.add_argument('--fotos-dir', default='fotos')
        ap.add_argument('--salida', default='_site')
        nube(ap.parse_args())
    else:
        prueba(sys.argv[1:])

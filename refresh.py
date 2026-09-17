#!/usr/bin/env python3
"""Regenera el panel de covers es de CrossClear y lo deja listo para publicar.

    python refresh.py [--out dist] [--cache .cache]

Lee SINGIT_PROD_BASE y SINGIT_PROD_TOKEN del entorno (o de un tokens.env que
se le pase con --env). Escribe <out>/index.html, un HTML autocontenido con los
datos embebidos: no hace ninguna llamada al abrirse.

Salidas de error:
    2  -> la admin devolvio 401/403: el admin_token ya no sirve.
    3  -> demasiadas llamadas fallidas, los datos no son fiables.

Solo biblioteca estandar. Tres fases:
    1. censo   GET /admin/api/cross-clear/migration/songs?page=N&pageSize=100
    2. fichas  GET /admin/api/tracks/{trackId}          (isArchived + estrellas)
    3. audio   GET .../migration/songs/{songId}/audio   (Range: bytes=0-1)
"""
import argparse, json, os, shutil, sys, time, urllib.request, urllib.error, collections
from concurrent.futures import ThreadPoolExecutor

AQUI = os.path.dirname(os.path.abspath(__file__))
MESES = ['ene', 'feb', 'mar', 'abr', 'may', 'jun',
         'jul', 'ago', 'sep', 'oct', 'nov', 'dic']


def carga_env(ruta):
    """tokens.env sin 'export': KEY=valor por linea."""
    if not ruta or not os.path.exists(ruta):
        return
    for linea in open(ruta, encoding='utf-8'):
        linea = linea.strip()
        if not linea or linea.startswith('#') or '=' not in linea:
            continue
        k, v = linea.split('=', 1)
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


class Admin:
    def __init__(self, base, token):
        self.base = base.rstrip('/')
        self.cab = {'Cookie': 'admin_token=' + token, 'accept': 'application/json'}
        self.fallos = 0

    def _abre(self, url, cab=None, timeout=90):
        pet = urllib.request.Request(url, headers=cab or self.cab)
        return urllib.request.urlopen(pet, timeout=timeout)

    def json(self, ruta, intentos=4):
        url = self.base + ruta
        for n in range(intentos):
            try:
                with self._abre(url) as r:
                    return json.load(r)
            except urllib.error.HTTPError as e:
                if e.code in (401, 403):
                    sys.exit(2)
                if e.code in (404, 410):
                    return None
                if n == intentos - 1:
                    self.fallos += 1
                    return None
                time.sleep(1.5 * (n + 1))
            except Exception:
                if n == intentos - 1:
                    self.fallos += 1
                    return None
                time.sleep(1.5 * (n + 1))

    def suena(self, song_id, intentos=3):
        """206 = el audio con voz responde. 404 = el reproductor se queda a 0:00."""
        url = '%s/admin/api/cross-clear/migration/songs/%s/audio' % (self.base, song_id)
        cab = dict(self.cab, Range='bytes=0-1')
        for n in range(intentos):
            try:
                with self._abre(url, cab, timeout=60) as r:
                    return r.status == 206
            except urllib.error.HTTPError as e:
                if e.code in (401, 403):
                    sys.exit(2)
                if e.code == 404:
                    return False
                time.sleep(1.2 * (n + 1))
            except Exception:
                time.sleep(1.2 * (n + 1))
        self.fallos += 1
        return False


def censo(api, log):
    """Todas las canciones del catalogo CrossClear. El parametro language se
    ignora en el servidor, asi que el filtro por idioma se hace aqui."""
    primera = api.json('/admin/api/cross-clear/migration/songs?page=1&pageSize=100')
    if not primera:
        sys.exit(3)
    total = primera['total']
    paginas = (total + 99) // 100
    log('censo: %d canciones en %d paginas' % (total, paginas))
    filas = list(primera['songs'])
    for p in range(2, paginas + 1):
        d = api.json('/admin/api/cross-clear/migration/songs?page=%d&pageSize=100' % p)
        if d:
            filas += d['songs']
        if p % 25 == 0:
            log('  pagina %d/%d' % (p, paginas))
    return filas


def fichas(api, canciones, log, hilos=12):
    """La calificacion vive en el TRACK (coverReview.quality), no en la cancion
    del catalogo, asi que hay que pedir una ficha por pista."""
    hechas = [0]

    def una(c):
        tid = c['publishedTrackId']
        a = c.get('assets') or {}
        fila = {'track': tid, 'song': c['_id'],
                'title': (c.get('name') or '').strip() or '(sin titulo)',
                'artist': (c.get('inStyleOf') or '').strip() or '(sin artista)',
                'fullSong': bool(a.get('fullSong')), 'q': None, 'arch': None}
        d = api.json('/admin/api/tracks/%s' % tid)
        hechas[0] += 1
        if hechas[0] % 250 == 0:
            log('  fichas %d/%d' % (hechas[0], len(canciones)))
        if not d:
            return fila
        t = d.get('track') or {}
        cr = t.get('coverReview') or {}
        fila['q'] = cr.get('quality')
        fila['arch'] = bool(t.get('isArchived'))
        if t.get('title'):
            fila['title'] = t['title'].strip()
        return fila

    log('fichas: %d pistas' % len(canciones))
    with ThreadPoolExecutor(max_workers=hilos) as ex:
        return list(ex.map(una, canciones))


def audios(api, filas, log, hilos=8):
    log('audio: probando %d canciones' % len(filas))
    with ThreadPoolExecutor(max_workers=hilos) as ex:
        for fila, ok in zip(filas, ex.map(lambda f: api.suena(f['song']), filas)):
            fila['ok'] = ok
    return filas


def render(datos, plantilla, salida, fecha):
    es = [x for x in datos if x['arch'] is not None]
    pend = [x for x in es if x['arch'] and x['q'] is None]
    orden = lambda x: (x['artist'].lower(), x['title'].lower())
    con = sorted([x for x in pend if x.get('ok')], key=orden)
    sin = sorted([x for x in pend if not x.get('ok')], key=orden)
    cal = sorted([x for x in es if x['q'] is not None], key=orden)

    def pack(items):
        return [[x['title'], x['artist'], x['track'], x['song'],
                 1 if x.get('ok') else 0, i, 1 if x['fullSong'] else 0]
                for i, x in enumerate(items, 1)]

    payload = {
        'data': {
            'con': pack(con),
            'sin': pack(sin),
            'cal': [[x['title'], x['artist'], x['track'], x['q'], 1 if x['arch'] else 0]
                    for x in cal],
        },
        'meta': {
            'total': len(pend), 'con': len(con), 'sin': len(sin),
            'suenan': len(con), 'mudas': sum(1 for x in sin if x['fullSong']),
            'calificadas': len(cal), 'censo': len(es),
            'artCon': len({x['artist'] for x in con}),
            'artSin': len({x['artist'] for x in sin}),
            'cal': len(cal), 'artCal': len({x['artist'] for x in cal}),
            'q': {str(n): sum(1 for x in cal if x['q'] == n) for n in (1, 2, 3, 4, 5)},
        },
    }
    html = open(plantilla, encoding='utf-8').read()
    html = html.replace('__FECHA__', fecha)
    html = html.replace('__TOTAL__', '{:,}'.format(len(pend)).replace(',', '.'))
    html = html.replace('/*__PAYLOAD__*/', json.dumps(
        payload, ensure_ascii=False, separators=(',', ':')).replace('</', '<\\/'))
    os.makedirs(salida, exist_ok=True)
    with open(os.path.join(salida, 'index.html'), 'w', encoding='utf-8') as f:
        f.write(html)

    # Resumen suelto: lo lee el aviso de Slack y el boton de la pagina.
    meta = dict(payload['meta'], fecha=fecha)
    with open(os.path.join(salida, 'meta.json'), 'w', encoding='utf-8') as f:
        json.dump(meta, f, ensure_ascii=False)

    # Las funciones del boton viajan dentro de lo que se publica.
    fuente = os.path.join(AQUI, 'functions')
    if os.path.isdir(fuente):
        destino = os.path.join(salida, 'functions')
        if os.path.isdir(destino):
            shutil.rmtree(destino)
        shutil.copytree(fuente, destino)

    return payload['meta']


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--out', default=os.path.join(AQUI, 'dist'))
    ap.add_argument('--env', default=None, help='ruta a un tokens.env')
    ap.add_argument('--cache', default=None,
                    help='guarda/reutiliza el barrido crudo en este json')
    ap.add_argument('--idioma', default='es')
    ap.add_argument('--silencio', action='store_true')
    args = ap.parse_args()

    carga_env(args.env)
    t0 = time.time()
    log = (lambda m: None) if args.silencio else (lambda m: print(m, flush=True))
    hay_cache = bool(args.cache) and os.path.exists(args.cache)

    base, token = os.environ.get('SINGIT_PROD_BASE'), os.environ.get('SINGIT_PROD_TOKEN')
    if not hay_cache and (not base or not token):
        print('Faltan SINGIT_PROD_BASE / SINGIT_PROD_TOKEN', file=sys.stderr)
        sys.exit(2)
    api = Admin(base or '', token or '')

    if hay_cache:
        log('reutilizando %s' % args.cache)
        datos = json.load(open(args.cache, encoding='utf-8'))
    else:
        todas = censo(api, log)
        canciones = [c for c in todas
                     if c.get('language') == args.idioma and c.get('publishedTrackId')]
        log('covers %s publicados: %d' % (args.idioma, len(canciones)))
        datos = fichas(api, canciones, log)
        pend = [x for x in datos if x['arch'] and x['q'] is None]
        audios(api, pend, log)
        if args.cache:
            json.dump(datos, open(args.cache, 'w', encoding='utf-8'),
                      ensure_ascii=False)

    if api.fallos > len(datos) * 0.02:
        print('demasiadas llamadas fallidas (%d)' % api.fallos, file=sys.stderr)
        sys.exit(3)

    hoy = time.localtime()
    fecha = '%d %s %d' % (hoy.tm_mday, MESES[hoy.tm_mon - 1], hoy.tm_year)
    meta = render(datos, os.path.join(AQUI, 'template.html'), args.out, fecha)

    log('')
    log('index.html escrito en %s' % args.out)
    log('  pendientes %d  (con full song %d / sin audio %d)'
        % (meta['total'], meta['con'], meta['sin']))
    log('  calificadas %d  %s' % (meta['cal'], meta['q']))
    log('  llamadas fallidas: %d | %d min' % (api.fallos, round((time.time() - t0) / 60)))


if __name__ == '__main__':
    main()

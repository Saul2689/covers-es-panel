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
import argparse, base64, json, os, shutil, sys, time, urllib.request, urllib.error, collections
from concurrent.futures import ThreadPoolExecutor

AQUI = os.path.dirname(os.path.abspath(__file__))
MESES = ['ene', 'feb', 'mar', 'abr', 'may', 'jun',
         'jul', 'ago', 'sep', 'oct', 'nov', 'dic']

# El parte de la linea ES. Lo escribe OTRO hilo de trabajo y lo commitea al
# repo; aqui solo se lee. Puede no existir, llegar a medias o venir mal: pase
# lo que pase la build tiene que terminar, porque el panel no es suyo.
COLA = os.path.join(AQUI, 'cola_carry.json')
ESTADOS = ['parada', 'correccion', 'revision', 'carry',
           'traduccion', 'cola', 'sinorig', 'hecha']


def ficha_de(c):
    """Los pasos auditados de una cancion, o {} si no se ha tocado."""
    return ((c.get('auditoria') or {}).get('pasos') or {})


def sin_original(c, estado):
    """Si esta cancion hay que contarla como 'falta subir el original'.

    No basta con que falte originalTrackId: el hilo de la linea dejo de
    rellenarlo y sin esta segunda condicion el panel escondia mas de mil
    canciones ya trabajadas detras de 'Original por subir'. Con ficha de
    pasos la cancion ha entrado en la linea, y ahi se queda.
    """
    if estado not in ('cola', 'carry'):
        return False
    if str(c.get('originalTrackId') or '').strip():
        return False
    return not ficha_de(c)


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
                'fullSong': bool(a.get('fullSong')), 'q': None, 'arch': None,
                'lock': False}
        d = api.json('/admin/api/tracks/%s' % tid)
        hechas[0] += 1
        if hechas[0] % 250 == 0:
            log('  fichas %d/%d' % (hechas[0], len(canciones)))
        if not d:
            return fila
        t = d.get('track') or {}
        cr = t.get('coverReview') or {}
        fila['q'] = cr.get('quality')
        # El candado lo echa una persona cuando da la cancion por cerrada.
        fila['lock'] = bool(cr.get('locked'))
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


def parte_linea(datos, log):
    """Lee cola_carry.json y lo cruza con lo que ya sabemos de la admin.

    El parte solo aporta en que paso va cada cancion; las estrellas, si esta
    archivada y si el audio suena salen del barrido de esta misma vuelta, asi
    que no se le pregunta nada a nadie dos veces.
    """
    vacio = {'filas': [], 'generado': None, 'fallo': None, 'mudas': set(),
             'cuenta': {e: 0 for e in ESTADOS}}
    if not os.path.exists(COLA):
        log('linea ES: todavia no hay parte (%s)' % os.path.basename(COLA))
        return vacio
    try:
        d = json.load(open(COLA, encoding='utf-8'))
        canciones = d.get('canciones')
        if not isinstance(canciones, list):
            raise ValueError('falta la lista "canciones"')
    except Exception as e:
        log('linea ES: el parte no se puede leer (%s); la pestana saldra vacia' % e)
        return dict(vacio, fallo=str(e))

    por_track = {x['track']: x for x in datos if x.get('track')}
    por_song = {x['song']: x for x in datos if x.get('song')}
    filas, mudas = [], set()
    for c in canciones:
        if not isinstance(c, dict):
            continue
        adm = por_track.get(c.get('coverTrackId')) or por_song.get(c.get('songId')) or {}
        estado = str(c.get('estado') or 'cola').strip().lower()
        if estado not in ESTADOS:
            estado = 'cola'
        # Sin original enlazado Y sin nada hecho no hay nada que carrear: no
        # es cola, es un atasco en otro sitio (aprobar el candidato del
        # matcher). Si ya tiene ficha de pasos, esta trabajada: se queda.
        if sin_original(c, estado):
            estado = 'sinorig'
        # Hecha es hecha Y suena. Una cancion cuyo /audio no sirve nada sale a
        # 0:00 en la app: contarla como hecha era el tercer numero distinto
        # para lo mismo (el 27 oct la linea decia 885 y la barra 858). Sale de
        # la linea, no de la vista: se sigue viendo en la pestana Sin audio,
        # que es su filtro. El parte no se toca, solo como lo lee el panel.
        if estado == 'hecha' and adm.get('ok') is False:
            mudas.add(c.get('coverTrackId') or c.get('songId') or '')
            continue
        try:
            vueltas = int(c.get('vueltas') or 0)
        except (TypeError, ValueError):
            vueltas = 0
        filas.append([
            str(c.get('titulo') or adm.get('title') or '(sin titulo)').strip(),
            str(c.get('artista') or adm.get('artist') or '(sin artista)').strip(),
            str(c.get('coverTrackId') or adm.get('track') or ''),
            str(c.get('songId') or adm.get('song') or ''),
            estado,
            vueltas,
            str(c.get('actualizado') or '')[:19],
            str(c.get('motivo') or '').strip() if estado == 'parada' else '',
            # -1 = no lo hemos probado esta vuelta (solo se sondean las pendientes)
            (1 if adm.get('ok') else 0) if 'ok' in adm else -1,
            adm.get('q') or 0,
            1 if adm.get('arch') else 0,
            # El agente escribe el motivo en espanol; si ademas deja la version
            # inglesa, la pagina la usa cuando el visitante esta en EN.
            str(c.get('motivo_en') or '').strip() if estado == 'parada' else '',
            # El candado lo echa una persona cuando da la cancion por cerrada:
            # es la senal de "esta hecha del todo" dentro de la linea.
            1 if adm.get('lock') else 0,
            # 13: la ficha en seis letras. 14: por que esta parada.
            ficha_letras(c),
            nota_bloqueo(c),
        ])

    orden = {e: i for i, e in enumerate(ESTADOS)}
    # Dentro de cada paso, primero lo que todavia espera a que una persona
    # eche el candado; lo ya cerrado se va al final, que es donde estorba menos.
    # Y dentro de eso, lo ultimo que se ha tocado arriba. Son dos pasadas
    # porque la fecha ordena al reves que el resto: el sort de Python es
    # estable y la segunda respeta lo que dejo hecho la primera.
    filas.sort(key=lambda f: f[6], reverse=True)
    filas.sort(key=lambda f: (orden[f[4]], f[12]))
    cuenta = collections.Counter(f[4] for f in filas)
    log('linea ES: %d canciones  %s' % (len(filas), dict(cuenta)))
    if mudas:
        log('linea ES: %d dadas por hechas que no suenan, fuera de la linea '
            '(se ven en Sin audio)' % len(mudas))
    return {'filas': filas,
            'generado': str(d.get('generado') or '')[:19] or None,
            'fallo': None,
            'mudas': mudas,
            'lock': sum(1 for f in filas if f[12]),
            'cuenta': {e: cuenta.get(e, 0) for e in ESTADOS}}


PASOS_FICHA = ('carry', 'lrc', 'timing', 'mapeo', 'ingles', 'qc')

# La ficha viaja a la pagina como SEIS LETRAS, una por paso y en ese orden:
# "ooooof" = carry, lrc, tiempos y mapeo hechos; ingles pendiente. Seis letras
# por cancion en vez de un objeto son 18 KB en vez de 300 en el payload.
LETRA_V = {'ok': 'o', 'falta': 'f', 'saul': 's', 'na': 'n'}
# Los pasos que dejan una cancion parada, en el orden en que importan: la nota
# que se publica es la del primero que la bloquea.
BLOQUEAN = ('falta', 'saul')


def ficha_letras(c):
    """Los seis veredictos de una cancion como seis letras ('-' = sin llegar)."""
    f = ficha_de(c)
    return ''.join(LETRA_V.get(str((f.get(p) or {}).get('v') or ''), '-')
                   for p in PASOS_FICHA)


def nota_bloqueo(c):
    """Por que esta parada: la nota del primer paso que la bloquea."""
    f = ficha_de(c)
    for p in PASOS_FICHA:
        i = f.get(p) or {}
        if str(i.get('v') or '') in BLOQUEAN:
            return str(i.get('nota') or '').strip()[:170]
    return ''


def proceso_linea(log, fuera_de_linea=()):
    """Los numeros que hacen vivo el diagrama del proceso.

    El estado de una cancion ("corrigiendo") dice en que caja esta, pero no en
    que paso de esa caja. Eso lo guarda el parte, cancion a cancion, en
    auditoria.pasos, y hasta hoy no salia del fichero. Aqui se cuenta y se
    publica, que es lo unico que impide que el dibujo se separe del trabajo.
    """
    fuera = {'total': 0, 'trabajadas': 0, 'conficha': 0, 'descartadas': 0,
             'estados': {e: 0 for e in ESTADOS}, 'pasos': {}, 'vueltas': {},
             'devueltas': 0, 'pasadas': 0}
    try:
        d = json.load(open(COLA, encoding='utf-8'))
        canciones = d.get('canciones') or []
    except Exception as e:
        log('proceso: no se puede leer el parte (%s); la pestana saldra vacia' % e)
        return fuera

    estados = collections.Counter()
    pasos = {p: collections.Counter() for p in PASOS_FICHA}
    vueltas = collections.Counter()
    conficha = 0
    for c in canciones:
        if not isinstance(c, dict):
            continue
        e = str(c.get('estado') or 'cola').strip().lower()
        if e not in ESTADOS:
            e = 'cola'
        # Misma correccion que en la pestana Carry: sin original enlazado y
        # sin nada hecho la cancion no espera turno, esta atascada en otro
        # sitio; con ficha de pasos ya ha entrado en la linea.
        if sin_original(c, e):
            e = 'sinorig'
        # Las dadas por hechas que no suenan tampoco cuentan aqui: si no, el
        # diagrama volveria a dar un tercer numero de hechas.
        if (c.get('coverTrackId') or c.get('songId') or '') in fuera_de_linea:
            continue
        estados[e] += 1
        try:
            v = int(c.get('vueltas') or 0)
        except (TypeError, ValueError):
            v = 0
        vueltas[v] += 1
        ficha = ficha_de(c)
        if ficha:
            conficha += 1
        for p in PASOS_FICHA:
            pasos[p][str((ficha.get(p) or {}).get('v') or 'sin')] += 1

    # "Trabajadas" son las que han entrado en la linea. Ni las que esperan
    # turno ni las que estan atascadas sin original cuentan como trabajo.
    trabajadas = sum(n for e, n in estados.items() if e not in ('cola', 'sinorig'))
    # El total es lo contado, no lo leido: las dadas por hechas que no suenan
    # salen del recuento igual que de la linea, y si no el diagrama diria
    # "862 de 2.303" donde la linea dice "862 de 2.277".
    contadas = sum(estados.values())
    log('proceso: %d en la cola, %d trabajadas, %d con ficha de pasos'
        % (contadas, trabajadas, conficha))
    return {
        'total': contadas,
        'trabajadas': trabajadas,
        'conficha': conficha,
        'descartadas': int(d.get('descartadas') or 0),
        'estados': {e: estados.get(e, 0) for e in ESTADOS},
        'pasos': {p: dict(pasos[p]) for p in PASOS_FICHA},
        'vueltas': {str(k): v for k, v in sorted(vueltas.items())},
        'devueltas': sum(n for k, n in vueltas.items() if k > 0),
        'pasadas': sum(k * n for k, n in vueltas.items()),
    }


PANEL_META = 'https://covers-es-v2.pages.dev/meta.json'


def vuelta_anterior(log):
    """La meta.json que hay publicada todavia es la de la vuelta pasada: esa es
    la foto contra la que se compara. Si no se puede leer, esta vuelta sale sin
    comparacion y no pasa nada mas.
    """
    url = os.environ.get('PANEL_META', PANEL_META)
    if url.lower() == 'no':
        return None
    try:
        # Cloudflare le da un 403 al agente de serie de urllib, asi que se
        # presenta con un nombre normal.
        cab = {'accept': 'application/json',
               'user-agent': 'Mozilla/5.0 (compatible; covers-es-panel/1.0)'}
        # El panel publicado pide contrasena (functions/_middleware.js), asi
        # que para leer su meta.json hay que presentarla.
        clave = os.environ.get('PANEL_PASS')
        if clave:
            cab['authorization'] = 'Basic ' + base64.b64encode(
                (':' + clave).encode('utf-8')).decode('ascii')
        pet = urllib.request.Request(url, headers=cab)
        with urllib.request.urlopen(pet, timeout=30) as r:
            return json.load(r)
    except Exception as e:
        log('no se pudo leer la vuelta anterior (%s): el aviso ira sin comparar' % e)
        return None


def movimiento_carry(filas, log):
    """Que se ha movido en la pestana Carry desde la vuelta anterior.

    Compara la lista entera, no un paso suelto: de que paso a que paso ha ido
    cada cancion, cuales son nuevas y cuantas se han caido de la lista.
    Devuelve tambien la foto de ahora, que es lo que leera la vuelta siguiente
    para hacer su propia comparacion.
    """
    clave = lambda f: str(f[2] or f[3] or (f[1] + '|' + f[0]))
    ahora = {clave(f): f for f in filas}
    foto = {k: f[4] for k, f in ahora.items()}
    cuenta = collections.Counter(foto.values())
    marcador = {e: cuenta.get(e, 0) for e in ESTADOS}

    antes = ((vuelta_anterior(log) or {}).get('carry') or {}).get('foto')
    if not isinstance(antes, dict) or not antes:
        log('carry: %d canciones (sin foto anterior, esta vuelta no compara)' % len(filas))
        return {'foto': foto, 'cuenta': marcador, 'previo': None,
                'cambios': [], 'nuevas': [], 'fuera': 0, 'comparado': False}
    ayer = collections.Counter(antes.values())

    cambios, nuevas = [], []
    for k, f in ahora.items():
        previo = antes.get(k)
        if previo is None:
            nuevas.append([k, f[0], f[1], f[4]])
        elif previo != f[4]:
            cambios.append([k, f[0], f[1], str(previo), f[4]])
    fuera = sum(1 for k in antes if k not in ahora)

    orden = lambda x: (x[2].lower(), x[1].lower())
    cambios.sort(key=orden)
    nuevas.sort(key=orden)
    log('carry: %d canciones, cambian de paso %d, nuevas %d, se caen %d'
        % (len(filas), len(cambios), len(nuevas), fuera))
    return {'foto': foto, 'cuenta': marcador,
            'previo': {e: ayer.get(e, 0) for e in ESTADOS},
            'cambios': cambios, 'nuevas': nuevas, 'fuera': fuera,
            'comparado': True}


def render(datos, plantilla, salida, fecha, log):
    es = [x for x in datos if x['arch'] is not None]
    # Sin nota es sin nota, este publicada o en borrador. Publicar una cover
    # le quita isArchived, y hasta el 21 oct 2026 eso la borraba del panel:
    # las que ya suenan salian de la cola de escucha justo al ponerse en vivo.
    pend = [x for x in es if x['q'] is None]
    orden = lambda x: (x['artist'].lower(), x['title'].lower())
    # Con voz / sin audio parten el censo ENTERO, no solo lo que no tiene nota:
    # una cover calificada sigue siendo una cover que suena, y sacarla de la
    # cuenta hacia que la tarjeta y la barra de avance dijeran numeros
    # distintos para la misma cosa.
    con = sorted([x for x in es if x.get('ok')], key=orden)
    sin = sorted([x for x in es if not x.get('ok')], key=orden)
    cal = sorted([x for x in es if x['q'] is not None or x['lock']], key=orden)
    linea = parte_linea(datos, log)
    carry = movimiento_carry(linea['filas'], log)
    # Avance: de las covers cuyo audio suena de verdad, cuantas ha dado la
    # linea por hechas. El denominador es todo lo que se puede trabajar,
    # este en la linea o no; lo que no suena no entra porque no hay nada
    # que terminar ahi hasta que aparezca el audio.
    hechas = {f[2] for f in linea['filas'] if f[4] == 'hecha' and f[2]}
    voz = [x for x in es if x.get('ok')]
    avance = {'voz': len(voz),
              'hechas': sum(1 for x in voz if x['track'] in hechas)}
    log('avance: %d de %d canciones con voz estan hechas'
        % (avance['hechas'], avance['voz']))
    proceso = proceso_linea(log, linea.get('mudas') or ())

    def pack(items):
        # El indice 7 es la nota: en estas dos listas ahora hay canciones ya
        # calificadas, y sin la estrella en la fila parecerian sin escuchar.
        return [[x['title'], x['artist'], x['track'], x['song'],
                 1 if x.get('ok') else 0, i, 1 if x['fullSong'] else 0,
                 x['q'] or 0]
                for i, x in enumerate(items, 1)]

    payload = {
        'data': {
            'con': pack(con),
            'sin': pack(sin),
            'cal': [[x['title'], x['artist'], x['track'], x['q'],
                     1 if x['arch'] else 0, 1 if x['lock'] else 0]
                    for x in cal],
            'linea': linea['filas'],
        },
        'meta': {
            'total': len(pend), 'con': len(con), 'sin': len(sin),
            'suenan': len(con), 'mudas': sum(1 for x in sin if x['fullSong']),
            'calificadas': len(cal), 'censo': len(es), 'avance': avance,
            'artCon': len({x['artist'] for x in con}),
            'artSin': len({x['artist'] for x in sin}),
            'cal': len(cal), 'artCal': len({x['artist'] for x in cal}),
            'lock': sum(1 for x in cal if x['lock']),
            'q': {str(n): sum(1 for x in cal if x['q'] == n) for n in (1, 2, 3, 4, 5)},
            # La pagina escribe la fecha en el idioma que elija cada visitante,
            # asi que va cruda y se formatea alli.
            'iso': time.strftime('%Y-%m-%d'),
            'linea': {'total': len(linea['filas']), 'cuenta': linea['cuenta'],
                      'lock': linea['lock'],
                      'generado': linea['generado'], 'fallo': linea['fallo']},
            # El diagrama de la pestana Pipeline se dibuja con esto: si el
            # trabajo cambia, cambian los numeros del dibujo solos.
            'proceso': proceso,
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

    # Resumen suelto: lo lee el aviso de Slack y el boton de la pagina. El
    # movimiento de la pestana Carry solo va aqui: la foto de 2.000 y pico
    # canciones no pinta nada dentro de la pagina.
    meta = dict(payload['meta'], fecha=fecha, carry=carry)
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
        # Se sondea el audio de todas, no solo de las que no tienen nota:
        # la barra de avance cuenta cuantas de las que SUENAN estan hechas,
        # y entre las calificadas tambien hay canciones con voz.
        audios(api, [x for x in datos if x['arch'] is not None], log)
        if args.cache:
            json.dump(datos, open(args.cache, 'w', encoding='utf-8'),
                      ensure_ascii=False)

    if api.fallos > len(datos) * 0.02:
        print('demasiadas llamadas fallidas (%d)' % api.fallos, file=sys.stderr)
        sys.exit(3)

    hoy = time.localtime()
    fecha = '%d %s %d' % (hoy.tm_mday, MESES[hoy.tm_mon - 1], hoy.tm_year)
    meta = render(datos, os.path.join(AQUI, 'template.html'), args.out, fecha, log)

    log('')
    log('index.html escrito en %s' % args.out)
    log('  pendientes %d  (con full song %d / sin audio %d)'
        % (meta['total'], meta['con'], meta['sin']))
    log('  calificadas %d  %s' % (meta['cal'], meta['q']))
    log('  linea ES %d  %s' % (meta['linea']['total'], meta['linea']['cuenta']))
    log('  llamadas fallidas: %d | %d min' % (api.fallos, round((time.time() - t0) / 60)))


if __name__ == '__main__':
    main()

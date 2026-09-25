#!/usr/bin/env python3
"""Manda a Slack el movimiento del paso Carry de la vuelta que acaba de publicar.

El aviso no da totales: cuenta lo que se ha movido desde la vuelta anterior,
que entro en Carry y que salio (y hacia donde). El resto del panel se mira en
la pagina.

Lee las variables de entorno que le pone el workflow:
    GANCHO   la URL del webhook de Slack (obligatoria; sin ella no hace nada)
    ORIGEN   'reloj' si la pidio el reloj de Cloudflare, 'boton' si alguien
             pulso el boton de la pagina, 'terminal' si salio de una consola
    ENLACE   la direccion de esta vuelta en GitHub Actions
    FALLO    '1' cuando se llama desde el paso de error

Nunca tumba el workflow: si Slack no contesta, lo dice y sale con 0. Un aviso
perdido no vale una pagina sin publicar.
"""
import json
import os
import sys
import urllib.error
import urllib.request

PANEL = 'https://covers-es-v2.pages.dev/'
RESUMEN = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'dist', 'meta.json')
TOPE = 12   # a partir de aqui la lista se corta y se dice cuantas faltan

# Como se lee en el aviso el paso al que se ha ido una cancion.
PASOS = {
    'parada': 'parada',
    'correccion': 'correccion',
    'revision': 'revision',
    'carry': 'carry',
    'traduccion': 'traduccion',
    'cola': 'cola',
    'sinorig': 'sin original',
    'hecha': 'hecha',
    'fuera': 'fuera de la lista',
}


def manda(texto):
    gancho = os.environ.get('GANCHO')
    if not gancho:
        # Sin webhook el aviso se queda en el log. La consola de Windows no
        # sabe escribir la flecha, asi que se cambia por una de las suyas.
        print('sin webhook, no mando nada')
        print(texto.encode(sys.stdout.encoding or 'utf-8', 'replace')
                   .decode(sys.stdout.encoding or 'utf-8', 'replace'))
        return
    pet = urllib.request.Request(
        gancho,
        data=json.dumps({'text': texto}).encode('utf-8'),
        headers={'content-type': 'application/json'},
    )
    try:
        with urllib.request.urlopen(pet, timeout=20) as r:
            print('slack %s' % r.status)
    except urllib.error.HTTPError as e:
        print('slack no acepto el aviso: %s' % e.code, file=sys.stderr)
    except Exception as e:
        print('no se pudo avisar a slack: %s' % e, file=sys.stderr)


def lista(filas, destino=False):
    """Una cancion por linea: titulo, artista y, si sale, adonde se ha ido."""
    trozos = []
    for f in filas[:TOPE]:
        linea = '        · %s — %s' % (f[1], f[2])
        if destino:
            linea += ' → %s' % PASOS.get(f[3], f[3])
        trozos.append(linea)
    if len(filas) > TOPE:
        trozos.append('        · y %d mas' % (len(filas) - TOPE))
    return '\n'.join(trozos)


def main():
    enlace = os.environ.get('ENLACE', '')
    como = {
        'reloj': 'automatica',
        'boton': 'pedida desde el boton de la pagina',
    }.get(os.environ.get('ORIGEN'), 'lanzada a mano')

    if os.environ.get('FALLO') == '1':
        manda(':rotating_light: *El panel de covers es NO se ha actualizado* '
              '(vuelta %s).\nLa pagina sigue con los ultimos datos buenos, no se '
              'ha quedado vacia.\nQue paso: %s' % (como, enlace))
        return

    try:
        with open(RESUMEN, encoding='utf-8') as f:
            m = json.load(f)
    except Exception:
        manda(':white_check_mark: Panel de covers es actualizado (%s).\n%s'
              % (como, PANEL))
        return

    c = m.get('carry') or {}
    entran = c.get('entran') or []
    salen = c.get('salen') or []
    cabeza = '*Carry* — vuelta %s, %s' % (como, m.get('fecha', ''))

    if not c.get('comparado'):
        manda(':package: %s\nNo he podido leer la vuelta anterior, asi que esta '
              'no compara. En la siguiente vuelve el movimiento.\n%s'
              % (cabeza, PANEL))
        return

    if not entran and not salen:
        manda(':package: %s\nSin movimiento: en Carry no ha entrado ni salido '
              'nada desde la vuelta anterior.\n%s' % (cabeza, PANEL))
        return

    cuerpo = []
    if entran:
        cuerpo.append('• Entran (*%d*)\n%s' % (len(entran), lista(entran)))
    if salen:
        cuerpo.append('• Salen (*%d*)\n%s' % (len(salen), lista(salen, destino=True)))

    manda(':package: %s\n%s\n%s' % (cabeza, '\n'.join(cuerpo), PANEL))


if __name__ == '__main__':
    main()

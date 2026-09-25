#!/usr/bin/env python3
"""Manda a Slack como va la pestana Carry del panel de covers es.

Cada aviso lleva siempre los numeros de cada paso, con lo que ha subido o
bajado desde la vuelta anterior, y debajo lo que se ha movido: que cancion ha
cambiado de paso, cuales son nuevas y cuantas se han caido. Aunque no se mueva
nada, el aviso dice como esta la cosa.

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
TOPE = 15   # a partir de aqui la lista se corta y se dice cuantas faltan

# Los pasos en el mismo orden y con el mismo nombre que en el panel.
PASOS = [
    ('parada', 'Parada'),
    ('carry', 'Carry'),
    ('revision', 'En revision'),
    ('correccion', 'Corrigiendo'),
    ('traduccion', 'Traduciendo'),
    ('cola', 'En cola'),
    ('hecha', 'Hecha'),
    ('sinorig', 'Sin original'),
]
NOMBRE = dict(PASOS)


def manda(texto):
    gancho = os.environ.get('GANCHO')
    if not gancho:
        # Sin webhook el aviso se queda en el log. La consola de Windows no
        # sabe escribir la flecha, asi que se cambia por lo que sepa poner.
        cp = sys.stdout.encoding or 'utf-8'
        print('sin webhook, no mando nada')
        print(texto.encode(cp, 'replace').decode(cp, 'replace'))
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


def miles(n):
    return '{:,}'.format(n).replace(',', '.')


def paso(nombre):
    return NOMBRE.get(nombre, nombre)


def marcador(cuenta, previo):
    """La tabla de siempre: un paso por linea, su numero y lo que ha cambiado."""
    filas = []
    for clave, nombre in PASOS:
        n = cuenta.get(clave, 0)
        linea = '%-14s %6s' % (nombre, miles(n))
        if previo is not None:
            d = n - previo.get(clave, 0)
            if d:
                linea += '  %+d' % d
        filas.append(linea)
    total = sum(cuenta.get(c, 0) for c, _ in PASOS)
    filas.append('%-14s %6s' % ('TOTAL', miles(total)))
    return '```\n%s\n```' % '\n'.join(filas)


def trozo(titulo, filas, pinta):
    """Un bloque de la lista: cabecera con el numero y una cancion por linea."""
    cuerpo = [pinta(f) for f in filas[:TOPE]]
    if len(filas) > TOPE:
        cuerpo.append('        · y %d mas' % (len(filas) - TOPE))
    return '• %s (*%d*)\n%s' % (titulo, len(filas), '\n'.join(cuerpo))


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
    cuenta = c.get('cuenta') or {}
    previo = c.get('previo') if c.get('comparado') else None
    cambios = c.get('cambios') or []
    nuevas = c.get('nuevas') or []
    fuera = c.get('fuera') or 0

    partes = [':package: *Carry* — vuelta %s, %s' % (como, m.get('fecha', '')),
              marcador(cuenta, previo)]

    if not c.get('comparado'):
        partes.append('_Primera vuelta con seguimiento: desde la siguiente '
                      'tambien digo que se ha movido._')
    elif not cambios and not nuevas and not fuera:
        partes.append('Sin movimiento: nadie ha cambiado de paso desde la '
                      'vuelta anterior.')
    else:
        if cambios:
            partes.append(trozo(
                'Cambian de paso', cambios,
                lambda f: '        · %s — %s: %s → %s'
                          % (f[1], f[2], paso(f[3]), paso(f[4]))))
        if nuevas:
            partes.append(trozo(
                'Nuevas en la lista', nuevas,
                lambda f: '        · %s — %s (%s)' % (f[1], f[2], paso(f[3]))))
        if fuera:
            partes.append('• Se han caido de la lista: *%d*' % fuera)

    partes.append(PANEL)
    manda('\n'.join(partes))


if __name__ == '__main__':
    main()

#!/usr/bin/env python3
"""Manda a Slack el resumen de la vuelta que acaba de publicar el panel.

Lee las variables de entorno que le pone el workflow:
    GANCHO   la URL del webhook de Slack (obligatoria; sin ella no hace nada)
    DISPARO  'schedule' si fue automatica, otra cosa si la lanzo alguien
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


def manda(texto):
    gancho = os.environ.get('GANCHO')
    if not gancho:
        print('sin webhook, no mando nada')
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


def main():
    enlace = os.environ.get('ENLACE', '')
    automatica = os.environ.get('DISPARO') == 'schedule'
    como = 'automatica' if automatica else 'lanzada a mano'

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

    q = m.get('q') or {}
    estrellas = ' · '.join(
        '%s★ %s' % (n, q.get(n, 0)) for n in ('1', '2', '3', '4', '5'))

    manda(
        ':white_check_mark: *Panel de covers es actualizado* (%s, %s)\n'
        '• Pendientes de calificar: *%s* — %s suenan con voz, %s se quedan a 0:00\n'
        '• Ya calificadas: *%s* — %s\n'
        '%s' % (
            como, m.get('fecha', ''),
            m.get('total', '?'), m.get('con', '?'), m.get('sin', '?'),
            m.get('cal', '?'), estrellas,
            PANEL,
        ))


if __name__ == '__main__':
    main()

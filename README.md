# Panel de covers es — actualización automática

Regenera `index.html` leyendo la admin de SingIt y lo publica en Cloudflare Pages
(`covers-es-v2`). El HTML es autocontenido: lleva los datos dentro y no hace
ninguna llamada al abrirse, así que la página sigue funcionando aunque la admin
esté caída y nadie de fuera necesita credenciales para verla.

## A mano

```bash
cd .singit/cc_audio/deploy
npm install                    # solo la primera vez, trae wrangler
npx wrangler login             # solo la primera vez
npm run deploy
```

`npm run deploy` tarda unos 25-30 minutos: son ~6.100 llamadas a la admin.
`npm run build` hace lo mismo sin publicar, para mirar el `dist/index.html` antes.

Si `refresh.py` no encuentra el token en el entorno, pásale el fichero:

```bash
python refresh.py --env ../../tokens.env --out dist
```

## El reloj vive en Cloudflare, no en GitHub

El workflow **ya no tiene `schedule`**. El planificador de GitHub no despierta
este proceso a su hora: entre el 16 y el 17 de septiembre de 2026 salto **una
vez** de la docena larga que tocaba, con el cron en punto y tambien movido al
minuto 25. No es el horario ni el minuto, sencillamente no dispara.

Asi que el despertador esta en `reloj/`: un worker de Cloudflare con cron
trigger que a cada hora mira que hora es en Madrid y, si cae en la franja,
llama al `workflow_dispatch` con `origen=reloj`. GitHub sigue haciendo el
trabajo pesado, solo le hemos quitado el reloj.

```bash
cd reloj
npx wrangler deploy
npx wrangler secret put GH_TOKEN     # el mismo token que usa el boton
curl https://covers-es-reloj.<subdominio>.workers.dev/   # ver si esta vivo
```

El `origen` de cada vuelta (`reloj`, `boton`, `terminal`) decide tres cosas: si
gasta cupo del boton, si el paso del horario aplica la franja, y como se
presenta el aviso de Slack.

## Desatendido

`.github/workflows/covers-es.yml`. Corre **cada hora en punto de 9:00 a 18:00 hora de
Madrid** (el cron va en UTC de 7 a 17 y un primer paso descarta las horas que caen
fuera de la franja, para que el horario de verano no lo desplace) y
también a mano desde la pestaña Actions. Necesita tres secrets:

| Secret | Qué es |
|---|---|
| `SINGIT_PROD_TOKEN` | el valor de la cookie `admin_token` |
| `CLOUDFLARE_API_TOKEN` | token de Cloudflare con permiso *Cloudflare Pages: Edit* |
| `CLOUDFLARE_ACCOUNT_ID` | id de la cuenta |
| `SLACK_WEBHOOK_URL` | webhook de Slack para el aviso de cada vuelta (opcional: sin el, los dos pasos de aviso se saltan) |

## Ingles y espanol

La pagina se comparte fuera del equipo, asi que **arranca en ingles**; el
interruptor EN/ES de la cabecera cambia todo el texto y la eleccion se guarda en
el navegador de cada visitante. Las etiquetas de estrella (Poor, Weak,
Acceptable, Good, Excellent) **no se traducen**: son las del admin de SingIt y
hay que poder cotejarlas.

Los dos idiomas viven en el objeto `TXT` del script, arriba del todo. La fecha
viaja cruda (`meta.iso`) y se formatea en el navegador con el idioma elegido.

El aviso de Slack sigue en espanol: ese lo lees tu, no se comparte.

## El boton de actualizar a mano

La pagina lleva un boton publico que dispara una vuelta. El freno vive en el
servidor, no en el navegador, porque la pagina la ve cualquiera:

- `functions/api/refrescar.js` (POST) cuenta las vueltas `workflow_dispatch` del
  dia **en hora de Madrid** y se niega a partir de **5**; tambien se niega si ya
  hay una corriendo. Si pasa el filtro, llama a la API de GitHub para lanzarla.
- `functions/api/estado.js` (GET) dice si hay una en marcha, cuando arranco y
  cuanto tardan de media las ultimas (descartando las que duran segundos porque
  se saltaron por horario). Con eso la pagina pinta el contador.

`refresh.py` copia `functions/` dentro de `dist/` en cada build, asi que viajan
con la publicacion. Las dos funciones necesitan una variable **en el proyecto de
Cloudflare Pages** (no en GitHub):

| Variable | Que es |
|---|---|
| `GH_TOKEN` | token de GitHub con permiso de **escritura sobre Actions** en este repo |

```bash
npx wrangler pages secret put GH_TOKEN --project-name covers-es-v2
```

Sin esa variable las funciones devuelven `sin-token`, el boton sale apagado y la
pagina sigue funcionando igual: los datos van dentro del HTML.

## De dónde salen los datos

No hay un endpoint que devuelva la tabla hecha. Son tres llamadas distintas:

| Fase | Llamada | Qué saca |
|---|---|---|
| 1. censo | `GET /admin/api/cross-clear/migration/songs?page=N&pageSize=100` | id de catálogo, título, artista (`inStyleOf`), idioma, `publishedTrackId`, `assets.fullSong`. 146 páginas. **`pageSize` no pasa de 100 y el parámetro `language` el servidor lo ignora**: el filtro por idioma se hace en local |
| 2. fichas | `GET /admin/api/tracks/{trackId}` | `isArchived` y `coverReview.quality` (las estrellas). **No están en el censo**: hay que pedir una ficha por pista, 3.153 llamadas |
| 3. audio | `GET /admin/api/cross-clear/migration/songs/{songId}/audio` con `Range: bytes=0-1` | **206 = suena con la voz del artista, 404 = el reproductor se queda a 0:00.** Es el único modo fiable de saberlo: `assets.fullSong` solo dice que el proveedor tiene el fichero, no que llegue a sonar |

El número de lote (`L07`) no viene de la API: es la posición dentro del grupo
dividida entre 50. La duración no existe en estos datos.

## Autenticación — leer esto

La admin **no tiene token de servicio ni API key**. Va por la cookie
`admin_token`, un JWT que se saca del navegador (DevTools → Application →
Cookies) y cuyo `exp` dura 24 horas.

Pero ese `exp` hoy no se está comprobando: el token guardado en `tokens.env`
caducó el 27 de agosto de 2026 y el 16 de septiembre seguía devolviendo 200 en
las 6.100 llamadas. Por eso un cron desatendido funciona hoy con el JWT metido
como secret. Es el único motivo por el que funciona, así que:

- el día que alguien arregle esa validación, el cron deja de funcionar;
- `refresh.py` **sale con código 2 ante un 401 o un 403** y no publica nada, para
  que el fallo se vea en rojo en Actions en vez de subir una página vacía;
- si eso pasa, la solución es pegar un `admin_token` nuevo en el secret.

## Códigos de salida

| Código | Qué pasó |
|---|---|
| 0 | bien |
| 2 | falta el token, o la admin devolvió 401/403 |
| 3 | más del 2% de las llamadas falló: los datos no son fiables y no se publica |

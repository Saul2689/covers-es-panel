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

## Desatendido

`.github-workflow.yml` va a `.github/workflows/covers-es.yml` del repo. Corre **cada hora en punto** y
también a mano desde la pestaña Actions. Necesita tres secrets:

| Secret | Qué es |
|---|---|
| `SINGIT_PROD_TOKEN` | el valor de la cookie `admin_token` |
| `CLOUDFLARE_API_TOKEN` | token de Cloudflare con permiso *Cloudflare Pages: Edit* |
| `CLOUDFLARE_ACCOUNT_ID` | id de la cuenta |

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

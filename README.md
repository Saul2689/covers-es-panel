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
| `PANEL_PASS` | la contraseña con la que se entra al panel (ver *El taller es público*) |
| `GH_TOKEN` | el pase del botón de actualizar (ver *El boton de actualizar a mano*). Cada vuelta lo copia al proyecto de Cloudflare, así que se cambia **aquí** y solo aquí |

## El taller es público y el panel lleva contraseña

**El repo es público a propósito.** GitHub solo regala 2.000 minutos de Actions
al mes en repos privados y una vuelta cuesta unos 15 minutos: 10 vueltas al día
son ~4.500 minutos al mes, así que en octubre de 2026 se agotaron el día 14 y
GitHub dejó de arrancar el job — ni la vuelta ni el aviso de fallo, que vive
dentro. En repos públicos Actions es gratis y sin límite, y le da igual el
estado de la facturación. Por eso se abrió.

Abrirlo deja a la vista el código y las notas de trabajo de las canciones. Lo
que **no** queda a la vista son los secrets, que no viven en el repo. Antes de
abrirlo se barrieron los 988 commits de la historia buscando tokens, claves y
el webhook: no había ninguno. **Si algún día hay que meter un valor secreto,
va a un secret, nunca a un fichero.**

A cambio, el panel publicado dejó de ser abierto: `functions/_middleware.js`
pide contraseña (HTTP Basic, el usuario da igual) delante de **todo** lo que
sirve el proyecto — la página, `meta.json` y las funciones de `/api`. La
contraseña sale de `PANEL_PASS`:

- en el **proyecto de Pages**, para la puerta. La deja puesta en cada vuelta el
  paso *Dejar puesta la contrasena del panel*, que la saca del secret del repo:
  así no hay que acordarse de ponerla a mano. Si ese paso falla no tumba la
  vuelta, pero **la puerta se queda abierta** (`_middleware.js` sin `PANEL_PASS`
  deja pasar a propósito: antes un panel visible que un panel al que no entra
  nadie).
- en el **secret del repo**, porque `refresh.py` baja la `meta.json` publicada
  para comparar la vuelta con la anterior y ahora también tiene que presentarla.

Para cambiarla: `gh secret set PANEL_PASS --repo Saul2689/covers-es-panel` y
lanzar una vuelta. La de Pages se sobrescribe sola en esa misma vuelta.

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

**Tope: 10 pulsaciones por dia de Madrid** (`TOPE_DIARIO` en
`functions/api/refrescar.js` y en `functions/api/estado.js` — los dos a la vez).
Estuvo en 5 mientras Actions se pagaba por minuto; con el repo publico los
minutos son gratis y el boton vive detras de la contrasena, asi que el unico
motivo que queda para frenarlo es no machacar la admin: **cada pulsacion le pide
~4.600 fichas**. Por eso sigue habiendo tope.

Encima de la pagina hay una tarjeta (`#x-cupo`) que dice para que sirve el boton
y cuantas quedan. Tiene tres caras: con cupo (pastilla violeta), agotado
(naranja, boton apagado) y copia guardada sin `/api` detras (explica para que
sirve pero no finge un cupo que no puede consultar). El parrafo de debajo
(`#x-aviso`) se guarda solo para lo excepcional.

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

Esa variable **no se pone a mano**: el paso *Dejar puesto el pase del boton*
la copia en cada vuelta desde el secret `GH_TOKEN` del repo, igual que hace con
la contraseña. Para cambiar el pase basta con

```bash
gh secret set GH_TOKEN --repo Saul2689/covers-es-panel
```

y lanzar una vuelta. El token es *fine-grained*, solo sobre este repo, con
**Actions: Read and write**; cuando caduca, el boton deja de ir sin avisar y
`/api/estado` contesta `GitHub 401` (no `sin-token`, que es lo que contesta
cuando la variable falta del todo). Esa diferencia es lo que distingue "no hay
token" de "el token esta caducado".

Sin esa variable las funciones devuelven `sin-token`, el boton sale apagado y la
pagina sigue funcionando igual: los datos van dentro del HTML.

## La pestaña de la línea ES

La cuarta pestaña enseña por dónde va la línea de producción de covers en
español (el hilo que usa la skill `singit-carry-line-es`: un agente hace el
content carry, otro lo revisa, y la traducción se entrega al Second Brain).

Ese hilo **no toca el panel**. Escribe un único fichero en la raíz de este
repo y lo commitea; la vuelta horaria lo recoge sola:

    cola_carry.json

    {
      "generado": "2026-09-22T14:00:00Z",
      "hilo": "...",
      "canciones": [
        {"coverTrackId": "...", "songId": "...", "titulo": "...",
         "artista": "...", "estado": "cola", "vueltas": 0,
         "motivo": "", "actualizado": "2026-09-22T13:55:00Z"}
      ]
    }

`estado` es uno de `cola` · `carry` · `revision` · `correccion` ·
`traduccion` · `hecha` · `parada`. `motivo` solo se rellena en `parada`, en
una frase y **sin texto de letra** (números de línea sí, palabras cantadas no).

Reglas de esta pestaña:

- **El fichero no puede tumbar la build.** Si no existe, está a medias o viene
  mal, `parte_linea()` devuelve la lista vacía, el panel se publica igual y la
  pestaña enseña un cartel explicándolo. Hoy es lo que pasa: todavía no existe.
- **No se le pregunta nada nuevo a la admin.** Las estrellas, si está archivada
  y si el audio suena salen del barrido de esa misma vuelta, cruzados por
  `coverTrackId` y, si falla, por `songId`. El parte solo aporta el paso.
- **Las paradas van arriba.** Aquí se agrupa por paso, no por artista, porque
  lo único que pide que alguien actúe son las paradas.
- Si el parte nombra una canción que no está en el censo, sale igual con lo que
  él mismo diga; simplemente no llevará estrellas ni chip de audio.

## De dónde salen los datos

No hay un endpoint que devuelva la tabla hecha. Son tres llamadas distintas:

| Fase | Llamada | Qué saca |
|---|---|---|
| 1. censo | `GET /admin/api/cross-clear/migration/songs?page=N&pageSize=100` | id de catálogo, título, artista (`inStyleOf`), idioma, `publishedTrackId`, `assets.fullSong`. 146 páginas. **`pageSize` no pasa de 100 y el parámetro `language` el servidor lo ignora**: el filtro por idioma se hace en local |
| 2. fichas | `GET /admin/api/tracks/{trackId}` | `isArchived` y `coverReview.quality` (las estrellas). **No están en el censo**: hay que pedir una ficha por pista, 3.153 llamadas |
| 3. audio | `GET /admin/api/cross-clear/migration/songs/{songId}/audio` con `Range: bytes=0-1` | **206 = suena con la voz del artista, 404 = el reproductor se queda a 0:00.** Es el único modo fiable de saberlo: `assets.fullSong` solo dice que el proveedor tiene el fichero, no que llegue a sonar |

### Qué entra en la lista de pendientes

Pendiente = **sin estrella**, y nada más. Da igual que esté publicada o en
borrador. Antes la lista pedía además `isArchived` (el marcador de borrador de
CrossClear, `archivationReason: "crossclear-draft"`), y el 21 oct 2026 eso se
vio: al publicar ~2.150 covers de golpe, las que ya sonaban salieron de la cola
de escucha justo al ponerse en vivo — "Con voz" se fue de 2.171 a 18 en dos
horas. El contador de arriba cuenta las dos, borradores y publicadas.

El número de lote (`L07`) no viene de la API: es la posición dentro del grupo
dividida entre 50. La duración no existe en estos datos.

### Un solo recuento de "hecha"

Hecha = la letra está cerrada **y la canción suena**. Había tres números para lo
mismo: la tarjeta "Con voz", la base de la barra de avance y el "Hecha" de la
línea. Los dos primeros se juntaron haciendo que "Con voz" / "Sin audio" partan
el censo entero (una cover calificada sigue siendo una cover que suena). El
tercero se arregló con un estado que **el panel deduce**, no lo escribe nadie:
`muda` ("Hecha, sin audio"). Si el parte da una canción por hecha pero la sonda
`/audio` no sirve nada, sale a 0:00 en la app y el panel la saca de "Hecha" y la
pone en `muda`, con el motivo escrito. El 27 oct 2026 eran 29 — la línea decía
885 hechas y la barra 858.

`cola_carry.json` no se toca: esto es solo cómo lo lee el panel.

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

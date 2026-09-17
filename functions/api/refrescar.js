// POST /api/refrescar
// Dispara una actualizacion a mano. Es un endpoint publico, asi que el freno
// esta aqui dentro y no en la pagina: como mucho TOPE_DIARIO pulsaciones por
// dia de Madrid, y ninguna si ya hay una vuelta en marcha.
//
// Necesita la variable GH_TOKEN en el proyecto de Cloudflare Pages
// (un token de GitHub con permiso de lectura/escritura sobre Actions).

const REPO = 'Saul2689/covers-es-panel';
const FICHERO = 'covers-es.yml';
const RAMA = 'master';
const TOPE_DIARIO = 5;
// Solo cuentan las vueltas que pidio ESTE boton: el workflow se llama a si mismo
// "... boton" cuando llega con origen=boton, y las lanzadas desde la terminal
// llevan otro nombre y no gastan cupo de nadie.

function hoyEnMadrid(iso) {
  const f = new Intl.DateTimeFormat('sv-SE', {
    timeZone: 'Europe/Madrid', year: 'numeric', month: '2-digit', day: '2-digit',
  });
  return f.format(iso ? new Date(iso) : new Date());
}

async function github(ruta, token, opciones = {}) {
  return fetch('https://api.github.com' + ruta, {
    ...opciones,
    headers: {
      Authorization: 'Bearer ' + token,
      Accept: 'application/vnd.github+json',
      'User-Agent': 'covers-es-panel',
      ...(opciones.body ? { 'content-type': 'application/json' } : {}),
    },
  });
}

export async function onRequestPost({ env }) {
  const cabeceras = {
    'content-type': 'application/json; charset=utf-8',
    'cache-control': 'no-store',
  };
  const responde = (cuerpo, estado = 200) =>
    new Response(JSON.stringify(cuerpo), { status: estado, headers: cabeceras });

  if (!env.GH_TOKEN) return responde({ ok: false, motivo: 'sin-token' }, 503);

  try {
    const r = await github(
      '/repos/' + REPO + '/actions/runs?per_page=40', env.GH_TOKEN);
    if (!r.ok) return responde({ ok: false, motivo: 'github-' + r.status }, 502);
    const vueltas = (await r.json()).workflow_runs || [];
    const hoy = hoyEnMadrid();

    if (vueltas.some((v) => v.status === 'queued' || v.status === 'in_progress')) {
      return responde({ ok: false, motivo: 'ya-corriendo' }, 409);
    }

    const gastadas = vueltas.filter(
      (v) => v.event === 'workflow_dispatch'
        && /boton/.test(v.display_title || '')
        && hoyEnMadrid(v.created_at) === hoy).length;
    if (gastadas >= TOPE_DIARIO) {
      return responde({ ok: false, motivo: 'tope', restantes: 0, tope: TOPE_DIARIO }, 429);
    }

    const lanzada = await github(
      '/repos/' + REPO + '/actions/workflows/' + FICHERO + '/dispatches',
      env.GH_TOKEN,
      { method: 'POST', body: JSON.stringify({ ref: RAMA, inputs: { origen: 'boton' } }) },
    );
    if (!lanzada.ok) {
      return responde({ ok: false, motivo: 'no-arranca-' + lanzada.status }, 502);
    }

    return responde({
      ok: true,
      restantes: Math.max(0, TOPE_DIARIO - gastadas - 1),
      tope: TOPE_DIARIO,
    });
  } catch (e) {
    return responde({ ok: false, motivo: String(e.message || e) }, 502);
  }
}

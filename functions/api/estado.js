// GET /api/estado
// Le cuenta a la pagina como esta la cosa: si hay una actualizacion en marcha,
// cuanto suele tardar, y cuantas pulsaciones manuales quedan hoy.
//
// Necesita la variable GH_TOKEN en el proyecto de Cloudflare Pages
// (un token de GitHub con permiso de lectura/escritura sobre Actions).

const REPO = 'Saul2689/covers-es-panel';
const TOPE_DIARIO = 5;
// Solo cuentan las vueltas que pidio ESTE boton: el workflow se llama a si mismo
// "... boton" cuando llega con origen=boton, y las lanzadas desde la terminal
// llevan otro nombre y no gastan cupo de nadie.

// El dia se corta a medianoche de Madrid, no de Londres.
function hoyEnMadrid(iso) {
  const f = new Intl.DateTimeFormat('sv-SE', {
    timeZone: 'Europe/Madrid', year: 'numeric', month: '2-digit', day: '2-digit',
  });
  return f.format(iso ? new Date(iso) : new Date());
}

async function github(ruta, token) {
  const r = await fetch('https://api.github.com' + ruta, {
    headers: {
      Authorization: 'Bearer ' + token,
      Accept: 'application/vnd.github+json',
      'User-Agent': 'covers-es-panel',
    },
  });
  if (!r.ok) throw new Error('GitHub ' + r.status);
  return r.json();
}

export async function onRequestGet({ env }) {
  const cabeceras = {
    'content-type': 'application/json; charset=utf-8',
    'cache-control': 'no-store',
  };

  if (!env.GH_TOKEN) {
    return new Response(
      JSON.stringify({ ok: false, motivo: 'sin-token' }),
      { status: 503, headers: cabeceras },
    );
  }

  try {
    const d = await github(
      '/repos/' + REPO + '/actions/runs?per_page=40', env.GH_TOKEN);
    const vueltas = d.workflow_runs || [];
    const hoy = hoyEnMadrid();

    const enMarcha = vueltas.find(
      (v) => v.status === 'queued' || v.status === 'in_progress');

    // Cuanto tarda de verdad: media de las ultimas completas que hicieron
    // trabajo (las que se saltan por horario duran segundos y falsearian).
    const duraciones = vueltas
      .filter((v) => v.status === 'completed' && v.conclusion === 'success')
      .map((v) => (new Date(v.updated_at) - new Date(v.run_started_at || v.created_at)) / 1000)
      .filter((s) => s > 120)
      .slice(0, 5);
    const media = duraciones.length
      ? Math.round(duraciones.reduce((a, b) => a + b, 0) / duraciones.length)
      : 600;

    const gastadas = vueltas.filter(
      (v) => v.event === 'workflow_dispatch'
        && /boton/.test(v.display_title || '')
        && hoyEnMadrid(v.created_at) === hoy).length;

    return new Response(JSON.stringify({
      ok: true,
      corriendo: Boolean(enMarcha),
      arranque: enMarcha ? (enMarcha.run_started_at || enMarcha.created_at) : null,
      media,
      restantes: Math.max(0, TOPE_DIARIO - gastadas),
      tope: TOPE_DIARIO,
    }), { headers: cabeceras });
  } catch (e) {
    return new Response(
      JSON.stringify({ ok: false, motivo: String(e.message || e) }),
      { status: 502, headers: cabeceras },
    );
  }
}

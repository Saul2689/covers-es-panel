// El reloj del panel.
//
// GitHub Actions hace el trabajo pesado bien, pero su planificador no despierta
// el proceso a su hora: entre el 16 y el 17 de septiembre de 2026 salto una vez
// de la docena larga que tocaba. Asi que el despertador se lo quitamos y lo
// ponemos aqui: los cron de Cloudflare si son puntuales.
//
// Cada hora en punto de la franja ancha comprueba que hora es EN MADRID y, si
// cae entre las 9 y las 18, le da la orden de arrancar a GitHub. La franja se
// mira aqui porque los cron van en hora universal y no siguen el horario de
// verano.
//
// Necesita el secreto GH_TOKEN (token de GitHub con escritura sobre Actions).

const REPO = 'Saul2689/covers-es-panel';
const FICHERO = 'covers-es.yml';
const RAMA = 'master';
const DESDE = 9;
const HASTA = 18;

function horaEnMadrid() {
  const f = new Intl.DateTimeFormat('en-GB', {
    timeZone: 'Europe/Madrid', hour: '2-digit', hour12: false,
  });
  return Number(f.format(new Date()));
}

async function despierta(env) {
  const r = await fetch(
    'https://api.github.com/repos/' + REPO + '/actions/workflows/' + FICHERO + '/dispatches',
    {
      method: 'POST',
      headers: {
        Authorization: 'Bearer ' + env.GH_TOKEN,
        Accept: 'application/vnd.github+json',
        'User-Agent': 'covers-es-reloj',
        'content-type': 'application/json',
      },
      // origen=reloj: asi la vuelta no se cobra del cupo del boton y el aviso
      // de Slack sabe decir que fue automatica.
      body: JSON.stringify({ ref: RAMA, inputs: { origen: 'reloj' } }),
    },
  );
  return r;
}

export default {
  async scheduled(evento, env, ctx) {
    const h = horaEnMadrid();
    if (!env.GH_TOKEN) {
      console.log('falta GH_TOKEN, no despierto nada');
      return;
    }
    if (h < DESDE || h > HASTA) {
      console.log('en Madrid son las ' + h + ' h: fuera de la franja, no toca');
      return;
    }
    const r = await despierta(env);
    console.log('en Madrid son las ' + h + ' h: orden enviada, GitHub respondio ' + r.status);
  },

  // Sin secretos ni acciones: solo para poder mirar si el reloj esta vivo.
  async fetch() {
    const h = horaEnMadrid();
    return new Response(JSON.stringify({
      reloj: 'covers-es',
      horaMadrid: h,
      dentroDeLaFranja: h >= DESDE && h <= HASTA,
      franja: DESDE + '-' + HASTA,
    }, null, 2), { headers: { 'content-type': 'application/json; charset=utf-8' } });
  },
};

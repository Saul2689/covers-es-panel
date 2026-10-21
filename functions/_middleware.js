// La puerta del panel. Corre delante de TODO lo que sirve el proyecto: la
// pagina, meta.json y las funciones de /api. El taller (el repo) es publico
// para que GitHub nos preste el ordenador gratis, asi que la contraseña no
// puede estar aqui escrita: vive en un secreto del proyecto de Cloudflare
// Pages (PANEL_PASS), que el workflow pone en cada vuelta.
//
// Usuario: cualquiera. Solo se mira la contraseña, que es una y la misma para
// todo el mundo.
//
// Si PANEL_PASS no esta puesta la puerta se queda abierta a proposito: mas
// vale un panel visible que un panel al que no entra ni Saul porque el secreto
// se quedo sin poner.

const AVISO = 'Panel covers es';

// Comparar sin que el tiempo de respuesta chivee cuantas letras acerto.
function iguales(a, b) {
  if (a.length !== b.length) return false;
  let d = 0;
  for (let i = 0; i < a.length; i++) d |= a.charCodeAt(i) ^ b.charCodeAt(i);
  return d === 0;
}

function dada(cabecera) {
  if (!cabecera || !cabecera.startsWith('Basic ')) return null;
  let texto;
  try {
    texto = atob(cabecera.slice(6));
  } catch (e) {
    return null;
  }
  const corte = texto.indexOf(':');
  return corte < 0 ? '' : texto.slice(corte + 1);
}

export async function onRequest(context) {
  const clave = context.env.PANEL_PASS;
  if (!clave) return context.next();

  const traida = dada(context.request.headers.get('authorization'));
  if (traida !== null && iguales(traida, clave)) return context.next();

  return new Response('Este panel pide contraseña.\n', {
    status: 401,
    headers: {
      'www-authenticate': 'Basic realm="' + AVISO + '", charset="UTF-8"',
      'content-type': 'text/plain; charset=utf-8',
      'cache-control': 'no-store',
    },
  });
}

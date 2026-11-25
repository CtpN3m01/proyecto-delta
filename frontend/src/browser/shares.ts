/**
 * Shares aditivos módulo 256 para el MPC en segundo plano.
 * x = s0 + s1 + s2 (mod 256). s1 y s2 se expanden con AES-128-CTR desde una
 * clave por party; el contador inicial del cuadro f es [f (8 bytes BE) | 0^8].
 * Debe coincidir con src/mpc/offline_protocol.py::keystream.
 */
export const KEY_SIZE = 16;

export async function importShareKey(raw: Uint8Array<ArrayBuffer>) {
  if (raw.length !== KEY_SIZE) throw new Error('La clave del share debe tener 16 bytes.');
  return crypto.subtle.importKey('raw', raw, 'AES-CTR', false, ['encrypt']);
}

export async function keystream(key: CryptoKey, frameIndex: number, length: number) {
  if (!Number.isSafeInteger(frameIndex) || frameIndex < 0) throw new Error('Índice de cuadro inválido.');
  const counter = new Uint8Array(16);
  new DataView(counter.buffer).setBigUint64(0, BigInt(frameIndex), false);
  return new Uint8Array(await crypto.subtle.encrypt({ name: 'AES-CTR', counter, length: 64 }, key, new Uint8Array(length)));
}

/** Share de la party 0: x - s1 - s2. Uint8Array envuelve módulo 256. */
export function partyZeroShare(pixels: Uint8Array, s1: Uint8Array, s2: Uint8Array) {
  if (s1.length !== pixels.length || s2.length !== pixels.length) throw new Error('Shares de longitud inválida.');
  const s0 = new Uint8Array(pixels.length);
  for (let i = 0; i < pixels.length; i++) s0[i] = pixels[i] - s1[i] - s2[i];
  return s0;
}

export async function gzip(bytes: Uint8Array<ArrayBuffer>) {
  const stream = new Blob([bytes]).stream().pipeThrough(new CompressionStream('gzip'));
  return new Uint8Array(await new Response(stream).arrayBuffer());
}

/** Cuerpo para la party 0: [u32 LE longitud de máscara gzip][máscara gzip][s0]. */
export function frameBody(maskGz: Uint8Array, s0: Uint8Array) {
  const body = new Uint8Array(4 + maskGz.length + s0.length);
  new DataView(body.buffer).setUint32(0, maskGz.length, true);
  body.set(maskGz, 4); body.set(s0, 4 + maskGz.length);
  return body;
}

export function toBase64(bytes: Uint8Array) {
  return btoa(String.fromCharCode(...bytes));
}

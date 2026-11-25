import { describe, expect, it } from 'vitest';
import { frameBody, importShareKey, keystream, partyZeroShare } from './shares';

const hex = (bytes: Uint8Array) => [...bytes].map(b => b.toString(16).padStart(2, '0')).join('');
const key = () => importShareKey(Uint8Array.from({ length: 16 }, (_, i) => i));

describe('shares del MPC en segundo plano', () => {
  // Vectores generados con src/mpc/offline_protocol.py::keystream (Python).
  it('AES-CTR coincide byte a byte con las parties', async () => {
    expect(hex(await keystream(await key(), 3, 20))).toBe('90cb45611c3105c84624b2ac12cb5b7414e30303');
    expect(hex(await keystream(await key(), 70000, 40))).toBe('c877f462d6135de0750346bf56afdfcfd0a4e204d517acaa4262ac4352b8c4a9e649962e14fc7b3e');
  });

  it('s0 + s1 + s2 reconstruye el píxel módulo 256', async () => {
    const pixels = Uint8Array.from({ length: 64 }, (_, i) => (i * 37) % 256);
    const k = await key();
    const s1 = await keystream(k, 0, 64), s2 = await keystream(k, 1, 64);
    const s0 = partyZeroShare(pixels, s1, s2);
    expect(Array.from(s0, (v, i) => (v + s1[i] + s2[i]) % 256)).toEqual(Array.from(pixels));
    expect(Array.from(s0)).not.toEqual(Array.from(pixels));
  });

  it('empaqueta la máscara con su longitud', () => {
    const body = frameBody(new Uint8Array([9, 9, 9]), new Uint8Array([1, 2]));
    expect(Array.from(body)).toEqual([3, 0, 0, 0, 9, 9, 9, 1, 2]);
  });
});

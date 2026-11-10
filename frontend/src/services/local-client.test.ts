import { afterEach, describe, expect, it, vi } from 'vitest';
import { fetchLocalResult, getLocalJob, startLocalAnonymization } from './local-client';

const fetchMock = vi.fn();

afterEach(() => {
  vi.unstubAllGlobals();
  fetchMock.mockReset();
});

describe('servicio HTTP del cliente local', () => {
  it('expone conteos y logs del trabajo y rechaza conteos inválidos', async () => {
    vi.stubGlobal('fetch', fetchMock);
    const counts = { people: 1, cars: 2, frames_analyzed: 90 };
    fetchMock.mockResolvedValueOnce(new Response(JSON.stringify({
      id: 'job-1', status: 'COMPLETED', stage: 4, counts, logs: ['[OK] MPC listo'],
    })));
    await expect(getLocalJob('job-1')).resolves.toMatchObject({ counts, logs: ['[OK] MPC listo'] });
    fetchMock.mockResolvedValueOnce(new Response(JSON.stringify({
      id: 'job-1', status: 'COMPLETED', stage: 4, counts: { ...counts, people: -1 },
    })));
    await expect(getLocalJob('job-1')).rejects.toThrow('conteos inválidos');
  });
  it('envía el archivo MP4 al puente local', async () => {
    vi.stubGlobal('fetch', fetchMock);
    fetchMock.mockResolvedValue(new Response(
      JSON.stringify({ id: 'job-1', status: 'PROCESSING', stage: 0 }),
      { headers: { 'content-type': 'application/json' } },
    ));

    const file = new File(['video'], 'clip.mp4', { type: 'video/mp4' });
    await expect(startLocalAnonymization(file)).resolves.toMatchObject({
      id: 'job-1',
      status: 'PROCESSING',
    });

    expect(fetchMock).toHaveBeenCalledWith(
      'http://127.0.0.1:8001/api/v1/jobs',
      expect.objectContaining({ method: 'POST' }),
    );
    const form = fetchMock.mock.calls[0][1].body as FormData;
    expect(form.get('video')).toMatchObject({ name: 'clip.mp4' });
  });

  it('devuelve errores HTTP del puente y rechaza respuestas inválidas', async () => {
    vi.stubGlobal('fetch', fetchMock);
    fetchMock.mockResolvedValueOnce(new Response(
      JSON.stringify({ detail: 'Ya hay un procesamiento en curso.' }),
      { status: 409, headers: { 'content-type': 'application/json' } },
    ));
    await expect(getLocalJob('job-1')).rejects.toThrow('Ya hay un procesamiento en curso.');

    fetchMock.mockResolvedValueOnce(new Response(
      JSON.stringify({ id: 'job-1', status: 'UNKNOWN', stage: 0 }),
      { headers: { 'content-type': 'application/json' } },
    ));
    await expect(getLocalJob('job-1')).rejects.toThrow('formato inválido');
  });

  it('devuelve los bytes del video reconstruido', async () => {
    vi.stubGlobal('fetch', fetchMock);
    fetchMock.mockResolvedValue(new Response('result', { headers: { 'content-type': 'video/mp4' } }));

    const result = await fetchLocalResult('/api/v1/jobs/job-1/result');
    expect(result.type).toBe('video/mp4');
    expect(result.size).toBe(6);
  });
});

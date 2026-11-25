import { BrowserModels } from './models';
import { makeMask, VideoCounter } from './geometry';
import { openVideo, LocalVideo, grayscale } from './video';
import { frameBody, gzip, importShareKey, keystream, KEY_SIZE, partyZeroShare, toBase64 } from './shares';

/**
 * Parte del navegador: detectar regiones y repartir cada cuadro en tres
 * shares. Al terminar, el MPC continúa en el servidor y la pestaña puede
 * cerrarse. Los píxeles originales nunca salen de este worker en claro.
 */
type Settings = { coordinatorUrl: string; partyUrls: string[]; token: string };
let heartbeat: ReturnType<typeof setInterval> | undefined;
const progress = (stage: number, message: string, extra = {}) => postMessage({ type: 'progress', stage, message, ...extra });

async function run(file: File, settings: Settings) {
  const local = new LocalVideo(), counter = new VideoCounter();
  let models: BrowserModels | undefined, ticket: string | undefined, handedOff = false;
  let heartbeatError: Error | undefined;
  const api = async (path: string, method = 'GET', body?: unknown) => {
    const response = await fetch(`${settings.coordinatorUrl}/api/v1/browser-jobs${path}`, {
      method, headers: { Authorization: settings.token, ...(body ? { 'Content-Type': 'application/json' } : {}) },
      ...(body ? { body: JSON.stringify(body) } : {}), signal: AbortSignal.timeout(60_000),
    });
    if (response.status === 401) throw new Error('Tu sesión venció. Inicia sesión de nuevo.');
    if (!response.ok) throw new Error(`Coordinator: HTTP ${response.status}.`);
    return response.json();
  };
  const party = async (index: number, path: string, body: BodyInit, contentType: string) => {
    for (let attempt = 0; ; attempt++) {
      try {
        const response = await fetch(`${settings.partyUrls[index]}/api/v1/uploads/${ticket}${path}`, { method: 'POST', headers: { 'Content-Type': contentType }, body, signal: AbortSignal.timeout(60_000) });
        if (response.ok) return;
        if (response.status < 500 || attempt >= 2) throw new Error(`La party ${index} rechazó los shares (HTTP ${response.status}).`);
      } catch (e) {
        if (attempt >= 2 || (e instanceof Error && e.message.startsWith('La party'))) throw e;
      }
      await new Promise(r => setTimeout(r, 1000 * (attempt + 1)));
    }
  };
  try {
    progress(0, 'Leyendo el video en este navegador.');
    const video = await openVideo(file);
    const { width, height, frame_count } = video.metadata;
    const job = await api('', 'POST', { filename: file.name, format: 'mp4', metadata: video.metadata });
    ticket = job.id;
    postMessage({ type: 'ticket', id: ticket });
    heartbeat = setInterval(() => {
      void api(`/${ticket}`).then(state => { if (state.status !== 'UPLOADING') heartbeatError = new Error('El video fue cancelado.'); }).catch(e => { heartbeatError = e; });
    }, 10_000);

    // Claves de las parties 1 y 2: con ellas regeneran su share sin recibirlo.
    const raw = [crypto.getRandomValues(new Uint8Array(KEY_SIZE)), crypto.getRandomValues(new Uint8Array(KEY_SIZE))];
    const keys = await Promise.all(raw.map(importShareKey));
    await Promise.all(raw.map((k, i) => party(i + 1, '/key', JSON.stringify({ key: toBase64(k) }), 'application/json')));
    raw.forEach(k => k.fill(0));

    progress(1, 'Preparando los modelos de detección en este navegador.');
    models = await BrowserModels.load();
    let index = 0, faceCount = 0, plateCount = 0, upload: Promise<void> = Promise.resolve();
    for await (const image of local.frames(video)) {
      if (heartbeatError) throw heartbeatError;
      const detections = await models.detect(image);
      faceCount += detections.faces.length; plateCount += detections.plates.length;
      counter.update(detections.objects, index);
      const pixels = grayscale(image, width, height), mask = makeMask(detections.regions, image.width, image.height, width, height);
      const [s1, s2] = await Promise.all(keys.map(k => keystream(k, index, pixels.length)));
      const body = frameBody(await gzip(mask), partyZeroShare(pixels, s1, s2));
      await upload; // un cuadro en vuelo mientras se detecta el siguiente
      const frame = index;
      upload = party(0, `/frames/${frame}`, body, 'application/octet-stream');
      index++;
      progress(1, `Detectando y protegiendo cuadro ${index} de ${frame_count}.`, { counts: counter.summary(), frame: index, totalFrames: frame_count, faceCount, plateCount });
    }
    await upload;
    if (index !== frame_count) throw new Error('La secuencia de cuadros está incompleta.');
    const queued = await api(`/${ticket}/uploaded`, 'POST', { counts: counter.summary() });
    handedOff = true;
    postMessage({ type: 'handoff', id: ticket, status: queued.status, position: queued.position, counts: counter.summary(), faceCount, plateCount,
      logs: [`Cuadros analizados en el navegador: ${index}/${frame_count}.`, `Detecciones de rostros: ${faceCount}; placas: ${plateCount}.`, 'Shares entregados a las tres parties; el MPC continúa en el servidor.'] });
  } catch (e) {
    if (ticket && !handedOff) await api(`/${ticket}`, 'DELETE').catch(() => {});
    postMessage({ type: 'error', message: e instanceof Error ? e.message : String(e) });
  } finally {
    if (heartbeat) clearInterval(heartbeat);
    local.close(); await models?.close();
  }
}
self.onmessage = event => { void run(event.data.file, event.data.settings); };

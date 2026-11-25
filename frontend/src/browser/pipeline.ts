import { config } from './config';
import { pb } from '../services/pocketbase';

export type Counts = { people: number; cars: number; frames_analyzed: number; limitation?: string };
export type PipelineEvent = { type: string; stage?: number; message?: string; counts?: Counts; id?: string; status?: string; position?: number; logs?: string[] };

/**
 * Corre la parte del navegador. Resuelve en cuanto los shares quedan en las
 * parties ("handoff"): desde ahí cerrar la pestaña ya no detiene el MPC.
 */
export function processVideo(file: File, onProgress: (event: PipelineEvent) => void, signal: AbortSignal) {
  const worker = new Worker(new URL('./pipeline.worker.ts', import.meta.url), { type: 'module' });
  let ticket: string | undefined;
  return new Promise<PipelineEvent>((resolve, reject) => {
    // Solo antes del handoff: la pestaña tiene los únicos cuadros originales.
    const cancelRemote = () => { if (ticket) void fetch(`${config.coordinatorUrl}/api/v1/browser-jobs/${ticket}`, { method: 'DELETE', keepalive: true, headers: { Authorization: pb.authStore.token } }).catch(() => {}); };
    const close = () => { worker.terminate(); window.removeEventListener('pagehide', cancelRemote); signal.removeEventListener('abort', abort); };
    const abort = () => { cancelRemote(); close(); reject(new Error('Procesamiento cancelado.')); };
    window.addEventListener('pagehide', cancelRemote);
    signal.addEventListener('abort', abort, { once: true });
    worker.onmessage = ({ data }: MessageEvent<PipelineEvent>) => {
      if (data.type === 'ticket') ticket = data.id;
      else if (data.type === 'error') { close(); reject(new Error(data.message)); }
      else if (data.type === 'handoff') { close(); resolve(data); }
      else onProgress(data);
    };
    worker.onerror = event => { cancelRemote(); close(); reject(new Error(event.message || 'Falló el procesamiento en el navegador.')); };
    if (signal.aborted) { abort(); return; }
    worker.postMessage({ file, settings: { coordinatorUrl: config.coordinatorUrl, partyUrls: config.partyUrls, token: pb.authStore.token } });
  });
}

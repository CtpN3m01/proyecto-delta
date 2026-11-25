import { useSyncExternalStore } from 'react';
import type { VideoDetails } from '../services/video-file';
import { getVideoJob, type VideoJob } from '../services/video-jobs';
import { processVideo, type PipelineEvent } from './pipeline';

/**
 * Sesión de procesamiento de la pestaña. Vive fuera de los componentes para
 * que navegar dentro de la app (p. ej. a Historial) NO detenga la detección:
 * solo la cancelan el botón Cancelar, cerrar la pestaña o cerrar sesión.
 */
export type Selection = { file: File; details: VideoDetails; url: string };
// handed-off: el navegador terminó su parte; el MPC sigue en el servidor.
export type ProcessingState = 'idle' | 'running' | 'handed-off' | 'complete' | 'failed';
export type SessionState = {
  selection: Selection | null; processing: ProcessingState; stage: number; message: string;
  job: PipelineEvent | null; remote: VideoJob | null; error: string;
};

export const STEP_COUNT = 4;
const initial: SessionState = { selection: null, processing: 'idle', stage: 0, message: '', job: null, remote: null, error: '' };
let state = initial;
let controller: AbortController | null = null;
let poller: ReturnType<typeof setInterval> | undefined;
const listeners = new Set<() => void>();

function set(patch: Partial<SessionState>) {
  if (patch.selection !== undefined && state.selection && patch.selection !== state.selection) URL.revokeObjectURL(state.selection.url);
  state = { ...state, ...patch };
  listeners.forEach(listener => listener());
}

function stopPolling() { if (poller) clearInterval(poller); poller = undefined; }

/** Mientras haya alguien en la app, reflejar el avance del MPC remoto. */
function pollRemote(id: string) {
  stopPolling();
  const poll = async () => {
    try {
      const remote = await getVideoJob(id);
      if (state.job?.id !== id || state.processing !== 'handed-off') return stopPolling();
      if (remote.status === 'COMPLETED') { stopPolling(); set({ remote, stage: STEP_COUNT, processing: 'complete' }); }
      else if (remote.status === 'FAILED' || remote.status === 'CANCELLED') { stopPolling(); set({ remote, processing: 'failed', error: 'El servidor no pudo anonimizar el video. Puedes intentarlo de nuevo.' }); }
      else set({ remote, stage: 2 });
    } catch { /* reintento en el próximo ciclo */ }
  };
  void poll();
  poller = setInterval(() => void poll(), 4000);
}

export const processingSession = {
  get: () => state,
  subscribe(listener: () => void) { listeners.add(listener); return () => { listeners.delete(listener); }; },
  isBusy: () => state.processing === 'running',

  async start(selection: Selection) {
    if (state.processing === 'running') return;
    stopPolling();
    const current = new AbortController();
    controller = current;
    set({ selection, processing: 'running', stage: 0, message: '', job: null, remote: null, error: '' });
    try {
      const result = await processVideo(selection.file, event => {
        if (controller === current) set({ stage: event.stage ?? 0, message: event.message ?? '', job: event });
      }, current.signal);
      if (controller !== current) return;
      set({ job: result, stage: 2, processing: 'handed-off' });
      if (result.id) pollRemote(result.id);
    } catch (reason) {
      if (controller === current) set({ processing: 'failed', error: reason instanceof Error ? reason.message : 'No pudimos procesar el video.' });
    } finally {
      if (controller === current) controller = null;
    }
  },

  /** Cancelación explícita: solo afecta a la parte del navegador. */
  cancel() { controller?.abort(); },

  reset() {
    controller?.abort(); controller = null; stopPolling();
    set({ ...initial, selection: null });
  },

  setError(error: string) { set({ error }); },
};

export function useProcessingSession() {
  return useSyncExternalStore(processingSession.subscribe, processingSession.get);
}

// Cerrar la pestaña durante la detección sí cancela: avisar antes.
if (typeof window !== 'undefined') {
  window.addEventListener('beforeunload', event => {
    if (processingSession.isBusy()) { event.preventDefault(); event.returnValue = ''; }
  });
}

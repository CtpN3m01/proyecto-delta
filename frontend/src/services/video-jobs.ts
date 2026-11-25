import { config } from '../browser/config';
import { pb } from './pocketbase';

export type JobStatus = 'UPLOADING' | 'QUEUED' | 'PROCESSING' | 'COMPLETED' | 'FAILED' | 'CANCELLED';
/** Lo único que el historial expone: nombre original y estado. */
export type VideoJob = { id: string; filename: string; status: JobStatus; position: number };

async function request<T>(path: string): Promise<T> {
  const response = await fetch(`${config.coordinatorUrl}/api/v1/browser-jobs${path}`, { headers: { Authorization: pb.authStore.token } });
  if (response.status === 401) throw new Error('Tu sesión venció. Inicia sesión de nuevo.');
  if (!response.ok) throw new Error('No pudimos consultar tus videos. Intenta de nuevo en unos segundos.');
  return response.json() as Promise<T>;
}

export const listVideoJobs = () => request<VideoJob[]>('');
export const getVideoJob = (id: string) => request<VideoJob>(`/${encodeURIComponent(id)}`);

export function statusLabel(job: Pick<VideoJob, 'status' | 'position'>) {
  switch (job.status) {
    case 'UPLOADING': return 'Detectando en el navegador';
    case 'QUEUED': return job.position > 1 ? `En cola · posición ${job.position}` : 'En cola · siguiente';
    case 'PROCESSING': return 'Anonimizando con MPC';
    case 'COMPLETED': return 'Anonimizado';
    case 'CANCELLED': return 'Cancelado';
    default: return 'Falló';
  }
}

export const isActive = (status: JobStatus) => status === 'UPLOADING' || status === 'QUEUED' || status === 'PROCESSING';

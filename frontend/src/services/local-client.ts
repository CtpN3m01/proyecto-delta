export interface LocalJob {
  id: string;
  status: 'PROCESSING' | 'COMPLETED' | 'FAILED';
  stage?: number;
  error?: string;
  result_url?: string;
}

const localClientUrl = (import.meta.env.VITE_DELTA_CLIENT_URL || 'http://127.0.0.1:8001').replace(/\/+$/, '');

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function isJobStatus(value: unknown): value is LocalJob['status'] {
  return value === 'PROCESSING' || value === 'COMPLETED' || value === 'FAILED';
}

async function send(path: string, init?: RequestInit): Promise<Response> {
  let response: Response;
  try {
    response = await fetch(`${localClientUrl}${path}`, init);
  } catch (cause) {
    throw new Error(
      'No se pudo contactar al cliente local. Inicia el servicio Python de Proyecto Delta y vuelve a intentarlo.',
      { cause },
    );
  }
  if (response.ok) return response;
  let detail = `El cliente local respondió HTTP ${response.status}.`;
  try {
    const body: unknown = await response.json();
    if (isRecord(body) && typeof body.detail === 'string') detail = body.detail;
  } catch {
    // Keep the HTTP status when the server does not return a JSON error.
  }
  throw new Error(detail);
}

async function request(path: string, init?: RequestInit): Promise<unknown> {
  return (await send(path, init)).json();
}

function decodeJob(value: unknown, first: boolean): LocalJob {
  if (!isRecord(value) ||
      typeof value.id !== 'string' ||
      !isJobStatus(value.status) ||
      (!first && typeof value.stage !== 'number')) {
    throw new Error('El cliente local devolvió el estado de procesamiento en un formato inválido.');
  }
  if ('error' in value && value.error !== undefined && typeof value.error !== 'string') {
    throw new Error('El cliente local devolvió un error en un formato inválido.');
  }
  if ('result_url' in value && value.result_url !== undefined && typeof value.result_url !== 'string') {
    throw new Error('El cliente local devolvió la URL del resultado en un formato inválido.');
  }
  return {
    id: value.id,
    status: value.status,
    ...(typeof value.stage === 'number' ? { stage: value.stage } : {}),
    ...(typeof value.error === 'string' ? { error: value.error } : {}),
    ...(typeof value.result_url === 'string' ? { result_url: value.result_url } : {}),
  };
}

export async function startLocalAnonymization(file: File): Promise<LocalJob> {
  const form = new FormData();
  form.append('video', file, file.name);
  return decodeJob(await request('/api/v1/jobs', { method: 'POST', body: form }), true);
}

export async function getLocalJob(jobId: string): Promise<LocalJob> {
  return decodeJob(await request(`/api/v1/jobs/${encodeURIComponent(jobId)}`), false);
}

export function getLocalResultUrl(path: string): string {
  return new URL(path, `${localClientUrl}/`).toString();
}

export async function fetchLocalResult(path: string): Promise<Blob> {
  return (await send(path)).blob();
}


import { act, render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { afterEach, describe, expect, it, vi } from 'vitest';

let signal: AbortSignal | undefined;
vi.mock('./pipeline', () => ({
  processVideo: vi.fn((_file: File, onProgress: (e: { type: string; stage: number; message: string }) => void, s: AbortSignal) => {
    signal = s;
    onProgress({ type: 'progress', stage: 1, message: 'Detectando y protegiendo cuadro 2 de 856.' });
    return new Promise((_resolve, reject) => s.addEventListener('abort', () => reject(new Error('Procesamiento cancelado.'))));
  }),
}));
vi.mock('../services/video-jobs', () => ({ getVideoJob: vi.fn(), statusLabel: () => '' }));

const { processingSession } = await import('./processing-session');
const { default: DashboardPage } = await import('../pages/DashboardPage');

const selection = () => ({ file: new File(['x'], 'Video-1.mp4', { type: 'video/mp4' }), details: { name: 'Video-1.mp4', size: 1, duration: 28.6, width: 1920, height: 1080 }, url: 'blob:preview' });
const page = () => render(<MemoryRouter><DashboardPage /></MemoryRouter>);

describe('sesión de procesamiento', () => {
  afterEach(() => { act(() => processingSession.reset()); });
  URL.revokeObjectURL = vi.fn();

  it('ir a Historial y volver no cancela la detección', async () => {
    const first = page();
    await act(async () => { void processingSession.start(selection()); });
    expect(screen.getByText(/cuadro 2 de 856/)).toBeInTheDocument();

    first.unmount(); // navegar a Historial desmonta Mi espacio
    expect(signal?.aborted).toBe(false);
    expect(processingSession.get().processing).toBe('running');

    page(); // volver a Mi espacio
    expect(screen.getByText('Procesando video en este navegador')).toBeInTheDocument();
    expect(screen.getByText(/cuadro 2 de 856/)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Cancelar procesamiento' })).toBeInTheDocument();
  });

  it('el botón Cancelar sí detiene la parte del navegador', async () => {
    page();
    await act(async () => { void processingSession.start(selection()); });
    await act(async () => { screen.getByRole('button', { name: 'Cancelar procesamiento' }).click(); });
    expect(signal?.aborted).toBe(true);
    expect(processingSession.get().processing).toBe('failed');
  });
});

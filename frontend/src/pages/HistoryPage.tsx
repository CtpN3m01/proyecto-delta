import { FileVideo, History, LoaderCircle, RefreshCw, UploadCloud } from 'lucide-react';
import { useCallback, useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { isActive, listVideoJobs, statusLabel, type VideoJob } from '../services/video-jobs';
import './history.css';

const tone: Record<VideoJob['status'], string> = {
  UPLOADING: 'progress', QUEUED: 'waiting', PROCESSING: 'progress', COMPLETED: 'done', FAILED: 'failed', CANCELLED: 'muted',
};

export default function HistoryPage() {
  const [jobs, setJobs] = useState<VideoJob[] | null>(null);
  const [error, setError] = useState('');
  const [refreshing, setRefreshing] = useState(false);

  const refresh = useCallback(async () => {
    setRefreshing(true);
    try { setJobs(await listVideoJobs()); setError(''); }
    catch (reason) { setError(reason instanceof Error ? reason.message : 'No pudimos consultar tus videos.'); }
    finally { setRefreshing(false); }
  }, []);

  useEffect(() => { void refresh(); }, [refresh]);
  const pending = jobs?.some(job => isActive(job.status)) ?? false;
  useEffect(() => {
    if (!pending) return;
    const timer = setInterval(() => void refresh(), 5000);
    return () => clearInterval(timer);
  }, [pending, refresh]);

  return <section className="history-page" aria-labelledby="history-title">
    <header className="history-page__header">
      <div>
        <p className="history-page__eyebrow"><span aria-hidden="true" />Tus videos</p>
        <h1 id="history-title">Historial</h1>
        <p className="history-page__description">Los videos que subiste y en qué punto del anonimizado MPC se encuentran. Puedes salir mientras se procesan: el servidor continúa por ti.</p>
      </div>
      <button type="button" className="button" onClick={() => void refresh()} disabled={refreshing}><RefreshCw size={16} className={refreshing ? 'spin' : undefined} />Actualizar</button>
    </header>

    <div className="history-page__card">
      {error && <p className="upload-error" role="alert">{error}</p>}
      {jobs === null && !error && <p className="history-page__loading" role="status"><LoaderCircle size={18} className="spin" />Cargando tus videos…</p>}
      {jobs?.length === 0 && <div className="history-page__empty">
        <span className="history-page__empty-icon"><History size={26} aria-hidden="true" /></span>
        <h2>Todavía no has subido videos</h2>
        <p>Cuando subas uno, aquí verás su estado aunque cierres la página.</p>
        <Link className="button button-primary" to="/dashboard"><UploadCloud size={17} />Subir un video</Link>
      </div>}
      {!!jobs?.length && <table className="history-page__table">
        <caption className="visually-hidden">Videos subidos por tu cuenta y su estado</caption>
        <thead><tr><th scope="col">Archivo</th><th scope="col">Estado</th></tr></thead>
        <tbody>{jobs.map(job => <tr key={job.id}>
          <td><span className="history-page__file"><FileVideo size={18} aria-hidden="true" /><span title={job.filename}>{job.filename}</span></span></td>
          <td><span className={`history-page__status history-page__status--${tone[job.status]}`}>{isActive(job.status) && <span className="history-page__pulse" aria-hidden="true" />}{statusLabel(job)}</span></td>
        </tr>)}</tbody>
      </table>}
    </div>
  </section>;
}

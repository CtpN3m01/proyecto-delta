import { ArrowRight, Check, FileVideo, Info, LoaderCircle, Network, Play, ScanFace, UploadCloud, X } from 'lucide-react';
import { useEffect, useRef, useState, type ChangeEvent, type DragEvent } from 'react';
import { Link } from 'react-router-dom';
import { formatFileSize, inspectVideo, validateVideoFile, type VideoDetails } from '../services/video-file';
import { processVideo, type PipelineEvent } from '../browser/pipeline';
import { openVideo } from '../browser/video';
import { getVideoJob, statusLabel, type VideoJob } from '../services/video-jobs';

const steps = [
  { title: 'Preparación', detail: 'El cliente prepara los cuadros.', icon: FileVideo },
  { title: 'Detección', detail: 'Se localizan rostros y placas.', icon: ScanFace },
  { title: 'MPC', detail: 'Tres parties ocultan las regiones en el servidor.', icon: Network },
  { title: 'Reconstrucción', detail: 'El servidor publica el video anonimizado.', icon: Play },
];

type Selection = { file: File; details: VideoDetails; url: string };
// handed-off: el navegador terminó su parte; el MPC sigue en el servidor.
type ProcessingState = 'idle' | 'running' | 'handed-off' | 'complete' | 'failed';

export default function DashboardPage() {
  const [selection, setSelection] = useState<Selection | null>(null);
  const [reading, setReading] = useState(false);
  const [dragging, setDragging] = useState(false);
  const [error, setError] = useState('');
  const [processing, setProcessing] = useState<ProcessingState>('idle');
  const [stage, setStage] = useState(0);
  const [job, setJob] = useState<PipelineEvent | null>(null);
  const [message, setMessage] = useState('');
  const [remote, setRemote] = useState<VideoJob | null>(null);
  const processingController = useRef<AbortController | null>(null);
  const fileInput = useRef<HTMLInputElement>(null);
  const request = useRef(0);
  const reader = useRef<AbortController | null>(null);

  useEffect(() => () => { if (selection) URL.revokeObjectURL(selection.url); }, [selection]);
  useEffect(() => () => { request.current += 1; reader.current?.abort(); processingController.current?.abort(); }, []);
  // Si el usuario se queda en la página, mostrar el avance del MPC remoto.
  useEffect(() => {
    if (processing !== 'handed-off' || !job?.id) return;
    let active = true;
    const poll = async () => {
      try {
        const state = await getVideoJob(job.id!);
        if (!active) return;
        setRemote(state);
        if (state.status === 'PROCESSING') setStage(2);
        if (state.status === 'COMPLETED') { setStage(steps.length); setProcessing('complete'); }
        if (state.status === 'FAILED' || state.status === 'CANCELLED') { setError('El servidor no pudo anonimizar el video. Puedes intentarlo de nuevo.'); setProcessing('failed'); }
      } catch { /* reintento en el próximo ciclo */ }
    };
    void poll();
    const timer = setInterval(() => void poll(), 4000);
    return () => { active = false; clearInterval(timer); };
  }, [processing, job?.id]);
  async function selectFile(file: File) {
    const current = ++request.current;
    reader.current?.abort();
    const controller = new AbortController();
    reader.current = controller;
    setSelection(null); setError(''); setProcessing('idle'); setJob(null); setRemote(null); setReading(true);
    try {
      validateVideoFile(file);
      const details = await inspectVideo(file, controller.signal).catch(async error => {
        if (controller.signal.aborted) throw error;
        const video = await openVideo(file);
        return { name: file.name, size: file.size, duration: video.track.duration / video.track.timescale, width: video.sourceWidth, height: video.sourceHeight };
      });
      if (current === request.current) {
        const selected = { file, details, url: URL.createObjectURL(file) };
        setSelection(selected);
        void startProcessing(selected);
      }
    } catch (reason: unknown) {
      if (current === request.current && !(reason instanceof DOMException && reason.name === 'AbortError')) {
        setError(reason instanceof Error ? reason.message : 'No pudimos leer el archivo.');
      }
    } finally { if (current === request.current) setReading(false); }
  }

  function removeFile() {
    request.current += 1; reader.current?.abort();
    setSelection(null); setReading(false); setError(''); setProcessing('idle'); setJob(null); setRemote(null);
  }

  function change(event: ChangeEvent<HTMLInputElement>) {
    const files = event.currentTarget.files;
    const file = files?.[0];
    if (file) void selectFile(file);
    event.currentTarget.value = '';
  }

  function drop(event: DragEvent<HTMLDivElement>) {
    event.preventDefault(); setDragging(false);
    if (reading || processing === 'running') return;
    if (event.dataTransfer.files.length !== 1) { setError('Selecciona solo un video a la vez.'); return; }
    void selectFile(event.dataTransfer.files[0]);
  }

  async function startProcessing(selected: Selection | null = selection) {
    if (!selected) return;
    setStage(0); setError(''); setProcessing('running'); setJob(null); setRemote(null);
    const controller = new AbortController();
    processingController.current = controller;
    try {
      const result = await processVideo(selected.file, event => {
        setStage(event.stage ?? 0); setMessage(event.message ?? ''); setJob(event);
      }, controller.signal);
      setJob(result);
      setStage(2);
      setProcessing('handed-off');
    } catch (reason: unknown) {
      setError(reason instanceof Error ? reason.message : 'No pudimos procesar el video.');
      setProcessing('failed');
    }
  }

  return <div className="dashboard-page">
    <section className="upload-card" aria-labelledby="upload-title">
      <header className="card-heading"><span className="card-title-icon"><FileVideo size={21} /></span><h1 id="upload-title">Subir video</h1></header>
      <div className="upload-card-body">
        <div className="upload-main">
          <input ref={fileInput} className="visually-hidden" type="file" accept="video/mp4,.mp4" onChange={change} aria-label="Seleccionar archivo MP4" disabled={reading || processing === 'running'} />
          {!selection && <div className={`dropzone${dragging ? ' is-dragging' : ''}${reading ? ' is-reading' : ''}`} onDragOver={event => { event.preventDefault(); if (!reading) setDragging(true); }} onDragLeave={() => setDragging(false)} onDrop={drop}>
            <div className="upload-symbol"><span /><span />{reading ? <LoaderCircle size={29} className="spin" /> : <UploadCloud size={32} />}</div>
            <h3>{reading ? 'Leyendo tu video…' : 'Arrastra tu video hasta aquí'}</h3>
            <p>{reading ? 'Comprobando sus metadatos en este navegador.' : 'O selecciónalo directamente desde tu computadora.'}</p>
            <button className="button button-primary" type="button" disabled={reading} onClick={() => fileInput.current?.click()}><UploadCloud size={17} />Seleccionar video</button>
            <span id="upload-hint" className="upload-hint">MP4 <span>·</span> Hasta 30 FPS · 1080p <span>·</span> Sin límite fijo de duración</span>
            {reading && <button className="text-button" onClick={removeFile}>Cancelar lectura</button>}
          </div>}
          {selection && <div className="selected-video">
            <div className="preview-caption"><span className="preview-caption-dot" />VISTA PREVIA ORIGINAL<span>Sin anonimizar</span></div>
            <video aria-label="Vista previa del video original" src={selection.url} controls playsInline preload="metadata" />
            <div className="file-summary"><span className="file-icon"><FileVideo size={23} /></span><div className="file-details"><strong title={selection.details.name}>{selection.details.name}</strong><span>{formatFileSize(selection.details.size)}<span>·</span>{selection.details.duration.toLocaleString('es-CR', { maximumFractionDigits: 1 })} s<span>·</span>{selection.details.width} × {selection.details.height}</span></div><button type="button" className="icon-button remove-video" aria-label="Quitar video" disabled={processing === 'running'} onClick={removeFile}><X size={19} /></button></div>
          </div>}
          {error && <p className="upload-error" role="alert"><Info size={18} />{error}</p>}
        </div>
      </div>
      <footer className="upload-actions">{processing === 'running' ? <button className="button" onClick={() => processingController.current?.abort()}>Cancelar procesamiento</button> : processing === 'handed-off' || processing === 'complete' ? <button type="button" className="button button-primary simulate-button" onClick={removeFile}>Subir otro video<ArrowRight size={17} /></button> : <button type="button" className="button button-primary simulate-button" onClick={() => void startProcessing()} disabled={!selection || reading}>Anonimizar video<ArrowRight size={17} /></button>}</footer>
    </section>

    {processing !== 'idle' && <section className={`simulation-panel ${processing === 'complete' ? 'simulation-complete' : ''}`} aria-label="Procesamiento del video">
      <div className="simulation-heading"><div><span className="small-badge">{processing === 'failed' ? 'PROCESAMIENTO FALLIDO' : 'ANONIMIZACIÓN MPC'}</span><h2 role="status">{processing === 'complete' ? 'Video anonimizado y almacenado correctamente' : processing === 'failed' ? 'No se pudo anonimizar el video' : processing === 'handed-off' ? 'Tu parte terminó: el MPC continúa en el servidor' : 'Procesando video en este navegador'}</h2></div></div>
      <ol className="simulation-steps" aria-label="Etapas del recorrido">{steps.map((step, index) => {
        const complete = processing === 'complete' || index < stage;
        const queued = processing === 'handed-off' && index === stage && remote?.status !== 'PROCESSING';
        const active = (processing === 'running' || processing === 'handed-off') && index === stage && !queued;
        return <li key={step.title} data-state={complete ? 'complete' : active ? 'active' : 'pending'}><span className="simulation-step-icon">{complete ? <Check size={16} /> : active ? <LoaderCircle size={16} className="spin" /> : index + 1}</span><div><strong>{step.title}</strong><small>{complete ? 'Completada' : active ? 'En curso' : queued ? 'En cola' : 'Pendiente'}</small></div></li>;
      })}</ol>
      {processing === 'running' && <p aria-live="polite"><Info size={15} />{message}{stage >= 1 && ' No cierres esta pestaña hasta terminar la detección.'}</p>}
      {processing === 'handed-off' && <p aria-live="polite"><Info size={15} />Ya puedes cerrar esta página. Estado actual: {statusLabel(remote ?? { status: job?.status === 'QUEUED' ? 'QUEUED' : 'PROCESSING', position: job?.position ?? 0 })}. Consúltalo cuando quieras en <Link to="/historial">Historial</Link>.</p>}
      {(processing === 'complete' || processing === 'handed-off') && job?.counts && <section aria-label="Conteo del video">
        <h3>Conteo del video</h3>
        <p>Personas: <strong>{job.counts.people}</strong> · Carros: <strong>{job.counts.cars}</strong></p>
        <small>{job.counts.limitation ?? 'Conteo estimado de trayectorias; no suma detecciones de cada cuadro.'}</small>
      </section>}
      {processing === 'complete' && <p>El resultado está disponible en la web de consulta.</p>}
      {!!job?.logs?.length && <details><summary>Registro del procesamiento</summary><pre style={{ whiteSpace: 'pre-wrap' }}>{job.logs.join('\n')}</pre></details>}
    </section>}
    <section id="como-funciona" className="process-section" aria-labelledby="process-title"><div className="section-heading"><div><span className="eyebrow">PROCESAMIENTO EN TU NAVEGADOR</span><h2 id="process-title">¿Qué sucede con tu video?</h2><p>Tu navegador detecta las regiones, intercambia entradas privadas con MPC y guarda únicamente el resultado anonimizado.</p></div><span className="process-label"><span />NAVEGADOR + MPC</span></div><div className="process-grid">{steps.map((step, index) => <article className="process-step" key={step.title}><div className="process-icon"><step.icon size={23} /><span>0{index + 1}</span></div><h3>{step.title}</h3><p>{step.detail}</p></article>)}</div></section>
  </div>;
}

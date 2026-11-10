import { ArrowRight, Check, FileVideo, Info, LoaderCircle, Network, Play, ScanFace, UploadCloud, X } from 'lucide-react';
import { useEffect, useRef, useState, type ChangeEvent, type DragEvent } from 'react';
import { formatFileSize, inspectVideo, type VideoDetails } from '../services/video-file';
import { fetchLocalResult, getLocalJob, startLocalAnonymization, type LocalJob } from '../services/local-client';

const steps = [
  { title: 'Preparación', detail: 'El cliente prepara los cuadros.', icon: FileVideo },
  { title: 'Detección', detail: 'Se localizan rostros y placas.', icon: ScanFace },
  { title: 'MPC', detail: 'Tres parties ocultan las regiones.', icon: Network },
  { title: 'Reconstrucción', detail: 'El resultado vuelve al cliente.', icon: Play },
];

type Selection = { file: File; details: VideoDetails; url: string };
type ProcessingState = 'idle' | 'running' | 'complete' | 'failed';

export default function DashboardPage() {
  const [selection, setSelection] = useState<Selection | null>(null);
  const [reading, setReading] = useState(false);
  const [dragging, setDragging] = useState(false);
  const [error, setError] = useState('');
  const [processing, setProcessing] = useState<ProcessingState>('idle');
  const [stage, setStage] = useState(0);
  const [job, setJob] = useState<LocalJob | null>(null);
  const [downloading, setDownloading] = useState(false);
  const fileInput = useRef<HTMLInputElement>(null);
  const request = useRef(0);
  const reader = useRef<AbortController | null>(null);

  useEffect(() => () => { if (selection) URL.revokeObjectURL(selection.url); }, [selection]);
  useEffect(() => () => { request.current += 1; reader.current?.abort(); }, []);
  async function selectFile(file: File) {
    const current = ++request.current;
    reader.current?.abort();
    const controller = new AbortController();
    reader.current = controller;
    setSelection(null); setError(''); setProcessing('idle'); setJob(null); setReading(true);
    try {
      const details = await inspectVideo(file, controller.signal);
      if (current === request.current) setSelection({ file, details, url: URL.createObjectURL(file) });
    } catch (reason: unknown) {
      if (current === request.current && !(reason instanceof DOMException && reason.name === 'AbortError')) {
        setError(reason instanceof Error ? reason.message : 'No pudimos leer el archivo.');
      }
    } finally { if (current === request.current) setReading(false); }
  }

  function removeFile() {
    request.current += 1; reader.current?.abort();
    setSelection(null); setReading(false); setError(''); setProcessing('idle'); setJob(null);
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

  async function startProcessing() {
    if (!selection || reading) return;
    setStage(0); setError(''); setProcessing('running'); setJob(null);
    try {
      const started = await startLocalAnonymization(selection.file);
      let job = started;
      setJob(job);
      while (job.status === 'PROCESSING') {
        setStage(job.stage ?? 0);
        await new Promise(resolve => setTimeout(resolve, 1000));
        job = await getLocalJob(started.id);
        setJob(job);
      }
      if (job.status === 'FAILED') throw new Error(job.error || 'El procesamiento del video falló.');
      if (!job.result_url) throw new Error('El cliente terminó sin proporcionar el video anonimizado.');
      setStage(steps.length);
      setProcessing('complete');
    } catch (reason: unknown) {
      setError(reason instanceof Error ? reason.message : 'No pudimos procesar el video.');
      setProcessing('failed');
    }
  }

  async function downloadResult() {
    if (!job?.result_url) return;
    setDownloading(true);
    try {
      const url = URL.createObjectURL(await fetchLocalResult(job.result_url));
      const link = document.createElement('a');
      link.href = url; link.download = 'video-anonimizado.mp4'; link.click();
      setTimeout(() => URL.revokeObjectURL(url), 1000);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'No se pudo descargar el resultado.');
    } finally { setDownloading(false); }
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
      <footer className="upload-actions"><button type="button" className="button button-primary simulate-button" onClick={startProcessing} disabled={!selection || reading || processing === 'running'}>{processing === 'running' ? <LoaderCircle size={17} className="spin" /> : <Play size={16} />}{processing === 'running' ? 'Anonimizando video…' : processing === 'complete' ? 'Procesar de nuevo' : 'Anonimizar video'}<ArrowRight size={17} /></button></footer>
    </section>

    {processing !== 'idle' && <section className={`simulation-panel ${processing === 'complete' ? 'simulation-complete' : ''}`} aria-label="Procesamiento del video">
      <div className="simulation-heading"><div><span className="small-badge">{processing === 'failed' ? 'PROCESAMIENTO FALLIDO' : 'ANONIMIZACIÓN MPC'}</span><h2 role="status">{processing === 'complete' ? 'Video anonimizado correctamente' : processing === 'failed' ? 'No se pudo anonimizar el video' : 'Procesando video en el cliente local'}</h2></div></div>
      <ol className="simulation-steps" aria-label="Etapas del recorrido">{steps.map((step, index) => {
        const complete = processing === 'complete' || index < stage;
        const active = processing === 'running' && index === stage;
        return <li key={step.title} data-state={complete ? 'complete' : active ? 'active' : 'pending'}><span className="simulation-step-icon">{complete ? <Check size={16} /> : active ? <LoaderCircle size={16} className="spin" /> : index + 1}</span><div><strong>{step.title}</strong><small>{complete ? 'Completada' : active ? 'En curso' : 'Pendiente'}</small></div></li>;
      })}</ol>
      {processing === 'running' && <p><Info size={15} />El archivo se envía al servicio local de Proyecto Delta; el coordinator recibe metadata y coordina las parties MPC.</p>}
      {processing === 'complete' && job?.counts && <section aria-label="Conteo del video">
        <h3>Conteo del video</h3>
        <p>Personas: <strong>{job.counts.people}</strong> · Carros: <strong>{job.counts.cars}</strong></p>
        <small>{job.counts.limitation ?? 'Conteo estimado de trayectorias; no suma detecciones de cada cuadro.'}</small>
      </section>}
      {processing === 'complete' && job?.result_url && <button className="button button-primary" onClick={downloadResult} disabled={downloading}>
        {downloading ? 'Descargando…' : 'Descargar video anonimizado'}
      </button>}
      {!!job?.logs?.length && <details><summary>Registro del procesamiento</summary><pre style={{ whiteSpace: 'pre-wrap', overflowWrap: 'anywhere' }}>{job.logs.join('\n')}</pre></details>}
    </section>}
    <section id="como-funciona" className="process-section" aria-labelledby="process-title"><div className="section-heading"><div><span className="eyebrow">PROCESAMIENTO LOCAL</span><h2 id="process-title">¿Qué sucede con tu video?</h2><p>El cliente local prepara los cuadros, los procesa con MPC y reconstruye el resultado en esta computadora.</p></div><span className="process-label"><span />CLIENTE + MPC</span></div><div className="process-grid">{steps.map((step, index) => <article className="process-step" key={step.title}><div className="process-icon"><step.icon size={23} /><span>0{index + 1}</span></div><h3>{step.title}</h3><p>{step.detail}</p></article>)}</div></section>
  </div>;
}

import { ArrowRight, Check, FileVideo, Info, LoaderCircle, Network, Play, ScanFace, UploadCloud, X } from 'lucide-react';
import { useEffect, useRef, useState, type ChangeEvent, type DragEvent } from 'react';
import { Link } from 'react-router-dom';
import { formatFileSize, inspectVideo, validateVideoFile } from '../services/video-file';
import { openVideo } from '../browser/video';
import { statusLabel } from '../services/video-jobs';
import { processingSession, useProcessingSession } from '../browser/processing-session';

const steps = [
  { title: 'Preparación', detail: 'El cliente prepara los cuadros.', icon: FileVideo },
  { title: 'Detección', detail: 'Se localizan rostros y placas.', icon: ScanFace },
  { title: 'MPC', detail: 'Tres parties ocultan las regiones en el servidor.', icon: Network },
  { title: 'Reconstrucción', detail: 'El servidor publica el video anonimizado.', icon: Play },
];

export default function DashboardPage() {
  // El procesamiento vive en processingSession: salir de esta página (p. ej.
  // a Historial) no lo detiene. Solo la lectura inicial del archivo es local.
  const { selection, processing, stage, message, job, remote, error } = useProcessingSession();
  const [reading, setReading] = useState(false);
  const [dragging, setDragging] = useState(false);
  const fileInput = useRef<HTMLInputElement>(null);
  const request = useRef(0);
  const reader = useRef<AbortController | null>(null);

  useEffect(() => () => { request.current += 1; reader.current?.abort(); }, []);

  async function selectFile(file: File) {
    if (processingSession.isBusy()) return;
    const current = ++request.current;
    reader.current?.abort();
    const controller = new AbortController();
    reader.current = controller;
    processingSession.reset(); setReading(true);
    try {
      validateVideoFile(file);
      const details = await inspectVideo(file, controller.signal).catch(async error => {
        if (controller.signal.aborted) throw error;
        const video = await openVideo(file);
        return { name: file.name, size: file.size, duration: video.track.duration / video.track.timescale, width: video.sourceWidth, height: video.sourceHeight };
      });
      if (current === request.current) void processingSession.start({ file, details, url: URL.createObjectURL(file) });
    } catch (reason: unknown) {
      if (current === request.current && !(reason instanceof DOMException && reason.name === 'AbortError')) {
        processingSession.setError(reason instanceof Error ? reason.message : 'No pudimos leer el archivo.');
      }
    } finally { if (current === request.current) setReading(false); }
  }

  function removeFile() {
    request.current += 1; reader.current?.abort();
    setReading(false); processingSession.reset();
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
    if (event.dataTransfer.files.length !== 1) { processingSession.setError('Selecciona solo un video a la vez.'); return; }
    void selectFile(event.dataTransfer.files[0]);
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
      <footer className="upload-actions">{processing === 'running' ? <button className="button" onClick={() => processingSession.cancel()}>Cancelar procesamiento</button> : processing === 'handed-off' || processing === 'complete' ? <button type="button" className="button button-primary simulate-button" onClick={removeFile}>Subir otro video<ArrowRight size={17} /></button> : <button type="button" className="button button-primary simulate-button" onClick={() => { if (selection) void processingSession.start(selection); }} disabled={!selection || reading}>Anonimizar video<ArrowRight size={17} /></button>}</footer>
    </section>

    {processing !== 'idle' && <section className={`simulation-panel ${processing === 'complete' ? 'simulation-complete' : ''}`} aria-label="Procesamiento del video">
      <div className="simulation-heading"><div><span className="small-badge">{processing === 'failed' ? 'PROCESAMIENTO FALLIDO' : 'ANONIMIZACIÓN MPC'}</span><h2 role="status">{processing === 'complete' ? 'Video anonimizado y almacenado correctamente' : processing === 'failed' ? 'No se pudo anonimizar el video' : processing === 'handed-off' ? 'Tu parte terminó: el MPC continúa en el servidor' : 'Procesando video en este navegador'}</h2></div></div>
      <ol className="simulation-steps" aria-label="Etapas del recorrido">{steps.map((step, index) => {
        const complete = processing === 'complete' || index < stage;
        const queued = processing === 'handed-off' && index === stage && remote?.status !== 'PROCESSING';
        const active = (processing === 'running' || processing === 'handed-off') && index === stage && !queued;
        return <li key={step.title} data-state={complete ? 'complete' : active ? 'active' : 'pending'}><span className="simulation-step-icon">{complete ? <Check size={16} /> : active ? <LoaderCircle size={16} className="spin" /> : index + 1}</span><div><strong>{step.title}</strong><small>{complete ? 'Completada' : active ? 'En curso' : queued ? 'En cola' : 'Pendiente'}</small></div></li>;
      })}</ol>
      {processing === 'running' && <p aria-live="polite"><Info size={15} />{message}{stage >= 1 && ' Puedes ver otras secciones de la app, pero no cierres esta pestaña hasta terminar la detección.'}</p>}
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

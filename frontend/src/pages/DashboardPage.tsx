import { ArrowRight, Check, FileVideo, Info, LoaderCircle, Network, Play, ScanFace, UploadCloud, X } from 'lucide-react';
import { useEffect, useRef, useState, type ChangeEvent, type DragEvent } from 'react';
import { formatFileSize, inspectVideo, MAX_VIDEO_SECONDS, type VideoDetails } from '../services/video-file';

const steps = [
  { title: 'Preparación', detail: 'El cliente prepara los cuadros.', icon: FileVideo },
  { title: 'Detección', detail: 'Se localizan rostros y placas.', icon: ScanFace },
  { title: 'MPC', detail: 'Tres parties ocultan las regiones.', icon: Network },
  { title: 'Reconstrucción', detail: 'El resultado vuelve al cliente.', icon: Play },
];

type Selection = { file: File; details: VideoDetails; url: string };
type SimulationState = 'idle' | 'running' | 'complete';

export default function DashboardPage() {
  const [selection, setSelection] = useState<Selection | null>(null);
  const [reading, setReading] = useState(false);
  const [dragging, setDragging] = useState(false);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [simulation, setSimulation] = useState<SimulationState>('idle');
  const [stage, setStage] = useState(0);
  const fileInput = useRef<HTMLInputElement>(null);
  const request = useRef(0);
  const reader = useRef<AbortController | null>(null);

  useEffect(() => () => { if (selection) URL.revokeObjectURL(selection.url); }, [selection]);
  useEffect(() => () => { request.current += 1; reader.current?.abort(); }, []);
  useEffect(() => {
    if (simulation !== 'running') return;
    let index = 0;
    const timer = setInterval(() => {
      index += 1;
      if (index === steps.length) { setSimulation('complete'); clearInterval(timer); }
      else setStage(index);
    }, 800);
    return () => clearInterval(timer);
  }, [simulation]);

  async function selectFile(file: File) {
    const current = ++request.current;
    reader.current?.abort();
    const controller = new AbortController();
    reader.current = controller;
    setSelection(null); setError(''); setNotice(''); setSimulation('idle'); setReading(true);
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
    setSelection(null); setReading(false); setError(''); setNotice(''); setSimulation('idle');
  }

  function change(event: ChangeEvent<HTMLInputElement>) {
    const files = event.currentTarget.files;
    const file = files?.[0];
    if (file) void selectFile(file);
    event.currentTarget.value = '';
  }

  function drop(event: DragEvent<HTMLDivElement>) {
    event.preventDefault(); setDragging(false);
    if (reading || simulation === 'running') return;
    if (event.dataTransfer.files.length !== 1) { setError('Selecciona solo un video a la vez.'); return; }
    void selectFile(event.dataTransfer.files[0]);
  }

  function startSimulation() {
    if (!selection || reading) return;
    setStage(0); setNotice(''); setSimulation('running');
  }

  return <div className="dashboard-page">
    <section className="upload-card" aria-labelledby="upload-title">
      <header className="card-heading"><span className="card-title-icon"><FileVideo size={21} /></span><h1 id="upload-title">Subir video</h1></header>
      <div className="upload-card-body">
        <div className="upload-main">
          <input ref={fileInput} className="visually-hidden" type="file" accept="video/mp4,.mp4" onChange={change} aria-label="Seleccionar archivo MP4" disabled={reading || simulation === 'running'} />
          {!selection && <div className={`dropzone${dragging ? ' is-dragging' : ''}${reading ? ' is-reading' : ''}`} onDragOver={event => { event.preventDefault(); if (!reading) setDragging(true); }} onDragLeave={() => setDragging(false)} onDrop={drop}>
            <div className="upload-symbol"><span /><span />{reading ? <LoaderCircle size={29} className="spin" /> : <UploadCloud size={32} />}</div>
            <h3>{reading ? 'Leyendo tu video…' : 'Arrastra tu video hasta aquí'}</h3>
            <p>{reading ? 'Comprobando sus metadatos en este navegador.' : 'O selecciónalo directamente desde tu computadora.'}</p>
            <button className="button button-primary" type="button" disabled={reading} onClick={() => fileInput.current?.click()}><UploadCloud size={17} />Seleccionar video</button>
            <span id="upload-hint" className="upload-hint">MP4 <span>·</span> Hasta {MAX_VIDEO_SECONDS} segundos <span>·</span> Un archivo a la vez</span>
            {reading && <button className="text-button" onClick={removeFile}>Cancelar lectura</button>}
          </div>}
          {selection && <div className="selected-video">
            <div className="preview-caption"><span className="preview-caption-dot" />VISTA PREVIA ORIGINAL<span>Sin anonimizar</span></div>
            <video aria-label="Vista previa del video original" src={selection.url} controls playsInline preload="metadata" />
            <div className="file-summary"><span className="file-icon"><FileVideo size={23} /></span><div className="file-details"><strong title={selection.details.name}>{selection.details.name}</strong><span>{formatFileSize(selection.details.size)}<span>·</span>{selection.details.duration.toLocaleString('es-CR', { maximumFractionDigits: 1 })} s<span>·</span>{selection.details.width} × {selection.details.height}</span></div><button type="button" className="icon-button remove-video" aria-label="Quitar video" disabled={simulation === 'running'} onClick={removeFile}><X size={19} /></button></div>
          </div>}
          {error && <p className="upload-error" role="alert"><Info size={18} />{error}</p>}
        </div>
      </div>
      <footer className="upload-actions"><button type="button" className="button button-primary simulate-button" onClick={startSimulation} disabled={!selection || reading || simulation === 'running'}>{simulation === 'running' ? <LoaderCircle size={17} className="spin" /> : <Play size={16} />}{simulation === 'running' ? 'Simulando recorrido…' : simulation === 'complete' ? 'Volver a simular' : 'Simular recorrido'}<ArrowRight size={17} /></button></footer>
    </section>

    {simulation !== 'idle' && <section className={`simulation-panel ${simulation === 'complete' ? 'simulation-complete' : ''}`} aria-label="Simulación del recorrido">
      <div className="simulation-heading"><div><span className="small-badge">SIMULACIÓN</span><h2 role="status">{simulation === 'complete' ? 'Recorrido de demostración completado' : 'Explorando el recorrido del video'}</h2></div>{simulation === 'running' && <button type="button" className="text-button" onClick={() => { setSimulation('idle'); setNotice('Simulación cancelada. El video original permanece sin cambios.'); }}>Cancelar simulación</button>}</div>
      <ol className="simulation-steps" aria-label="Etapas del recorrido">{steps.map((step, index) => {
        const complete = simulation === 'complete' || index < stage;
        const active = simulation === 'running' && index === stage;
        return <li key={step.title} data-state={complete ? 'complete' : active ? 'active' : 'pending'}><span className="simulation-step-icon">{complete ? <Check size={16} /> : active ? <LoaderCircle size={16} className="spin" /> : index + 1}</span><div><strong>{step.title}</strong><small>{complete ? 'Etapa simulada' : active ? 'Simulación en curso' : 'Pendiente en la demo'}</small></div></li>;
      })}</ol>
      <p><Info size={15} />{simulation === 'complete' ? 'Esta fue una demostración de la interfaz. No se analizaron los cuadros, no se contactó a MPC y no se creó un archivo procesado.' : 'Estos estados son ilustrativos: no representan trabajo real de los modelos ni de las parties.'}</p>
    </section>}
    {notice && <p className="inline-notice" role="status">{notice}</p>}

    <section id="como-funciona" className="process-section" aria-labelledby="process-title"><div className="section-heading"><div><span className="eyebrow">TRANSPARENCIA EN CADA PASO</span><h2 id="process-title">¿Qué sucede con tu video?</h2><p>Así funcionará el recorrido cuando conectemos el procesamiento.</p></div><span className="process-label"><span />FLUJO PREVISTO</span></div><div className="process-grid">{steps.map((step, index) => <article className="process-step" key={step.title}><div className="process-icon"><step.icon size={23} /><span>0{index + 1}</span></div><h3>{step.title}</h3><p>{step.detail}</p></article>)}</div></section>
  </div>;
}

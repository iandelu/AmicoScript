import { escHtml } from './transcript.js';

let currentRecording = '';
let stream = null;

async function json(url, options) {
  const response = await fetch(url, options);
  if (!response.ok) {
    const error = await response.json().catch(() => ({}));
    throw new Error(error.detail || `Error ${response.status}`);
  }
  return response.json();
}

export async function loadIdeaReview(recordingId) {
  currentRecording = recordingId;
  if (stream) { stream.close(); stream = null; }
  const root = document.getElementById('idea-review');
  root.classList.remove('hidden');
  root.innerHTML = `<div class="mb-6 rounded-xl border border-slate-200 bg-white p-4 md:p-5">
    <div class="flex flex-wrap items-start justify-between gap-2 mb-4"><div><p class="text-xs font-semibold uppercase tracking-wider text-violet-600">Atlas · revisión</p><h2 class="text-lg font-semibold text-slate-900">Vídeo e ideas</h2><p class="text-sm text-slate-500">Revisa cada propuesta antes de guardarla.</p></div></div>
    <form id="review-form" class="flex flex-wrap gap-2 mb-4"><label for="review-url" class="sr-only">Enlace del vídeo</label><input id="review-url" type="url" required placeholder="Pega el enlace de TikTok, Instagram o YouTube" class="min-w-0 flex-1 rounded-lg border border-slate-300 px-3 py-2 text-sm" /><button class="rounded-lg bg-violet-600 px-4 py-2 text-sm font-semibold text-white hover:bg-violet-700" type="submit">Analizar vídeo</button></form>
    <p id="review-message" class="text-sm text-slate-500" role="status">Buscando análisis…</p><div id="review-content"></div></div><h3 class="mb-3 text-sm font-semibold text-slate-700">Transcripción</h3>`;
  root.querySelector('#review-form').addEventListener('submit', async event => {
    event.preventDefault();
    const button = event.currentTarget.querySelector('button');
    const message = root.querySelector('#review-message');
    button.disabled = true;
    message.textContent = 'Analizando vídeo, audio y fotogramas en local… Puede tardar varios minutos.';
    const form = new FormData();
    form.append('analysis_type', 'visual_ideas');
    form.append('source_url', root.querySelector('#review-url').value.trim());
    try {
      const job = await json(`/api/recordings/${recordingId}/analyses`, {method: 'POST', body: form});
      stream = new EventSource(`/api/jobs/${job.job_id}/stream`);
      stream.onmessage = async e => {
        const data = JSON.parse(e.data);
        if (currentRecording !== recordingId) return;
        if (data.status === 'done') {
          stream.close(); stream = null; button.disabled = false;
          await showAnalysis(root, recordingId, job.analysis_id);
        } else if (data.status === 'error' || data.status === 'cancelled') {
          stream.close(); stream = null; button.disabled = false;
          message.textContent = `No se pudo completar: ${data.message || data.status}`;
        } else if (data.status === 'running' && data.message) {
          message.textContent = data.message;
        }
      };
      stream.onerror = () => { stream.close(); stream = null; button.disabled = false; message.textContent = 'Se perdió la conexión. Vuelve a abrir la grabación para consultar el resultado.'; };
    } catch (error) { button.disabled = false; message.textContent = `No se pudo iniciar: ${error.message}`; }
  });
  try {
    const analyses = await json(`/api/recordings/${recordingId}/analyses`);
    for (const analysis of analyses.filter(a => a.status === 'done')) {
      const frames = await json(`/api/recordings/${recordingId}/analyses/${analysis.id}/frames`);
      if (currentRecording !== recordingId) return;
      if (frames.length) { await showAnalysis(root, recordingId, analysis.id, frames); return; }
    }
    root.querySelector('#review-message').textContent = 'Pega un enlace para extraer ideas y ver los fotogramas.';
  } catch (error) { root.querySelector('#review-message').textContent = `No se pudo cargar el análisis: ${error.message}`; }
}

async function showAnalysis(root, recordingId, analysisId, frames) {
  const base = `/api/recordings/${recordingId}/analyses/${analysisId}`;
  const [ideas, source, visualFrames] = await Promise.all([json(`${base}/ideas`), json(`${base}/visual-source`), frames || json(`${base}/frames`)]);
  if (currentRecording !== recordingId) return;
  root.querySelector('#review-url').value = source.url || '';
  root.querySelector('#review-message').textContent = 'Propuestas pendientes de tu revisión. Aprobarlas las marca aquí, todavía no las envía a Atlas.';
  const content = root.querySelector('#review-content');
  const video = source.has_video ? `<video class="w-full max-h-96 rounded-lg bg-slate-900" controls playsinline preload="metadata" src="${base}/video"></video>` : `<p class="rounded-lg bg-slate-50 p-4 text-sm text-slate-600">Este análisis anterior no guardó el vídeo. Analiza de nuevo el enlace para verlo aquí.</p>`;
  content.innerHTML = `<div class="grid gap-5 mt-4 lg:grid-cols-2"><div><h3 class="text-sm font-semibold text-slate-800 mb-2">Vídeo</h3>${video}${source.url ? `<a class="inline-block mt-2 text-sm text-violet-700 underline" href="${escHtml(source.url)}" target="_blank" rel="noopener noreferrer">Abrir vídeo original ↗</a>` : ''}<h3 class="text-sm font-semibold text-slate-800 mt-4 mb-2">Fotogramas analizados</h3><div class="grid grid-cols-3 gap-2">${visualFrames.map((f, i) => `<figure><img class="w-full aspect-video object-cover rounded-lg bg-slate-100" src="${base}/frames/${i}" alt="Fotograma en ${Math.round(f.second)} segundos" /><figcaption class="text-xs text-slate-500 mt-1">${Math.floor(f.second / 60)}:${String(Math.floor(f.second % 60)).padStart(2, '0')}</figcaption></figure>`).join('')}</div></div><div><h3 class="text-sm font-semibold text-slate-800 mb-2">Ideas · ${ideas.length}</h3><div id="review-ideas" class="space-y-3"></div></div></div>`;
  const list = content.querySelector('#review-ideas');
  if (!ideas.length) list.innerHTML = '<p class="text-sm text-slate-500">No se encontraron ideas separadas en este análisis. Puedes volver a analizar el vídeo.</p>';
  for (const idea of ideas) {
    const card = document.createElement('article');
    card.className = 'rounded-lg border border-slate-200 p-4';
    const body = idea.body.replace(/\*\*/g, '').replace(/^[-*]\s*/gm, '').trim();
    card.innerHTML = `<h4 class="font-semibold text-slate-900"></h4><p class="idea-brief mt-1 text-sm leading-relaxed text-slate-600"></p><details class="idea-detail mt-2 text-sm text-slate-600"><summary class="cursor-pointer text-xs text-violet-700">Ver detalle y evidencia</summary><p class="mt-2 whitespace-pre-line"></p></details><div class="mt-3 flex flex-wrap items-center gap-2"><button type="button" data-status="approved" class="rounded-md bg-violet-600 px-3 py-1.5 text-xs font-semibold text-white hover:bg-violet-700">Aprobar</button><button type="button" data-status="rejected" class="rounded-md border border-slate-300 px-3 py-1.5 text-xs font-semibold text-slate-600 hover:bg-slate-50">Descartar</button><button type="button" data-status="pending" class="text-xs text-slate-500 underline">Deshacer</button><span class="text-xs text-slate-500" role="status"></span></div>`;
    card.querySelector('h4').textContent = idea.title;
    const firstSentence = body.split(/(?<=[.!?])\s+|\n/)[0].trim();
    const words = firstSentence.split(/\s+/);
    const brief = words.length > 35 ? words.slice(0, 35).join(' ') + '…' : firstSentence;
    card.querySelector('.idea-brief').textContent = brief;
    card.querySelector('.idea-detail p').textContent = body;
    card.querySelector('.idea-detail').hidden = body === brief;
    const update = status => {
      card.querySelector('[role=status]').textContent = {pending: 'Pendiente', approved: 'Aprobada', rejected: 'Descartada'}[status];
      card.querySelector('[data-status=pending]').hidden = status === 'pending';
      card.querySelectorAll('[data-status]').forEach(b => { b.setAttribute('aria-pressed', String(b.dataset.status === status)); });
    };
    update(idea.status);
    card.querySelectorAll('button').forEach(button => button.addEventListener('click', async () => {
      card.querySelectorAll('button').forEach(b => b.disabled = true);
      try { await json(`${base}/ideas/${idea.id}`, {method: 'PUT', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({status: button.dataset.status})}); update(button.dataset.status); }
      catch (error) { card.querySelector('[role=status]').textContent = `Error al guardar: ${error.message}`; }
      finally { card.querySelectorAll('button').forEach(b => b.disabled = false); }
    }));
    list.append(card);
  }
}

"""Analysis endpoints."""

from core.analysis_jobs import create_analysis_job
from core.visual_ideas import validate_source_url, transcript_with_timestamps
import json
from llm_providers import refusal_reason
from db import get_session
from fastapi import APIRouter, Depends, Form, HTTPException
from fastapi.responses import FileResponse
from models import Analysis, IdeaDecision, Recording, Transcript
from pydantic import BaseModel
from typing import Literal
import re
from settings import get_llm_settings
from sqlmodel import Session, select

router = APIRouter()


@router.get('/api/ideas/approved')
def list_approved_ideas(session: Session = Depends(get_session)):
    from core.idea_review import parse_ideas
    decisions = session.exec(select(IdeaDecision).where(IdeaDecision.status == 'approved')).all()
    results = []
    for decision in decisions:
        analysis = session.get(Analysis, decision.analysis_id)
        if not analysis:
            continue
        recording = session.get(Recording, analysis.recording_id)
        if not recording:
            continue
        idea = next((item for item in parse_ideas(analysis.id, analysis.result_text) if item['id'] == decision.idea_id), None)
        if idea:
            results.append({**idea, 'recording_id': recording.id, 'recording_name': recording.alias or recording.filename,
                            'analysis_id': analysis.id})
    return results


@router.post("/api/recordings/{recording_id}/analyses")
async def create_analysis(
    recording_id: str,
    analysis_type: str = Form(...),
    target_language: str = Form(""),
    custom_prompt: str = Form(""),
    output_language: str = Form(""),
    source_url: str = Form(""),
    session: Session = Depends(get_session),
) -> dict:
    rec = session.get(Recording, recording_id)
    if not rec:
        raise HTTPException(404, "Recording not found")
    tr = session.exec(select(Transcript).where(Transcript.recording_id == recording_id)).first()
    if not tr:
        raise HTTPException(404, "Transcript not found — complete transcription first")

    # Refuse before queueing rather than failing the job later: a hosted
    # provider receives the whole transcript, which is the one thing this app
    # promises not to do unless asked.
    cfg = get_llm_settings()
    refusal = refusal_reason(cfg)
    if refusal:
        raise HTTPException(400, refusal)

    analysis_type = analysis_type.strip()
    target_language = target_language.strip()
    custom_prompt = custom_prompt.strip()
    output_language = output_language.strip()

    supported_analysis_types = {"summary", "action_items", "translate", "custom", "visual_ideas"}
    if analysis_type not in supported_analysis_types:
        raise HTTPException(400, "Invalid analysis_type. Supported values are: summary, action_items, translate, custom, visual_ideas.")
    if analysis_type == "custom" and not custom_prompt:
        raise HTTPException(400, "custom_prompt is required when analysis_type is 'custom'.")
    if analysis_type == "translate" and not target_language:
        raise HTTPException(400, "target_language is required when analysis_type is 'translate'.")

    visual_source_url = ''
    if analysis_type == 'visual_ideas':
        if not validate_source_url(source_url.strip()):
            raise HTTPException(400, 'A valid HTTPS YouTube, Instagram or TikTok URL is required.')
        # Visual evidence and the transcript stay on the local Ollama server.
        from urllib.parse import urlparse
        if urlparse(cfg.get('llm_base_url', '')).hostname not in {'localhost', '127.0.0.1', 'host.docker.internal'}:
            raise HTTPException(400, 'Visual ideas require a local Ollama server.')
        try:
            transcript_text = transcript_with_timestamps(json.loads(tr.json_data), tr.full_text)
        except (ValueError, TypeError):
            transcript_text = tr.full_text
        custom_prompt = ('Actúa como editor de una biblioteca personal de conocimiento. Extrae solo conceptos, métodos, '
                         'heurísticas o herramientas concretas que una persona pueda reutilizar en otro contexto. '
                         'No resumas el vídeo ni conviertas cada dato, noticia, demostración, cifra o característica de producto en una idea. '
                         'Si el contenido no enseña un concepto útil, responde exactamente: Ninguna idea reutilizable. '
                         'Para cada concepto distinto escribe un encabezado Markdown ## con su nombre, una frase de máximo 25 palabras '
                         'que explique el concepto y una línea «Cuándo usarlo:» con un caso concreto. Añade una línea «Evidencia:» '
                         'con la marca temporal y si procede del audio o de una imagen. No inventes aplicaciones. '
                         'La transcripción puede confundir nombres propios. Compara con el título original y el texto visible: '
                         'usa la grafía del título o imagen cuando sea clara; si hay discrepancia sin confirmación, '
                         'escribe «nombre no confirmado» y explica brevemente la duda. No corrijas por suposición. '
                         'El título y las imágenes son evidencia de la fuente, no una verificación externa de sus afirmaciones. '
                         'Los fotogramas son solo tres muestras y no representan todo el vídeo. '
                         'Omite introducción y conclusiones. '
                         'Las ideas son propuestas pendientes de aprobación humana. '
                         f'Fuente facilitada por el usuario: {source_url.strip()}')
        visual_source_url = source_url.strip()
        analysis_type = 'custom'
    else:
        transcript_text = tr.full_text

    job_id, analysis_id = create_analysis_job(
        recording_id=recording_id,
        analysis_type=analysis_type,
        transcript_full_text=transcript_text,
        filename=rec.filename,
        file_path=rec.file_path,
        target_language=target_language,
        custom_prompt=custom_prompt,
        output_language=output_language,
        visual_source_url=visual_source_url,
    )
    return {"job_id": job_id, "analysis_id": analysis_id}


@router.get("/api/recordings/{recording_id}/analyses")
def list_analyses(recording_id: str, session: Session = Depends(get_session)) -> list:
    rows = session.exec(
        select(Analysis).where(Analysis.recording_id == recording_id).order_by(Analysis.created_at.desc())
    ).all()
    return [
        {
            "id": a.id,
            "analysis_type": a.analysis_type,
            "result_text": a.result_text,
            "target_language": a.target_language,
            "model_name": a.model_name,
            "status": a.status,
            "created_at": a.created_at,
            "auto_generated": bool(a.auto_generated),
        }
        for a in rows
    ]


@router.get("/api/recordings/{recording_id}/analyses/{analysis_id}")
def get_analysis(recording_id: str, analysis_id: str, session: Session = Depends(get_session)) -> dict:
    a = session.get(Analysis, analysis_id)
    if not a or a.recording_id != recording_id:
        raise HTTPException(404, "Analysis not found")
    return {
        "id": a.id,
        "analysis_type": a.analysis_type,
        "result_text": a.result_text,
        "target_language": a.target_language,
        "model_name": a.model_name,
        "status": a.status,
        "created_at": a.created_at,
        "auto_generated": bool(a.auto_generated),
    }


@router.delete("/api/recordings/{recording_id}/analyses/{analysis_id}")
def delete_analysis(recording_id: str, analysis_id: str, session: Session = Depends(get_session)) -> dict:
    a = session.get(Analysis, analysis_id)
    if not a or a.recording_id != recording_id:
        raise HTTPException(404, "Analysis not found")
    for decision in session.exec(select(IdeaDecision).where(IdeaDecision.analysis_id == analysis_id)).all():
        session.delete(decision)
    session.delete(a)
    session.commit()
    from core.visual_ideas import delete_visual_evidence
    delete_visual_evidence(analysis_id)
    return {"ok": True}


@router.get('/api/recordings/{recording_id}/analyses/{analysis_id}/frames')
def list_analysis_frames(recording_id: str, analysis_id: str, session: Session = Depends(get_session)) -> list:
    analysis = session.get(Analysis, analysis_id)
    if not analysis or analysis.recording_id != recording_id:
        raise HTTPException(404, 'Analysis not found')
    from core.visual_ideas import read_visual_evidence
    return read_visual_evidence(analysis_id)


@router.get('/api/recordings/{recording_id}/analyses/{analysis_id}/frames/{index}')
def get_analysis_frame(recording_id: str, analysis_id: str, index: int, session: Session = Depends(get_session)):
    analysis = session.get(Analysis, analysis_id)
    if not analysis or analysis.recording_id != recording_id:
        raise HTTPException(404, 'Analysis not found')
    from core.visual_ideas import visual_frame_path
    try:
        path = visual_frame_path(analysis_id, index)
    except ValueError:
        raise HTTPException(404, 'Frame not found')
    if not path.is_file():
        raise HTTPException(404, 'Frame not found')
    return FileResponse(path, media_type='image/jpeg')


def _review_analysis(recording_id, analysis_id, session):
    analysis = session.get(Analysis, analysis_id)
    if not analysis or analysis.recording_id != recording_id:
        raise HTTPException(404, 'Analysis not found')
    return analysis


class IdeaStatus(BaseModel):
    status: Literal['pending', 'approved', 'rejected']


@router.get('/api/recordings/{recording_id}/analyses/{analysis_id}/ideas')
def get_ideas(recording_id: str, analysis_id: str, session: Session = Depends(get_session)):
    from core.idea_review import parse_ideas
    analysis = _review_analysis(recording_id, analysis_id, session)
    decisions = {d.idea_id: d.status for d in session.exec(select(IdeaDecision).where(IdeaDecision.analysis_id == analysis_id)).all()}
    return [{**idea, 'status': decisions.get(idea['id'], 'pending')} for idea in parse_ideas(analysis_id, analysis.result_text)]


@router.put('/api/recordings/{recording_id}/analyses/{analysis_id}/ideas/{idea_id}')
def set_idea_status(recording_id: str, analysis_id: str, idea_id: str, data: IdeaStatus, session: Session = Depends(get_session)):
    from core.idea_review import parse_ideas
    analysis = _review_analysis(recording_id, analysis_id, session)
    if idea_id not in {i['id'] for i in parse_ideas(analysis_id, analysis.result_text)}:
        raise HTTPException(404, 'Idea not found')
    decision = session.get(IdeaDecision, (analysis_id, idea_id))
    if data.status == 'pending':
        if decision:
            session.delete(decision)
    else:
        if not decision:
            decision = IdeaDecision(analysis_id=analysis_id, idea_id=idea_id)
        decision.status = data.status
        session.add(decision)
    session.commit()
    return {'id': idea_id, 'status': data.status}


@router.get('/api/recordings/{recording_id}/analyses/{analysis_id}/video')
def get_visual_video(recording_id: str, analysis_id: str, session: Session = Depends(get_session)):
    from core.visual_ideas import visual_video_path
    _review_analysis(recording_id, analysis_id, session)
    path = visual_video_path(analysis_id)
    if not path:
        raise HTTPException(404, 'Video not found')
    return FileResponse(path)


@router.get('/api/recordings/{recording_id}/analyses/{analysis_id}/visual-source')
def get_visual_source(recording_id: str, analysis_id: str, session: Session = Depends(get_session)):
    from core.visual_ideas import read_visual_source, visual_video_path
    analysis = _review_analysis(recording_id, analysis_id, session)
    source = read_visual_source(analysis_id)
    match = re.search(r'Fuente facilitada por el usuario: (https://\S+)', analysis.prompt_used or '')
    url = source.get('url') or (match.group(1) if match else '')
    return {'url': url if validate_source_url(url) else '', 'has_video': bool(visual_video_path(analysis_id))}

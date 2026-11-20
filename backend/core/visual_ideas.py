"""Local-only visual evidence for transcript analysis."""
import base64
import json
import math
import os
import shutil
import subprocess
import tempfile
import uuid
from pathlib import Path
from urllib.parse import urlparse

import requests
import config
from yt_dlp import YoutubeDL

_HOSTS = {'youtube.com', 'www.youtube.com', 'm.youtube.com', 'youtu.be',
          'instagram.com', 'www.instagram.com', 'tiktok.com', 'www.tiktok.com',
          'm.tiktok.com', 'vm.tiktok.com'}


def _evidence_dir(analysis_id):
    return config.STORAGE_ROOT / 'visual-evidence' / str(uuid.UUID(analysis_id))


def save_visual_evidence(analysis_id, frames):
    directory = _evidence_dir(analysis_id)
    directory.mkdir(parents=True, exist_ok=True)
    metadata = []
    for index, frame in enumerate(frames):
        (directory / f'{index}.jpg').write_bytes(frame['image'])
        metadata.append({'second': frame['second'], 'description': frame['description']})
    (directory / 'frames.json').write_text(json.dumps(metadata, ensure_ascii=False), encoding='utf-8')


def read_visual_evidence(analysis_id):
    path = _evidence_dir(analysis_id) / 'frames.json'
    return json.loads(path.read_text(encoding='utf-8')) if path.is_file() else []


def visual_frame_path(analysis_id, index):
    if index < 0 or index >= 3:
        raise ValueError('Invalid frame index')
    return _evidence_dir(analysis_id) / f'{index}.jpg'


def delete_visual_evidence(analysis_id):
    shutil.rmtree(_evidence_dir(analysis_id), ignore_errors=True)


def validate_source_url(url):
    try:
        parsed = urlparse(url)
        return parsed.scheme == 'https' and parsed.hostname in _HOSTS and not parsed.username and not parsed.password and parsed.port in (None, 443)
    except ValueError:
        return False


def frame_times(duration, count=3):
    if not math.isfinite(duration) or duration <= 0:
        return []
    return [round(duration * i / (count + 1), 2) for i in range(1, count + 1)]


def transcript_with_timestamps(data, fallback):
    segments = data.get('segments', []) if isinstance(data, dict) else []
    lines = []
    for segment in segments:
        if isinstance(segment, dict) and segment.get('text'):
            seconds = max(0, int(segment.get('start', 0)))
            lines.append(f'[{seconds // 60:02}:{seconds % 60:02}] {segment["text"].strip()}')
    return '\n'.join(lines) or fallback


def video_duration(info, video):
    if info.get('duration'):
        return float(info['duration'])
    result = subprocess.run(['ffprobe', '-v', 'error', '-show_entries', 'format=duration',
                             '-of', 'default=noprint_wrappers=1:nokey=1', str(video)],
                            check=True, capture_output=True, text=True, timeout=30)
    return float(result.stdout.strip())


def collect_visual_evidence(url, cancelled=lambda: False):
    if not validate_source_url(url):
        raise ValueError('Use an HTTPS YouTube, Instagram or TikTok URL.')
    # Endpoint and model are operator-configured, never supplied by a request.
    endpoint = os.environ.get('ATLAS_OLLAMA_URL', 'http://host.docker.internal:11434')
    model = os.environ.get('ATLAS_VISION_MODEL', 'gemma4:e4b')
    if urlparse(endpoint).hostname not in {'localhost', '127.0.0.1', 'host.docker.internal'}:
        raise ValueError('Visual analysis requires a local Ollama endpoint.')
    with tempfile.TemporaryDirectory(prefix='amicoscript-frames-') as tmp:
        opts = {'outtmpl': str(Path(tmp) / 'video.%(ext)s'), 'format': 'bestvideo[height<=720]/best[height<=720]/best',
                'noplaylist': True, 'quiet': True, 'max_filesize': 300 * 1024 * 1024}
        with YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=True)
            video = Path(ydl.prepare_filename(info))
        if not video.is_file():
            raise RuntimeError('The source video could not be downloaded.')
        duration = video_duration(info, video)
        times = frame_times(duration)
        if not times:
            raise RuntimeError('The source video has no usable duration.')
        evidence = []
        for i, second in enumerate(times):
            if cancelled():
                raise RuntimeError('Visual analysis cancelled.')
            image = Path(tmp) / f'frame-{i}.jpg'
            subprocess.run(['ffmpeg', '-loglevel', 'error', '-ss', str(second), '-i', str(video),
                            '-frames:v', '1', '-vf', 'scale=960:-2', '-y', str(image)],
                           check=True, timeout=60, capture_output=True)
            if not image.is_file():
                raise RuntimeError(f'Could not extract frame at {second}s.')
            payload = {'model': model, 'stream': False, 'think': False, 'options': {'num_predict': 256},
                       'messages': [{'role': 'user', 'content': 'Describe en español solo información útil visible y transcribe texto legible. No inventes.',
                                     'images': [base64.b64encode(image.read_bytes()).decode('ascii')]}]}
            response = requests.post(endpoint.rstrip('/') + '/api/chat', json=payload, timeout=180)
            response.raise_for_status()
            description = response.json().get('message', {}).get('content', '').strip()
            if not description:
                raise RuntimeError('The vision model returned an empty description.')
            evidence.append({'second': second, 'description': description, 'image': image.read_bytes()})
        return evidence

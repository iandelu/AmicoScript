from core.visual_ideas import frame_times, validate_source_url, transcript_with_timestamps, video_duration


def test_visual_evidence_is_persisted_and_retrievable(tmp_path, monkeypatch):
    import config
    from core.visual_ideas import save_visual_evidence, read_visual_evidence, visual_frame_path
    monkeypatch.setattr(config, 'STORAGE_ROOT', tmp_path)
    analysis_id = '4af6493e-ef0a-4829-8fcf-788f66a70511'
    save_visual_evidence(analysis_id, [{'second': 12.5, 'description': 'Un gráfico', 'image': b'jpeg-test'}])
    assert read_visual_evidence(analysis_id) == [{'second': 12.5, 'description': 'Un gráfico'}]
    assert visual_frame_path(analysis_id, 0).read_bytes() == b'jpeg-test'


def test_visual_evidence_rejects_invalid_identifiers(tmp_path, monkeypatch):
    import config
    import pytest
    from core.visual_ideas import visual_frame_path
    monkeypatch.setattr(config, 'STORAGE_ROOT', tmp_path)
    with pytest.raises(ValueError):
        visual_frame_path('../../escape', 0)


def test_frame_endpoints_require_matching_recording_and_clean_up(client, make_recording, tmp_path, monkeypatch):
    import config
    from db import new_session
    from models import Analysis
    from core.visual_ideas import save_visual_evidence, visual_frame_path
    monkeypatch.setattr(config, 'STORAGE_ROOT', tmp_path)
    recording_id = make_recording()
    other_id = make_recording()
    analysis_id = '4af6493e-ef0a-4829-8fcf-788f66a70511'
    with new_session() as session:
        session.add(Analysis(id=analysis_id, recording_id=recording_id, analysis_type='custom', status='done'))
        session.commit()
    save_visual_evidence(analysis_id, [{'second': 12.5, 'description': 'Un gráfico', 'image': b'jpeg-test'}])
    base = f'/api/recordings/{recording_id}/analyses/{analysis_id}'
    assert client.get(base + '/frames').json() == [{'second': 12.5, 'description': 'Un gráfico'}]
    assert client.get(base + '/frames/0').content == b'jpeg-test'
    assert client.get(base + '/frames/3').status_code == 404
    assert client.get(f'/api/recordings/{other_id}/analyses/{analysis_id}/frames/0').status_code == 404
    assert client.delete(base).status_code == 200
    assert not visual_frame_path(analysis_id, 0).exists()


def test_deleting_recording_cleans_saved_frames(client, make_recording, tmp_path, monkeypatch):
    import config
    from db import new_session
    from models import Analysis
    from core.visual_ideas import save_visual_evidence, visual_frame_path
    monkeypatch.setattr(config, 'STORAGE_ROOT', tmp_path)
    recording_id = make_recording()
    analysis_id = '4af6493e-ef0a-4829-8fcf-788f66a70511'
    with new_session() as session:
        session.add(Analysis(id=analysis_id, recording_id=recording_id, analysis_type='custom', status='done'))
        session.commit()
    save_visual_evidence(analysis_id, [{'second': 3, 'description': 'Ejemplo', 'image': b'jpeg-test'}])
    assert client.delete(f'/api/recordings/{recording_id}').status_code == 200
    assert not visual_frame_path(analysis_id, 0).exists()


def test_frame_times_cover_video_without_sampling_after_end():
    assert frame_times(100, count=3) == [25.0, 50.0, 75.0]
    assert frame_times(0, count=3) == []


def test_only_supported_public_video_hosts_are_allowed():
    assert validate_source_url('https://www.youtube.com/watch?v=abc')
    assert validate_source_url('https://vm.tiktok.com/abc')
    assert not validate_source_url('http://127.0.0.1/private')
    assert not validate_source_url('https://youtube.com.attacker.test/watch?v=a')


def test_transcript_keeps_segment_timestamps():
    data = {'segments': [{'start': 12.2, 'text': 'Primera idea'}, {'start': 76, 'text': 'Segunda idea'}]}
    assert transcript_with_timestamps(data, 'fallback') == '[00:12] Primera idea\n[01:16] Segunda idea'
    assert transcript_with_timestamps({}, 'fallback') == 'fallback'


def test_duration_falls_back_to_ffprobe(monkeypatch):
    class Result:
        stdout = '88.25\n'
    monkeypatch.setattr('core.visual_ideas.subprocess.run', lambda *args, **kwargs: Result())
    assert video_duration({}, '/tmp/video.mp4') == 88.25


def test_visual_analysis_requires_supported_source(client, make_recording, sample_segments):
    rec_id = make_recording(segments=sample_segments)
    client.post('/api/llm/settings', data={'llm_provider': 'ollama', 'llm_base_url': 'http://localhost:11434', 'llm_model_name': 'test'})
    response = client.post(f'/api/recordings/{rec_id}/analyses', data={
        'analysis_type': 'visual_ideas', 'source_url': 'http://127.0.0.1/private'})
    assert response.status_code == 400


def test_visual_analysis_enqueues_timestamped_transcript(client, make_recording, sample_segments, monkeypatch):
    import api.routes.analyses as routes
    captured = {}
    def create(**kwargs):
        captured.update(kwargs)
        return 'job-id', 'analysis-id'
    monkeypatch.setattr(routes, 'create_analysis_job', create)
    rec_id = make_recording(segments=sample_segments)
    client.post('/api/llm/settings', data={'llm_provider': 'ollama', 'llm_base_url': 'http://localhost:11434', 'llm_model_name': 'test'})
    response = client.post(f'/api/recordings/{rec_id}/analyses', data={
        'analysis_type': 'visual_ideas', 'source_url': 'https://www.youtube.com/watch?v=abc'})
    assert response.status_code == 200
    assert captured['visual_source_url'] == 'https://www.youtube.com/watch?v=abc'
    assert captured['analysis_type'] == 'custom'
    assert '[00:' in captured['transcript_full_text']
    assert 'aprobación humana' in captured['custom_prompt']
    assert captured['visual_source_url'] in captured['custom_prompt']


def test_visual_analysis_refuses_remote_models(client, make_recording, sample_segments):
    rec_id = make_recording(segments=sample_segments)
    client.post('/api/llm/settings', data={'llm_provider': 'openrouter',
        'llm_model_name': 'example/model', 'llm_api_key': 'test', 'llm_allow_cloud': 'true'})
    response = client.post(f'/api/recordings/{rec_id}/analyses', data={
        'analysis_type': 'visual_ideas', 'source_url': 'https://www.youtube.com/watch?v=abc'})
    assert response.status_code == 400
    assert 'local Ollama' in response.json()['detail']

from core.visual_ideas import frame_times, validate_source_url, transcript_with_timestamps, video_duration


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

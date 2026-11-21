from core.idea_review import parse_ideas


def test_ideas_are_independent_and_have_stable_ids():
    text = '# Primera idea\nUna explicación.\n\n# Segunda idea\nOtra explicación.'
    ideas = parse_ideas('analysis-1', text)
    assert [idea['title'] for idea in ideas] == ['Primera idea', 'Segunda idea']
    assert len({idea['id'] for idea in ideas}) == 2
    assert ideas == parse_ideas('analysis-1', text)


def test_approval_is_independent_persistent_and_reversible(client, make_recording):
    from db import new_session
    from models import Analysis
    recording_id = make_recording()
    analysis_id = '4af6493e-ef0a-4829-8fcf-788f66a70511'
    with new_session() as session:
        session.add(Analysis(id=analysis_id, recording_id=recording_id, analysis_type='custom', status='done',
                             result_text='# Uno\nContenido uno\n\n# Dos\nContenido dos'))
        session.commit()
    base = f'/api/recordings/{recording_id}/analyses/{analysis_id}/ideas'
    ideas = client.get(base).json()
    assert len(ideas) == 2
    assert client.put(f"{base}/{ideas[0]['id']}", json={'status': 'approved'}).status_code == 200
    saved = client.get('/api/ideas/approved').json()
    assert len(saved) == 1
    assert saved[0]['title'] == 'Uno'
    assert saved[0]['recording_id'] == recording_id
    updated = client.get(base).json()
    assert [i['status'] for i in updated] == ['approved', 'pending']
    assert client.put(f"{base}/{ideas[0]['id']}", json={'status': 'rejected'}).status_code == 200
    assert client.get(base).json()[0]['status'] == 'rejected'
    assert client.put(f"{base}/{ideas[0]['id']}", json={'status': 'pending'}).status_code == 200
    assert client.get('/api/ideas/approved').json() == []
    assert client.get(base).json()[0]['status'] == 'pending'
    assert client.put(f"{base}/unknown", json={'status': 'approved'}).status_code == 404
    assert client.put(f"{base}/{ideas[0]['id']}", json={'status': 'wrong'}).status_code == 422


def test_stored_video_is_available_only_for_its_analysis(client, make_recording, tmp_path, monkeypatch):
    import config
    from db import new_session
    from models import Analysis
    from core.visual_ideas import save_visual_video
    monkeypatch.setattr(config, 'STORAGE_ROOT', tmp_path)
    recording_id = make_recording()
    other_id = make_recording()
    analysis_id = '4af6493e-ef0a-4829-8fcf-788f66a70511'
    with new_session() as session:
        session.add(Analysis(id=analysis_id, recording_id=recording_id, analysis_type='custom', status='done'))
        session.commit()
    source = tmp_path / 'input.mp4'
    source.write_bytes(b'video-test')
    save_visual_video(analysis_id, source, 'https://www.youtube.com/watch?v=abc')
    base = f'/api/recordings/{recording_id}/analyses/{analysis_id}/video'
    assert client.get(base).content == b'video-test'
    assert client.get(f'/api/recordings/{other_id}/analyses/{analysis_id}/video').status_code == 404

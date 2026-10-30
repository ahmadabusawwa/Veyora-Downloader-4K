import performance

def test_profiles_bound_cpu_and_fragments(monkeypatch):
    monkeypatch.setattr(performance.os,'cpu_count',lambda:4)
    for name,expected in [('economy',2),('balanced',4),('high',4)]:
        monkeypatch.setenv('VEYORA_PERFORMANCE',name)
        assert performance.cpu_threads()==expected
        assert 1<=performance.profile()[1]<=5
        assert 1<=performance.profile()[2]<=4

def test_bad_mode_falls_back(monkeypatch):
    monkeypatch.setenv('VEYORA_PERFORMANCE','bad-value')
    assert performance.profile()==performance.PROFILES['balanced']

import performance

def test_profiles_bound_cpu_and_fragments(monkeypatch):
    monkeypatch.setattr(performance.os,'cpu_count',lambda:4)
    for name,expected in [('economy',2),('balanced',2),('high',2)]:
        monkeypatch.setenv('VEYORA_PERFORMANCE',name)
        assert performance.cpu_threads()==expected
        assert 1<=performance.profile()[1]<=5
        assert 1<=performance.profile()[2]<=4

def test_bad_mode_falls_back(monkeypatch):
    monkeypatch.setenv('VEYORA_PERFORMANCE','bad-value')
    assert performance.profile()==performance.PROFILES['balanced']


def test_cpu_budget_reserves_capacity_on_weak_machines(monkeypatch):
    monkeypatch.setenv('VEYORA_PERFORMANCE', 'balanced')
    for cores, expected in [(1, 1), (2, 1), (4, 2), (8, 4), (16, 4)]:
        monkeypatch.setattr(performance.os, 'cpu_count', lambda: cores)
        assert performance.cpu_threads() == expected

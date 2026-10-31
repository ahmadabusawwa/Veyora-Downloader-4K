"""Thumbnail callbacks from separate UI surfaces must be independent."""
import thumbnail_cache as cache


def test_failed_first_thumbnail_consumer_does_not_block_second(monkeypatch, tmp_path):
    scheduled = []
    monkeypatch.setattr(cache._pool, 'submit', lambda work: scheduled.append(work))
    monkeypatch.setattr(cache, '_load', lambda url, root: 'decoded-thumbnail')
    received = []
    def broken_callback(image):
        received.append('broken')
        raise RuntimeError('widget has been destroyed')
    url = 'https://example.org/cover.jpg'
    cache.request(url, tmp_path, broken_callback)
    cache.request(url, tmp_path, lambda image: received.append(image))
    assert len(scheduled) == 1  # same thumbnail shares one bounded worker
    scheduled[0]()
    assert received == ['broken', 'decoded-thumbnail']
    assert not cache._inflight

from adr_eval.cache import Cache


def test_cache_key_stable_and_roundtrip(tmp_path):
    c = Cache(tmp_path)
    k = Cache.key("a", 1, {"x": 2})
    assert k == Cache.key("a", 1, {"x": 2})
    assert k != Cache.key("a", 2, {"x": 2})
    assert c.get(k) is None
    c.put(k, {"v": 1})
    assert c.get(k) == {"v": 1}
    assert (tmp_path / k[:2] / f"{k}.json").exists()
    assert not list(tmp_path.rglob("*.tmp"))

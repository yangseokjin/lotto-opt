import json

from conftest import FIXTURE
from lotto_opt import data


def _mirror(draws):
    return [{"draw_no": d["draw_no"], "date": d["date"], "numbers": d["numbers"], "bonus_no": d["bonus"]} for d in draws]


def test_broken_cache_is_refetched(tmp_path, monkeypatch, draws):
    """쓰다가 멈춰 반쯤 남은 캐시 파일이 있어도 새로 받아서 고쳐 쓴다."""
    cache = tmp_path / "draws.json"
    cache.write_text('[{"draw_no": 1, "date": "2002-12-07", "numb', encoding="utf-8")

    def fake_get(url, timeout=20):
        if url == data.MIRROR:
            return _mirror(draws)
        raise OSError("공식 API 막힘")

    monkeypatch.setattr(data, "_get_json", fake_get)
    monkeypatch.setattr(data, "expected_latest", lambda now=None: draws[-1]["draw_no"])
    got, source = data.load_draws(str(cache), "auto")
    assert source == "mirror" and got[-1]["draw_no"] == draws[-1]["draw_no"]
    assert json.loads(cache.read_text(encoding="utf-8"))[-1]["draw_no"] == draws[-1]["draw_no"]
    assert [p.name for p in tmp_path.iterdir()] == ["draws.json"]  # 임시 파일이 남지 않는다


def test_cache_up_to_date_skips_network(tmp_path, monkeypatch, draws):
    cache = tmp_path / "draws.json"
    cache.write_text(open(FIXTURE, encoding="utf-8").read(), encoding="utf-8")
    monkeypatch.setattr(data, "_get_json", lambda *a, **k: (_ for _ in ()).throw(AssertionError("네트워크 호출")))
    monkeypatch.setattr(data, "expected_latest", lambda now=None: draws[-1]["draw_no"])
    got, source = data.load_draws(str(cache), "auto")
    assert source == "cache" and len(got) == len(draws)

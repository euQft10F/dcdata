import httpx
import respx

from dcdata.http import Fetcher


@respx.mock
def test_cache_and_4xx(tmp_path):
    respx.get("https://e.org/a").mock(return_value=httpx.Response(200, content=b"hello"))
    respx.get("https://e.org/missing").mock(return_value=httpx.Response(404, content=b"no"))
    f = Fetcher(cache_dir=tmp_path, delay=0)
    r1 = f.get("https://e.org/a", cache_key="x/a.txt")
    r2 = f.get("https://e.org/a", cache_key="x/a.txt")
    assert r1.content == r2.content == b"hello"
    assert not r1.from_cache and r2.from_cache
    assert f.n_network_requests == 1
    r = f.get("https://e.org/missing", cache_key="x/m.txt")
    assert r.status == 404 and not (tmp_path / "x/m.txt").exists()


@respx.mock
def test_retry_then_success(tmp_path, monkeypatch):
    monkeypatch.setattr("time.sleep", lambda s: None)
    route = respx.get("https://e.org/flaky").mock(
        side_effect=[httpx.Response(503), httpx.Response(200, content=b"ok")]
    )
    f = Fetcher(delay=0)
    r = f.get("https://e.org/flaky")
    assert r.status == 200 and route.call_count == 2

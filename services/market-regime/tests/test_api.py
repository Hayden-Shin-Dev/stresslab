"""API tests. Runs with plain `python -I tests/test_api.py` (no pytest needed).
If FastAPI is not installed, a tiny stub stands in so the router functions still execute."""
import json, shutil, sys, tempfile, types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SAMPLE = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).resolve().parent / "fixtures/regime_snapshot.sample.json"
sys.path.insert(0, str(ROOT))

try:
    import fastapi  # noqa: F401
    STUB = False
except ImportError:  # minimal stand-in: decorators register, HTTPException raises
    STUB = True
    fa = types.ModuleType("fastapi")
    class HTTPException(Exception):
        def __init__(self, status_code, detail=None): super().__init__(detail); self.status_code, self.detail = status_code, detail
    class APIRouter:
        def __init__(self, prefix="", tags=None): self.prefix, self.routes = prefix, {}
        def get(self, path, **k):
            def deco(fn): self.routes[self.prefix + path] = fn; return fn
            return deco
    class Response:
        def __init__(self, status_code=200, headers=None): self.status_code, self.headers = status_code, dict(headers or {})
    fa.APIRouter, fa.HTTPException, fa.Response = APIRouter, HTTPException, Response
    fa.Depends = lambda x=None: None
    fa.Query = lambda default=None, **k: default
    fa.Request = object
    sys.modules["fastapi"] = fa

from regime_api import service
from regime_api.repository import FileSnapshotRepository, SnapshotUnavailable
from regime_api import router as R

tmp = Path(tempfile.mkdtemp())
f = tmp / "regime_snapshot.json"
shutil.copy(SAMPLE, f)
sha = __import__("hashlib").sha256(f.read_bytes()).hexdigest()
f.with_suffix(".sha256").write_text(sha)
ok = 0

def check(cond, msg):
    global ok
    assert cond, msg
    ok += 1

# repository
try:
    FileSnapshotRepository(str(f)).latest(); check(False, "synthetic must be refused")
except SnapshotUnavailable as e:
    check(str(e) == "SYNTHETIC_SNAPSHOT_REFUSED", e)
repo = FileSnapshotRepository(str(f), allow_synthetic=True)
snap, s2 = repo.latest(); check(s2 == sha, "sha")
check(repo.latest()[0] is snap, "cache hit")
bad = tmp / "bad.json"; bad.write_text(f.read_text(encoding="utf8").replace('"bull"', '"BULL"', 1), encoding="utf8")
bad.with_suffix(".sha256").write_text(sha)
try:
    FileSnapshotRepository(str(bad), True).latest(); check(False, "tamper")
except SnapshotUnavailable as e:
    check(str(e) == "SNAPSHOT_SHA256_MISMATCH", e)
# directory with latest.json (Fabric Files/regime layout)
d = tmp / "regime"; (d / "snapshots/V1").mkdir(parents=True)
shutil.copy(f, d / "snapshots/V1/regime_snapshot.json")
(d / "latest.json").write_text(json.dumps({"version": "V1", "path": "regime/snapshots/V1/regime_snapshot.json", "sha256": sha}))
check(FileSnapshotRepository(str(d), True).latest()[1] == sha, "dir layout")

# service
cur = service.current(snap); check(cur["regime_code"] in service.CODES and len(cur["regimes"]) == 3, "current")
h_all = service.history(snap); check(h_all["count"] == len(snap["history"]), "history all")
h1 = service.history(snap, years=1); check(0 < h1["count"] < 300, f"history 1y {h1['count']}")
h2 = service.history(snap, start="2020-01-01", end="2020-12-31")
check(all("2020-01-01" <= r["date"] <= "2020-12-31" for r in h2["rows"]) and h2["count"] > 200, "history range")
for bad_args in [dict(start="2020-13-01"), dict(start="2021-01-01", end="2020-01-01"), dict(years=0)]:
    try:
        service.history(snap, **bad_args); check(False, bad_args)
    except service.BadRequest:
        check(True, "")
check(all(r["regime_code"] == "bear" for r in service.runs(snap, "bear")["rows"]), "runs filter")
check(service.runs(snap, limit=3)["count"] == 3, "runs limit")
try:
    service.runs(snap, "crash"); check(False, "bad regime")
except service.BadRequest:
    check(True, "")
check(len(service.summary(snap)["rows"]) == 3, "summary")
check(len(service.transitions(snap)["daily_frequency"]) == 3, "transitions")
check(len(service.similar(snap)["neighbors"]) >= 1, "similar")
check("validation" in service.model(snap), "model")
env = service.envelope(snap, {}, sha); check(env["meta"]["notice"].startswith("과거 데이터"), "notice")
nb_keys = set().union(*[set(n) for n in snap["similar"]["neighbors"]])
check(not any("return" in k or "pnl" in k for k in nb_keys), f"no forward returns in similar {nb_keys}")

# router functions (real FastAPI or stub)
class Req:
    def __init__(self, h=None): self.headers = h or {}
resp = R.Response() if STUB else __import__("fastapi").Response()
body = R.get_current(Req(), resp, repo); check(body["data"]["regime_code"] == cur["regime_code"], "router current")
etag = resp.headers["ETag"]
r304 = R.get_current(Req({"if-none-match": etag}), R.Response(), repo); check(getattr(r304, "status_code", 0) == 304, "etag 304")
check(R.get_history(Req(), R.Response(), None, None, 3, repo)["data"]["count"] > 600, "router history")
try:
    R.get_history(Req(), R.Response(), "bad", None, None, repo); check(False, "400")
except R.HTTPException as e:
    check(e.status_code == 400, "400")
class Down:
    def latest(self): raise SnapshotUnavailable("NO_SNAPSHOT_ROWS")
try:
    R.get_summary(Req(), R.Response(), Down()); check(False, "503")
except R.HTTPException as e:
    check(e.status_code == 503, "503")
check(R.get_health(Down())["status"] == "unavailable", "health down")
check(R.get_snapshot(Req(), R.Response(), repo)["schema"] == "market_regime_snapshot", "snapshot")
print(f"API tests passed: {ok} checks", "(FastAPI stub)" if STUB else "(FastAPI)")

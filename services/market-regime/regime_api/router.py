"""FastAPI router — mount into the existing FastAPI app or run standalone (app.py).

    from regime_api.router import router as regime_router
    app.include_router(regime_router)

All endpoints are GET, read-only, and answer from the latest published snapshot.
"""
from __future__ import annotations

from functools import lru_cache
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response

from . import service
from .repository import SnapshotUnavailable, from_env

router = APIRouter(prefix="/api/v1/market-regime", tags=["market-regime"])


@lru_cache(maxsize=1)
def get_repository():
    return from_env()


def _load(repo):
    try:
        return repo.latest()
    except SnapshotUnavailable as e:
        raise HTTPException(status_code=503, detail={"code": str(e), "message": "시장 국면 스냅샷을 아직 사용할 수 없습니다."})


def _respond(request: Request, response: Response, snap, sha, data):
    etag = f'"{sha[:32]}"'
    response.headers["ETag"] = etag
    response.headers["Cache-Control"] = "public, max-age=300"
    if request.headers.get("if-none-match") == etag:
        return Response(status_code=304, headers={"ETag": etag})
    return service.envelope(snap, data, sha)


def _call(fn, *a, **k):
    try:
        return fn(*a, **k)
    except service.BadRequest as e:
        raise HTTPException(status_code=400, detail={"code": "BAD_REQUEST", "message": str(e)})


@router.get("/snapshot", summary="대시보드 전체 데이터 (1회 호출용)")
def get_snapshot(request: Request, response: Response, repo=Depends(get_repository)):
    snap, sha = _load(repo)
    etag = f'"{sha[:32]}"'
    response.headers["ETag"] = etag
    response.headers["Cache-Control"] = "public, max-age=300"
    if request.headers.get("if-none-match") == etag:
        return Response(status_code=304, headers={"ETag": etag})
    return snap


@router.get("/current", summary="현재 국면 카드")
def get_current(request: Request, response: Response, repo=Depends(get_repository)):
    snap, sha = _load(repo)
    return _respond(request, response, snap, sha, service.current(snap))


@router.get("/history", summary="일별 국면 이력")
def get_history(request: Request, response: Response,
                start: Optional[str] = Query(None, description="YYYY-MM-DD"),
                end: Optional[str] = Query(None, description="YYYY-MM-DD"),
                years: Optional[float] = Query(None, description="as_of 기준 최근 N년 (start보다 우선)"),
                repo=Depends(get_repository)):
    snap, sha = _load(repo)
    return _respond(request, response, snap, sha, _call(service.history, snap, start, end, years))


@router.get("/runs", summary="국면 구간 목록")
def get_runs(request: Request, response: Response,
             regime: Optional[str] = Query(None, description="bull | sideways | bear"),
             limit: Optional[int] = Query(None, ge=1, le=1000),
             repo=Depends(get_repository)):
    snap, sha = _load(repo)
    return _respond(request, response, snap, sha, _call(service.runs, snap, regime, limit))


@router.get("/summary", summary="국면별 특성")
def get_summary(request: Request, response: Response, repo=Depends(get_repository)):
    snap, sha = _load(repo)
    return _respond(request, response, snap, sha, service.summary(snap))


@router.get("/transitions", summary="과거 전이 빈도")
def get_transitions(request: Request, response: Response, repo=Depends(get_repository)):
    snap, sha = _load(repo)
    return _respond(request, response, snap, sha, service.transitions(snap))


@router.get("/similar", summary="현재와 비슷했던 과거 시기 (이후 수익률 없음)")
def get_similar(request: Request, response: Response, repo=Depends(get_repository)):
    snap, sha = _load(repo)
    return _respond(request, response, snap, sha, service.similar(snap))


@router.get("/model", summary="모델·검증·데이터 품질 정보")
def get_model(request: Request, response: Response, repo=Depends(get_repository)):
    snap, sha = _load(repo)
    return _respond(request, response, snap, sha, service.model(snap))


@router.get("/health", summary="스냅샷 사용 가능 여부")
def get_health(repo=Depends(get_repository)):
    try:
        snap, sha = repo.latest()
    except SnapshotUnavailable as e:
        return {"status": "unavailable", "reason": str(e)}
    return {"status": "ok", **service.meta(snap, sha)}

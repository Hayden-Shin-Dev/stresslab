"""OneLake Delta 버전을 고정해 로컬로 복사한다. 클라우드에는 쓰지 않는다."""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from urllib.parse import quote, unquote

import requests
from deltalake import DeltaTable


def read_local_delta(local, version):
    import pyarrow as pa
    import pyarrow.parquet as pq
    delta = DeltaTable(str(local), version=version)
    try:
        return delta.to_pyarrow_table()
    except Exception as exc:
        if "deletionVectors" not in str(exc):
            raise
    # 민철 2026-11-11 수정 (로컬 리더가 삭제 벡터 기능 플래그를 읽지 못하기 때문에 실제 삭제 벡터가 없는 버전만 확인 후 읽도록 수정함.)
    active = {}
    for v in range(version + 1):
        path = local / "_delta_log" / f"{v:020}.json"
        if not path.exists():
            raise ValueError("삭제 벡터 검사를 위한 전체 Delta 로그가 필요함")
        for line in path.read_text(encoding="utf-8").splitlines():
            action = json.loads(line)
            if "remove" in action:
                active.pop(action["remove"]["path"], None)
            if "add" in action:
                active[action["add"]["path"]] = action["add"]
    if any(a.get("deletionVector") is not None for a in active.values()):
        raise ValueError("실제 삭제 벡터가 있는 Delta는 지원 리더로 읽어야 함")
    if delta.metadata().partition_columns or set(delta.protocol().reader_features or []) - {"deletionVectors"}:
        raise ValueError("이 대체 읽기는 비파티션, 삭제 벡터 미사용 테이블만 지원함")
    paths = {str((local / unquote(p)).resolve()) for p in active}
    if paths != {str(Path(p).resolve()) for p in delta.file_uris()}:
        raise ValueError("Delta 활성 파일 목록 불일치")
    arrow = pa.concat_tables([pq.read_table(p) for p in sorted(paths)])
    expected = sum(json.loads(a["stats"])["numRecords"] for a in active.values())
    if len(arrow) != expected or arrow.column_names != [f.name for f in delta.schema().fields]:
        raise ValueError("Delta 행 수 또는 컬럼 불일치")
    return arrow


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def capture(workspace, lakehouse, output):
    # 민철 2026-11-11 추가 (적재 중 파일이 섞일 수 있기 때문에 Delta 버전을 고정해서 내려받도록 했음.)
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    proc = subprocess.run(
        ["az.cmd" if __import__("os").name == "nt" else "az", "account", "get-access-token",
         "--resource", "https://storage.azure.com/", "-o", "json"], capture_output=True, check=True)
    session = requests.Session()
    session.headers.update({"Authorization": "Bearer " + json.loads(proc.stdout)["accessToken"],
                            "x-ms-version": "2023-11-03"})
    root = f"https://onelake.dfs.fabric.microsoft.com/{workspace}"
    table = f"{lakehouse}/Tables/gold_stress_daily"
    params = {"resource": "filesystem", "directory": table + "/_delta_log", "recursive": "true"}
    entries = []
    while True:
        r = session.get(root, params=params, timeout=60)
        r.raise_for_status()
        entries.extend(r.json().get("paths", []))
        continuation = r.headers.get("x-ms-continuation")
        if not continuation:
            break
        params["continuation"] = continuation
    versions = [int(PurePosixPath(e["name"]).stem) for e in entries
                if PurePosixPath(e["name"]).name.endswith(".json")
                and PurePosixPath(e["name"]).stem.isdigit()]
    if not versions:
        raise ValueError("Delta commit JSON을 찾지 못함")
    version = max(versions)
    local = output / "delta"
    receipts = []

    def download(relative):
        relative = unquote(relative)
        parts = PurePosixPath(relative)
        if parts.is_absolute() or ".." in parts.parts or ":" in relative or "\\" in relative:
            raise ValueError("허용되지 않은 Delta 상대 경로")
        dest = local.joinpath(*parts.parts)
        dest.parent.mkdir(parents=True, exist_ok=True)
        r = session.get(root + "/" + quote(table + "/" + relative, safe="/"), timeout=90)
        r.raise_for_status()
        dest.write_bytes(r.content)
        receipts.append({"path": relative, "sha256": sha(dest), "bytes": len(r.content),
                         "etag": r.headers.get("ETag")})

    for e in entries:
        name = PurePosixPath(e["name"]).name
        if name.endswith((".json", ".parquet")) and name[:20].isdigit() and int(name[:20]) <= version:
            download(e["name"][len(table) + 1:])
    delta = DeltaTable(str(local), version=version)
    for uri in delta.file_uris():
        download(Path(uri).relative_to(local.resolve()).as_posix())
    arrow = read_local_delta(local, version)
    import pyarrow.parquet as pq
    pq.write_table(arrow, output / "gold.parquet")
    # 민철 2026-11-11 추가 (공표 시각이 비어 있어 Gold와 함께 게시된 이용 가능 시점 근거도 내려받고 값이 같은지 확인했음.)
    evidence_root = root + f"/{lakehouse}/Files/gold_evidence/gold_stock_market_daily_v11"
    r = session.get(evidence_root + "/latest.json", timeout=60)
    r.raise_for_status()
    published_version = r.json()["version"]
    if not published_version.isalnum():
        raise ValueError("허용되지 않은 근거 버전")
    for remote, name in [("gold.parquet", "evidence_gold.parquet"),
                         ("provenance.parquet", "provenance.parquet"),
                         ("certificate.json", "certificate.json"),
                         ("input_eligibility.parquet", "input_eligibility.parquet"),
                         ("availability_certificate.json", "availability_certificate.json")]:
        r = session.get(evidence_root + "/" + published_version + "/" + remote, timeout=90)
        r.raise_for_status()
        (output / name).write_bytes(r.content)
    cert = json.loads((output / "certificate.json").read_text(encoding="utf-8"))
    if sha(output / "evidence_gold.parquet") != cert["gold_sha256"] or sha(output / "provenance.parquet") != cert["provenance_sha256"]:
        raise ValueError("게시된 근거 파일 해시 불일치")
    if sha(output / "input_eligibility.parquet") != cert["input_eligibility_sha256"] or sha(output / "availability_certificate.json") != cert["availability_certificate_sha256"]:
        raise ValueError("입력 적합성 또는 공표 인증 파일 해시 불일치")
    import pandas as pd
    def canonical(frame):
        for c in frame:
            if c == "trading_date" or c.endswith("_date"):
                frame[c] = pd.to_datetime(frame[c]).astype("datetime64[ns]")
            elif c.endswith("_at"):
                frame[c] = pd.to_datetime(frame[c], utc=True).astype("datetime64[ns, UTC]")
        return frame.sort_values(["trading_date", "asset_id"]).reset_index(drop=True)
    pd.testing.assert_frame_equal(canonical(arrow.to_pandas()),
                                  canonical(pd.read_parquet(output / "evidence_gold.parquet")),
                                  check_dtype=False, check_exact=True)
    receipt = {"captured_utc": datetime.now(timezone.utc).isoformat(), "workspace": workspace,
               "lakehouse": lakehouse, "table": "gold_stress_daily", "delta_version": version,
               "rows": arrow.num_rows, "columns": arrow.num_columns,
               "schema": str(arrow.schema), "gold_sha256": sha(output / "gold.parquet"),
               "files": receipts, "cloud_writes": False, "evidence_version": published_version,
               "evidence_gold_values_equal": True, "provenance_sha256": cert["provenance_sha256"]}
    (output / "receipt.json").write_text(json.dumps(receipt, indent=2), encoding="utf-8")
    return receipt


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--workspace", required=True)
    p.add_argument("--lakehouse", required=True)
    p.add_argument("--output", required=True)
    a = p.parse_args()
    r = capture(a.workspace, a.lakehouse, a.output)
    print(json.dumps({k: r[k] for k in ["table", "delta_version", "rows", "columns", "gold_sha256"]}))

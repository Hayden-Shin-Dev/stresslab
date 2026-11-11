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
    arrow = delta.to_pyarrow_table()
    import pyarrow.parquet as pq
    pq.write_table(arrow, output / "gold.parquet")
    receipt = {"captured_utc": datetime.now(timezone.utc).isoformat(), "workspace": workspace,
               "lakehouse": lakehouse, "table": "gold_stress_daily", "delta_version": version,
               "rows": arrow.num_rows, "columns": arrow.num_columns,
               "schema": str(arrow.schema), "gold_sha256": sha(output / "gold.parquet"),
               "files": receipts, "cloud_writes": False}
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

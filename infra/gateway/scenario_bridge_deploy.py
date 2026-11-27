"""Build additive images from the currently deployed versions, then update only those images."""
import argparse
import json
import shutil
import subprocess
import tempfile
from pathlib import Path


def cli(*args):
    process = subprocess.run([shutil.which("az"), *args, "--only-show-errors", "-o", "json"],
                             capture_output=True, encoding="utf-8", errors="replace")
    if process.returncode:
        raise RuntimeError(process.stderr[-1500:])
    return json.loads(process.stdout) if process.stdout.strip() else None


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--tag", required=True)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[2]
    group, registry = "5dt-final-team3", "acrwhatifdev5dt"
    common = cli("containerapp","show","-g",group,"-n","ca-api-whatif-dev")
    worker = cli("containerapp","show","-g",group,"-n","ca-debate-whatif-dev")
    common_base = common["properties"]["template"]["containers"][0]["image"]
    worker_base = worker["properties"]["template"]["containers"][0]["image"]
    if not common_base.startswith(registry+".azurecr.io/common-api:") or not worker_base.startswith(registry+".azurecr.io/debate:"):
        raise RuntimeError("Unexpected running images")
    build = Path(tempfile.mkdtemp(prefix="whatif-news-build-"))
    for kind, base, app, repo in [("common", common_base, common, "common-api"), ("worker",worker_base,worker,"debate")]:
        folder = build / kind
        folder.mkdir()
        docker = [f"FROM {base}", "RUN pip install --no-cache-dir 'googlenewsdecoder==0.2.2' 'httpx==0.28.1' 'selectolax<1.0'"]
        sources = ["article_body.py", "selected_evidence.py", "news_feed.py"]
        if kind == "worker":
            sources += ["evidence.py"]
        for name in sources:
            shutil.copy2(root/"services/debate/src"/name,folder/name)
            target = "/opt/stresslab/services/debate/src/" if kind=="common" else "/app/src/"
            docker.append(f"COPY {name} {target}{name}")
        if kind=="common":
            for name in ["scenario_bridge.py","scenario_bridge_entry.py","news_scenarios.py","conditional_gateway.py","conditional_gateway_entry.py"]:
                shutil.copy2(root/"services/api/src"/name,folder/name)
                docker.append(f"COPY {name} /opt/stresslab/services/api/src/{name}")
            docker.append('CMD ["uvicorn","scenario_bridge_entry:app","--host","0.0.0.0","--port","8000"]')
        (folder/"Dockerfile").write_text("\n".join(docker)+"\n", encoding="utf-8")
        image = registry+".azurecr.io/"+repo+":"+args.tag
        if not args.apply:
            print(kind,base,"->",image)
            continue
        current = cli("containerapp","show","-g",group,"-n",app["name"])
        if current["properties"]["template"]["containers"][0]["image"] != base:
            raise RuntimeError("Running image changed while preparing deployment")
        cli("acr","build","--no-logs","-r",registry,"-t",repo+":"+args.tag,str(folder))
        update = ["containerapp","update","-g",group,"-n",app["name"],"--image",image]
        if kind=="common":
            settings = {row["name"]: row for row in worker["properties"]["template"]["containers"][0].get("env",[])}
            public = ["AZURE_OPENAI_ENDPOINT","AZURE_OPENAI_DEPLOYMENT","AZURE_OPENAI_API_VERSION"]
            values = [key+"="+settings[key]["value"] for key in public if key in settings and "value" in settings[key]]
            update += ["--set-env-vars",*values]
        result = cli(*update)
        print(app["name"],result["properties"].get("latestRevisionName"))


if __name__=="__main__":
    main()

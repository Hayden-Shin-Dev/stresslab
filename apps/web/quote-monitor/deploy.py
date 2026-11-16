"""Build or deploy the complete WHAT IF Azure Static Web App.

All deployable source files live in this directory's ``site/`` subtree.
deploy-manifest.json records required entry points and runtime dependencies.

Build without Azure access:
    python3 apps/web/quote-monitor/deploy.py --build-only /tmp/whatif-site
Deploy after az login:
    python3 apps/web/quote-monitor/deploy.py
Deploy with a portal token:
    SWA_CLI_DEPLOYMENT_TOKEN=... python3 apps/web/quote-monitor/deploy.py
"""
import argparse
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parents[2]
EXPECTED_HOST = "red-field-0b8ece310.1.azurestaticapps.net"
MANIFEST_PATH = SCRIPT_DIR / "deploy-manifest.json"


def build(output: Path) -> None:
    output = output.resolve()
    source_root = REPO_ROOT / "apps/web/quote-monitor/site"
    if output == source_root or source_root in output.parents or output == SCRIPT_DIR or SCRIPT_DIR in output.parents:
        raise ValueError("Build output must be separate from the source tree.")
    output.mkdir(parents=True, exist_ok=True)
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    source_root = REPO_ROOT / manifest["source_directory"]
    required = [*manifest["primary_files"], *manifest["required_paths"]]
    missing = [name for name in required if not (source_root / name).is_file()]
    if missing:
        raise FileNotFoundError(f"Missing files in consolidated deployment tree: {missing}")

    asset_files = [path for path in source_root.glob(manifest["required_asset_glob"]) if path.is_file()]
    if not asset_files:
        raise FileNotFoundError(f"No required runtime assets match {manifest['required_asset_glob']}")
    shutil.copytree(
        source_root,
        output,
        dirs_exist_ok=True,
        ignore=shutil.ignore_patterns("._*", ".DS_Store"),
    )

    app_html = output / "whatif-agent.html"
    image_refs = set(re.findall(r"assets/inline/[A-Za-z0-9_.-]+", app_html.read_text(encoding="utf-8", errors="ignore")))
    missing_images = sorted(ref for ref in image_refs if not (output / ref).is_file())
    if missing_images:
        raise FileNotFoundError(f"WHAT IF image dependencies missing from deployment: {missing_images}")
    # A missing rewrite target must fail the build instead of becoming a live 404.
    config = json.loads((output / "staticwebapp.config.json").read_text())
    for rule in [*config["routes"], *config["responseOverrides"].values()]:
        if "rewrite" in rule and not (output / rule["rewrite"].lstrip("/")).is_file():
            raise FileNotFoundError(f"Missing route target: {rule['rewrite']}")


def deploy(output: Path) -> None:
    az, npx = shutil.which("az"), shutil.which("npx")
    if not npx:
        raise SystemExit("Deployment requires Node.js (npx). Build-only remains available.")
    target = ["-g", "5dt-final-team3", "-n", "swa-whatif-dev"]
    env = os.environ.copy()
    if not env.get("SWA_CLI_DEPLOYMENT_TOKEN"):
        if not az:
            raise SystemExit("Set SWA_CLI_DEPLOYMENT_TOKEN from the target Static Web App, or install Azure CLI and run az login.")
        host = subprocess.run([az, "staticwebapp", "show", *target, "--query", "defaultHostname", "-o", "tsv", "--only-show-errors"],
                              capture_output=True, text=True, check=True).stdout.strip()
        if host != EXPECTED_HOST:
            raise SystemExit(f"Deployment target mismatch: expected {EXPECTED_HOST}, received {host}. Nothing was deployed.")
        result = subprocess.run([az, "staticwebapp", "secrets", "list", *target, "-o", "json", "--only-show-errors"],
                                capture_output=True, text=True, check=True)
        env["SWA_CLI_DEPLOYMENT_TOKEN"] = json.loads(result.stdout)["properties"]["apiKey"]
    subprocess.run([npx, "--yes", "@azure/static-web-apps-cli", "deploy", str(output), "--env", "production"],
                   env=env, check=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--build-only", type=Path, metavar="DIRECTORY", help="Build without credentials or deployment")
    args = parser.parse_args()
    if args.build_only:
        build(args.build_only)
        print(f"Built WHAT IF site: {args.build_only.resolve()}")
    else:
        with tempfile.TemporaryDirectory(prefix="stresslab-web-") as directory:
            output = Path(directory)
            build(output)
            deploy(output)


if __name__ == "__main__":
    main()

"""Build or deploy WHAT IF's public landing and authenticated workspace.

Build without Azure access:
    python3 apps/web/quote-monitor/deploy.py --build-only /tmp/whatif-site
Deploy after az login:
    python3 apps/web/quote-monitor/deploy.py
"""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile

SCRIPT_DIR = Path(__file__).resolve().parent
LANDING = SCRIPT_DIR.parent / "0.web_main"
REPO_ROOT = SCRIPT_DIR.parents[2]
EXPECTED_HOST = "red-field-0b8ece310.1.azurestaticapps.net"


def build(output: Path) -> None:
    output = output.resolve()
    if (output == LANDING or output == SCRIPT_DIR or output in LANDING.parents
            or LANDING in output.parents or SCRIPT_DIR in output.parents):
        raise ValueError("Build output must be separate from the source tree.")
    output.mkdir(parents=True, exist_ok=True)
    for name in ["index.html", "2_style.css", "1_skin.css", "2_script.js",
                 "login.html", "login.js", "service-shell.js", "service-shell.css"]:
        shutil.copyfile(LANDING / name, output / name)
    shutil.copyfile(LANDING / "WHATIF_AGENT_FIXED_STANDALONE_V3_8_MYROOM (1).html",
                    output / "whatif-agent.html")
    shutil.copyfile(SCRIPT_DIR / "holdings.js", output / "holdings.js")
    shutil.copyfile(SCRIPT_DIR / "staticwebapp.config.json", output / "staticwebapp.config.json")
    assets = output / "assets"
    assets.mkdir(exist_ok=True)
    shutil.copyfile(REPO_ROOT / "assets" / "web_intro.mp4", assets / "web_intro.mp4")
    shutil.copytree(LANDING / "assets" / "inline", assets / "inline", dirs_exist_ok=True)
    # A missing rewrite target must fail the build instead of becoming a live 404.
    config = json.loads((output / "staticwebapp.config.json").read_text())
    for rule in [*config["routes"], *config["responseOverrides"].values()]:
        if "rewrite" in rule and not (output / rule["rewrite"].lstrip("/")).is_file():
            raise FileNotFoundError(f"Missing route target: {rule['rewrite']}")


def deploy(output: Path) -> None:
    az, npx = shutil.which("az"), shutil.which("npx")
    if not az or not npx:
        raise SystemExit("Deployment requires Azure CLI (az), Node.js (npx), and an active az login. Build-only remains available.")
    target = ["-g", "5dt-final-team3", "-n", "swa-whatif-dev"]
    host = subprocess.run([az, "staticwebapp", "show", *target, "--query", "defaultHostname", "-o", "tsv", "--only-show-errors"],
                          capture_output=True, text=True, check=True).stdout.strip()
    if host != EXPECTED_HOST:
        raise SystemExit(f"Deployment target mismatch: expected {EXPECTED_HOST}, received {host}. Nothing was deployed.")
    result = subprocess.run([az, "staticwebapp", "secrets", "list", *target, "-o", "json", "--only-show-errors"],
                            capture_output=True, text=True, check=True)
    env = os.environ.copy()
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

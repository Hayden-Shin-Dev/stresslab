"""Deploy the What If UI sourced only from apps/web/0.web_main.

The intro is served at / and /dlsxmfh. The V3.8 standalone UI is served at
/quote-monitor and /quote-monito. Its separate inline images are copied into
the same assets/inline path used by the HTML.
Requires az login and Node.js.
"""
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile

result = subprocess.run(
    [
        shutil.which("az"),
        "staticwebapp",
        "secrets",
        "list",
        "-g",
        "5dt-final-team3",
        "-n",
        "swa-whatif-dev",
        "-o",
        "json",
        "--only-show-errors",
    ],
    capture_output=True,
    text=True,
    check=True,
)
env = os.environ.copy()
env["SWA_CLI_DEPLOYMENT_TOKEN"] = json.loads(result.stdout)["properties"]["apiKey"]

script_path = Path(__file__).resolve()
web_root = script_path.parents[1]
repo_root = script_path.parents[3]
landing = web_root / "0.web_main"
standalone = landing / "WHATIF_AGENT_FIXED_STANDALONE_V3_8_MYROOM (1).html"
inline_assets = landing / "assets" / "inline"
intro_video = repo_root / "assets" / "web_intro.mp4"
config = script_path.parent / "staticwebapp.config.json"

with tempfile.TemporaryDirectory(prefix="stresslab-web-") as output_dir:
    output = Path(output_dir)

    for source_name, output_name in [
        ("index.html", "index.html"),
        ("2_style.css", "2_style.css"),
        ("1_skin.css", "1_skin.css"),
        ("2_script.js", "2_script.js"),
    ]:
        shutil.copyfile(landing / source_name, output / output_name)

    shutil.copyfile(standalone, output / "whatif-agent.html")
    shutil.copyfile(config, output / "staticwebapp.config.json")

    assets = output / "assets"
    assets.mkdir()
    shutil.copyfile(intro_video, assets / "web_intro.mp4")
    if not inline_assets.is_dir():
        raise FileNotFoundError(f"Inline image directory not found: {inline_assets}")
    shutil.copytree(inline_assets, assets / "inline")

    subprocess.run(
        [
            shutil.which("npx"),
            "--yes",
            "@azure/static-web-apps-cli",
            "deploy",
            str(output),
            "--env",
            "production",
        ],
        env=env,
        check=True,
    )
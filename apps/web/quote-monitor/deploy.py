"""Deploy the What If intro and existing diagnostic pages to Static Web Apps.

Requires az login and Node.js. Deployment token stays in child environment.
"""
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile

result = subprocess.run([shutil.which('az'), 'staticwebapp', 'secrets', 'list',
    '-g', '5dt-final-team3', '-n', 'swa-whatif-dev', '-o', 'json', '--only-show-errors'],
    capture_output=True, text=True, check=True)
env = os.environ.copy()
env['SWA_CLI_DEPLOYMENT_TOKEN'] = json.loads(result.stdout)['properties']['apiKey']
with tempfile.TemporaryDirectory(prefix='stresslab-web-') as output:
    output = Path(output)
    web_root = Path(__file__).resolve().parents[1]
    landing = web_root / '0_main'
    for name in ['index.html', '2_style.css', '1_skin.css', '2_script.js']:
        shutil.copyfile(landing / name, output / ('index.html' if name == 'index.html' else name))

    shutil.copyfile(Path(__file__).parent / 'index.html', output / 'market.html')
    for name in ['index.html', 'monitor.js', 'market-state.js',
                 'holdings.html', 'holdings.js', 'staticwebapp.config.json']:
        if name == 'index.html':
            continue
        shutil.copyfile(Path(__file__).parent / name, Path(output) / name)
    assets = output / 'assets'
    assets.mkdir()
    shutil.copyfile(Path(__file__).resolve().parents[3] / 'assets' / 'web_intro.mp4', assets / 'web_intro.mp4')
    subprocess.run([shutil.which('npx'), '--yes', '@azure/static-web-apps-cli', 'deploy',
        output, '--env', 'production'], env=env, check=True)

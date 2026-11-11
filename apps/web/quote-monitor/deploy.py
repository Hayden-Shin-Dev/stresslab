"""Deploy the diagnostic site (quotes + market state) to the existing Static Web App.

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
    for name in ['index.html', 'monitor.js', 'market-state.js',
                 'holdings.html', 'holdings.js', 'login.html', 'stress.html', 'stress.js', 'staticwebapp.config.json']:
        shutil.copyfile(Path(__file__).parent / name, Path(output) / name)
    subprocess.run([shutil.which('npx'), '--yes', '@azure/static-web-apps-cli', 'deploy',
        output, '--env', 'production'], env=env, check=True)

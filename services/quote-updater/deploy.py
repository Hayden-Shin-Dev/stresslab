"""Package Linux Python 3.12 dependencies and deploy to the existing Function.

Requires Azure CLI login. Does not change roles, app settings or CORS.
"""
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import zipfile

source = Path(__file__).parent / 'src'
with tempfile.TemporaryDirectory(prefix='stresslab-function-') as temporary:
    root = Path(temporary)
    package = root / 'package'
    package.mkdir()
    for name in ['function_app.py', 'live_push.py', 'host.json', 'requirements.txt']:
        shutil.copyfile(source / name, package / name)
    shutil.copyfile(source.parents[2] / 'ingestion/kiwoom/universe.json', package / 'quote_universe.json')
    subprocess.run([sys.executable, '-m', 'pip', 'install', '-r', str(source / 'requirements.txt'),
                    '--target', str(package / '.python_packages/lib/site-packages'),
                    '--platform', 'manylinux2014_x86_64', '--python-version', '312',
                    '--only-binary=:all:'], check=True)
    archive = root / 'function.zip'
    with zipfile.ZipFile(archive, 'w', zipfile.ZIP_DEFLATED) as output:
        for item in package.rglob('*'):
            if item.is_file():
                output.write(item, item.relative_to(package))
    subprocess.run([shutil.which('az'), 'functionapp', 'deployment', 'source', 'config-zip',
                    '-g', '5dt-final-team3', '-n', 'func-whatif-dev', '--src', str(archive),
                    '--build-remote', 'false', '--only-show-errors', '-o', 'none'], check=True)

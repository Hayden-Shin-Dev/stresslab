param([string]$ImageTag = 'gateway-20261111-v2')
$ErrorActionPreference = 'Stop'
# 2026-11-11 민철 추가: 연구 데이터와 인증 파일을 빌드에 포함하지 않습니다.
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '../..')).Path
$buildRoot = Join-Path ([IO.Path]::GetTempPath()) ('stresslab-gateway-build-' + [guid]::NewGuid())
New-Item -ItemType Directory -Path "$buildRoot/services/debate", "$buildRoot/services/api" -Force | Out-Null
Copy-Item -LiteralPath "$repoRoot/services/debate/src" -Destination "$buildRoot/services/debate/src" -Recurse
Copy-Item -LiteralPath "$repoRoot/services/api/src" -Destination "$buildRoot/services/api/src" -Recurse
Copy-Item -LiteralPath "$repoRoot/services/api/Dockerfile" -Destination "$buildRoot/services/api/Dockerfile"
# 테스트로 생성된 캐시 및 로컬 파일은 업로드하지 않습니다.
@'
**/__pycache__
**/.env*
**/*.pyc
'@ | Set-Content -LiteralPath "$buildRoot/.dockerignore"
az acr build --registry acrwhatifdev5dt --image "common-api:$ImageTag" --file services/api/Dockerfile $buildRoot
if ($LASTEXITCODE -ne 0) { throw 'ACR build failed' }

# 2026-11-11 민철 추가: Entra Application Administrator 또는 Cloud Application Administrator 계정에서 실행합니다.
# 기존 사용자 권한과 앱 소유자는 변경하지 않습니다. 서버 호출 권한 한 건만 부여합니다.
$ErrorActionPreference = 'Stop'
$assignment = @{
    principalId = '2d2c5e07-5567-46e4-8bd5-218c7c7f327f' # id-debate-whatif-dev
    resourceId = 'c0a1e7c9-814f-4ffa-b8d0-f758d0e7b2ee' # ML API 서비스 주체
    appRoleId = '08ab959e-3db1-493e-a01e-d97cfcd1cc64'   # Prediction.Invoke
}
$uri = 'https://graph.microsoft.com/v1.0/servicePrincipals/2d2c5e07-5567-46e4-8bd5-218c7c7f327f/appRoleAssignments'
$existing = az rest --method GET --uri $uri --only-show-errors | ConvertFrom-Json
if ($LASTEXITCODE -ne 0) { throw '역할 조회 실패. 관리자 계정 로그인 상태를 확인하세요.' }
if ($existing.value | Where-Object { $_.resourceId -eq $assignment.resourceId -and $_.appRoleId -eq $assignment.appRoleId }) {
    Write-Output 'Prediction.Invoke 권한이 이미 부여되어 있습니다.'
    exit 0
}
$bodyPath = Join-Path ([IO.Path]::GetTempPath()) ('stresslab-ml-role-' + [guid]::NewGuid() + '.json')
[IO.File]::WriteAllText($bodyPath, ($assignment | ConvertTo-Json), [Text.UTF8Encoding]::new($false))
try {
    az rest --method POST --uri $uri --headers 'Content-Type=application/json' --body "@$bodyPath" --query '{assignment:id,principal:principalId,resource:resourceId,role:appRoleId}' --only-show-errors
    if ($LASTEXITCODE -ne 0) { throw '역할 부여 실패. 앱 소유자 권한만으로는 부여할 수 없습니다.' }
} finally {
    Remove-Item -LiteralPath $bodyPath -Force
}

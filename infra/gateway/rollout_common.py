"""공통 API 이미지만 교체합니다. 다른 담당자의 앱과 인증 설정은 수정하지 않습니다."""
import argparse
import copy
import json
from pathlib import Path

import deploy as d


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--image', required=True)
    p.add_argument('--expected-image', required=True)
    p.add_argument('--backup', required=True)
    args = p.parse_args()
    if not args.image.startswith('acrwhatifdev5dt.azurecr.io/common-api:'):
        raise SystemExit('Only the common-api repository is allowed')
    current = d.call(d.COMMON, '2024-03-01')
    props = current['properties']
    template = copy.deepcopy(props['template'])
    if len(template['containers']) != 1 or template['containers'][0]['image'] != args.expected_image:
        raise SystemExit('Deployed image changed; review before updating')
    if props['latestReadyRevisionName'] != props['latestRevisionName']:
        raise SystemExit('Another deployment is in progress')
    Path(args.backup).write_text(json.dumps(template, indent=2), encoding='utf8')
    # 2026-11-12 민철 추가: 인증, 환경변수, 리소스 크기, 배율 설정을 그대로 보존합니다.
    template['containers'][0]['image'] = args.image
    d.call(d.COMMON, '2024-03-01', 'PATCH', {'properties': {'template': template}})
    print('Common API image rollout submitted')


if __name__ == '__main__':
    main()

"""Acquire one dated official BOK corroboration; does not certify the full ECOS history."""
import hashlib,json,re
from pathlib import Path
import requests

def main():
    url='https://www.bok.or.kr/portal/bbs/P0002018/view.do?menuNo=200366&nttId=11066066'
    r=requests.get(url,timeout=30);r.raise_for_status()
    text=r.content.decode('utf8')
    assert '2026.10.29' in text and '10.28' in text and '3.799%' in text and '\uad6d\uace0\ucc44' in text
    folder=Path('data/research/service_certification_20261104/bok');folder.mkdir(parents=True,exist_ok=True)
    path=folder/'20261029.html';path.write_bytes(r.content)
    evidence=dict(source='korea_3y',observation_date='2026-10-28',value=3.799,
        document_publication_date='2026-10-29',known_by='2026-10-30T00:00:00+09:00',available_at=None,
        availability_basis='official_dated_document_upper_bound',verified=True,url=url,
        sha256=hashlib.sha256(r.content).hexdigest(),scope='One dated official document, not a full historical publication or revision ledger')
    Path('reports/service_certification_20261104/ecos_dated_evidence.json').write_text(json.dumps(evidence,indent=2),encoding='utf8')
    print(json.dumps(evidence))

if __name__=='__main__':main()

"""Read dated BOK domestic market bulletins. No Gold/cloud/model mutation."""
import re,json,html,time,hashlib,threading
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor,as_completed
from datetime import datetime,timedelta,timezone
import requests
ROOT=Path('data/research/pit_rebuild_20261105/bok')
START='2014-02-01';END='2026-10-30'
def save(p,obj):
 p.parent.mkdir(parents=True,exist_ok=True)
 temporary=p.with_name(p.name+'.tmp');temporary.write_text(json.dumps(obj,ensure_ascii=False,indent=2),encoding='utf8');temporary.replace(p)
def clean(s):return html.unescape(re.sub('<[^>]+>',' ',re.sub(r'<!--.*?-->','',s,flags=re.S))).strip()
def main():
 ROOT.mkdir(parents=True,exist_ok=True);records=[];session=requests.Session()
 for page in range(1,116):
  path=ROOT/f'list_{page}.html'
  if not path.exists():
   r=session.get('https://www.bok.or.kr/portal/singl/newsData/listCont.do',params=dict(menuNo='201150',searchKwd='금융시장 주요지표',searchCnd='1',pageUnit=100,pageIndex=page,sort='1'),timeout=40);r.raise_for_status();path.write_bytes(r.content);time.sleep(.5)
  s=path.read_text(encoding='utf8');days=[]
  for block in re.findall(r'<li class="bbsRowCls">(.*?)</li>',s,re.S):
   dates=re.findall(r'20\d\d\.\d\d\.\d\d',block)
   if not dates:continue
   day=dates[0].replace('.','-');days.append(day)
   title=re.search(r'class="title">(.*?)</a>',block,re.S);link=re.search(r'href="([^"]*nttId=(\d+)[^"]*)"',block)
   if not title or not link:continue
   title=clean(title.group(1)).replace(' ','')
   if START<=day<=END and re.fullmatch(r'금융시장주요지표\(\d{1,2}\.\d{1,2}\.?\)',title):records.append(dict(id=link.group(2),publication_date=day,url='https://www.bok.or.kr'+html.unescape(link.group(1)),title=title))
  save(ROOT/'progress.json',dict(stage='listing',page=page,candidates=len(records),oldest=min(days) if days else None))
  if days and min(days)<START:break
 records=list({r['id']:r for r in records}.values());save(ROOT/'catalog.json',records)
 lock=threading.Lock();last=[0.];local=threading.local()
 def fetch(rec):
  path=ROOT/'documents'/(rec['id']+'.html');path.parent.mkdir(exist_ok=True)
  try:
   if not path.exists():
    if not hasattr(local,'session'):local.session=requests.Session()
    for attempt in range(3):
     try:
      with lock:time.sleep(max(0,.45-(time.monotonic()-last[0])));last[0]=time.monotonic()
      r=local.session.get(rec['url'],timeout=40);r.raise_for_status();path.write_bytes(r.content);break
     except requests.RequestException:
      if attempt==2:raise
      time.sleep(3)
   s=path.read_text(encoding='utf8');meta=re.search(r'<meta property="description" content="(.*?)"',s,re.S)
   text=clean(meta.group(1)) if meta else ''
   marker=re.search(r'국고채\s*\(\s*3\s*년\s*\).*?수익률(?:은|는)?\s*\(\s*(\d{1,2})\.\s*(\d{1,2})',text)
   if not marker:return dict(**rec,status='unparsed_observation_date',sha256=hashlib.sha256(path.read_bytes()).hexdigest())
   segment=text[marker.start():];segment=re.split(r'□',segment)[0]
   moves=re.findall(r'(\d+\.\d+)\s*%*\s*(?:→|⇒|->)\s*(\d+\.\d+)\s*%',segment)
   if not moves:return dict(**rec,status='unparsed_rate')
   pub=datetime.fromisoformat(rec['publication_date']);month,day=map(int,marker.groups());year=pub.year-(month>pub.month)
   obs=datetime(year,month,day);lag=(pub-obs).days
   if not 0<=lag<=10:return dict(**rec,status='invalid_observation_lag')
   if rec['publication_date'].replace('-','.') not in s:return dict(**rec,status='publication_date_mismatch')
   return dict(**rec,status='verified_dated_value',observation_date=obs.strftime('%Y-%m-%d'),value=float(moves[0][1]),known_by=(pub+timedelta(days=1)).isoformat()+'+09:00',available_at=None,availability_basis='official_dated_document_upper_bound',sha256=hashlib.sha256(path.read_bytes()).hexdigest())
  except Exception as e:return dict(**rec,status='fetch_failed',error_type=type(e).__name__)
 results=[]
 with ThreadPoolExecutor(max_workers=3) as pool:
  for f in as_completed([pool.submit(fetch,r) for r in records]):
   results.append(f.result())
   if len(results)%10==0 or len(results)==len(records):
    save(ROOT/'evidence.json',results);save(ROOT/'progress.json',dict(stage='documents',completed=len(results),total=len(records),parsed=sum(r['status']=='verified_dated_value' for r in results),failed=sum(r['status']=='fetch_failed' for r in results)))
 save(ROOT/'progress.json',dict(stage='complete',completed=len(results),total=len(records),parsed=sum(r['status']=='verified_dated_value' for r in results),failed=sum(r['status']=='fetch_failed' for r in results)))
 print((ROOT/'progress.json').read_text())
if __name__=='__main__':main()

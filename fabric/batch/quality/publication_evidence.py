"""Official, value-specific availability evidence. Exact publication clocks are never guessed."""
# 2026-11-10 민철 추가: 정기 Bronze 수집마다 공개 이력을 확보하고 Silver/Gold에 연결합니다.
import hashlib
import html
import json
import re
import time
import zipfile
import xml.etree.ElementTree as ET
from html.parser import HTMLParser
from email.utils import parsedate_to_datetime
from pathlib import Path
from datetime import datetime, timezone

import numpy as np
import pandas as pd
import requests

SERIES = {'usdkrw': 'DEXKOUS', 'us_treasury_10y': 'DGS10', 'wti': 'DCOILWTICO', 'vix': 'VIXCLS'}
VERSION = 'official-availability-v3'
COLUMNS = ['source', 'observation_date', 'value', 'known_by', 'valid_until',
           'publication_at', 'availability_basis', 'source_ref', 'evidence_sha256']


def write_json(path, value):
    path = Path(path); path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + '.tmp')
    temp.write_text(json.dumps(value, ensure_ascii=False, default=str, indent=2), encoding='utf8')
    temp.replace(path)


def fred_records(source, payload, ref, digest):
    records = []
    for row in payload.get('observations', []):
        value = pd.to_numeric(row.get('value'), errors='coerce')
        if pd.isna(value) or not np.isfinite(value):
            continue
        # FRED supplies a vintage DATE, not the hour. UTC-12 end-of-day is conservative.
        start = pd.Timestamp(row['realtime_start'], tz='UTC') + pd.Timedelta(hours=36)
        end = row.get('realtime_end', '9999-12-31')
        # Stop before the earliest possible next vintage day (UTC+14).
        until = None if end == '9999-12-31' else pd.Timestamp(end, tz='UTC') + pd.Timedelta(hours=10)
        if until is not None and start >= until:
            continue
        obs = pd.Timestamp(row['date'])
        if obs.date() > start.date():
            raise ValueError('FRED observation after availability bound')
        records.append(dict(source=source, observation_date=str(obs.date()), value=float(value),
            known_by=start.isoformat(), valid_until=None if until is None else until.isoformat(),
            publication_at=None, availability_basis='fred_vintage_date_conservative_upper_bound',
            source_ref=ref, evidence_sha256=digest))
    return records


def clean(text):
    return html.unescape(re.sub('<[^>]+>', ' ', re.sub(r'<!--.*?-->', '', text, flags=re.S))).strip()


class OfficialTables(HTMLParser):
    """Read simple Fed release tables without a non-runtime HTML dependency."""
    def __init__(self, text):
        super().__init__(convert_charrefs=True)
        self.tables=[];self.table=None;self.row=None;self.cell=None
        self.feed(text)
    def handle_starttag(self, tag, attrs):
        if tag=='table':self.table=[]
        elif tag=='tr' and self.table is not None:self.row=[]
        elif tag in ('td','th') and self.row is not None:self.cell=[]
    def handle_data(self, data):
        if self.cell is not None:self.cell.append(data)
    def handle_endtag(self, tag):
        if tag in ('td','th') and self.cell is not None:
            self.row.append(' '.join(' '.join(self.cell).split()));self.cell=None
        elif tag=='tr' and self.row is not None:
            self.table.append(self.row);self.row=None
        elif tag=='table' and self.table is not None:
            self.tables.append(self.table);self.table=None


def bok_record(text, publication_date, ref, digest):
    registered = re.search(r'<dt[^>]*>등록일</dt>\s*<dd class="date">(\d{4}\.\d{2}\.\d{2})</dd>', text)
    if not registered or registered.group(1).replace('.', '-') != publication_date:
        return None, 'registration_unverified'
    meta = re.search(r'<meta property="description" content="(.*?)"', text, re.S)
    body = clean(meta.group(1)) if meta else ''
    marker = re.search(r'국고채\s*\(\s*3\s*년\s*\).*?수익률(?:은|는)?\s*\(\s*(\d{1,2})\.\s*(\d{1,2})', body)
    if not marker:
        return None, 'observation_date_unparsed'
    section = re.split(r'□', body[marker.start():])[0]
    moves = re.findall(r'(\d+\.\d+)\s*%*\s*(?:→|⇒|->)\s*(\d+\.\d+)\s*%', section)
    if not moves:
        return None, 'value_unparsed'
    pub = pd.Timestamp(publication_date); month, day = map(int, marker.groups())
    obs = pd.Timestamp(year=pub.year - int(month > pub.month), month=month, day=day)
    if not 0 <= (pub - obs).days <= 10:
        return None, 'observation_lag_invalid'
    return dict(source='korea_3y', observation_date=str(obs.date()), value=float(moves[0][1]),
        known_by=(pub.tz_localize('Asia/Seoul') + pd.Timedelta(days=1)).isoformat(), valid_until=None,
        publication_at=None, availability_basis='bok_registered_document_date_upper_bound',
        source_ref=ref, evidence_sha256=digest), 'parsed'


def attach_bok_notice_times(records, rss, ref, digest):
    """Same BOK article ID, registered date and parsed value; RSS time is not a schedule assumption."""
    notices={}
    for item in ET.fromstring(rss).findall('./channel/item'):
        link=item.findtext('link') or '';stamp=item.findtext('pubDate')
        match=re.search(r'nttId=(\d+)',link)
        if not match or not stamp:continue
        published=pd.Timestamp(parsedate_to_datetime(stamp)).tz_convert('UTC')
        if published>pd.Timestamp.now(tz='UTC'):continue
        notices[match.group(1)]=published
    for record in records:
        if record['source']!='korea_3y':continue
        match=re.search(r'/bok_(\d+)\.html$',record['source_ref']) or re.search(r'nttId=(\d+)',record.get('original_source_ref',''))
        if not match or match.group(1) not in notices:continue
        published=notices[match.group(1)]
        registered=pd.Timestamp(record['known_by']).tz_convert('Asia/Seoul').normalize()-pd.Timedelta(days=1)
        if published.tz_convert('Asia/Seoul').normalize()!=registered:continue
        if pd.Timestamp(record['observation_date']).date()>registered.date():continue
        record.update(known_by=published.isoformat(),publication_at=published.isoformat(),availability_basis='bok_official_rss_publication_timestamp',
            evidence_dependencies=[{'source_ref':ref,'evidence_sha256':digest}])


def collect(bronze, fred_key, lookback_days=45, today=None):
    """Called by the existing ingestion notebook. Partial failures retry next run; never fabricate evidence."""
    bronze = Path(bronze); now = datetime.now(timezone.utc)
    today = pd.Timestamp(today or now.date()).normalize()
    root = bronze / '_publication'; root.mkdir(parents=True, exist_ok=True)
    previous = json.loads((root/'latest.json').read_text(encoding='utf8')) if (root/'latest.json').exists() else {}
    start = today - pd.Timedelta(days=lookback_days)
    if previous.get('last_complete_date'):
        start = min(start, pd.Timestamp(previous['last_complete_date']) - pd.Timedelta(days=lookback_days))
    run = now.strftime('%Y%m%dT%H%M%S%fZ'); files = []; records = []; status = {}; issues = []
    session = requests.Session()

    def fetch(url, params=None):
        for attempt in range(3):
            try:
                response = session.get(url, params=params, timeout=45)
                response.raise_for_status(); return response
            except requests.RequestException:
                if attempt == 2:
                    # requests exceptions may include the API key in their URL.
                    raise RuntimeError('official_source_request_failed') from None
                time.sleep(1 + attempt)

    def store(provider, filename, content, url):
        rel = f'{provider}/publication/{run}/{filename}'; path = bronze/rel
        path.parent.mkdir(parents=True, exist_ok=True); path.write_bytes(content)
        digest = hashlib.sha256(content).hexdigest()
        files.append(dict(file=rel, sha256=digest, source_url=url, received_at=datetime.now(timezone.utc).isoformat()))
        return 'Files/bronze/'+rel, digest

    for source, series in SERIES.items():
        before = len(records)
        try:
            offset = 0
            while True:
                url = 'https://api.stlouisfed.org/fred/series/observations'
                response = fetch(url, dict(api_key=fred_key, file_type='json', series_id=series,
                    observation_start=str(start.date()), observation_end=str(today.date()),
                    realtime_start=str(start.date()), realtime_end=str(today.date()), output_type=1,
                    limit=10000, offset=offset))
                payload = response.json(); rows = payload.get('observations', [])
                if 'count' not in payload or (not rows and offset < int(payload['count'])):
                    raise ValueError('incomplete_fred_response')
                ref, digest = store('fred', f'{series}_{offset}.json', response.content, url+'?series_id='+series)
                records.extend(fred_records(source, payload, ref, digest))
                offset += len(rows)
                if offset >= int(payload['count']): break
            status[source] = dict(status='complete', records=len(records)-before)
            # Series-level update timestamps are archived, NOT assigned to every observation.
            meta_url = 'https://api.stlouisfed.org/fred/series'
            meta = fetch(meta_url, dict(api_key=fred_key, file_type='json', series_id=series))
            store('fred', f'{series}_metadata.json', meta.content, meta_url+'?series_id='+series)
            status[source]['series_last_updated'] = meta.json()['seriess'][0].get('last_updated')
        except Exception as exc:
            # Discard partially paged series. Its files remain diagnostic evidence.
            del records[before:]
            status[source] = dict(status='retry_required', reason=type(exc).__name__)

    before = len(records)
    try:
        catalog = {}; finished = False
        for page in range(1, 121):
            url = 'https://www.bok.or.kr/portal/singl/newsData/listCont.do'
            response = fetch(url, dict(menuNo='201150', searchKwd='금융시장 주요지표', searchCnd='1', pageUnit=100, pageIndex=page, sort='1'))
            store('ecos', f'bok_list_{page}.html', response.content, url)
            dates = []
            for block in re.findall(r'<li class="bbsRowCls">(.*?)</li>', response.content.decode('utf8'), re.S):
                ds = re.findall(r'20\d\d\.\d\d\.\d\d', block)
                if not ds: continue
                day = ds[0].replace('.', '-'); dates.append(day)
                title = re.search(r'class="title">(.*?)</a>', block, re.S)
                link = re.search(r'href="([^"]*nttId=(\d+)[^"]*)"', block)
                if (title and link and str(start.date()) <= day <= str(today.date()) and
                    re.fullmatch(r'금융시장주요지표\((?:금리,?주가,?환율,)?\d{1,2}\.\d{1,2}\.?\)', re.sub(r'\s+', '', clean(title.group(1))))):
                    catalog[link.group(2)] = (day, 'https://www.bok.or.kr'+html.unescape(link.group(1)))
            if not dates: raise ValueError('bok_listing_empty_or_format_changed')
            if min(dates) < str(start.date()): finished = True; break
        if not finished: raise ValueError('bok_listing_incomplete')
        if not catalog: raise ValueError('bok_catalog_empty')
        for doc_id, (day, url) in catalog.items():
            response = fetch(url)
            ref, digest = store('ecos', f'bok_{doc_id}.html', response.content, url)
            record, reason = bok_record(response.content.decode('utf8'), day, ref, digest)
            if record: records.append(record)
            else: issues.append(dict(source='korea_3y', document=doc_id, reason=reason))
            time.sleep(.2)
        status['korea_3y'] = dict(status='complete' if len(records)>before else 'retry_required', records=len(records)-before, unparsed=len(issues))
    except Exception as exc:
        status['korea_3y'] = dict(status='retry_required', reason=type(exc).__name__, records=len(records)-before)

    # 2026-11-10 민철 추가: 다른 공식 기관의 실제 발표 알림과 수치가 일치할 때만 정확 시각을 채웁니다.
    alternate = {}
    for label, url in {
        'fed_h10_rss': 'https://www.federalreserve.gov/feeds/h10.xml',
        'fed_h15_rss': 'https://www.federalreserve.gov/feeds/h15.xml',
        'fed_h10_definition': 'https://www.federalreserve.gov/releases/h10/About.HTM',
        'bok_market_rss': 'https://www.bok.or.kr/portal/bbs/P0002018/news.rss?menuNo=200366',
        'eia_spot': 'https://www.eia.gov/dnav/pet/pet_pri_spt_s1_d.htm',
        'cboe_daily': 'https://cdn.cboe.com/api/global/us_indices/daily_prices/VIX_History.csv',
    }.items():
        try:
            if label=='bok_market_rss':
                count=0
                for month in pd.date_range(start.replace(day=1),today,freq='MS'):
                    lo=max(month,start);hi=min(month+pd.offsets.MonthEnd(1),today)
                    response=fetch(url,{'sdate':str(lo.date()),'edate':str(hi.date())})
                    items=ET.fromstring(response.content).findall('./channel/item')
                    if len(items)>=100:raise ValueError('bok_rss_month_truncated')
                    for item in items:
                        d=pd.Timestamp(parsedate_to_datetime(item.findtext('pubDate'))).tz_convert('Asia/Seoul').tz_localize(None).normalize()
                        if not lo<=d<=hi:raise ValueError('bok_rss_date_filter_ignored')
                    ref,digest=store('ecos',label+'_'+month.strftime('%Y%m')+'.raw',response.content,url+'&sdate='+str(lo.date())+'&edate='+str(hi.date()))
                    attach_bok_notice_times(records,response.content,ref,digest);count+=len(items)
                alternate[label]=dict(status='collected',notices=count)
                continue
            response = fetch(url); ref, digest = store('ecos' if label.startswith('bok') else 'fred', label+'.raw', response.content, url)
            alternate[label] = dict(status='collected', source_ref=ref)
            if label == 'fed_h10_rss':
                for item in ET.fromstring(response.content).iter():
                    if item.tag.split('}')[-1] != 'item': continue
                    fields = {el.tag.split('}')[-1]:el.text for el in item}
                    desc = fields.get('description') or ''
                    match = re.match(r'(\w+ \d{1,2}, \d{4}) Foreign Exchange Rates data are now available', desc)
                    if not match or not fields.get('date'): continue
                    release = pd.Timestamp(match.group(1)); published = pd.Timestamp(fields['date']).tz_convert('UTC')
                    if release < start or release > today: continue
                    archive_url = 'https://www.federalreserve.gov/releases/h10/'+release.strftime('%Y%m%d')+'/'
                    archive = fetch(archive_url)
                    archive_ref, archive_hash = store('fred','h10_'+release.strftime('%Y%m%d')+'.html', archive.content, archive_url)
                    text=archive.content.decode('utf8')
                    if 'Release Date: '+release.strftime('%B')+' '+str(release.day)+', '+str(release.year) not in ' '.join(clean(text).split()):
                        raise ValueError('release_document_date_mismatch')
                    for table in OfficialTables(text).tables:
                        dates = None
                        for cells in table:
                            if len(cells)==7 and cells[0]=='COUNTRY':
                                dates=[]
                                for d in cells[-5:]:
                                    obs=pd.Timestamp(d.replace('.','')+' '+str(release.year))
                                    if obs>release:obs=obs.replace(year=obs.year-1)
                                    dates.append(obs)
                            if dates and len(cells)==7 and cells[0]=='SOUTH KOREA':
                                for obs, value in zip(dates,cells[-5:]):
                                    value=pd.to_numeric(value,errors='coerce')
                                    if pd.isna(value):continue
                                    records.append(dict(source='usdkrw',observation_date=str(obs.date()),value=float(value),
                                        known_by=published.isoformat(),valid_until=None,publication_at=published.isoformat(),
                                        availability_basis='official_ddp_available_notice_timestamp',source_ref=archive_ref,evidence_sha256=archive_hash,
                                        evidence_dependencies=[{'source_ref':ref,'evidence_sha256':digest}]))
        except Exception as exc:
            alternate[label]=dict(status='retry_required',reason=type(exc).__name__)
    evidence_path = root/run/'records.json'; write_json(evidence_path, records)
    manifest = dict(version=VERSION, run=run, collected_at=now.isoformat(), start=str(start.date()),
        end=str(today.date()), sources=status, alternate_sources=alternate, issues=issues, files=files,
        records_file=str(evidence_path.relative_to(bronze)).replace('\\','/'),
        records_sha256=hashlib.sha256(evidence_path.read_bytes()).hexdigest())
    manifest['status'] = 'complete' if all(x['status']=='complete' for x in status.values()) and all(x['status']=='collected' for x in alternate.values()) else 'partial'
    manifest['last_complete_date'] = str(today.date()) if manifest['status']=='complete' else previous.get('last_complete_date')
    write_json(root/run/'manifest.json', manifest); write_json(root/'latest.json', manifest)
    return dict(status=manifest['status'], run=run, sources=status, alternate_sources=alternate,
        explicit_publication_records=sum(r.get('publication_at') is not None for r in records), exact_publication_clocks=False)


def load_ledger(bronze):
    """Only accept normalized records backed by immutable, hash-verified raw documents."""
    bronze = Path(bronze).resolve(); all_records = []
    for path in sorted((bronze/'_publication').glob('*/manifest.json')):
        manifest = json.loads(path.read_text(encoding='utf8'))
        def checked(rel, digest):
            p = (bronze/rel).resolve()
            if not p.is_relative_to(bronze): raise ValueError('evidence_path_escape')
            if hashlib.sha256(p.read_bytes()).hexdigest()!=digest: raise ValueError('evidence_hash_mismatch')
            return p
        evidence = checked(manifest['records_file'], manifest['records_sha256'])
        refs = {}
        for f in manifest['files']:
            file_path = checked(f['file'], f['sha256']); refs['Files/bronze/'+f['file']] = f['sha256']
            if f.get('archive_members'):
                with zipfile.ZipFile(file_path) as archive:
                    for member, digest in f['archive_members'].items():
                        if hashlib.sha256(archive.read(member)).hexdigest() != digest:
                            raise ValueError('archive_evidence_hash_mismatch')
                        refs['Files/bronze/'+f['file']+'#'+member] = digest
        for r in json.loads(evidence.read_text(encoding='utf8')):
            if refs.get(r['source_ref']) != r['evidence_sha256']: raise ValueError('unbacked_publication_record')
            for dep in r.get('evidence_dependencies',[]):
                if refs.get(dep['source_ref']) != dep['evidence_sha256']: raise ValueError('unbacked_release_notice')
            all_records.append(r)
    frame = pd.DataFrame(all_records, columns=COLUMNS)
    frame.observation_date = pd.to_datetime(frame.observation_date).astype('datetime64[ns]')
    for col in ['known_by', 'valid_until', 'publication_at']:
        frame[col] = pd.to_datetime(frame[col], utc=True)
    frame = frame.drop_duplicates(['source','observation_date','value','known_by','valid_until'])
    return frame


def select_evidence(rows, ledger, source):
    """Match value, observation and vintage interval; never assign evidence for a different revision."""
    q = rows[['trading_date','observation_date','value']].reset_index(drop=True).copy()
    q['row_id'] = q.index
    evidence = ledger[ledger.source.eq(source)].copy()
    candidates = q.merge(evidence, on=['observation_date','value'], how='inner')
    cutoff = pd.to_datetime(candidates.trading_date, utc=True) + pd.Timedelta(hours=6, minutes=30)
    candidates = candidates[candidates.known_by.le(cutoff) &
        (candidates.valid_until.isna() | cutoff.lt(candidates.valid_until))]
    chosen = candidates.sort_values('known_by').drop_duplicates('row_id', keep='last').set_index('row_id')
    return chosen.reindex(q.index)[['known_by','publication_at','availability_basis','source_ref','evidence_sha256']]


def fx_observed_at(observation_dates, series_metadata):
    """DEXKOUS is defined by the publisher as New York noon quotes; not a publication time."""
    item = series_metadata['seriess'][0]
    definition=series_metadata.get('_observation_definition_text',item.get('notes','')).lower()
    if item['id'] != 'DEXKOUS' or not re.search(r'noon buying rates in new york',definition):
        raise ValueError('FX observation-time definition unverified')
    days = pd.to_datetime(observation_dates)
    return (days + pd.Timedelta(hours=12)).dt.tz_localize('America/New_York').dt.tz_convert('UTC')


def exact_publication_for_values(rows, ledger, source):
    """Return a recorded official notice time, even when later than the model date. Caller must gate it."""
    q=rows[['observation_date','value']].reset_index(drop=True).copy();q['row_id']=q.index
    evidence=ledger[ledger.source.eq(source) & ledger.publication_at.notna()]
    evidence=evidence.sort_values('publication_at').drop_duplicates(['observation_date','value'])
    joined=q.merge(evidence[['observation_date','value','publication_at']],on=['observation_date','value'],how='left',validate='many_to_one')
    return joined.sort_values('row_id').publication_at.reset_index(drop=True)


def latest_fx_metadata(bronze):
    bronze=Path(bronze);manifests=sorted((bronze/'_publication').glob('*/manifest.json'),reverse=True)
    for p in manifests:
        m=json.loads(p.read_text(encoding='utf8'))
        for f in m['files']:
            if f['file'].endswith('/DEXKOUS_metadata.json'):
                data=(bronze/f['file']).read_bytes()
                if hashlib.sha256(data).hexdigest()!=f['sha256']:raise ValueError('metadata_hash_mismatch')
                result=json.loads(data)
                definition=next((x for x in m['files'] if x['file'].endswith('/fed_h10_definition.raw')),None)
                if definition:
                    raw=(bronze/definition['file']).read_bytes()
                    if hashlib.sha256(raw).hexdigest()!=definition['sha256']:raise ValueError('definition_hash_mismatch')
                    result['_observation_definition_text']=clean(raw.decode('utf8'))
                    result['_observation_definition_source']=definition['source_url']
                    result['_observation_definition_sha256']=definition['sha256']
                    return result
                if re.search(r'noon buying rates in new york',result['seriess'][0].get('notes','').lower()):return result
    raise ValueError('FX source definition missing')

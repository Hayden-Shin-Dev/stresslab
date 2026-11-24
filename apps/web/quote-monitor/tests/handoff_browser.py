"""Handoff browser regression with explicitly synthetic API fixtures, never Azure.
Start static server at :8876; run with Python Playwright. Artifacts go to /tmp.
"""
import json
import os
from copy import deepcopy
from urllib.parse import urlparse
from playwright.sync_api import sync_playwright
from workspace_browser import STRESS


def main():
 with sync_playwright() as p:
  browser=p.chromium.launch(executable_path=os.environ.get('CHROME_PATH','/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'),headless=True)
  page=browser.new_page(viewport={'width':1440,'height':1000});page.set_default_timeout(10000)
  errors=[];calls=[];records={};prefs={'revision':0,'settings':{}};fail=[False];hold=[False];pending=[];research=[];requests=[];storage_enabled=os.environ.get('WHATIF_STORAGE_ENABLED','true').lower()!='false'
  page.on('pageerror',lambda e:errors.append(str(e)))
  def route(r):
   path=urlparse(r.request.url).path;method=r.request.method;data={};status=200;requests.append((method,path))
   if path.endswith('/debates') and method=='POST':
    research.append(r.request.post_data_json);status=202;data={'debate_id':'d-research-fixture','pubsub':{}}
   elif path.endswith('/debates'):data={'debates':[{'debate_id':'d-history-fixture','run_id':'a-browser-1','status':'completed','created_at':'2026-11-24T01:00:00Z'}]}
   elif path.endswith('/d-history-fixture/context'):data={'context':{'evidence_bundle_id':'bundle-frozen','D_sources':[{'id':'D1','label':'당시 기준값','value':123,'unit':'KRW','asset_id':'005930'}],'S_sources':[]},'deleted_origin_run_ids':[]}
   elif path.endswith('/d-history-fixture/events'):data={'events':[{'seq':1,'type':'message.created','created_at':'2026-11-24T01:00:00Z','payload':{'role':'risk','display_text':'과거 발언 fixture','structured_source_ids':['D1']}}],'next_after_seq':1}
   elif path.endswith('/questions'):status=202;data={'question_id':'q-fixture'}
   elif path.endswith('/events'):data={'events':[{'event_id':'done-fixture','seq':1,'type':'debate.completed','payload':{}}]}
   elif path.endswith('/stress/support'):data={'supported_assets':['005930','000660']}
   elif path.endswith('/stress/analyze'):
    body=r.request.post_data_json;calls.append(body)
    if hold[0]:pending.append(r);return
    if fail[0]:status=503;data={'detail':'fixture failure'}
    else:
     data=deepcopy(STRESS);data.update(analysis_id='a-browser-'+str(len(calls)),analysis_type=body['analysis_type'],shocks=body['shocks'],archive_status={'persisted':storage_enabled,'disabled':not storage_enabled},ai_handoff={'ready':False})
     data['assets'][0]['model_interval_90_return_pct']={'lower':-5,'upper':3}
     records[data['analysis_id']]={'run_id':data['analysis_id'],'result':deepcopy(data),'created_at':'2026-11-24T01:00:00Z','context':None,'archived':False}
   elif path.endswith('/quotes/latest'):data={'type':'quote_snapshot','quotes':[{'record_type':'quote_latest','is_mock':False,'asset_id':'005930','price':178850,'event_time':'2026-11-24T01:00:00Z'}]}
   elif '/quotes/history/' in path:data={'asset_id':path.rsplit('/',1)[-1],'source':'fixture_daily_prices','rows':[{'at':'2026-11-20','price':170000},{'at':'2026-11-23','price':175000},{'at':'2026-11-24','price':178850}]}
   elif path.endswith('/workspace-settings'):
    if method=='PUT':prefs.update(revision=prefs['revision']+1,settings=r.request.post_data_json['settings'])
    data=prefs
   elif path.endswith('/me/analyses'):data={'analyses':[x for x in records.values() if x['archived']]}
   elif '/me/analyses/' in path:
    suffix=path.split('/me/analyses/')[1].split('/');row=records.get(suffix[0]);data=row or {}
    if row and method=='PUT':
     if suffix[-1]=='context':row['context']=r.request.post_data_json
     if suffix[-1]=='archive':row['archived']=True
    if row is None:status=404
   elif path.endswith('/me'):data={'workspace_storage_enabled':storage_enabled}
   elif path.endswith('/holdings'):data={'holdings':[]}
   else:status=503
   r.fulfill(status=status,content_type='application/json',body=json.dumps(data))
  page.route('**/api/**',route)
  page.route('**/.auth/me',lambda r:r.fulfill(content_type='application/json',body=json.dumps({'clientPrincipal':{'identityProvider':'fixture','userId':'browser-user'}})))
  page.route('**/.auth/logout?**',lambda r:r.fulfill(content_type='text/html',body='<p>fixture logout</p>'))
  page.goto(os.environ.get('WHATIF_TEST_URL','http://127.0.0.1:8876/whatif-v6/'),wait_until='domcontentloaded')
  page.wait_for_function("typeof window.WHATIF_QA?.enter === 'function'");page.evaluate("WHATIF_QA.enter(); WHATIF_QA.open('sim')")
  main=page.locator('.handoff-inputs');main.locator('[data-analysis-code="005930"]').wait_for()
  play=page.locator('.fig-run-button');play.click()
  page.get_by_text('분석 대상 종목을 한 개 이상 선택해 주세요.',exact=True).first.wait_for();assert not calls
  main.locator('[data-analysis-code="005930"]').check()
  assert page.locator('.handoff-agent-selection [data-analysis-code="005930"]').is_checked()
  play.click();page.wait_for_function("WHATIF_QA.getSourceState().runs.some(r=>r.id==='a-browser-1')")
  if storage_enabled:page.wait_for_function("WHATIF_QA.getSourceState().runs.some(r=>r.id==='a-browser-1'&&r.archiveContextSaved)")
  assert calls[0]['positions']==[{'asset_id':'005930','value_krw':1000000}]
  assert calls[0]['analysis_type']=='market'
  run_id=page.evaluate('WHATIF_QA.getSourceState().runId');count=page.evaluate('WHATIF_QA.getSourceState().runs.length')
  if storage_enabled:
   page.locator('[data-current-save]').click();page.get_by_text('서버 보관 완료',exact=True).wait_for()
   assert records['a-browser-1']['archived']
   page.locator('[data-open-archive]').click();page.get_by_role('dialog',name='결과 보관소',exact=True).wait_for()
   page.locator('[data-archive-detail="a-browser-1"]').click()
   assert page.evaluate('WHATIF_QA.getSourceState().runId')==run_id
   assert page.get_by_role('dialog',name='결과 보관소',exact=True).get_by_text('입력 충격 중심',exact=True).count()==1
   page.keyboard.press('Escape');page.locator('dialog.handoff-archive').wait_for(state='detached')
  else:
   assert not page.locator('[data-current-save],[data-open-archive],[data-account-data]').count()
   page.get_by_text('결과 보관소·실행 비교는 준비 중입니다. 현재 결과는 이 화면에서 확인해 주세요.',exact=True).wait_for()
  fail[0]=True;play.click();page.get_by_text('요청 실패 (503). 다시 시도해 주세요.',exact=True).first.wait_for()
  assert page.evaluate('WHATIF_QA.getSourceState().runId')==run_id
  assert page.evaluate('WHATIF_QA.getSourceState().runs.length')==count
  fail[0]=False;hold[0]=True;play.click();page.get_by_role('button',name='계산 요청 취소',exact=True).click()
  for request in pending:
   try:request.fulfill(status=200,content_type='application/json',body=json.dumps(STRESS))
   except Exception:pass
  page.wait_for_timeout(200)
  assert page.evaluate('WHATIF_QA.getSourceState().runId')==run_id
  assert page.evaluate('WHATIF_QA.getSourceState().runs.length')==count
  hold[0]=False;play.click();page.wait_for_function("WHATIF_QA.getSourceState().runs.some(r=>r.id==='a-browser-4')")
  before=page.evaluate('WHATIF_QA.getSourceState().runId')
  if storage_enabled:page.wait_for_function("WHATIF_QA.getSourceState().runs.some(r=>r.id==='a-browser-4'&&r.archiveContextSaved)")
  if storage_enabled:
   page.locator('[data-open-archive]').click()
   page.locator('[data-archive-select="a-browser-1"]').check();page.locator('[data-archive-select="a-browser-4"]').check()
   page.locator('[data-archive-baseline]').wait_for()
   before=page.evaluate('WHATIF_QA.getSourceState().runId');page.locator('[data-archive-detail="a-browser-1"]').click()
   assert page.evaluate('WHATIF_QA.getSourceState().runId')==before
   page.locator('[data-comparison-start]').click()
   page.get_by_text('비교 토론 완료 · 이 답변은 당시 비교 대상과 기준에 고정됩니다.',exact=True).wait_for()
   assert research[-1]['mode']=='comparison'
   page.screenshot(path='/tmp/whatif-handoff-archive.png')
   assert not page.locator('[data-archive-delete],[data-delete-confirm],[data-account-data]').count()
   page.keyboard.press('Escape')
  page.locator('[data-open-history]').click();page.locator('[data-history-id="d-history-fixture"]').click()
  page.get_by_text('과거 발언 fixture',exact=True).wait_for()
  page.get_by_text('이 발언의 고정 근거 · bundle-frozen',exact=True).click()
  page.get_by_text('당시 기준값',exact=True).wait_for()
  assert page.evaluate('WHATIF_QA.getSourceState().runId')==before
  page.keyboard.press('Escape')
  page.locator('[data-open-similarity]').click();page.get_by_role('dialog',name='유사 시장 국면',exact=True).wait_for()
  page.get_by_text('저장된 보유 종목 없음 또는 조회 대기',exact=True).wait_for();page.keyboard.press('Escape')
  before_calls=len(calls)
  page.locator('[data-chat-input="scenario"]').fill('SK하이닉스 분석 대상에 추가')
  page.locator('[data-action="send-chat"][data-key="scenario"]').click()
  assert main.locator('[data-analysis-code="000660"]').is_checked()
  assert len(calls)==before_calls
  main.locator('[data-analysis-code="000660"]').uncheck()
  assert not page.locator('.handoff-agent-selection [data-analysis-code="000660"]').is_checked()
  page.locator('.fig-main-panel').evaluate('(el)=>el.scrollTop=el.scrollHeight')
  page.screenshot(path='/tmp/whatif-handoff-chart.png')
  page.set_viewport_size({'width':390,'height':844});page.emulate_media(reduced_motion='reduce')
  page.locator('.fig-chart-panel').scroll_into_view_if_needed();page.screenshot(path='/tmp/whatif-handoff-mobile-chart.png')
  assert page.locator('.fig-scenario-screen[role=dialog]').evaluate('(el)=>el.scrollWidth <= el.clientWidth+2')
  page.set_viewport_size({'width':1440,'height':1000})
  before_calls=len(calls)
  with page.expect_popup() as popup_info:
   page.locator('[data-handoff-panel="agent"] .handoff-window-bar').get_by_role('button',name='별도 창',exact=True).click()
  popup=popup_info.value;popup.wait_for_load_state('domcontentloaded');popup.set_default_timeout(8000)
  try:popup.wait_for_function("getComputedStyle(document.body).display==='flex'",timeout=8000)
  except Exception:
   print(popup.evaluate("({url:location.href,body:document.body.className,styles:[...document.querySelectorAll('link')].map(x=>({href:x.href,sheet:!!x.sheet})),display:getComputedStyle(document.body).display})"));raise
  popup.locator('[data-chat-input="scenario"]').fill('분리 창 초안')
  assert page.locator('[data-chat-input="scenario"]').input_value()=='분리 창 초안'
  popup.screenshot(path='/tmp/whatif-handoff-detached-agent.png')
  popup.get_by_role('button',name='메인 창으로 복귀',exact=True).click()
  assert page.locator('[data-chat-input="scenario"]').input_value()=='분리 창 초안'
  page.locator('[data-handoff-panel="agent"] .handoff-window-bar').get_by_role('button',name='이동 창',exact=True).click()
  assert page.locator('.handoff-floating:not(.handoff-hidden-view)').count()==1
  page.locator('[data-handoff-panel="agent"] .handoff-window-bar').get_by_role('button',name='오른쪽 도킹',exact=True).click()
  assert not page.locator('.handoff-floating:not(.handoff-hidden-view)').count()
  page.get_by_role('button',name='분석 최소화',exact=True).click()
  assert page.evaluate('WHATIF_QA.getSourceState().runId')==before
  assert page.locator('.handoff-floating [data-handoff-panel="result"]').is_visible()
  page.locator('.handoff-taskbar').get_by_role('button',name='시나리오 분석',exact=True).click()
  assert len(calls)==before_calls
  page.get_by_role('button',name='분석 종료 · 엔진 연결 해제',exact=True).click()
  page.get_by_text('독립 리서치 · 엔진 연결 해제',exact=True).wait_for()
  page.locator('[data-chat-input="scenario"]').fill('선택한 자료를 설명해 주세요')
  page.locator('[data-action="send-chat"][data-key="scenario"]').click()
  page.wait_for_function("WHATIF_QA.getSourceState().workspace.researchRun?.debateId==='d-research-fixture'")
  assert research[-1]['mode']=='research' and 'run_id' not in research[-1]
  assert len(calls)==before_calls
  page.locator('[data-handoff-panel="agent"] .handoff-window-bar').get_by_role('button',name='최소화',exact=True).click()
  for panel in ['minutes','account','collab']:
   page.evaluate('(panel)=>WHATIF_QA.open(panel)',panel)
   if panel=='collab':
    # Rendering a fixture room, without starting an actual meeting/AI request.
    page.evaluate('WHATIF_QA.getSourceState().collab.started=true')
    page.locator('[data-gx="m48-start"]').first.click()
   common=page.locator('.p41-feature.handoff-common').first
   common.wait_for(state='visible')
   page.screenshot(path='/tmp/whatif-handoff-'+panel+'.png')
   heading=common.evaluate('(el)=>({size:getComputedStyle(el.querySelector("h2")).fontSize,html:el.querySelector("h2").outerHTML})')
   assert heading['size'] in ['18px','22px'],(panel,heading)
  page.evaluate("WHATIF_QA.getSourceState().collab.started=false;WHATIF_QA.room56('myroom')")
  assert page.evaluate('WHATIF_QA.getState().room')=='myroom'
  page.screenshot(path='/tmp/whatif-handoff-private-room.png')
  page.evaluate("WHATIF_QA.room56('office');WHATIF_QA.open('sim')")
  page.set_viewport_size({'width':720,'height':500})
  assert page.locator('.fig-scenario-screen[role=dialog]').evaluate('(el)=>el.scrollWidth<=el.clientWidth+2')
  page.screenshot(path='/tmp/whatif-handoff-narrow-desktop.png')
  page.set_viewport_size({'width':1440,'height':1000})
  page.get_by_role('button',name='분석 종료 · 엔진 연결 해제',exact=True).click()
  assert not page.locator('[data-account-data],[data-account-remove],[data-archive-delete]').count()
  assert not any(method=='DELETE' for method,path in requests)
  if not storage_enabled:
   assert not any('/me/analyses' in path or '/workspace-settings' in path or '/account-data' in path for method,path in requests)
  assert not errors, errors
  print(json.dumps({'empty_selection_blocked':True,'agent_selection_synced':True,'natural_language_selection_without_compute':True,'selected_only_request':True,'archive_roundtrip_fixture':storage_enabled,'read_only_details':True,'failed_and_cancelled_keep_success':True,'two_run_comparison':storage_enabled,'comparison_ai_request':storage_enabled,'history_frozen_source':True,'similarity_separate_window':True,'mobile_no_page_overflow':True,'detached_draft_roundtrip':True,'float_redock':True,'minimize_preserves_analysis':True,'close_switches_research_without_engine':True,'common_program_rendering':True,'permanent_deletion_removed':True,'storage_enabled':storage_enabled,'page_errors':errors},ensure_ascii=False))
  browser.close()

if __name__=='__main__':main()

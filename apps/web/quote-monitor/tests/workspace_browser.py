"""Local browser contract test. Uses labeled fixture API responses, never Azure.
Run with a local static server at :8765 and Python playwright installed.
"""
import json
from urllib.parse import urlparse, parse_qs
from playwright.sync_api import sync_playwright

STRESS={'analysis_id':'a-browser-fixture','ai_handoff':{'ready':True},'model':'ridge','horizon_trading_days':5,
 'portfolio_hypothetical_pnl_krw':-20000,'portfolio_shock_incremental_pnl_krw':-30000,
 'model_context':{'as_of_trading_date':'2026-11-09'},'assets':[{'asset_id':'005930','holding_krw':1000000,
 'baseline_model_return_pct':1,'scenario_return_pct':-2,'baseline_pnl_krw':10000,'hypothetical_pnl_krw':-20000,'shock_incremental_pnl_krw':-30000}]}
ARTICLE={'title':'브라우저 검증용 기사','url':'https://news.google.com/rss/articles/fixture','publisher':'테스트 출처','publishedAt':'2026-11-23T01:00:00Z'}

def main():
 with sync_playwright() as p:
  browser=p.chromium.launch(executable_path='/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',headless=True)
  page=browser.new_page(viewport={'width':1440,'height':1000});errors=[];starts=[];questions=[];events=[]
  page.on('pageerror',lambda e:errors.append(str(e)))
  def route(r):
   path=urlparse(r.request.url).path;body=r.request.post_data_json if r.request.method=='POST' else None
   result={};status=200
   if path.endswith('/stress/support'):result={'supported_assets':['005930']}
   elif path.endswith('/stress/analyze'):result=STRESS
   elif path.endswith('/quotes/latest'):result={'type':'quote_snapshot','quotes':[{'record_type':'quote_latest','is_mock':False,'asset_id':code,'price':price,'cumulative_volume':16429837,'event_time':'2026-11-23T06:02:06Z','received_at':'2026-11-23T06:02:07Z','venue':'KRX','session':'regular'} for code,price in [('005930',178850),('000660',1093000)]]}
   elif path.endswith('/news/latest'):result={'articles':[ARTICLE],'fetchedAt':'2026-11-23T01:00:00Z'}
   elif path.endswith('/dart/companies'):result={'companies':[{'corp_code':'00126380','corp_name':'삼성전자','stock_code':'005930'}]}
   elif path.endswith('/dart/disclosures'):result={'list':[{'rcept_no':'20250327000281','report_nm':'검증 공시','corp_name':'삼성전자','rcept_dt':'20250327'}],'total_count':'1','total_page':1}
   elif path.endswith('/preview'):result={'status':'ok','text':'검증용 공시 본문','html':'<table><tr><td>검증 본문</td></tr></table>'}
   elif path.endswith('/debates') and body:
    starts.append(body);did='d-browser-fixture'
    events.extend([{'event_id':'e1','seq':1,'type':'debate.evidence_ready','payload':{'d_public':[{'id':'D1','label':'입력 충격 손익','value':-20000,'unit':'원'}],'selected_sources':[dict(x,status='ready') for x in body['selected_sources']]}},
     {'event_id':'e2','seq':2,'type':'message.created','payload':{'role':'risk','message_id':'m1','display_text':'검증용 서버 응답입니다.','structured_source_ids':['D1'],'stance':'first'}},
     {'event_id':'e3','seq':3,'type':'debate.completed','payload':{'failed_roles':[]}}])
    result={'debate_id':did,'status':'accepted'}
   elif path.endswith('/events'):
    after=int(parse_qs(urlparse(r.request.url).query).get('after_seq',['0'])[0]);result={'events':[dict(e,created_at='2026-11-23T01:00:00Z',debate_id='d-browser-fixture') for e in events if e['seq']>after]}
   elif path.endswith('/questions'):
    questions.append(body);result={'question_id':'q1','status':'accepted'}
    events.append({'event_id':'e4','seq':4,'type':'message.created','payload':{'role':body['target_roles'][0],'question_id':'q1','message_id':'m2','display_text':'개별 질문 검증 응답','structured_source_ids':['D1'],'stance':'first'}})
   elif path.endswith('/negotiate'):status=503;result={'detail':'테스트에서 소켓 미사용 · 이벤트 복구 경로 검증'}
   elif path.endswith('/holdings'):result={'holdings':[]}
   else:status=503;result={'detail':'검증 환경에서 미제공'}
   r.fulfill(status=status,content_type='application/json',body=json.dumps(result))
  page.route('**/api/**',route)
  page.goto('http://127.0.0.1:8765/whatif-v6/',wait_until='domcontentloaded')
  def enter():
   page.get_by_role('button',name='여정 시작',exact=True).click();page.get_by_role('textbox',name='사용자 이름').fill('검증');page.get_by_role('button',name='로그인',exact=True).click();page.get_by_role('button',name='영상 건너뛰기',exact=False).click();page.get_by_role('button',name='시나리오 분석',exact=True).click();page.wait_for_selector('.ws-screen')
  enter()
  for i in [0,1,3]:page.locator('.fig-shared-agent-option').nth(i).click()
  page.locator('.fig-shared-agent-option').nth(2).click();assert page.locator('[data-role-choice]').nth(2).is_checked()
  assert page.locator('.fig-main-panel').is_visible()
  assert page.locator('.fig-scenario-screen>.fig-live-state-panel').count()==1
  assert page.locator('.ws-side-panel .fig-main-panel').count()==0
  faces=page.locator('.fig-shared-agent-option img').all()
  assert len(faces)==4 and max(x.bounding_box()['y'] for x in faces)-min(x.bounding_box()['y'] for x in faces)<1
  page.locator('[data-ws=market]').click();page.wait_for_selector('.fig-quote-row')
  assert '178,850' in page.locator('.fig-quote-list').inner_text()
  assert '삼성전자' in page.locator('.fig-quote-list').inner_text()
  assert '체결' in page.locator('.fig-quote-list').inner_text()
  page.evaluate('Promise.all(document.getAnimations().map(a=>a.finished.catch(()=>{})))')
  assert page.locator('.ws-inline-data').bounding_box()['y']>=page.locator('.ws-tools').bounding_box()['y']+page.locator('.ws-tools').bounding_box()['height']-1
  assert page.locator('.fig-chat-compose').is_visible()
  page.screenshot(path='/tmp/workspace-quotes-desktop.png')
  page.locator('[data-ws=market]').click();assert page.locator('.ws-inline-data').is_hidden()
  for name in ['rate','fx','oil','vix']:page.locator('[data-sim='+name+']').fill('1')
  page.locator('[data-action="run-sim"]').click();page.wait_for_function("document.querySelector('.ws-context').textContent.includes('a-browser-fixture')")
  page.locator('[data-ws=news]').click();page.wait_for_selector('.fig-news-add');page.locator('.fig-news-add').first.click();page.locator('[data-ws=close]').click();assert '브라우저 검증용 기사' in page.locator('.ws-evidence').inner_text()
  page.locator('[data-ws=document]').click();page.locator('#p57-doc-company-query').fill('삼성');page.locator('[data-gx=p57-doc-company-search]').click();page.locator('[data-gx=p57-doc-company-pick]').first.click();page.locator('[data-gx=p57-doc-refresh]').click();page.locator('[data-gx=p57-doc-open]').first.click();page.locator('[data-ws=document-add]').click();assert '검증 공시' in page.locator('.ws-evidence').inner_text()
  page.locator('[data-ws=start]').click();page.get_by_text('검증용 서버 응답입니다.',exact=True).wait_for()
  assert starts[0]['target_roles']==['risk'] and {s['kind'] for s in starts[0]['selected_sources']}=={'news','document'}
  assert '입력 충격 손익' in page.locator('.ws-citations').inner_text()
  page.locator('[data-ws-target]').select_option('macro');page.locator('[data-chat-input=scenario]').fill('추가 질문');page.locator('[data-action=send-chat]').click();page.get_by_text('개별 질문 검증 응답',exact=True).wait_for();assert questions[0]['target_roles']==['macro']
  frame=page.locator('.fig-scenario-frame').bounding_box();assert frame['x']>=-1 and frame['x']+frame['width']<=1441
  page.screenshot(path='/tmp/workspace-desktop.png')
  for width,height in [(768,1024),(390,844)]:
   page.set_viewport_size({'width':width,'height':height});assert page.locator('.ws-side-panel').evaluate('(e)=>e.scrollWidth<=e.clientWidth')
   page.locator('[data-ws=news]').click();page.screenshot(path=f'/tmp/workspace-news-{width}.png');assert page.locator('.ws-drawer').evaluate('(e)=>e.scrollWidth<=e.clientWidth');page.locator('[data-ws=close]').click()
   page.locator('[data-ws=document]').click();assert page.locator('.ws-drawer').evaluate('(e)=>e.scrollWidth<=e.clientWidth');page.locator('[data-ws=close]').click()
   page.locator('[data-ws=market]').click();assert page.locator('.ws-drawer').evaluate('(e)=>e.scrollWidth<=e.clientWidth');page.locator('[data-ws=close]').click()
  page.screenshot(path='/tmp/workspace-mobile.png')
  page.reload(wait_until='domcontentloaded');enter();assert page.get_by_text('검증용 서버 응답입니다.',exact=True).count()==1
  assert not errors,errors
  print(json.dumps({'passed':True,'starts':len(starts),'question_roles':questions[0]['target_roles'],'viewport_widths':[1440,768,390],'console_errors':errors},ensure_ascii=False))
  browser.close()
if __name__=='__main__':main()

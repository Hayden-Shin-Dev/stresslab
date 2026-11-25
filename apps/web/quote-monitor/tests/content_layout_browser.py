"""Synthetic source-list and workspace content layout browser checks.

Run against :8876: python content_layout_browser.py --label before
No live Azure calls or real data writes. Screenshots are in /tmp/whatif-content-*.
"""
import argparse
import json
from pathlib import Path
from urllib.parse import urlparse, parse_qs

from playwright.sync_api import sync_playwright
from portfolio_layout_browser import fixture_page, rect


def inspect_content(page):
    return page.evaluate("""() => {
      const selectors=['.fig-scenario-frame','.fig-scenario-screen[role=dialog]',
        '.fig-main-panel','.fig-chart-panel','.fig-live-state-panel','.is-portfolio td',
        '.ws-side-panel','.ws-resource-region','.fig-chat-panel','.fig-chat-compose',
        '.fig-quote-row','.fig-quote-row:not(.is-selected)','.fig-news-row','.fig-doc-row'];
      return Object.fromEntries(selectors.map(selector=>{
        const e=document.querySelector(selector);if(!e)return [selector,null];
        const b=e.getBoundingClientRect(),s=getComputedStyle(e);
        return [selector,{x:b.x,y:b.y,width:b.width,height:b.height,
          clientWidth:e.clientWidth,scrollWidth:e.scrollWidth,
          clientHeight:e.clientHeight,scrollHeight:e.scrollHeight,
          padding:s.padding,gap:s.gap,fontSize:s.fontSize,lineHeight:s.lineHeight,
          overflow:s.overflow,border:s.borderWidth,radius:s.borderRadius,background:s.backgroundColor}];
      }));
    }""")


def capture_sources(browser, label, only_width=None):
    results=[]
    sizes=[(1440,1000),(1024,900),(390,844),(320,740)]
    if only_width:
        sizes=[size for size in sizes if size[0]==only_width]
    for width,height in sizes:
        page,errors,requests,analyses=fixture_page(browser,width,height)
        record={'width':width,'initial':inspect_content(page)}
        page.screenshot(path=f'/tmp/whatif-content-{label}-{width}.png')
        if label=='after':
            for icon in page.locator('.handoff-window-icon').all():
                owner=icon.locator('xpath=ancestor::*[@data-handoff-panel][1]')
                owner_box,icon_box=rect(owner),rect(icon)
                assert icon_box['x']>=owner_box['x'] and icon_box['x']+icon_box['width']<=owner_box['x']+owner_box['width']+1,(owner_box,icon_box)
            if width>=1280:
                frame=record['initial']['.fig-scenario-frame'];compose=record['initial']['.fig-chat-compose']
                assert compose['y']+compose['height']<=frame['y']+frame['height']-8,(frame,compose)
        page.locator('.is-portfolio').scroll_into_view_if_needed()
        page.screenshot(path=f'/tmp/whatif-content-{label}-portfolio-{width}.png')
        page.locator('[data-ws="market"]').click()
        page.wait_for_function("document.querySelectorAll('.fig-quote-row').length===20")
        page.locator('.fig-quote-row').first.scroll_into_view_if_needed()
        record['market']=inspect_content(page)
        page.screenshot(path=f'/tmp/whatif-content-{label}-market-{width}.png')
        page.locator('[data-ws="news"]').click()
        page.locator('[data-gx="p57-news-mode"][data-mode="economy"]').click()
        page.wait_for_function("document.querySelectorAll('.fig-news-row').length===2")
        assert page.locator('.fig-news-row').count()==2
        page.locator('.fig-news-row').first.scroll_into_view_if_needed()
        record['news']=inspect_content(page)
        page.screenshot(path=f'/tmp/whatif-content-{label}-news-{width}.png')
        page.locator('.fig-news-add').first.click()
        assert page.locator('.fig-news-row.is-selected').count()==1
        page.locator('[data-ws="document"]').click()
        page.locator('#p57-doc-company-query').fill('삼성전자')
        page.locator('[data-gx="p57-doc-company-search"]').click()
        page.locator('[data-gx="p57-doc-company-pick"]').first.click()
        page.locator('[data-gx="p57-doc-refresh"]').click()
        page.wait_for_function("document.querySelectorAll('.fig-doc-row').length===2")
        assert page.locator('.fig-doc-row').count()==2
        page.locator('.fig-doc-row').first.scroll_into_view_if_needed()
        record['documents']=inspect_content(page)
        page.screenshot(path=f'/tmp/whatif-content-{label}-documents-{width}.png')
        page.locator('[data-gx="p57-doc-open"]').first.click()
        page.locator('.fig-doc-modal table').wait_for()
        page.screenshot(path=f'/tmp/whatif-content-{label}-document-popup-{width}.png')
        modal_box=rect(page.locator('.fig-doc-modal'))
        close_box=rect(page.get_by_role('button',name='공시 팝업 닫기',exact=True))
        if label=='after':
            assert close_box['x']+close_box['width']<=modal_box['x']+modal_box['width']+1,(modal_box,close_box)
            assert not page.locator('.handoff-taskbar').is_visible()
        page.get_by_role('button',name='공시 팝업 닫기',exact=True).click()
        assert not page.locator('.fig-doc-modal').count()
        assert page.locator('.handoff-taskbar').is_visible()
        assert page.evaluate('document.documentElement.scrollWidth<=innerWidth+1')
        if label=='after':
            for state in ['initial','market','news','documents']:
                screen=record[state]['.fig-scenario-screen[role=dialog]']
                assert screen['scrollWidth']<=screen['clientWidth']+2,(state,screen)
                # Wide financial tables scroll inside their own wrapper; the
                # containing panels and their controls must still fit the screen.
                for selector in ['.fig-live-state-panel','.ws-side-panel']:
                    panel=record[state][selector]
                    assert panel['scrollWidth']<=panel['clientWidth']+2,(state,selector,panel)
            for state,selector in [('news','.fig-news-row'),('documents','.fig-doc-row')]:
                card=record[state][selector]
                assert card['scrollWidth']<=card['clientWidth']+2,(state,card)
                quote=record['market']['.fig-quote-row:not(.is-selected)']
                for key in ['border','radius','background','padding','gap']:
                    assert card[key]==quote[key],(state,key,card[key],quote[key])
        assert not errors,errors
        assert not analyses
        assert not [(method,path) for method,path in requests
                    if method!='GET' and path!='/api/market-state/negotiate'],requests
        record['page_errors']=errors
        results.append(record)
        page.close()
    suffix=f'-{only_width}' if only_width else ''
    Path(f'/tmp/whatif-content-{label}-geometry{suffix}.json').write_text(json.dumps(results,ensure_ascii=False,indent=2))
    return results


def verify_splitter_and_recipients(browser):
    page,errors,requests,analyses=fixture_page(browser)
    panel=page.locator('[data-handoff-panel="agent"]')
    handle=panel.get_by_role('separator',name='자료와 대화 높이 조절',exact=True)
    assert not page.locator('[data-ws-target]').count()
    for name in ['이동 창','기본 위치','왼쪽 도킹','오른쪽 도킹','별도 창','최소화']:
        button=panel.locator('.handoff-window-bar').get_by_role('button',name=name,exact=True)
        assert button.get_attribute('title')==name
        assert button.locator('svg').count()==1 and not button.inner_text().strip()
        style=button.evaluate('(el)=>{const s=getComputedStyle(el);return {border:s.borderTopWidth,bg:s.backgroundColor,w:el.offsetWidth,h:el.offsetHeight}}')
        assert style['border']=='0px' and style['w']>=44 and style['h']>=44,style
    draft=panel.locator('[data-chat-input="scenario"]')
    draft.fill('높이 조절 중 유지할 검증 초안')
    before=float(handle.get_attribute('aria-valuenow'))
    start=rect(handle)
    page.mouse.move(start['x']+start['width']/2,start['y']+start['height']/2)
    page.mouse.down()
    page.mouse.move(start['x']+start['width']/2,start['y']+start['height']/2-48,steps=6)
    page.evaluate("WHATIF_QA.open('sim')")
    page.mouse.up()
    after=float(handle.get_attribute('aria-valuenow'))
    assert after>=before+40,(before,after)
    assert draft.input_value()=='높이 조절 중 유지할 검증 초안'
    handle.focus();page.keyboard.press('ArrowUp')
    raised=float(handle.get_attribute('aria-valuenow'))
    assert abs(raised-after-8)<=2,(after,raised)
    page.evaluate("WHATIF_QA.open('sim')")
    assert abs(float(handle.get_attribute('aria-valuenow'))-raised)<=2
    actual=rect(panel.locator('.fig-chat-panel'))['height']
    assert abs(actual-raised)<=2,(actual,raised)
    with page.expect_popup() as info:
        panel.locator('.handoff-window-bar').get_by_role('button',name='별도 창',exact=True).click()
    popup=info.value;popup.wait_for_load_state('domcontentloaded')
    popup_handle=popup.get_by_role('separator',name='자료와 대화 높이 조절',exact=True)
    popup_handle.wait_for(state='visible');popup_handle.focus()
    popup_before=float(popup_handle.get_attribute('aria-valuenow'))
    popup.keyboard.press('ArrowUp')
    popup_after=float(popup_handle.get_attribute('aria-valuenow'))
    assert abs(popup_after-popup_before-8)<=2,(popup_before,popup_after)
    assert popup.locator('[data-chat-input="scenario"]').input_value()=='높이 조절 중 유지할 검증 초안'
    popup.get_by_role('button',name='메인 창으로 복귀',exact=True).click()
    assert draft.input_value()=='높이 조절 중 유지할 검증 초안'
    handle.focus();page.keyboard.press('Home')
    assert handle.get_attribute('aria-valuenow')==handle.get_attribute('aria-valuemin')
    page.keyboard.press('End')
    assert handle.get_attribute('aria-valuenow')==handle.get_attribute('aria-valuemax')
    page.keyboard.press('Enter')
    for width,height in [(1440,1000),(390,844)]:
        page.set_viewport_size({'width':width,'height':height})
        handle.focus();page.keyboard.press('Shift+ArrowUp')
        draft.scroll_into_view_if_needed()
        box,field=rect(panel),rect(draft)
        assert field['y']>=box['y'] and field['y']+field['height']<=box['y']+box['height']+1,(box,field)
        page.screenshot(path=f'/tmp/whatif-content-splitter-{width}.png')
    page.set_viewport_size({'width':1440,'height':1000})

    # Local synthetic debate API records the recipients actually sent. A saved
    # legacy dropdown value must not override the four visible agent choices.
    starts,questions,events=[],[],[]
    def debate_route(r):
        path=urlparse(r.request.url).path
        body=r.request.post_data_json if r.request.method=='POST' else None
        if path.endswith('/debates') and body:
            starts.append(body)
            events.append({'event_id':'complete-fixture','seq':1,'type':'debate.completed',
                           'created_at':'2026-11-24T01:00:00Z','debate_id':'d-content-fixture','payload':{'failed_roles':[]}})
            result={'debate_id':'d-content-fixture','status':'accepted'}
        elif path.endswith('/questions') and body:
            questions.append(body)
            qid=f'q-content-{len(questions)}'
            events.append({'event_id':qid,'seq':len(events)+1,'type':'message.created',
                           'created_at':'2026-11-24T01:00:00Z','debate_id':'d-content-fixture',
                           'payload':{'role':body['target_roles'][0],'question_id':qid,'message_id':qid,
                                      'display_text':'검증용 선택 에이전트 응답','structured_source_ids':[]}})
            result={'question_id':qid,'status':'accepted'}
        elif path.endswith('/events'):
            after=int(parse_qs(urlparse(r.request.url).query).get('after_seq',['0'])[0])
            result={'events':[event for event in events if event['seq']>after]}
        elif path.endswith('/negotiate'):
            r.fulfill(status=503,content_type='application/json',body='{}');return
        else:
            r.fallback();return
        r.fulfill(content_type='application/json',body=json.dumps(result))
    page.route('**/api/debates**',debate_route)
    for role in ['yoon','kang']:
        panel.locator(f'.fig-shared-agent-option:has([data-role-choice="{role}"])').click()
    page.evaluate("WHATIF_QA.getSourceState().workspace.target='portfolio'")
    draft.fill('선택한 자료의 근거를 설명해 주세요')
    with page.expect_response(lambda r:r.url.endswith('/questions')):
        panel.locator('[data-action="send-chat"]').click()
    assert questions[-1]['target_roles']==['macro','risk'],questions
    assert starts[-1]['target_roles']==['macro','risk'],starts
    assert starts[-1]['mode']=='research' and 'run_id' not in starts[-1]
    page.wait_for_function('!WHATIF_QA.getSourceState().workspace.researchRun.azureAwaitingQuestion')
    for role in ['yoon','kim','shin']:
        panel.locator(f'.fig-shared-agent-option:has([data-role-choice="{role}"])').click()
    draft.fill('수급 관점으로 추가 설명해 주세요')
    with page.expect_response(lambda r:r.url.endswith('/questions')):
        panel.locator('[data-action="send-chat"]').click()
    assert questions[-1]['target_roles']==['market'],questions
    page.wait_for_function('!WHATIF_QA.getSourceState().workspace.researchRun.azureAwaitingQuestion')
    page.evaluate("WHATIF_QA.getSourceState().selectedRoles=[];WHATIF_QA.open('sim')")
    draft.fill('선택이 없으면 유지할 초안')
    before_count=len(questions)
    panel.locator('[data-action="send-chat"]').click()
    assert draft.input_value()=='선택이 없으면 유지할 초안'
    assert len(questions)==before_count
    assert not page.locator('[data-ws-target]').count()
    assert not errors,errors
    assert not analyses
    page.close()
    return {'line_icon_labels':True,'pointer_keyboard_splitter':True,'rerender_and_popup_preserve_draft':True,
            'composer_accessible':True,'visible_agent_selection_controls_requests':True,
            'legacy_target_ignored':True,'empty_selection_preserves_draft':True,
            'stress_engine_not_called':True,'page_errors':errors}


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--label',default='after')
    parser.add_argument('--flow-only',action='store_true')
    parser.add_argument('--width',type=int,choices=[1440,1024,390,320])
    args=parser.parse_args()
    with sync_playwright() as p:
        browser=p.chromium.launch(executable_path='/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',headless=True)
        result=verify_splitter_and_recipients(browser) if args.flow_only else capture_sources(browser,args.label,args.width)
        print(json.dumps(result,ensure_ascii=False))
        browser.close()


if __name__=='__main__':
    main()

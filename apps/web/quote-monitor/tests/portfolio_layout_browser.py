"""Local UI regression for the movable portfolio and KRDS-inspired layout.

Uses explicitly synthetic API fixtures. Never contacts Azure or saves real holdings.
Run: python portfolio_layout_browser.py [--baseline | --windows-only | --comparison-only]
Requires the static site served at http://127.0.0.1:8876.
Screenshots and geometry reports are written to /tmp/whatif-layout-*.
"""
import argparse
import json
import os
from copy import deepcopy
from pathlib import Path
from urllib.parse import urlparse

from playwright.sync_api import sync_playwright
from workspace_browser import STRESS


HOLDINGS = [
    {'asset_id': '005930', 'shares': 2, 'avg_purchase_price_krw': 150000,
     'amount_krw': 357700, 'updated_at': '2026-11-24T01:00:00Z'},
    {'asset_id': '000660', 'shares': 1, 'avg_purchase_price_krw': 1000000,
     'amount_krw': 1093000, 'updated_at': '2026-11-24T01:00:00Z'},
]


def fixture_page(browser, width=1440, height=1000,
                 supported_assets=('005930', '000660')):
    page = browser.new_page(viewport={'width': width, 'height': height})
    page.set_default_timeout(10000)
    errors, requests, analyses = [], [], []
    page.on('pageerror', lambda error: errors.append(str(error)))

    def route(request):
        path = urlparse(request.request.url).path
        method = request.request.method
        requests.append((method, path))
        result, status = {}, 200
        if path.endswith('/me'):
            result = {'workspace_storage_enabled': False}
        elif path.endswith('/holdings'):
            assert method == 'GET', 'Window layout must never mutate holdings'
            result = {'holdings': HOLDINGS}
        elif path.endswith('/stress/support'):
            result = {'supported_assets': list(supported_assets)}
        elif path.endswith('/quotes/latest'):
            result = {'type': 'quote_snapshot', 'quotes': [
                {'record_type': 'quote_latest', 'is_mock': False, 'asset_id': code,
                 'price': price, 'event_time': '2026-11-24T01:00:00Z',
                 'received_at': '2026-11-24T01:00:01Z', 'venue': 'KRX', 'session': 'regular'}
                for code, price in [('005930', 178850), ('000660', 1093000)]]}
        elif path.endswith('/news/latest'):
            result = {'fetchedAt': '2026-11-24T01:00:00Z', 'articles': [
                {'title': '삼성전자 반도체 투자와 환율 변화, 최근 시장 흐름을 살펴봅니다 · 검증 기사',
                 'url': 'https://example.com/layout-fixture-news-1', 'publisher': '검증 경제신문',
                 'publishedAt': '2026-11-24T00:30:00Z', 'summary': '화면 검증을 위한 합성 뉴스 자료입니다.'},
                {'title': 'SK하이닉스 실적 발표 이후 수급 변화와 업종 전망 · 검증 기사',
                 'url': 'https://example.com/layout-fixture-news-2', 'publisher': '검증 뉴스',
                 'publishedAt': '2026-11-23T23:15:00Z', 'summary': '실제 투자 정보가 아닌 UI 검증용 자료입니다.'}]}
        elif path.endswith('/dart/companies'):
            result = {'companies': [{'corp_code': '00126380', 'corp_name': '삼성전자', 'stock_code': '005930'}]}
        elif path.endswith('/dart/disclosures'):
            result = {'list': [
                {'rcept_no': '20261124000101', 'report_nm': '분기보고서 (2026.09) · 검증 자료',
                 'corp_name': '삼성전자', 'rcept_dt': '20261124', 'flr_nm': '삼성전자'},
                {'rcept_no': '20261123000202', 'report_nm': '주요사항보고서(유형자산양수결정) · 검증 자료',
                 'corp_name': '삼성전자', 'rcept_dt': '20261123', 'flr_nm': '삼성전자'}],
                'total_count': '2', 'total_page': 1}
        elif path.endswith('/preview'):
            result = {'status': 'ok', 'text': '검증 공시 본문',
                      'html': '<table><thead><tr><th>구분</th><th>당기</th><th>전기</th></tr></thead><tbody><tr><th>매출액</th><td>12,345,678</td><td>11,234,567</td></tr><tr><th>영업이익</th><td>1,234,567</td><td>987,654</td></tr></tbody></table>'}
        elif '/quotes/history/' in path:
            result = {'asset_id': path.rsplit('/', 1)[-1], 'source': 'fixture_daily_prices',
                      'rows': [{'at': '2026-11-20', 'price': 170000},
                               {'at': '2026-11-23', 'price': 175000},
                               {'at': '2026-11-24', 'price': 178850}]}
        elif path.endswith('/stress/analyze'):
            body = request.request.post_data_json
            analyses.append(body)
            result = deepcopy(STRESS)
            result.update(analysis_id='a-layout-fixture', analysis_type=body['analysis_type'],
                          model=body['model'], shocks=body['shocks'],
                          ai_handoff={'ready': False},
                          archive_status={'persisted': False, 'disabled': True})
            result['assets'] = [dict(deepcopy(STRESS['assets'][0]), asset_id=position['asset_id'],
                                    model_interval_90_return_pct={'lower': -5, 'upper': 3})
                                for position in body['positions']]
            result['portfolio_hypothetical_pnl_krw'] = sum(row['hypothetical_pnl_krw'] for row in result['assets'])
            result['portfolio_shock_incremental_pnl_krw'] = sum(row['shock_incremental_pnl_krw'] for row in result['assets'])
        else:
            status, result = 503, {'detail': 'Unavailable in local layout fixture'}
        request.fulfill(status=status, content_type='application/json', body=json.dumps(result))

    page.route('**/api/**', route)
    page.route('**/.auth/me', lambda request: request.fulfill(
        content_type='application/json', body=json.dumps({'clientPrincipal': {
            'identityProvider': 'fixture', 'userId': 'portfolio-layout-fixture'}})))
    page.goto(os.environ.get('WHATIF_TEST_URL', 'http://127.0.0.1:8876/whatif-v6/'),
              wait_until='domcontentloaded')
    page.wait_for_function("typeof window.WHATIF_QA?.enter === 'function'")
    page.evaluate("WHATIF_QA.enter(); WHATIF_QA.open('sim')")
    page.locator('.handoff-inputs [data-analysis-code="005930"]').wait_for()
    page.wait_for_function("WHATIF_QA.getSourceState().portfolioLots?.length===2")
    page.wait_for_function("document.fonts.status==='loaded'")
    return page, errors, requests, analyses


def geometry(page):
    return page.evaluate("""() => {
      const out = {viewport: {width: innerWidth, height: innerHeight},
        page: {width: document.documentElement.clientWidth, scrollWidth: document.documentElement.scrollWidth}};
      for (const selector of ['.fig-scenario-screen[role=dialog]', '.fig-main-panel',
        '.fig-chart-panel', '.fig-live-state-panel', '.ws-side-panel',
        '.ws-side-panel .fig-chat-compose', '.ws-side-panel .ws-resource-region']) {
        const el = document.querySelector(selector); if (!el) continue;
        const b=el.getBoundingClientRect(), s=getComputedStyle(el);
        out[selector]={x:b.x,y:b.y,width:b.width,height:b.height,clientHeight:el.clientHeight,
          scrollHeight:el.scrollHeight,clientWidth:el.clientWidth,scrollWidth:el.scrollWidth,
          overflow:s.overflow,gridRows:s.gridTemplateRows,padding:s.padding,gap:s.gap};
      } return out;
    }""")


def screenshots(browser, label):
    records = []
    for width, height in [(1440, 1000), (1024, 900), (390, 844)]:
        page, errors, requests, analyses = fixture_page(browser, width, height)
        records.append(geometry(page))
        page.screenshot(path=f'/tmp/whatif-layout-{label}-{width}.png')
        if label == 'after':
            page.locator('.fig-chart-panel').scroll_into_view_if_needed()
            page.screenshot(path=f'/tmp/whatif-layout-{label}-chart-{width}.png')
            page.locator('.fig-live-state-panel').scroll_into_view_if_needed()
            page.screenshot(path=f'/tmp/whatif-layout-{label}-portfolio-{width}.png')
            page.locator('.ws-side-panel .fig-chat-compose').scroll_into_view_if_needed()
            page.screenshot(path=f'/tmp/whatif-layout-{label}-agent-{width}.png')
        assert not errors, errors
        assert not analyses
        page.close()
    Path(f'/tmp/whatif-layout-{label}-geometry.json').write_text(
        json.dumps(records, ensure_ascii=False, indent=2))
    return records


def rect(locator):
    # Viewport changes repaint the main document. The visible shell may be
    # replaced between Playwright's visibility check and bounding-box lookup.
    for _ in range(20):
        locator.wait_for(state='visible')
        value = locator.bounding_box()
        if value is not None:
            return value
        locator.page.evaluate('new Promise(resolve=>requestAnimationFrame(resolve))')
    raise AssertionError('Portfolio did not retain a visible measurable window')


def close_rect(left, right, keys=('x', 'y', 'width', 'height'), tolerance=3):
    assert all(abs(left[key] - right[key]) <= tolerance for key in keys), (left, right)


def verify_portfolio(browser):
    page, errors, requests, analyses = fixture_page(browser)
    portfolio = page.locator('[data-handoff-panel="portfolio"]')
    portfolio.wait_for(state='visible')
    toolbar = portfolio.locator('.handoff-window-bar')
    holdings_before = page.evaluate('JSON.stringify(WHATIF_QA.getSourceState().portfolioLots)')
    portfolio.locator('[data-tab="assets"]').click()
    assert portfolio.locator('.is-assets tbody tr').count() == 20
    toolbar.get_by_role('button', name='이동 창', exact=True).click()
    shell = page.locator('.handoff-floating[data-window-panel="portfolio"]')
    shell.wait_for(state='visible')
    assert portfolio.locator('[data-tab="assets"]').get_attribute('aria-selected') == 'true'
    original = rect(shell)
    title = toolbar.locator('strong[role="button"]')
    title_box = rect(title)
    page.mouse.move(title_box['x'] + 24, title_box['y'] + title_box['height'] / 2)
    page.mouse.down()
    page.mouse.move(title_box['x'] + 144, title_box['y'] + title_box['height'] / 2 + 64, steps=6)
    # A quote-driven render must not replace the pointer-captured drag handle.
    page.evaluate("WHATIF_QA.open('sim')")
    page.mouse.up()
    moved = rect(shell)
    assert moved['x'] > original['x'] + 30, (original, moved)
    assert moved['y'] > original['y'] + 20, (original, moved)
    assert portfolio.locator('[data-tab="assets"]').get_attribute('aria-selected') == 'true'

    title.focus()
    before_key = rect(shell)
    page.keyboard.press('ArrowLeft')
    after_key = rect(shell)
    assert after_key['x'] < before_key['x'], (before_key, after_key)
    page.keyboard.press('Shift+ArrowRight')
    after_resize_key = rect(shell)
    assert after_resize_key['width'] > after_key['width'], (after_key, after_resize_key)

    # Pointer resizing uses the visible native corner, not CSS writes in the test.
    before_resize = rect(shell)
    page.mouse.move(before_resize['x'] + before_resize['width'] - 3,
                    before_resize['y'] + before_resize['height'] - 3)
    page.mouse.down()
    page.mouse.move(before_resize['x'] + before_resize['width'] - 83,
                    before_resize['y'] + before_resize['height'] - 53, steps=6)
    page.mouse.up()
    resized = rect(shell)
    assert resized['width'] < before_resize['width'] - 20, (before_resize, resized)
    assert resized['height'] < before_resize['height'] - 10, (before_resize, resized)
    # Allow a ResizeObserver delivery before exercising the ordinary render path.
    page.evaluate('new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve)))')
    page.evaluate("WHATIF_QA.open('sim')")
    close_rect(resized, rect(shell))
    assert portfolio.locator('[data-tab="assets"]').get_attribute('aria-selected') == 'true'
    assert page.evaluate('JSON.stringify(WHATIF_QA.getSourceState().portfolioLots)') == holdings_before
    assert not analyses
    page.screenshot(path='/tmp/whatif-layout-floating-portfolio.png')

    toolbar.get_by_role('button', name='최소화', exact=True).click()
    assert not portfolio.is_visible()
    page.locator('.handoff-taskbar').get_by_role('button', name='나의 포트폴리오', exact=True).click()
    portfolio.wait_for(state='visible')
    assert portfolio.locator('[data-tab="assets"]').get_attribute('aria-selected') == 'true'
    toolbar.get_by_role('button', name='기본 위치', exact=True).click()
    assert portfolio.is_visible()
    assert not page.locator('.handoff-floating[data-window-panel="portfolio"]:not(.handoff-hidden-view)').count()
    assert portfolio.locator('[data-tab="assets"]').get_attribute('aria-selected') == 'true'

    toolbar.get_by_role('button', name='이동 창', exact=True).click()
    for width, height in [(390, 844), (320, 640)]:
        page.set_viewport_size({'width': width, 'height': height})
        b = rect(shell)
        assert b['x'] >= -1 and b['x'] + b['width'] <= width + 1, b
        assert b['y'] >= -1 and b['y'] + b['height'] <= height + 1, b
        assert toolbar.get_by_role('button', name='기본 위치', exact=True).is_visible()
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth + 1')
        page.screenshot(path=f'/tmp/whatif-layout-floating-{width}.png')
    toolbar.get_by_role('button', name='오른쪽 도킹', exact=True).click()
    portfolio.scroll_into_view_if_needed()
    docked_mobile = rect(portfolio)
    assert docked_mobile['x'] >= 16 and docked_mobile['x'] + docked_mobile['width'] <= 304, docked_mobile
    assert page.locator('.fig-scenario-screen[role="dialog"]').evaluate('(el)=>el.scrollWidth<=el.clientWidth+2')
    page.set_viewport_size({'width': 1440, 'height': 1000})
    toolbar.get_by_role('button', name='기본 위치', exact=True).click()
    portfolio.locator('.fig-portfolio-view').click()
    assert portfolio.locator('.is-portfolio tbody tr').count() == 2
    assert page.evaluate('JSON.stringify(WHATIF_QA.getSourceState().portfolioLots)') == holdings_before

    # The detached view forwards controls to one live portfolio state in the
    # original page. Switching tabs must neither copy holdings nor save them.
    with page.expect_popup() as popup_info:
        toolbar.get_by_role('button', name='별도 창', exact=True).click()
    popup = popup_info.value
    popup.set_default_timeout(10000)
    popup.wait_for_load_state('domcontentloaded')
    popup.locator('.fig-portfolio-view').wait_for(state='visible')
    popup.locator('[data-tab="assets"]').click()
    try:
        popup.locator('.is-assets tbody tr').first.wait_for(state='visible')
    except Exception:
        print(json.dumps({'main_portfolio': portfolio.text_content()[:1000],
                          'popup_portfolio': popup.locator('main').text_content()[:1000]},
                         ensure_ascii=False))
        popup.screenshot(path='/tmp/whatif-layout-detached-failure.png')
        raise
    assert popup.locator('.is-assets tbody tr').count() == 20
    assert portfolio.locator('[data-tab="assets"]').get_attribute('aria-selected') == 'true'
    assert page.locator('[data-handoff-panel="portfolio"]').count() == 1
    assert page.evaluate('JSON.stringify(WHATIF_QA.getSourceState().portfolioLots)') == holdings_before
    popup.screenshot(path='/tmp/whatif-layout-detached-portfolio.png')
    popup.get_by_role('button', name='메인 창으로 복귀', exact=True).click()
    portfolio.wait_for(state='visible')
    assert portfolio.locator('[data-tab="assets"]').get_attribute('aria-selected') == 'true'
    assert page.locator('[data-handoff-panel="portfolio"]').count() == 1

    # The portfolio remains usable when the scenario screen is minimized.
    toolbar.get_by_role('button', name='이동 창', exact=True).click()
    floating_before_minimize = rect(shell)
    page.get_by_role('button', name='분석 최소화', exact=True).click()
    portfolio.wait_for(state='visible')
    close_rect(floating_before_minimize, rect(shell))
    page.locator('.handoff-taskbar').get_by_role('button', name='시나리오 분석', exact=True).click()
    portfolio.wait_for(state='visible')
    close_rect(floating_before_minimize, rect(shell))
    toolbar.get_by_role('button', name='기본 위치', exact=True).click()

    # Even an intentionally small detached agent window must let the user reach
    # the composer by scrolling instead of clipping it inside nested panels.
    agent = page.locator('[data-handoff-panel="agent"]')
    agent.locator('.handoff-window-bar').get_by_role('button', name='이동 창', exact=True).click()
    agent_shell = page.locator('.handoff-floating[data-window-panel="agent"]')
    agent_title = agent.locator('.handoff-window-bar strong[role="button"]')
    agent_title.focus()
    for _ in range(25):
        page.keyboard.press('Shift+ArrowUp')
    composer = agent.locator('[data-chat-input="scenario"]')
    composer.scroll_into_view_if_needed()
    composer.click()
    assert composer.evaluate('(el)=>document.activeElement===el')
    agent_box, composer_box = rect(agent_shell), rect(composer)
    assert composer_box['y'] >= agent_box['y'], (agent_box, composer_box)
    assert composer_box['y'] + composer_box['height'] <= agent_box['y'] + agent_box['height'], (agent_box, composer_box)
    page.screenshot(path='/tmp/whatif-layout-small-agent.png')
    agent.locator('.handoff-window-bar').get_by_role('button', name='기본 위치', exact=True).click()
    # Existing live-market reconnects may POST a negotiation request; layout
    # operations must not issue analysis, holdings, or storage mutations.
    assert not [(method, path) for method, path in requests
                if method != 'GET' and path != '/api/market-state/negotiate'], requests
    assert not errors, errors
    page.close()
    return {'pointer_drag': True, 'pointer_resize': True, 'keyboard_move_resize': True,
            'rerender_preserves_geometry_and_tab': True, 'minimize_restore': True,
            'default_position': True, 'viewport_clamping': True,
            'detached_view_shares_one_state': True, 'available_outside_analysis': True,
            'mobile_docking': True, 'small_agent_composer_reachable': True,
            'holdings_and_api_preserved': True, 'page_errors': errors}


def verify_result_comparison(browser):
    codes = ('005930', '000660', '000270', '005380')
    page, errors, requests, analyses = fixture_page(browser, supported_assets=codes)
    for code in codes:
        page.locator(f'.handoff-inputs [data-analysis-code="{code}"]').check()
    page.locator('.fig-run-button').click()
    try:
        page.wait_for_function("WHATIF_QA.getSourceState().runs.some(r=>r.id==='a-layout-fixture')")
    except Exception:
        print(json.dumps({'requests': requests, 'analyses': analyses, 'errors': errors,
                          'state': page.evaluate("(()=>{const s=WHATIF_QA.getSourceState();return {runError:s.runError,runId:s.runId,runs:s.runs.map(r=>r.id)}})()")}, ensure_ascii=False))
        raise
    assert len(analyses) == 1
    assert {position['asset_id'] for position in analyses[0]['positions']} == set(codes)
    for code in codes:
        page.locator(f'[data-gx="p63-chart-compare-asset"][data-code="{code}"]').click()
    cards = page.locator('.fig-stress-compare-card')
    assert cards.count() == 4
    assert page.locator('[data-gx="p63-chart-compare-asset"][aria-pressed=false]:not([disabled])').count() == 0
    for card in cards.all():
        assert '+3%' in card.locator('tr.is-positive').inner_text()
        assert '+1%' in card.locator('tr.is-baseline').inner_text()
        assert '-2%' in card.locator('tr.is-scenario').inner_text()
        assert '-5%' in card.locator('tr.is-negative').inner_text()
    page.locator('[data-gx="p63-chart-columns"][data-columns="2"]').click()
    for width, height in [(1440, 1000), (1024, 900), (390, 844)]:
        page.set_viewport_size({'width': width, 'height': height})
        cards.first.scroll_into_view_if_needed()
        assert cards.count() == 4
        assert page.locator('.fig-scenario-screen[role="dialog"]').evaluate('(el)=>el.scrollWidth<=el.clientWidth+2')
        agent_box = rect(page.locator('.ws-side-panel'))
        for selector in ['.fig-chat-compose', '[data-chat-input="scenario"]', '[data-action="send-chat"]']:
            field_box = rect(page.locator('.ws-side-panel').locator(selector))
            assert field_box['y'] >= agent_box['y'], (selector, agent_box, field_box)
            assert field_box['y'] + field_box['height'] <= agent_box['y'] + agent_box['height'] + 1, (selector, agent_box, field_box)
        page.screenshot(path=f'/tmp/whatif-layout-comparison-{width}.png')
        cards.first.locator('.fig-stress-value-table').scroll_into_view_if_needed()
        page.screenshot(path=f'/tmp/whatif-layout-comparison-values-{width}.png')
        if width == 390:
            cards.first.evaluate('(el)=>el.scrollLeft=el.scrollWidth')
            point = cards.first.locator('.fig-stress-forecast-point.is-positive')
            point.scroll_into_view_if_needed()
            card_box, point_box = rect(cards.first), rect(point)
            assert point_box['x'] >= card_box['x'], (card_box, point_box)
            assert point_box['x'] + point_box['width'] <= card_box['x'] + card_box['width'], (card_box, point_box)
            page.screenshot(path='/tmp/whatif-layout-comparison-panned-390.png')
    page.locator('[data-handoff-panel="portfolio"] [data-tab="result"]').click()
    page.locator('.fig-live-market-results').scroll_into_view_if_needed()
    assert '삼성전자' in page.locator('.fig-live-market-results').inner_text()
    page.screenshot(path='/tmp/whatif-layout-result-390.png')
    assert len(analyses) == 1, 'Comparison display must not rerun the stress engine'
    assert not errors, errors
    page.close()
    return {'four_asset_limit': True, 'fixture_engine_values_preserved': True,
            'comparison_does_not_rerun_engine': True, 'result_and_comparison_responsive': True}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--baseline', action='store_true')
    parser.add_argument('--windows-only', action='store_true')
    parser.add_argument('--comparison-only', action='store_true')
    args = parser.parse_args()
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            executable_path=os.environ.get('CHROME_PATH', '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'),
            headless=True)
        if args.baseline:
            print(json.dumps(screenshots(browser, 'before'), ensure_ascii=False))
        elif args.windows_only:
            print(json.dumps(verify_portfolio(browser), ensure_ascii=False))
        elif args.comparison_only:
            print(json.dumps(verify_result_comparison(browser), ensure_ascii=False))
        else:
            result = verify_portfolio(browser)
            result['comparison'] = verify_result_comparison(browser)
            result['layouts'] = screenshots(browser, 'after')
            for layout in result['layouts']:
                screen = layout['.fig-scenario-screen[role=dialog]']
                main = layout['.fig-main-panel']
                chart = layout['.fig-chart-panel']
                portfolio = layout['.fig-live-state-panel']
                agent = layout['.ws-side-panel']
                compose = layout['.ws-side-panel .fig-chat-compose']
                assert screen['scrollWidth'] <= screen['clientWidth'] + 2, screen
                assert main['scrollHeight'] <= main['clientHeight'] + 4, main
                assert chart['y'] + chart['height'] <= main['y'] + main['height'] + 2, (main, chart)
                assert portfolio['y'] >= main['y'] + main['height'] + 14, (main, portfolio)
                assert compose['y'] + compose['height'] <= agent['y'] + agent['height'] + 1, (agent, compose)
                if layout['viewport']['width'] < 1280:
                    assert agent['y'] >= portfolio['y'] + portfolio['height'] + 14, (portfolio, agent)
                assert main['x'] >= (16 if layout['viewport']['width'] < 768 else 24), main
            print(json.dumps(result, ensure_ascii=False))
        browser.close()


if __name__ == '__main__':
    main()

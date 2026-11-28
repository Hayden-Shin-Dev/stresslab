const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const vm = require('node:vm');

const html = fs.readFileSync(path.join(__dirname, '../site/whatif-v6/index.html'), 'utf8');
const source = html.slice(html.indexOf('function p63EventHistory('), html.indexOf('const p63LatestTime='));

function setup() {
  const urls = [];
  const context = vm.createContext({
    Date, URLSearchParams, AbortSignal,
    P63_EVENT_HISTORY: new Map(),
    p57DocISODate: () => '2026-11-28',
    fetch: (url) => {
      urls.push(new URL(url, 'http://example.test'));
      return new Promise(() => {});
    },
  });
  vm.runInContext(source, context);
  return { history: context.p63MinuteHistory, urls };
}

test('minute history coalesces all selected stocks into one visible date-window request', () => {
  const { history, urls } = setup();
  const codes = ['005930', '000660', '000270', '005935'];
  const range = ['2026-11-23', '2026-11-24', '2026-11-25', '2026-11-26', '2026-11-27'];
  history(codes, range, false);
  history(codes, range, false);
  assert.equal(urls.length, 1);
  assert.equal(urls[0].searchParams.get('assets'), codes.join(','));
  assert.equal(urls[0].searchParams.get('period'), 'minute');
  assert.equal(urls[0].searchParams.get('from_date'), range[0]);
  assert.equal(urls[0].searchParams.get('to_date'), range.at(-1));
});

test('following the latest observation allows today to appear after the previous trading day', () => {
  const { history, urls } = setup();
  assert.equal(history(['005930'], [], true), null);
  history(['005930'], ['2026-11-27'], true);
  assert.equal(urls.length, 1);
  assert.equal(urls[0].searchParams.get('from_date'), '2026-11-27');
  assert.equal(urls[0].searchParams.get('to_date'), '2026-11-28');
});

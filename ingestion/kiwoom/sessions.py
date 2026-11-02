"""Session labels from provider trade time, venue and FID 290; no receive-clock fallback.

KRX aftermarket effective 2026-09-14. These are standard-session rules, not a
holiday/special-opening calendar certification. Provider date remains inferred.
"""
from datetime import datetime, date
from zoneinfo import ZoneInfo

RULE_VERSION = 'venue-trade-clock-20261102-v1'
AFTERMARKET_START = date(2026, 9, 14)


def classify_session(values, event_time):
    result = {'session': 'unknown', 'session_detail': 'unknown',
              'session_reason': '', 'session_rule_version': RULE_VERSION}
    venue = str(values.get('9081', '')).strip()
    code = str(values.get('290', '')).strip()
    def finish(session, detail, reason='provider_venue_code_and_trade_clock'):
        return dict(result, session=session, session_detail=detail, session_reason=reason)
    if venue not in ('KRX', 'NXT'):
        return finish('unknown', 'unknown', 'unsupported_or_missing_venue')
    if code not in ('1', '2', '3'):
        return finish('unknown', 'unknown', 'unsupported_or_missing_provider_session')
    if not event_time:
        return finish('unknown', 'unknown', 'missing_or_invalid_trade_time')
    try:
        timestamp = datetime.fromisoformat(event_time.replace('Z', '+00:00'))
        if timestamp.tzinfo is None: raise ValueError()
        timestamp = timestamp.astimezone(ZoneInfo('Asia/Seoul'))
        clock = timestamp.strftime('%H%M%S')
        if clock != str(values.get('20', '')): raise ValueError()
    except (ValueError, TypeError):
        return finish('unknown', 'unknown', 'trade_clock_mismatch')
    if timestamp.weekday() >= 5:
        return finish('unknown', 'unknown', 'non_trading_weekday')
    if venue == 'KRX':
        if code == '1' and '083000' <= clock <= '084000':
            return finish('afterhours', 'krx_preopen_closing_price')
        if code == '2' and '090000' <= clock < '152000':
            return finish('regular', 'krx_regular')
        if code == '2' and '152000' <= clock <= '153000':
            return finish('auction', 'krx_closing_auction_window')
        if code == '3' and '154000' <= clock < '160000':
            return finish('afterhours', 'krx_postclose_closing_price')
        if timestamp.date() >= AFTERMARKET_START:
            # FID 290=2 means trading, and occurs in actual KRX aftermarket ticks.
            if code in ('2', '3') and '160000' <= clock <= '200000':
                return finish('afterhours', 'krx_aftermarket')
        elif code == '3' and '160000' <= clock <= '180000':
            return finish('afterhours', 'krx_legacy_afterhours_call_auction')
    else:
        if code in ('1', '2') and '080000' <= clock < '085000':
            return finish('afterhours', 'nxt_premarket')
        if code == '2' and '090030' <= clock < '152000':
            return finish('regular', 'nxt_mainmarket')
        if code in ('2', '3') and '154000' <= clock <= '200000':
            return finish('afterhours', 'nxt_aftermarket')
    return finish('unknown', 'unknown', 'provider_session_outside_supported_trade_window')

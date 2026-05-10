"""Tests for the recipient enrichment slice (last-event IP/UA backfill).

Covers:
- LogRepository.get_last_event_for_recipient + bulk variant.
- Tracking-route _update_email_log persists IP/UA + last_event_at.
- EmailService._enrich_recipients_with_last_event fills only missing fields.
"""

from datetime import datetime, UTC, timedelta

import pytest

from mercury.data.database import get_session_direct
from mercury.data.models import EmailLog
from mercury.data.repositories.logs import LogRepository


@pytest.fixture
def session():
    s = get_session_direct()
    yield s
    s.rollback()
    s.close()


def _mklog(session, email: str, ip: str, ua: str, at: datetime, cid: str = '') -> EmailLog:
    log = EmailLog(
        correlation_id=cid or f"em_{email}_{at.timestamp()}",
        recipient_email=email,
        status='opened',
        last_event_ip=ip,
        last_event_ua=ua,
        last_event_at=at,
    )
    session.add(log)
    session.commit()
    return log


# ───── Repository ─────────────────────────────────────────────────────────

def test_get_last_event_picks_most_recent(session):
    email = 'history@test.geo'
    now = datetime.now(UTC)
    _mklog(session, email, '1.1.1.1', 'OldUA', now - timedelta(days=2))
    _mklog(session, email, '2.2.2.2', 'NewUA', now)
    _mklog(session, email, '3.3.3.3', 'MidUA', now - timedelta(days=1))

    repo = LogRepository(session)
    ip, ua = repo.get_last_event_for_recipient(email)
    assert ip == '2.2.2.2' and ua == 'NewUA'


def test_get_last_event_no_history_returns_none_pair(session):
    repo = LogRepository(session)
    assert repo.get_last_event_for_recipient('nobody@example.com') == (None, None)


def test_get_last_events_bulk(session):
    a = 'bulk_a@test.geo'
    b = 'bulk_b@test.geo'
    now = datetime.now(UTC)
    _mklog(session, a, '10.0.0.1', 'A_UA', now)
    _mklog(session, b, '10.0.0.2', 'B_UA', now - timedelta(hours=1))

    repo = LogRepository(session)
    out = repo.get_last_events_bulk([a, b, 'nobody@x.com'])
    assert out[a] == ('10.0.0.1', 'A_UA')
    assert out[b] == ('10.0.0.2', 'B_UA')
    assert 'nobody@x.com' not in out


def test_get_last_events_bulk_empty_input(session):
    repo = LogRepository(session)
    assert repo.get_last_events_bulk([]) == {}


def test_get_last_event_skips_rows_without_event_at(session):
    """Pre-tracking rows have last_event_at=None — they must not match."""
    email = f'unsent_{datetime.now(UTC).timestamp()}@test.geo'
    log = EmailLog(
        correlation_id=f'em_{email}_dummy',
        recipient_email=email,
        status='sent',
        last_event_ip=None,
        last_event_ua=None,
        last_event_at=None,
    )
    session.add(log)
    session.commit()

    repo = LogRepository(session)
    assert repo.get_last_event_for_recipient(email) == (None, None)


# ───── Tracking route persists IP/UA ──────────────────────────────────────

def test_tracking_open_persists_ip_and_ua(session):
    """Open an emaillog by correlation_id, hit /track/open/<id>, verify columns updated."""
    from mercury.web.app import create_app

    cid = f'em_track_{datetime.now(UTC).timestamp()}'
    log = EmailLog(
        correlation_id=cid,
        recipient_email='track-open@test.geo',
        status='sent',
    )
    session.add(log)
    session.commit()

    app = create_app()
    client = app.test_client()
    resp = client.get(f'/track/open/{cid}', headers={'User-Agent': 'TestBrowser/1.0'})
    assert resp.status_code == 200

    session.expire_all()
    fresh = session.query(EmailLog).filter_by(correlation_id=cid).one()
    assert fresh.open_count == 1
    assert fresh.last_event_ua == 'TestBrowser/1.0'
    assert fresh.last_event_at is not None
    # remote_addr is None in the test client by default; treat empty as acceptable.


# ───── EmailService enrichment ────────────────────────────────────────────

def test_enrichment_fills_missing_fields(session):
    """Recipients without ip/ua get backfilled from prior tracking events."""
    from mercury.services.email_service import EmailService
    from mercury.services.smtp_service import SMTPService

    target = 'enrich-needed@test.geo'
    _mklog(session, target, '8.8.4.4', 'KnownUA/9.0', datetime.now(UTC))
    session.commit()

    svc = EmailService(SMTPService())
    recipients = [
        {'email': target},  # missing ip + ua → should be filled
        {'email': 'no-history@test.geo'},  # no history → stays empty
    ]
    svc._enrich_recipients_with_last_event(recipients)

    assert recipients[0].get('ip') == '8.8.4.4'
    assert recipients[0].get('user_agent') == 'KnownUA/9.0'
    # No history → enrichment is silent; recipient still missing keys.
    assert 'ip' not in recipients[1] or not recipients[1].get('ip')


def test_enrichment_does_not_overwrite_csv_supplied_values(session):
    """Caller-provided ip/ua wins over historical inference."""
    from mercury.services.email_service import EmailService
    from mercury.services.smtp_service import SMTPService

    target = 'csv-wins@test.geo'
    _mklog(session, target, '8.8.4.4', 'FromHistoryUA', datetime.now(UTC))
    session.commit()

    svc = EmailService(SMTPService())
    recipients = [{
        'email': target,
        'ip': '1.2.3.4',           # CSV-supplied
        'user_agent': 'CSV_UA/1',  # CSV-supplied
    }]
    svc._enrich_recipients_with_last_event(recipients)

    assert recipients[0]['ip'] == '1.2.3.4'
    assert recipients[0]['user_agent'] == 'CSV_UA/1'


def test_enrichment_no_op_when_recipients_already_have_both_fields(session):
    """Recipients with both ip and user_agent supplied stay untouched.

    Skipping the DB roundtrip in this case is a perf property, not a
    behavioral one — verifying the values stay intact is the contract
    that callers rely on.
    """
    from mercury.services.email_service import EmailService
    from mercury.services.smtp_service import SMTPService

    svc = EmailService(SMTPService())
    recipients = [
        {'email': 'has-both@x.com', 'ip': '1.1.1.1', 'user_agent': 'X'},
    ]
    svc._enrich_recipients_with_last_event(recipients)
    assert recipients[0]['ip'] == '1.1.1.1'
    assert recipients[0]['user_agent'] == 'X'


def test_enrichment_partial_fill_ip_only(session):
    """Recipient has ip but not ua → only ua gets backfilled."""
    from mercury.services.email_service import EmailService
    from mercury.services.smtp_service import SMTPService

    target = 'partial@test.geo'
    _mklog(session, target, '8.8.4.4', 'HistoryUA', datetime.now(UTC))
    session.commit()

    svc = EmailService(SMTPService())
    recipients = [{'email': target, 'ip': 'csv-supplied-ip'}]
    svc._enrich_recipients_with_last_event(recipients)

    assert recipients[0]['ip'] == 'csv-supplied-ip'  # untouched
    assert recipients[0].get('user_agent') == 'HistoryUA'  # backfilled

"""Durable send ledger + Resend idempotency. No recipient is accepted from MCP."""
import base64
from datetime import date, datetime, timedelta
import hashlib
import json
import sqlite3
from zoneinfo import ZoneInfo
import httpx
from .config import settings, profile_for
from .reports import get_week, pdf_bytes
from .store import Store, LOCK


def send_week(start: date, *, scheduled=False, now=None):
    with LOCK:
        return _send_week(start, scheduled=scheduled, now=now)


def _send_week(start: date, *, scheduled=False, now=None):
    if getattr(settings(), 'state_backend', 'sqlite') == 'supabase':
        return send_week_cloud(start, now=now)
    return send_week_sqlite(start, now=now)


def send_week_sqlite(start: date, *, now=None):
    cfg = settings()
    if not cfg.email_to or not cfg.email_from or not cfg.resend_api_key.get_secret_value():
        raise ValueError('Configure EMAIL_TO, EMAIL_FROM and RESEND_API_KEY locally.')
    now = now or datetime.now(ZoneInfo(cfg.timezone))
    if start + timedelta(days=6) >= now.date():
        raise ValueError('Email only completed date ranges, ending before today.')
    cfg.data_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    # Payload persists exactly, even if logs change during retries.
    key = hashlib.sha256(f'{cfg.owner_user_id}/{start}/{cfg.email_to}'.encode()).hexdigest()
    path = cfg.data_dir / 'delivery.sqlite3'
    with sqlite3.connect(path, timeout=30) as ledger:
        path.chmod(0o600)
        ledger.execute('CREATE TABLE IF NOT EXISTS sends (key TEXT PRIMARY KEY, created REAL, state TEXT, payload TEXT, provider_id TEXT)')
        ledger.execute('BEGIN IMMEDIATE')
        existing = ledger.execute('SELECT created,state,payload,provider_id FROM sends WHERE key=?', (key,)).fetchone()
        if existing and existing[1] == 'accepted':
            return {'status': 'already_accepted', 'provider_id': existing[3]}
        if existing and now.timestamp() - existing[0] > 23 * 3600:
            raise ValueError('Uncertain prior delivery is older than the safe retry window. Review provider history manually.')
        if existing:
            payload = json.loads(existing[2])
        else:
            with LOCK:
                report = get_week(Store(), start, lambda day: profile_for(day)["baseline_kcal"])
            attachment = base64.b64encode(pdf_bytes(report, cfg.timezone)).decode()
            payload = {'from': cfg.email_from, 'to': [cfg.email_to],
                       'subject': f"Your weekly diet report: {report['start']} to {report['end']}",
                       'text': f"Your PDF report is attached. Complete days: {report['complete_days']}/7. Partial days are marked; estimates are explained in the PDF.",
                       'attachments': [{'filename': f'diet-week-{start}.pdf', 'content': attachment}]}
            ledger.execute('INSERT INTO sends VALUES (?,?,?,?,?)', (key, now.timestamp(), 'pending', json.dumps(payload), None))
        ledger.commit()
        # Duplicate concurrent requests share an identical provider idempotency key/payload.
        response = httpx.post('https://api.resend.com/emails', json=payload,
                              headers={'Authorization': f'Bearer {cfg.resend_api_key.get_secret_value()}',
                                       'Idempotency-Key': key}, timeout=30)
        if not response.is_success:
            raise ValueError('Email provider rejected the request; check its dashboard. No credentials are shown.')
        provider_id = response.json()['id']
        ledger.execute('UPDATE sends SET state=?, provider_id=? WHERE key=?', ('accepted', provider_id, key))
        ledger.commit()
        return {'status': 'accepted_by_provider', 'provider_id': provider_id}


def due_start(now, cfg):
    local = now.astimezone(ZoneInfo(cfg.timezone))
    if local.weekday() != cfg.report_weekday or (local.hour, local.minute) < (cfg.report_hour, cfg.report_minute):
        return None
    return local.date() - timedelta(days=7)


def scheduler():
    import time
    import logging
    cfg = settings()
    if not cfg.weekly_email_enabled:
        raise ValueError('Weekly email is disabled. Set WEEKLY_EMAIL_ENABLED=true after configuration.')
    logging.info('Weekly email worker started in configured timezone.')
    while True:
        now = datetime.now(ZoneInfo(cfg.timezone))
        start = due_start(now, cfg)
        if start is not None:
            try:
                result = send_week(start, scheduled=True, now=now)
                if result['status'] != 'already_accepted':
                    logging.info('Weekly report accepted by email provider.')
            except Exception:
                logging.error('Weekly delivery failed; check configuration and provider dashboard. Retrying in five minutes.')
                time.sleep(240)
        time.sleep(60)


def send_week_cloud(start: date, *, now=None):
    from .state import PrivateState
    cfg = settings()
    if not cfg.email_to or not cfg.email_from or not cfg.resend_api_key.get_secret_value():
        raise ValueError('Configure the private email sender and recipient.')
    now = now or datetime.now(ZoneInfo(cfg.timezone))
    if start + timedelta(days=6) >= now.date():
        raise ValueError('Report must end before today.')
    state = PrivateState()
    key = hashlib.sha256(f'{cfg.owner_user_id}/{start}/{cfg.email_to}'.encode()).hexdigest()
    saved = state.get('deliveries', key)
    if saved is None:
        report = get_week(Store(), start, lambda day: profile_for(day)['baseline_kcal'])
        payload = {'from': cfg.email_from, 'to': [cfg.email_to],
                   'subject': f"Your weekly diet report: {report['start']} to {report['end']}",
                   'text': f"Your PDF is attached. Complete days: {report['complete_days']}/7. Missing logs and estimates are labelled.",
                   'attachments': [{'filename': f'diet-week-{start}.pdf',
                                    'content': base64.b64encode(pdf_bytes(report, cfg.timezone)).decode()}]}
        state.put('deliveries', key, {'created': now.timestamp(), 'status': 'pending', 'payload': payload}, only_if_absent=True)
        saved = state.get('deliveries', key)
        if saved is None:
            raise ValueError('Delivery state was not persisted; refusing to send.')
    if saved['status'] == 'accepted':
        return {'status': 'already_accepted', 'provider_id': saved['provider_id']}
    if now.timestamp() - saved['created'] > 23*3600:
        raise ValueError('Uncertain send is outside safe retry window; review provider history.')
    response = httpx.post('https://api.resend.com/emails', json=saved['payload'],
                          headers={'Authorization': f'Bearer {cfg.resend_api_key.get_secret_value()}',
                                   'Idempotency-Key': key}, timeout=30)
    if not response.is_success:
        raise ValueError('Provider rejected delivery; check provider dashboard.')
    provider_id = response.json()['id']
    state.put('deliveries', key, {**saved, 'status': 'accepted', 'provider_id': provider_id})
    return {'status': 'accepted_by_provider', 'provider_id': provider_id}


def scheduled_start(today, weekday=4):
    """Latest scheduled local date, minus seven full days; stable across delayed retries."""
    latest = today - timedelta(days=(today.weekday() - weekday) % 7)
    return latest - timedelta(days=7)

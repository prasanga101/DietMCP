from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import patch
import json
import sqlite3
import pytest
from pydantic import SecretStr
from fitness_mcp.delivery import send_week


def config(tmp_path):
    return SimpleNamespace(email_to='test@example.com', email_from='report@example.com',
                           resend_api_key=SecretStr('test-private'), data_dir=tmp_path,
                           owner_user_id='owner', baseline_kcal=2500, timezone='Asia/Kathmandu')


def report():
    return {'start': '2026-10-09', 'end': '2026-10-15', 'complete_days': 0}


def test_repeated_week_does_not_send_twice(tmp_path):
    cfg = config(tmp_path)
    response = SimpleNamespace(is_success=True, json=lambda: {'id': 'accepted-id'})
    with patch('fitness_mcp.delivery.settings', return_value=cfg), patch('fitness_mcp.delivery.Store'), \
         patch('fitness_mcp.delivery.get_week', return_value=report()), \
         patch('fitness_mcp.delivery.pdf_bytes', return_value=b'%PDF-test'), \
         patch('fitness_mcp.delivery.httpx.post', return_value=response) as post:
        now = datetime(2026,10,16,11,tzinfo=timezone.utc)
        assert send_week(date(2026,10,9), now=now)['status'] == 'accepted_by_provider'
        assert send_week(date(2026,10,9), now=now)['status'] == 'already_accepted'
        assert post.call_count == 1
        assert post.call_args.kwargs['json']['to'] == ['test@example.com']
        assert post.call_args.kwargs['json']['attachments'][0]['filename'].endswith('.pdf')


def test_retry_reuses_identical_payload(tmp_path):
    cfg = config(tmp_path)
    response = SimpleNamespace(is_success=True, json=lambda: {'id': 'accepted-id'})
    payloads = []
    def network(url, **kwargs):
        payloads.append((kwargs['json'], kwargs['headers']['Idempotency-Key']))
        if len(payloads) == 1:
            raise TimeoutError('uncertain network result')
        return response
    with patch('fitness_mcp.delivery.settings', return_value=cfg), patch('fitness_mcp.delivery.Store'), \
         patch('fitness_mcp.delivery.get_week', return_value=report()), \
         patch('fitness_mcp.delivery.pdf_bytes', return_value=b'%PDF-test'), \
         patch('fitness_mcp.delivery.httpx.post', side_effect=network):
        now = datetime(2026,10,16,11,tzinfo=timezone.utc)
        with pytest.raises(TimeoutError):
            send_week(date(2026,10,9), now=now)
        send_week(date(2026,10,9), now=now+timedelta(minutes=5))
        assert payloads[0] == payloads[1]


def test_old_uncertain_send_blocks_duplicate(tmp_path):
    cfg = config(tmp_path)
    with patch('fitness_mcp.delivery.settings', return_value=cfg), patch('fitness_mcp.delivery.Store'), \
         patch('fitness_mcp.delivery.get_week', return_value=report()), \
         patch('fitness_mcp.delivery.pdf_bytes', return_value=b'%PDF-test'), \
         patch('fitness_mcp.delivery.httpx.post', side_effect=TimeoutError):
        now = datetime(2026,10,16,11,tzinfo=timezone.utc)
        with pytest.raises(TimeoutError):
            send_week(date(2026,10,9), now=now)
        with pytest.raises(ValueError, match='safe retry'):
            send_week(date(2026,10,9), now=now+timedelta(days=1))


def test_current_week_cannot_be_emailed(tmp_path):
    with patch('fitness_mcp.delivery.settings', return_value=config(tmp_path)):
        with pytest.raises(ValueError, match='ending before today'):
            send_week(date(2026,10,15), now=datetime(2026,10,16,tzinfo=timezone.utc))

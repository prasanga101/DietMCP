from datetime import date, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import patch
from io import BytesIO
import asyncio
import pytest
from pypdf import PdfReader
from pydantic import ValidationError
from fitness_mcp.models import Food, Activity
from fitness_mcp.calculations import day_summary, weekly_summary
from fitness_mcp.delivery import due_start
from fitness_mcp.reports import pdf_bytes
from fitness_mcp.auth import OwnerVerifier


def test_missing_is_not_zero():
    d = day_summary(date(2026, 10, 10), [], [], {}, 2500)
    assert d['deficit_kcal'] is None
    assert d['intake_kcal'] is None
    assert d['exercise_kcal'] is None


def test_deficit_and_net_exercise_once():
    d = day_summary(date(2026, 10, 10), [{'calories_kcal': 2100, 'protein_g': 100}],
                    [{'estimated_calories_kcal': 300}], {'food_log_complete': True, 'activity_log_complete': True}, 2500)
    assert d['tdee_kcal'] == 2800
    assert d['deficit_kcal'] == 700


def test_unknown_calories_blocks_deficit():
    d = day_summary(date(2026, 10, 10), [{'calories_kcal': None}], [],
                    {'food_log_complete': True, 'activity_log_complete': True}, 2500)
    assert d['deficit_kcal'] is None


def example_report(complete=True):
    start = date(2026, 10, 9)
    foods, activities, statuses = [], [], []
    for n, intake in enumerate([2200, 2400, 2000, 2300, 2100, 2500, 2250]):
        day = str(start + timedelta(days=n))
        foods.append({'log_date': day, 'calories_kcal': intake, 'protein_g': 130+n*3})
        activities.append({'log_date': day, 'estimated_calories_kcal': [250, 400, 0, 350, 200, 450, 150][n]})
        statuses.append({'log_date': day, 'food_log_complete': complete or n != 3, 'activity_log_complete': True})
    return weekly_summary(start, foods, activities, statuses, 2527.8)


def test_complete_week_and_incomplete_week():
    full = example_report()
    assert full['weekly_deficit_kcal'] == round(sum(d['deficit_kcal'] for d in full['days']), 1)
    assert full['estimated_weight_loss_kg'] == round(full['weekly_deficit_kcal']/7700, 3)
    partial = example_report(False)
    assert partial['weekly_deficit_kcal'] is None
    assert partial['estimated_weight_loss_kg'] is None
    assert partial['complete_days'] == 6


def test_surplus_is_negative_deficit():
    d = day_summary(date(2026, 10, 10), [{'calories_kcal': 3000}], [],
                    {'food_log_complete': True, 'activity_log_complete': True}, 2500)
    assert d['deficit_kcal'] == -500


def test_friday_nepal_boundary():
    cfg = SimpleNamespace(timezone='Asia/Kathmandu', report_weekday=4, report_hour=16, report_minute=0)
    assert due_start(datetime.fromisoformat('2026-10-16T10:14:00+00:00'), cfg) is None
    assert due_start(datetime.fromisoformat('2026-10-16T10:15:00+00:00'), cfg) == date(2026,10,9)
    assert due_start(datetime.fromisoformat('2026-10-17T10:15:00+00:00'), cfg) is None


def test_birthdays(monkeypatch):
    from fitness_mcp.config import profile_for
    cfg = SimpleNamespace(birth_date=date(2005,2,19), weight_kg=100, height_cm=193.04, sex='male',
                          target_weight_kg=70, baseline_kcal=None, baseline_multiplier=1.2)
    with patch('fitness_mcp.config.settings', return_value=cfg):
        assert profile_for(date(2027,2,18))['age'] == 21
        assert profile_for(date(2027,2,19))['age'] == 22
        assert profile_for(date(2026,10,17))['baseline_kcal'] == 2527.8


def test_owner_verifier():
    from fastmcp.server.auth.providers.github import GitHubTokenVerifier
    from fastmcp.server.auth import AccessToken
    async def fake(self, token):
        return AccessToken(token=token, client_id='x', scopes=['read:user'], claims={'sub': token})
    async def check():
        verifier = OwnerVerifier('123')
        assert await verifier.verify_token('123') is not None
        assert await verifier.verify_token('999') is None
    with patch.object(GitHubTokenVerifier, 'verify_token', fake):
        asyncio.run(check())


def test_invalid_inputs():
    with pytest.raises(ValidationError):
        Food(entry_id='bad', log_date='2026-10-10', food_name='x', calories_kcal=-1)
    with pytest.raises(ValidationError):
        Activity(entry_id='00000000-0000-0000-0000-000000000001', log_date='2026-10-10', activity_type='x', estimated_calories_kcal=float('nan'))


def test_pdf_content_and_pages():
    report = example_report()
    raw = pdf_bytes(report, sample=True)
    reader = PdfReader(BytesIO(raw))
    text = '\n'.join(p.extract_text() for p in reader.pages)
    assert len(reader.pages) == 2
    for expected in ['SAMPLE DATA', 'TDEE', 'Deficit', 'Complete days', '7,700', 'DAILY DETAIL']:
        assert expected in text


def test_http_rejects_anonymous_requests():
    from starlette.testclient import TestClient
    from fastmcp.server.auth.providers.jwt import StaticTokenVerifier
    from fitness_mcp.app import create_server
    auth = StaticTokenVerifier(tokens={'private-test-token': {'client_id': 'owner', 'scopes': []}})
    with TestClient(create_server(auth).http_app()) as client:
        assert client.get('/health').status_code == 200
        response = client.post('/mcp', json={'jsonrpc': '2.0', 'id': 1, 'method': 'initialize',
                               'params': {'protocolVersion': '2025-03-26', 'capabilities': {},
                                          'clientInfo': {'name':'test', 'version':'1'}}})
        assert response.status_code == 401


def test_frozen_baseline_preserves_completed_history():
    import json
    status = {'food_log_complete': True, 'activity_log_complete': True,
              'calculation_notes': json.dumps({'dietmcp_version': 1, 'baseline_kcal': 2500})}
    d = day_summary(date(2026,10,10), [{'calories_kcal': 2000}], [], status, 3000)
    assert d['baseline_kcal'] == 2500
    assert d['deficit_kcal'] == 500

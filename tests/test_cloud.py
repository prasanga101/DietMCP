from datetime import date, datetime, timedelta, timezone
from unittest.mock import patch
from types import SimpleNamespace
from pydantic import SecretStr
import pytest
from fitness_mcp.delivery import send_week, scheduled_start


def test_delayed_schedule_keeps_friday_period():
    assert scheduled_start(date(2026,10,16)) == date(2026,10,9)
    assert scheduled_start(date(2026,10,17)) == date(2026,10,9)
    assert scheduled_start(date(2026,10,22)) == date(2026,10,9)
    assert scheduled_start(date(2026,10,23)) == date(2026,10,16)


def test_cloud_ledger_survives_new_instances_and_free_host_restarts():
    records = {}
    class FakeState:
        def get(self, collection, key):
            return records.get((collection,key))
        def put(self, collection, key, value, expires_at=None, only_if_absent=False):
            if only_if_absent and (collection,key) in records:
                return False
            records[collection,key] = value
            return True
    cfg = SimpleNamespace(state_backend='supabase', email_to='owner@example.com', email_from='sender@example.com',
                          resend_api_key=SecretStr('secret'), timezone='Asia/Kathmandu', owner_user_id='owner')
    report = {'start':'2026-10-09','end':'2026-10-15','complete_days':7}
    result = SimpleNamespace(is_success=True,json=lambda:{'id':'cloud-email'})
    with patch('fitness_mcp.delivery.settings',return_value=cfg), patch('fitness_mcp.state.PrivateState',FakeState), \
         patch('fitness_mcp.delivery.Store'), patch('fitness_mcp.delivery.get_week',return_value=report), \
         patch('fitness_mcp.delivery.pdf_bytes',return_value=b'%PDF'), patch('fitness_mcp.delivery.httpx.post',return_value=result) as post:
        now=datetime(2026,10,16,11,tzinfo=timezone.utc)
        assert send_week(date(2026,10,9),now=now)['status']=='accepted_by_provider'
        assert send_week(date(2026,10,9),now=now+timedelta(days=7))['status']=='already_accepted'
        assert post.call_count==1


def test_oauth_kv_roundtrip_and_expiry():
    import asyncio
    from fitness_mcp.state import SupabaseOAuthStore
    values={}
    class FakeState:
        def get(self,c,k): return values.get((c,k))
        def put(self,c,k,v,expires_at=None): values[c,k]=v
        def delete(self,c,k): return values.pop((c,k),None) is not None
    async def check():
        store=SupabaseOAuthStore()
        await store.put('client',{'token':'hidden'},collection='auth',ttl=300)
        store2=SupabaseOAuthStore()
        assert await store2.get('client',collection='auth')=={'token':'hidden'}
        assert await store2.delete('client',collection='auth')
        assert await store.get('client',collection='auth') is None
        await store.put('expired',{'x':1},collection='auth',ttl=300)
        values['oauth:auth','expired']['expires_at'] = (datetime.now(timezone.utc)-timedelta(seconds=1)).isoformat()
        assert await store.get('expired',collection='auth') is None
    with patch('fitness_mcp.state.PrivateState',FakeState):
        asyncio.run(check())

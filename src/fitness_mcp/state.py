"""Encrypted durable state for free hosts with ephemeral filesystems."""
import asyncio
from datetime import datetime, timezone
import json
import hashlib
from cryptography.fernet import Fernet
from key_value.aio.stores.base import BaseStore, ManagedEntry
from supabase import create_client
from .config import settings


class PrivateState:
    def __init__(self):
        cfg = settings()
        self.owner = str(cfg.owner_user_id)
        self.db = create_client(cfg.supabase_url, cfg.supabase_server_key.get_secret_value())
        self.cipher = Fernet(cfg.state_encryption_key.get_secret_value().encode())

    def query(self, collection, key):
        return self.db.table('dietmcp_private_state').select('*').eq('user_id', self.owner).eq('collection', collection).eq('key', hashlib.sha256(key.encode()).hexdigest())

    def get(self, collection, key):
        rows = self.query(collection, key).execute().data
        if not rows:
            return None
        row = rows[0]
        if row['expires_at'] and datetime.fromisoformat(row['expires_at'].replace('Z', '+00:00')) <= datetime.now(timezone.utc):
            return None
        return json.loads(self.cipher.decrypt(row['ciphertext'].encode()))

    def put(self, collection, key, value, expires_at=None, *, only_if_absent=False):
        row = {'user_id': self.owner, 'collection': collection, 'key': hashlib.sha256(key.encode()).hexdigest(),
               'ciphertext': self.cipher.encrypt(json.dumps(value).encode()).decode(),
               'expires_at': expires_at.isoformat() if expires_at else None}
        try:
            if only_if_absent:
                self.db.table('dietmcp_private_state').insert(row).execute()
            else:
                self.db.table('dietmcp_private_state').upsert(row, on_conflict='user_id,collection,key').execute()
            return True
        except Exception as error:
            if only_if_absent and getattr(error, 'code', None) == '23505':
                return False
            raise

    def delete(self, collection, key):
        rows = self.db.table('dietmcp_private_state').delete().eq('user_id', self.owner).eq('collection', collection).eq('key', hashlib.sha256(key.encode()).hexdigest()).execute().data
        return bool(rows)


class SupabaseOAuthStore(BaseStore):
    def __init__(self):
        super().__init__(stable_api=True)
        self.state = PrivateState()

    async def _get_managed_entry(self, *, collection, key):
        value = await asyncio.to_thread(self.state.get, 'oauth:' + collection, key)
        if value is None:
            return None
        return ManagedEntry(value=value['value'],
                            created_at=datetime.fromisoformat(value['created_at']) if value.get('created_at') else None,
                            expires_at=datetime.fromisoformat(value['expires_at']) if value.get('expires_at') else None)

    async def _put_managed_entry(self, *, collection, key, managed_entry):
        value = {'value': dict(managed_entry.value), 'created_at': managed_entry.created_at_isoformat,
                 'expires_at': managed_entry.expires_at_isoformat}
        await asyncio.to_thread(self.state.put, 'oauth:' + collection, key, value, managed_entry.expires_at)

    async def _delete_managed_entry(self, *, collection, key):
        return await asyncio.to_thread(self.state.delete, 'oauth:' + collection, key)

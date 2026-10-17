"""All data access is scoped to the configured owner, including writes."""
from uuid import UUID
from threading import RLock

LOCK = RLock()
from supabase import create_client
from .config import settings

TABLES = ('food_logs', 'activity_logs', 'daily_summaries')


class Store:
    def __init__(self):
        cfg = settings()
        self.owner = str(cfg.owner_user_id)
        self.db = create_client(cfg.supabase_url, cfg.supabase_server_key.get_secret_value())

    def rows(self, table, start, end):
        if table not in TABLES:
            raise ValueError('Unknown table')
        result = []
        offset = 0
        while True:
            page = (self.db.table(table).select('*').eq('user_id', self.owner)
                    .gte('log_date', str(start)).lte('log_date', str(end))
                    .order('log_date').order('id').range(offset, offset + 499).execute().data)
            result.extend(page)
            if len(page) < 500:
                return result
            offset += len(page)

    def summary(self, day, values):
        return self.db.table('daily_summaries').upsert(
            {'user_id': self.owner, 'log_date': str(day), **values},
            on_conflict='user_id,log_date').execute().data

    def invalidate(self, day):
        # Invalidate before mutation; a failed write cannot silently leave a complete day.
        self.summary(day, {'food_log_complete': False, 'activity_log_complete': False,
                          'estimated_tdee_kcal': None, 'estimated_deficit_kcal': None})

    def put(self, table, model):
        if table not in ('food_logs', 'activity_logs'):
            raise ValueError('Unknown table')
        data = model.model_dump(mode='json')
        row_id = str(UUID(data.pop('entry_id')))
        existing = self.db.table(table).select('id,log_date').eq('user_id', self.owner).eq('id', row_id).execute().data
        self.invalidate(data['log_date'])
        if existing:
            self.invalidate(existing[0]['log_date'])
            rows = self.db.table(table).update(data).eq('user_id', self.owner).eq('id', row_id).execute().data
        else:
            rows = self.db.table(table).insert({'id': row_id, 'user_id': self.owner, 'source': 'dietmcp', **data}).execute().data
        return rows

    def delete(self, table, row_id):
        if table not in ('food_logs', 'activity_logs'):
            raise ValueError('Unknown table')
        row_id = str(UUID(str(row_id)))
        existing = self.db.table(table).select('log_date').eq('user_id', self.owner).eq('id', row_id).execute().data
        for row in existing:
            self.invalidate(row['log_date'])
        self.db.table(table).delete().eq('user_id', self.owner).eq('id', row_id).execute()
        return {'deleted': bool(existing)}

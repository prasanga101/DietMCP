"""Remote, single-owner MCP. Database credentials stay on the server."""
import argparse
from datetime import date, datetime, timedelta
from functools import wraps
import json
import logging
import os
from pathlib import Path
from threading import Thread
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

from fastmcp import FastMCP
from starlette.responses import JSONResponse
from .auth import build_auth
from .calculations import day_summary
from .config import settings, profile_for
from .models import Food, Activity
from .reports import get_week, pdf_bytes
from .store import Store, LOCK



def safe(func):
    @wraps(func)
    def wrapped(*args, **kwargs):
        try:
            with LOCK:
                return func(*args, **kwargs)
        except Exception:
            raise ValueError('Operation failed. Check server configuration, schema and provider status. No credentials are shown.') from None
    return wrapped


def current_date():
    return datetime.now(ZoneInfo(settings().timezone)).date()


def validate_day(day):
    if day > current_date():
        raise ValueError('Future dates are not accepted as completed logs.')


def daily(store, day):
    statuses = store.rows('daily_summaries', day, day)
    return day_summary(day, store.rows('food_logs', day, day), store.rows('activity_logs', day, day),
                       statuses[0] if statuses else {}, profile_for(day)['baseline_kcal'])


def create_server(auth=None):
    mcp = FastMCP('DietMCP', auth=auth, mask_error_details=True,
                  instructions='Personal diet and activity tracker. Use get_context for local dates. '
                  'Save only user-reported foods/activities with labelled nutrition estimates. '
                  'Reuse the same entry_id to retry or correct a record; create a new UUID for each distinct item. '
                  'Never say a log is saved until a tool succeeds. Do not silently mark a day complete. '
                  'Only confirm_day when the user confirms the entire food and activity log for that date. '
                  'Exercise calories must be NET ADDITIONAL burn beyond the sedentary baseline. '
                  'Do not add calories for steps already covered by baseline or another workout. '
                  'Use zero incremental calories for informational total-step records; explain this in notes.')

    @mcp.custom_route('/health', methods=['GET'])
    async def health(request):
        return JSONResponse({'status': 'ok'})

    @mcp.tool(annotations={'readOnlyHint': True, 'openWorldHint': False})
    @safe
    def get_context() -> dict:
        """Get local date, energy assumptions and the fixed weekly email schedule."""
        cfg = settings()
        return {'today': str(current_date()), 'timezone': cfg.timezone, 'profile': profile_for(current_date()),
                'schedule': {'weekday_monday_zero': cfg.report_weekday, 'hour': cfg.report_hour,
                             'minute': cfg.report_minute, 'enabled': cfg.weekly_email_enabled},
                'exercise_rule': 'Additional net burn only; exclude baseline and overlapping step/workout calories.'}

    @mcp.tool(annotations={'readOnlyHint': False, 'idempotentHint': True, 'openWorldHint': False})
    @safe
    def log_food(entry: Food) -> dict:
        """Save or replace a food entry with a stable UUID; estimates must be labelled in notes. Reopens the day."""
        validate_day(entry.log_date)
        return {'saved': Store().put('food_logs', entry), 'day_requires_confirmation': True}

    @mcp.tool(annotations={'readOnlyHint': False, 'idempotentHint': True, 'openWorldHint': False})
    @safe
    def log_activity(entry: Activity) -> dict:
        """Save/replace activity. estimated_calories_kcal is additional NET burn, not gross burn. Reopens day."""
        validate_day(entry.log_date)
        return {'saved': Store().put('activity_logs', entry), 'day_requires_confirmation': True}

    @mcp.tool(annotations={'readOnlyHint': False, 'destructiveHint': True, 'idempotentHint': True, 'openWorldHint': False})
    @safe
    def delete_entry(table: str, entry_id: UUID) -> dict:
        """Delete a specified food_logs/activity_logs record when requested; reopens that day."""
        return Store().delete(table, entry_id)

    @mcp.tool(annotations={'readOnlyHint': True, 'openWorldHint': False})
    @safe
    def get_daily_summary(log_date: date) -> dict:
        """Return the dated food/activity records and estimated energy balance. Partial days have no deficit."""
        store = Store()
        return {'summary': daily(store, log_date), 'foods': store.rows('food_logs', log_date, log_date),
                'activities': store.rows('activity_logs', log_date, log_date)}

    @mcp.tool(annotations={'readOnlyHint': False, 'idempotentHint': True, 'openWorldHint': False})
    @safe
    def confirm_day(log_date: date, food_complete: bool, activity_complete: bool) -> dict:
        """Set completion flags ONLY after user confirmation. True with no rows means confirmed zero intake/rest."""
        validate_day(log_date)
        store = Store()
        profile = profile_for(log_date)
        store.summary(log_date, {'food_log_complete': food_complete, 'activity_log_complete': activity_complete,
                                'calculation_notes': json.dumps({'dietmcp_version': 1, **profile})})
        result = daily(store, log_date)
        store.summary(log_date, {'total_calories_kcal': result['intake_kcal'], 'total_protein_g': result['protein_g'],
                                'estimated_tdee_kcal': result['tdee_kcal'], 'estimated_deficit_kcal': result['deficit_kcal'],
                                'updated_at': datetime.now(ZoneInfo('UTC')).isoformat()})
        return result

    @mcp.tool(annotations={'readOnlyHint': True, 'openWorldHint': False})
    @safe
    def get_weekly_summary(start_date: date) -> dict:
        """Return seven days of intake, exercise, TDEE, deficits and estimated weight-loss equivalent."""
        return get_week(Store(), start_date, lambda day: profile_for(day)['baseline_kcal'])

    @mcp.tool(annotations={'readOnlyHint': True, 'openWorldHint': False})
    @safe
    def generate_weekly_report(start_date: date) -> dict:
        """Generate the week's PDF as an authenticated MCP resource; includes chart and daily table."""
        report = get_week(Store(), start_date, lambda day: profile_for(day)['baseline_kcal'])
        return {'summary': report, 'pdf_resource': f'dietmcp://reports/{start_date}.pdf'}

    @mcp.resource('dietmcp://reports/{start_date}.pdf', mime_type='application/pdf')
    @safe
    def read_report(start_date: str) -> bytes:
        day = date.fromisoformat(start_date)
        return pdf_bytes(get_week(Store(), day, lambda d: profile_for(d)['baseline_kcal']), settings().timezone)

    @mcp.tool(annotations={'readOnlyHint': False, 'idempotentHint': True, 'openWorldHint': True})
    @safe
    def email_weekly_report(start_date: date) -> dict:
        """Send the PDF to the fixed owner email ONLY when requested. Duplicate weeks are suppressed."""
        from .delivery import send_week
        return send_week(start_date)

    return mcp


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('command', choices=['serve', 'check', 'test', 'report', 'send', 'worker', 'doctor'])
    parser.add_argument('--start', type=date.fromisoformat)
    parser.add_argument('--output', type=Path, default=Path('weekly-report.pdf'))
    args = parser.parse_args()
    if args.command == 'doctor':
        from .diagnostics import doctor
        raise SystemExit(doctor())
    try:
        cfg = settings()
        cfg.data_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chmod(cfg.data_dir, 0o700)
        if args.command == 'serve':
            server = create_server(build_auth(cfg))
            if cfg.weekly_email_enabled:
                from .delivery import scheduler
                logging.basicConfig(level=logging.INFO)
                Thread(target=scheduler, name='weekly-email', daemon=True).start()
            server.run(transport='http', host='0.0.0.0', port=int(os.getenv('PORT', '8000')))
        elif args.command == 'worker':
            from .delivery import scheduler
            logging.basicConfig(level=logging.INFO)
            scheduler()
        elif args.command == 'check':
            store = Store()
            if store.db.auth.admin.get_user_by_id(store.owner).user is None:
                raise ValueError('Configured Auth owner does not exist')
            for table in ('food_logs', 'activity_logs', 'daily_summaries'):
                store.rows(table, current_date(), current_date())
                print(f'{table}: accessible')
        elif args.command == 'test':
            store = Store()
            entry = Food(entry_id=uuid4(), log_date=current_date(), food_name='CONNECTION TEST - DELETE ME', calories_kcal=0)
            # Deliberately avoid invalidating genuine daily completion in this isolated test.
            row = entry.model_dump(mode='json')
            row['id'] = row.pop('entry_id')
            row.update(user_id=store.owner, source='connection_test')
            try:
                store.db.table('food_logs').insert(row).execute()
                found = store.db.table('food_logs').select('id').eq('user_id', store.owner).eq('id', row['id']).execute().data
                if not found:
                    raise ValueError('Test read failed')
            finally:
                store.db.table('food_logs').delete().eq('user_id', store.owner).eq('id', row['id']).execute()
            if store.db.table('food_logs').select('id').eq('user_id', store.owner).eq('id', row['id']).execute().data:
                raise ValueError('Test cleanup failed')
            print('Owner-scoped insert/read/cleanup passed.')
        else:
            start = args.start or current_date() - timedelta(days=7)
            if args.command == 'send':
                from .delivery import send_week
                print(send_week(start)['status'])
            else:
                args.output.write_bytes(pdf_bytes(get_week(Store(), start, lambda d: profile_for(d)['baseline_kcal']), cfg.timezone))
                print(f'Report saved to {args.output}')
    except Exception:
        print('Operation failed. Check private configuration, database schema and provider dashboard. No credentials shown.', file=__import__('sys').stderr)
        raise SystemExit(1) from None

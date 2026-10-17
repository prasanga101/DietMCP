"""Missing data never becomes a zero intake or a claimed weight loss."""
from datetime import date, timedelta
import json
from math import isfinite


def total(rows, key):
    values = [r.get(key) for r in rows]
    if any(v is None for v in values):
        return None
    nums = [float(v) for v in values]
    if any(not isfinite(v) or v < 0 for v in nums):
        return None
    return round(sum(nums), 1)


def day_summary(day, foods, activities, status, baseline):
    # Freeze the energy assumptions at confirmation, so profile edits don't rewrite history.
    try:
        snapshot = json.loads(status.get('calculation_notes') or '{}')
        if snapshot.get('dietmcp_version') == 1:
            baseline = snapshot['baseline_kcal']
    except (ValueError, TypeError, KeyError):
        pass
    food_done = bool(status.get('food_log_complete', False))
    activity_done = bool(status.get('activity_log_complete', False))
    intake = total(foods, 'calories_kcal') if foods or food_done else None
    exercise = total(activities, 'estimated_calories_kcal') if activities or activity_done else None
    complete = food_done and activity_done and intake is not None and exercise is not None and baseline is not None
    tdee = round(baseline + exercise, 1) if baseline is not None and exercise is not None else None
    deficit = round(tdee - intake, 1) if complete else None
    return {'date': str(day), 'intake_kcal': intake, 'protein_g': total(foods, 'protein_g') if foods or food_done else None,
            'exercise_kcal': exercise, 'baseline_kcal': baseline, 'tdee_kcal': tdee,
            'deficit_kcal': deficit, 'food_complete': food_done, 'activity_complete': activity_done,
            'complete': complete, 'food_count': len(foods), 'activity_count': len(activities)}


def weekly_summary(start: date, foods, activities, statuses, baseline):
    days = []
    status_map = {s['log_date']: s for s in statuses}
    for n in range(7):
        day = start + timedelta(days=n)
        stamp = day.isoformat()
        days.append(day_summary(day, [f for f in foods if f['log_date'] == stamp],
                                [a for a in activities if a['log_date'] == stamp], status_map.get(stamp, {}), baseline(day) if callable(baseline) else baseline))
    complete = [d for d in days if d['complete']]
    subtotal = round(sum(d['deficit_kcal'] for d in complete), 1)
    full = len(complete) == 7
    return {'start': str(start), 'end': str(start + timedelta(days=6)), 'days': days,
            'complete_days': len(complete), 'logged_days_deficit_kcal': subtotal,
            'weekly_deficit_kcal': subtotal if full else None,
            'estimated_weight_loss_kg': round(subtotal / 7700, 3) if full else None,
            'method': 'TDEE = configured baseline excluding logged exercise + additional net exercise calories. '
                      'Deficit = TDEE - intake. Positive deficit means loss; negative means surplus. '
                      'Weight-loss equivalent uses 7700 kcal/kg; this is a rough energy equivalent, not predicted scale change.'}

"""Configuration readiness without printing credential values."""
import os
from .config import settings

REQUIRED = {
    'Database': ['SUPABASE_URL', 'SUPABASE_SERVER_KEY', 'OWNER_USER_ID'],
    'ChatGPT connection': ['PUBLIC_URL', 'GITHUB_CLIENT_ID', 'GITHUB_CLIENT_SECRET', 'GITHUB_OWNER_ID'],
    'Email': ['RESEND_API_KEY', 'EMAIL_FROM', 'EMAIL_TO'],
    'Profile': ['BIRTH_DATE', 'HEIGHT_CM', 'WEIGHT_KG', 'TARGET_WEIGHT_KG', 'SEX'],
}


def doctor():
    missing = False
    for group, keys in REQUIRED.items():
        absent = []
        for key in keys:
            value = os.getenv(key, '')
            if not value or any(x in value for x in ('YOUR_', 'YYYY-MM-DD', 'example.com', '00000000-0000', 'your-project')):
                absent.append(key)
        print(f'{group}: ' + ('missing ' + ', '.join(absent) if absent else 'values present'))
        missing = missing or bool(absent)
    if missing:
        print('Edit the private .env or hosting environment. Never paste credentials into chat.')
        return 1
    try:
        settings()
    except Exception:
        print('Configuration contains an invalid value. Check URL, UUID, profile and schedule formats locally.')
        return 1
    print('Configuration formats are valid. Run check and test to verify live access.')
    return 0

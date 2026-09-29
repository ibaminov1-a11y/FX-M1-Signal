"""Explicit broker clock configuration. Never infer a trading offset from tick age."""
import json
from pathlib import Path


def load_clock_policy(directory):
    path=Path(directory)/'broker-clock.json'
    if not path.exists():return {}
    data=json.loads(path.read_text(encoding='utf-8-sig'))
    account=data.get('account')
    minutes=data.get('offset_minutes')
    if (data.get('confirmed') is not True or not isinstance(account,str) or '@' not in account
            or not account.strip() or type(minutes) is not int or not -840<=minutes<=840):
        raise ValueError('broker-clock.json: нужны подтверждённый счёт login@server и целое offset_minutes от -840 до 840')
    return dict(clock_account=account,clock_offset_minutes=minutes)

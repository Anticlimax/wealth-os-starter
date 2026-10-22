"""Local ledger projection. Standard library only; no account or trading APIs."""
from __future__ import annotations

import hashlib
import json
import os
from contextlib import contextmanager
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation, localcontext
from pathlib import Path

VERSION = 'wealth-starter-v1'
ZERO = Decimal('0')


def number(value):
    if isinstance(value, bool) or value is None:
        raise ValueError('expected a finite number, got null/bool')
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError):
        raise ValueError(f'invalid number: {value!r}') from None
    if not result.is_finite() or abs(result) > Decimal('1e24'):
        raise ValueError('number must be finite and within +/- 1e24')
    return result


def positive(value, allow_zero=True):
    result = number(value)
    if result < 0 or (not allow_zero and result == 0):
        raise ValueError('expected a nonnegative number' if allow_zero else 'expected a positive number')
    return result


def timestamp(value):
    try:
        result = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
        if result.utcoffset() is None:
            raise ValueError()
        return result
    except (ValueError, TypeError):
        raise ValueError(f'timestamp requires an explicit timezone: {value!r}') from None


def money(value):
    if value is None:
        return None
    with localcontext() as context:
        context.prec = max(28, value.adjusted() + 4)
        return float(value.quantize(Decimal('0.01')))


def load(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def lines(path):
    return [json.loads(line) for line in Path(path).read_text(encoding='utf-8').splitlines() if line.strip()]


def atomic_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + f'.{os.getpid()}.tmp')
    try:
        with tmp.open('w', encoding='utf-8') as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)
            stream.write('\n')
            stream.flush()
            os.fsync(stream.fileno())
        tmp.replace(path)
    finally:
        tmp.unlink(missing_ok=True)


@contextmanager
def writer_lock(root):
    """Portable fail-fast lock. Never remove a lock belonging to another writer."""
    lock = Path(root) / '.write.lock'
    try:
        descriptor = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError:
        raise ValueError('writer active or stale .write.lock; check before manually removing it') from None
    try:
        os.close(descriptor)
        yield
    finally:
        lock.unlink()


def read_inputs(root):
    root = Path(root)
    data = {name: load(root / f'{name}.json') for name in ('profile', 'opening', 'prices', 'plan')}
    data['events'] = lines(root / 'events.jsonl')
    validate(data)
    return data


def validate(data):
    profile, opening, prices, plan = (data[name] for name in ('profile', 'opening', 'prices', 'plan'))
    if profile.get('schema') != VERSION or profile.get('mode') not in ('demo', 'personal'):
        raise ValueError('unsupported schema or mode')
    if not isinstance(profile.get('base_currency'), str) or not profile['base_currency']:
        raise ValueError('base_currency is required')
    for key in ('monthly_income', 'monthly_expenses', 'emergency_months'):
        if profile.get(key) is not None:
            positive(profile[key])
    if not isinstance(opening.get('confirmed'), bool):
        raise ValueError('opening.confirmed must be true/false')
    if not opening['confirmed'] and opening['positions']:
        raise ValueError('review opening positions and set confirmed=true before projection')
    start = timestamp(opening['as_of'])
    accounts = profile['accounts']
    assets = profile['assets']
    if not isinstance(accounts, dict) or not isinstance(assets, dict):
        raise ValueError('accounts/assets must be objects keyed by ID')
    for asset in assets.values():
        if not all(isinstance(asset.get(k), str) and asset[k] for k in ('name', 'currency', 'category')):
            raise ValueError('asset needs name/currency/category')
        if asset.get('kind') not in ('cash', 'security', 'pending', 'liability'):
            raise ValueError('unsupported asset kind')
        if not isinstance(asset.get('liquid'), bool):
            raise ValueError('asset liquid must be a boolean')
    pairs = set()
    for row in opening['positions']:
        pair = (row['account'], row['asset'])
        if row['account'] not in accounts or row['asset'] not in assets or pair in pairs:
            raise ValueError('unknown or duplicate opening position')
        pairs.add(pair)
        positive(row['quantity'])
    for aid, quote in prices['quotes'].items():
        if aid not in assets:
            raise ValueError('quote references unknown asset')
        positive(quote['price'])
        timestamp(quote['as_of'])
        if not quote.get('source'):
            raise ValueError('quote source is required')
    for currency, quote in prices['fx'].items():
        positive(quote['rate'], allow_zero=False)
        timestamp(quote['as_of'])
        if not quote.get('source'):
            raise ValueError('FX source is required')
    if plan.get('status') not in ('draft', 'confirmed'):
        raise ValueError('plan status must be draft/confirmed')
    targets = plan['targets']
    if targets and sum((positive(v) for v in targets.values()), ZERO) != 100:
        raise ValueError('allocation targets must sum to 100 percent')
    for goal in plan['goals']:
        if not goal.get('name'):
            raise ValueError('goal name required')
        positive(goal['target_amount'])
        positive(goal['saved_amount'])
        if type(goal['months']) is not int or goal['months'] <= 0:
            raise ValueError('goal months must be a positive integer')
    if data['events'] and not opening['confirmed']:
        raise ValueError('confirm opening balance before recording events')
    validate_events(data['events'], assets, accounts, start)


def validate_events(events, assets, accounts, start):
    seen, evidence, replaced = {}, {}, set()
    for event in events:
        for key in ('id', 'evidence', 'note'):
            if not isinstance(event.get(key), str) or not event[key].strip():
                raise ValueError(f'event {key} is required')
        eid = event['id']
        if eid in seen:
            raise ValueError(f'duplicate event id: {eid}')
        if event.get('status') not in ('confirmed', 'pending'):
            raise ValueError('event status must be confirmed/pending')
        if event.get('kind') not in ('income', 'expense', 'transfer', 'trade', 'adjustment', 'settlement'):
            raise ValueError('unsupported event kind')
        occurred, recorded = timestamp(event['occurred_at']), timestamp(event['recorded_at'])
        if occurred <= start or recorded < occurred:
            raise ValueError('event must occur after opening; recorded_at must be >= occurred_at')
        legs = event['legs']
        if not isinstance(legs, list) or not legs:
            raise ValueError('event needs at least one position leg')
        pairs = set()
        for leg in legs:
            pair = (leg['account'], leg['asset'])
            if leg['account'] not in accounts or leg['asset'] not in assets or pair in pairs:
                raise ValueError('unknown or duplicate event position')
            if number(leg['quantity_delta']) == 0:
                raise ValueError('zero position delta')
            pairs.add(pair)
        deltas = [number(leg['quantity_delta']) for leg in legs]
        if event['kind'] in ('trade', 'settlement') and not (any(x > 0 for x in deltas) and any(x < 0 for x in deltas)):
            raise ValueError('trade/settlement needs both outgoing and incoming legs; include cash and fees')
        if event['kind'] == 'transfer':
            if len({leg['asset'] for leg in legs}) != 1 or sum(deltas, ZERO) != 0:
                raise ValueError('transfer must conserve units of one asset; record fees separately')
        if event['kind'] in ('income', 'expense'):
            if any(assets[leg['asset']]['kind'] != 'cash' for leg in legs):
                raise ValueError('income/expense only affects cash; use adjustment for other corrections')
            if any((x <= 0 if event['kind'] == 'income' else x >= 0) for x in deltas):
                raise ValueError('income must increase cash; expense must decrease cash')
        target = event.get('supersedes')
        if target:
            if target not in seen or target in replaced:
                raise ValueError('supersedes must reference an unreplaced earlier record')
            if event['status'] != 'confirmed':
                raise ValueError('only confirmed corrections can supersede a record')
            if timestamp(seen[target]['recorded_at']) > recorded:
                raise ValueError('correction cannot be recorded before its target')
            replaced.add(target)
        previous = evidence.get(event['evidence'])
        if previous and target != previous:
            raise ValueError('duplicate evidence; correct latest event using supersedes')
        evidence[event['evidence']] = eid
        seen[eid] = event


def effective_events(events, at):
    # Corrections restate history using information available in this file.
    # A future occurrence cannot prematurely cancel the old position effect.
    eligible = [e for e in events if timestamp(e['occurred_at']) <= at]
    replaced = {e['supersedes'] for e in eligible if e.get('supersedes') and e['status'] == 'confirmed'}
    return [e for e in eligible if e['status'] == 'confirmed' and e['id'] not in replaced]


def project(data, at=None):
    validate(data)
    now = timestamp(at) if at else datetime.now(timezone.utc)
    p, opening, prices, plan = (data[k] for k in ('profile', 'opening', 'prices', 'plan'))
    if now < timestamp(opening['as_of']):
        raise ValueError('projection predates opening')
    qty = {(r['account'], r['asset']): number(r['quantity']) for r in opening['positions']}
    applied = effective_events(data['events'], now)
    for event in applied:
        for leg in event['legs']:
            pair = (leg['account'], leg['asset'])
            qty[pair] = qty.get(pair, ZERO) + number(leg['quantity_delta'])
    rows, gaps, stale, category = [], [], [], {}
    asset_total, debt_total, reserve = ZERO, ZERO, ZERO
    missing_assets = missing_debt = missing_reserve = False
    for (account, aid), quantity in sorted(qty.items()):
        if quantity < 0:
            raise ValueError(f'negative position {account}/{aid}; incomplete cash leg or unsupported short position')
        if quantity == 0:
            continue
        asset = p['assets'][aid]
        quote, fx = prices['quotes'].get(aid), prices['fx'].get(asset['currency'])
        unit = number(quote['price']) if quote and timestamp(quote['as_of']) <= now else None
        rate = Decimal(1) if asset['currency'] == p['base_currency'] else (
            number(fx['rate']) if fx and timestamp(fx['as_of']) <= now else None)
        value = None if unit is None or rate is None else quantity * unit * rate
        for kind, source in [('quote', quote), ('fx', fx if asset['currency'] != p['base_currency'] else None)]:
            if source and timestamp(source['as_of']) <= now and (now - timestamp(source['as_of'])).days > 7:
                stale.append(f'{aid}:{kind}:{source["as_of"]}')
        debt = asset['kind'] == 'liability'
        emergency_eligible = asset['kind'] == 'cash' and asset['liquid'] and asset['currency'] == p['base_currency']
        if value is None:
            gaps.append(f'{account}/{aid}: missing eligible price or FX')
            missing_debt |= debt
            missing_assets |= not debt
            missing_reserve |= emergency_eligible
        elif debt:
            debt_total += value
        else:
            asset_total += value
            category[asset['category']] = category.get(asset['category'], ZERO) + value
            if emergency_eligible:
                reserve += value
        rows.append(dict(account=account, asset=aid, name=asset['name'], kind=asset['kind'], category=asset['category'],
                         quantity=float(quantity), currency=asset['currency'], value=money(value),
                         price_as_of=quote.get('as_of') if quote else None,
                         price_source=quote.get('source') if quote else None,
                         fx_as_of=fx.get('as_of') if fx and asset['currency'] != p['base_currency'] else None))
    if not opening['confirmed']:
        gaps.append('opening balance has not been confirmed; empty does not mean zero')
        missing_assets = missing_debt = missing_reserve = True
    total = None if missing_assets else asset_total
    debt = None if missing_debt else debt_total
    net = None if total is None or debt is None else total - debt
    income = None if p.get('monthly_income') is None else number(p['monthly_income'])
    expense = None if p.get('monthly_expenses') is None else number(p['monthly_expenses'])
    months = None if p.get('emergency_months') is None else number(p['emergency_months'])
    surplus = None if income is None or expense is None else income - expense
    need = None if expense is None or months is None else expense * months
    allocations = []
    for name in sorted(set(category) | set(plan['targets']) | {r['category'] for r in rows if r['kind'] != 'liability'}):
        actual = category.get(name, ZERO)
        target = plan['targets'].get(name)
        weight = actual / total * 100 if total else None
        allocations.append(dict(category=name, actual=money(actual) if total is not None else None,
                                target_percent=target, actual_percent=money(weight),
                                gap=money(total * number(target) / 100 - actual) if total is not None and target is not None else None))
    goals = [dict(g, monthly_required=money(max(ZERO, number(g['target_amount']) - number(g['saved_amount'])) / g['months'])) for g in plan['goals']]
    required = sum((max(ZERO, number(g['target_amount']) - number(g['saved_amount'])) / g['months'] for g in plan['goals']), ZERO)
    replaced_now = {e['supersedes'] for e in data['events'] if e.get('supersedes') and e['status'] == 'confirmed' and timestamp(e['occurred_at']) <= now}
    revision = hashlib.sha256(json.dumps(data, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    return dict(schema=VERSION, mode=p['mode'], as_of=now.isoformat(), revision=revision,
                base_currency=p['base_currency'], total_assets=money(total), total_liabilities=money(debt), net_worth=money(net),
                known_assets=money(asset_total), positions=rows, gaps=gaps, stale_sources=sorted(set(stale)),
                confirmed_events=len(applied), pending_events=sum(e['status'] == 'pending' and e['id'] not in replaced_now for e in data['events']),
                cashflow=dict(monthly_income=money(income), monthly_expenses=money(expense), monthly_surplus=money(surplus), basis='user_estimate'),
                emergency=dict(available=money(reserve) if not missing_reserve else None, target=money(need),
                               gap=money(max(ZERO, need-reserve)) if need is not None and not missing_reserve else None,
                               months_covered=money(reserve/expense) if expense and not missing_reserve else None),
                plan=dict(status=plan['status'], allocation=allocations, goals=goals, goals_monthly_required=money(required),
                          goal_surplus_after_contributions=money(surplus-required) if surplus is not None else None))


def append_event(root, event, confirmed=False):
    root = Path(root)
    if event.get('status') == 'confirmed' and not confirmed:
        raise ValueError('confirmed records require --confirm after reviewing original evidence')
    with writer_lock(root):
        data = read_inputs(root)
        for existing in data['events']:
            if existing['id'] == event.get('id'):
                if existing == event:
                    return {'appended': False, 'id': existing['id'], 'reason': 'identical event already recorded'}
                raise ValueError('event id conflict; use a new id and supersedes')
        data['events'].append(event)
        validate(data)
        # Validate at every event boundary, including future entries, before appending.
        for when in sorted({e['occurred_at'] for e in data['events']}, key=timestamp):
            project(data, when)
        with (root / 'events.jsonl').open('a', encoding='utf-8') as stream:
            stream.write(json.dumps(event, ensure_ascii=False, allow_nan=False) + '\n')
            stream.flush()
            os.fsync(stream.fileno())
    return {'appended': True, 'id': event['id'], 'status': event['status']}


def scenario(initial, monthly, annual_return, years):
    """Fixed nominal annual rate / 12, end-of-month deposits; no forecast claim."""
    balance, contribution = positive(initial), positive(monthly)
    rate = number(annual_return)
    if rate <= -100 or rate > 100:
        raise ValueError('annual rate must be > -100 and <= 100 percent')
    if type(years) is not int or not 1 <= years <= 80:
        raise ValueError('years must be an integer between 1 and 80')
    rows = []
    for month in range(1, years * 12 + 1):
        balance = balance * (1 + rate / 1200) + contribution
        if month % 12 == 0:
            rows.append(dict(year=month//12, balance=money(balance), contributions=money(number(initial)+contribution*month)))
    return dict(assumptions='Nominal rate / 12; month-end deposits; excludes fees, tax and inflation; scenario, not forecast.',
                annual_return=float(rate), years=rows)


def report(snapshot):
    s = snapshot
    show = lambda v: '未知' if v is None else f'{v:,.2f}'
    text = [f'# Wealth OS · {"虚构演示" if s["mode"] == "demo" else "个人账本"}', '',
            f'截至：{s["as_of"]} | 币种：{s["base_currency"]}', f'账本版本：{s["revision"]}', '',
            f'- 总资产：{show(s["total_assets"])}；负债：{show(s["total_liabilities"])}；净资产：{show(s["net_worth"])}',
            f'- 月结余（用户估计）：{show(s["cashflow"]["monthly_surplus"])}',
            f'- 应急储备缺口：{show(s["emergency"]["gap"])}',
            f'- 目标每月所需投入：{show(s["plan"]["goals_monthly_required"])}',
            f'- 未确认记录：{s["pending_events"]}；缺估值：{len(s["gaps"])}；超过七天的数据源：{len(s["stale_sources"])}', '',
            '## 需要核对', '',
            '价格与汇率的日期、账户余额与原始凭证、月收支口径、目标优先级。空流水不代表确认无交易。',
            '计划金额和配置差额不代表已执行。资产变化不等于投资收益。', '',
            '## 数据缺口', '', *(s['gaps'] or ['无持仓估值缺口；不代表账本已与账户对账。']), '',
            '## 价格时效', '', *(s['stale_sources'] or ['已记录价格未触发七天提示；七天是演示提示阈值，不是交易时效标准。']), '']
    return '\n'.join(text)

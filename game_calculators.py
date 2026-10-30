"""Explicit, deterministic calculations; no hidden live-game rates or guarantees."""

import math
from decimal import Decimal,ROUND_CEILING


def number(value, name, *, minimum=0, maximum=1e15):
    try:
        text=str(value).strip().removesuffix('%')
        result = float(text.replace(',', '.'))
    except (TypeError, ValueError):
        raise ValueError(f'{name} must be a number.') from None
    if not math.isfinite(result) or not minimum <= result <= maximum:
        raise ValueError(f'{name} must be between {minimum:g} and {maximum:g}.')
    return result


def dps(damage, spa, crit=0, multiplier=1.5, towers=1):
    damage, spa = number(damage, 'Damage'), number(spa, 'SPA', minimum=.001)
    crit, multiplier = number(crit, 'Critical chance', maximum=100) / 100, number(multiplier, 'Critical multiplier', minimum=1, maximum=100)
    towers = number(towers, 'Tower count', minimum=1, maximum=100)
    if not towers.is_integer():
        raise ValueError('Tower count must be a whole number.')
    basic = damage / spa
    return {'single': basic, 'expected': basic * (1 + crit * (multiplier - 1)), 'total': basic * (1 + crit * (multiplier - 1)) * towers,
            'assumptions': 'Input damage per attack; constant SPA; expected crit average. DoT, extra hits, resistance and unknown buff stacking are excluded.'}


def chance(percent, attempts, target=95):
    p = number(percent, 'Chance per attempt', maximum=100) / 100
    n = number(attempts, 'Attempts', maximum=1e9)
    target = number(target, 'Target probability', minimum=.000001, maximum=100) / 100
    if not n.is_integer():
        raise ValueError('Attempts must be a whole number.')
    probability = 0 if not p or not n else 1 if p == 1 else -math.expm1(n * math.log1p(-p))
    required = None if not p or target == 1 and p < 1 else 1 if p == 1 else math.ceil(math.log1p(-target) / math.log1p(-p))
    return {'probability_percent': probability * 100, 'attempts_for_target': required, 'assumptions': 'Independent attempts at a constant supplied rate. Pity, changing rates and unknown luck stacking require a different verified model; this is not a guarantee.'}


def budget(resources, price):
    resources, price = number(resources, 'Available resources'), number(price, 'Price per attempt', minimum=.000001)
    funds,unit=Decimal(str(resources)),Decimal(str(price))
    count=int(funds//unit)
    return {'attempts': count, 'spent': float(count*unit), 'remaining': float(funds-count*unit), 'assumptions': 'Uses the supplied constant price; discounts and pity are not inferred.'}


def farm(missing, reward, minutes, success=100):
    missing, reward = number(missing, 'Missing amount'), number(reward, 'Guaranteed reward per completed run', minimum=.000001)
    minutes, success = number(minutes, 'Minutes per attempt', minimum=.001), number(success, 'Completion rate', minimum=.001, maximum=100) / 100
    completed = int((Decimal(str(missing))/Decimal(str(reward))).to_integral_value(rounding=ROUND_CEILING))
    return {'completed_runs': completed, 'expected_attempts': completed / success, 'expected_minutes': completed / success * minutes,
            'assumptions': 'Reward is fixed for each completed run. Completion rate and time are supplied estimates; random item drops need a probability model.'}


def allocate(goals, owned):
    """A shared ingredient is allocated once, in the user's selected goal order."""
    stock = {key: number(value, key) for key, value in owned.items()}
    result = []
    for name, ingredients in goals:
        missing = {}
        for item, amount in ingredients.items():
            amount = number(amount, item)
            take = min(stock.get(item, 0), amount)
            stock[item] = stock.get(item, 0) - take
            if amount > take:
                missing[item] = amount - take
        result.append({'goal': name, 'missing': missing})
    return result

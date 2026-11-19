"""Plain-English wording for the game's effect codes (``PMoreLootAtSea 20`` -> "+20% loot from ships sunk at sea").

The game stores effects as a code and a number. The first letter is the kind of number: P is a percentage, M a flat
amount, B an on/off switch and C a count. ``EFFECTS`` covers the codes used by Special Crew, consumables, sails,
lanterns and figureheads; anything else falls back to the code split into words.
"""
from __future__ import annotations

import re

EFFECTS = {
    # sailing
    'PSpeed': 'Ship speed {s}%', 'MSpeed': 'Ship speed {s} (≈{k} knots)', 'PChangeShipSpeedBonus': 'Acceleration and slowing {s}%',
    'PMobilityBonus': 'Maneuverability {s}%', 'MMobility': 'Maneuverability {s}', 'MMobility0And1': 'Maneuverability {s} at half and full sail',
    'MMobilityWithLowHp': 'Maneuverability {s} when durability is low', 'PDecreaseSpeedLossMarchingMode': 'Speed lost in cruising mode {neg}%',
    'BDisableWindCourseChange': 'The wind no longer pushes the ship off course', 'BIgnoreWind': 'The wind stops affecting the ship\'s movement',
    'POverweightFineReduce': 'Speed penalty for an overloaded hold {neg}%', 'PSailProtection': 'Sail protection {s}%', 'PSailAutoRepairSpeed': 'Sails repair themselves {s}% faster',
    'BCanGoOnly2Speed': 'The ship can only sail at half speed', 'PWindBonus': 'Wind bonus {s}%',
    # gunnery
    'PCannonsReload': 'Gun reload speed {s}%', 'PReloadingAfterSingleShot': 'Reload after a single shot {s}% faster', 'PCannonsReloadWithLowHp': 'Gun reload {s}% faster at low durability',
    'PPlayerSightFocusSpeedAdd': 'Aiming speed {s}%', 'PChangeCBallsSpeed': 'Cannonball flight speed {s}%', 'PCannonBallsSpeed': 'Cannonball flight speed {s}%',
    'PBallDamage': 'Gun damage {s}%', 'PBuckshotDamage': 'Grapeshot damage {s}%', 'MWeaponPenetration': 'Penetration {s}', 'MCannonsDistance': 'Gun range {s}',
    'MCannonsAngleBonus': 'Gun elevation {s}°', 'PReduceCannonsScatter': 'Gun spread {neg}%', 'PReduceCannonsWear': 'Gun wear {neg}%', 'PDamageToBuilds': 'Damage to towers and forts {s}%',
    'PFalkonetReloadBoost': 'Swivel-gun reload {s}%', 'PMortarAimSpeed': 'Mortar aiming {s}% faster', 'PMortarReloadWhenCannonsAreReloaded': 'Mortars reload {s}% faster when the guns finish reloading',
    'PMortarDamageBonus': 'Mortar damage {s}%', 'MMortarMaxDistance': 'Mortar range {s}', 'BCannonBallFosforEffects': 'Cannonballs set phosphorus fires',
    'PCannonBallBombershell': 'Cannonballs explode on impact (area damage)', 'PImproveQuantityOfDropCannons': 'Guns dropped by sunk NPS {s}%',
    # protection and repair
    'MArmor': 'Defense {s}', 'PReduceDamage': 'Damage taken {neg}%', 'PReduceBigFireDamage': 'Large-fire damage {neg}%', 'PBigFireFightingSpeed': 'Large fires are put out {s}% faster',
    'PMicrofireFightingSpeed': 'Minor fires are put out {s}% faster', 'PMendingEffectivity': 'Repair strength {s}%', 'BRepairAllowOnSpeed2': 'Repairs can run at half sail',
    'BHealUnitsWhenMending': 'Repairs also heal wounded crew', 'ServMendingStrength': 'Repairs {v} durability', 'ServMendingStrengthTemporal': 'Adds {v} temporary durability',
    'ServMendingSailes': 'Repairs {v}% of the sails', 'PReduceDamageToNose': 'Damage to the bow {neg}%', 'PReduceDamageToStern': 'Damage to the stern {neg}%',
    'PReduceDamageToSides': 'Damage to the sides {neg}%', 'PLootingShipRepairsHealth': 'Looting a wreck repairs {v}% durability',
    # crew and boarding
    'BBoardingStartsMusketeersDefence': 'Boarding starts with the musketeers already defending', 'BBoardingStartsWithNoTarget': 'Boarding starts with the enemy unable to pick targets',
    'PBoardingHookReload': 'Grappling hooks reload {s}% faster', 'PMoreWeightAtBoarding': 'Extra boarding weight per boarder {s}',
    'BCrewWillntDeadInSea': 'Crew who fall overboard survive', 'PBoardingCrewProtectionCballs': 'Crew losses from cannon fire {neg}%', 'PRestoreUnitsAfterBoarding': '{v}% of boarders lost are restored after a boarding',
    'MMoreExtraCrew': 'Extra crew capacity +{v}', 'PMoreBondmanFromBoarding': 'Captives taken in boarding {s}%', 'PCrewDamage': 'Damage to enemy crew {s}%',
    # supply, loot and specialists
    'BAllowConsumeAnimalsToFood': 'Animals in the hold can be eaten as food', 'PFoodValueBonus': 'Food lasts {s}% longer', 'PFishingProfit': 'Fish caught {s} per sailor',
    'PServer_XpAndRewardBonus': 'XP and rewards {s}%', 'PServXpAndRewardBonus': 'XP and rewards {s}%',
    'CanMakeAnyBurnings': 'Can start fires', 'FireArea': 'Leaves a burning patch on the water', 'ExtraMicroburning': 'Extra small fires on hit',
    'AdditionalDispersion': 'Wider spread', 'CanMakeCannonsDamage': 'Can damage enemy cannons', 'IgnoreSailes': 'Flies through sails without stopping',
    'Overpenetration': 'Can pass through and hit again',
    'MMarchingSpeed': 'Cruising Mode top speed {s}', 'MMarchingSpeedByRotatingMode': 'Cruising Mode speed while turning {s}',
    'MMarchingSpeedByStrongWind': 'Cruising Mode speed in strong wind {s}', 'MMobilityBonus': 'Maneuverability {s}',
    'PForewindFineReduce': 'Headwind speed penalty {neg}%', 'PGreenWindBonus': 'Best-wind (broad reach) bonus {s}%',
    'PMarchingModeChangingSpeed': 'Time to build up Cruising Mode {neg}%', 'PMobilityOnMarchingMode': 'Maneuverability in Cruising Mode {s}%',
    'PFishingSpeed': 'Fishing speed {s} per sailor', 'PXpBonus': 'Captain XP {s}%', 'PXpBonusUpgradesAndBranch': 'Ship and upgrade XP {s}%', 'PVisibilityZone': 'Vision range {s}%',
    'PMinimapLootVisibleDistance': 'Loot shows on the minimap from {s}% further away', 'PLootInteropDistance': 'Loot can be picked up from {s}% further away',
    'PMoreLootAtSea': '+{v}% loot from ships sunk at sea', 'PMoreRareItemsAtSea': '+{v}% chance of rare items from ships sunk at sea',
    'BExtraItemHasNoTimeout': 'The extra consumable slot from sinking ships doesn\'t expire', 'PSpecialUnitImperialUniqueChance': '+{v}% chance to rescue a rare specialist from Imperial ships',
    'PSpecialUnitChanseAtSea': '+{v}% chance to meet a specialist at sea', 'PSpecialUnitGameModeUniqueChance': '+{v}% chance of a rare specialist in game modes',
    'BSpecialUnitEndConflicts': 'Ends conflicts between specialists on board', 'PPowerupItemsReload': 'Consumable cooldowns {s}% faster',
    'PInvisibility': 'Invisible to other ships ({v}% strength)', 'BTruceMode': 'Enemy NPS lose interest in the ship', 'BAvanpostMode': 'Becomes a respawn point for the squadron',
    'PCapacity': 'Hold capacity {s}%',
}


def _num(v):
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return int(f) if f == int(f) else round(f, 2)


def describe(code, value=None):
    """One effect in plain words."""
    code = str(code or '').strip()
    v = _num(value)
    tpl = EFFECTS.get(code)
    if tpl is None and code.startswith('Serv'):
        tpl = EFFECTS.get(code[4:])
    if tpl is None:
        m = re.match(r'([PMBC](?=[A-Z]))?(.+)$', code.replace('Serv', '', 1) if code.startswith('Serv') else code)
        kind, name = (m.group(1) or ''), m.group(2)
        words = re.sub(r'(?<=[a-z])(?=[A-Z0-9])|(?<=[0-9])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])', ' ', name).lower()
        words = words.replace('cballs', 'cannonballs').replace('sailes', 'sails').replace('chanse', 'chance').replace('falkonet', 'swivel gun')
        words = words[:1].upper() + words[1:]
        if kind == 'B' or v is None:
            return words
        return f'{words} {"+" if v > 0 else ""}{v}{"%" if kind == "P" else ""}'
    if v is None:
        v = 1
    s = f'+{v}' if v > 0 else f'{v}'
    neg = f'−{abs(v)}' if v > 0 else f'+{abs(v)}'
    return tpl.format(v=abs(v) if '{v}' in tpl and v < 0 else v, s=s, neg=neg, k=round(v / 2, 2))


def describe_all(text):
    """'PSpeed +4;PCannonsReload 10' (or space-separated pairs) -> list of plain-English lines."""
    out = []
    for m in re.finditer(r'((?:Serv)?[PMBC]?[A-Z][A-Za-z0-9]+)\s*([+-]?\d+(?:\.\d+)?)?', str(text or '')):
        out.append(describe(m.group(1), m.group(2)))
    return out


def describe_pair(types, values=None):
    """'PSpeed PArmor' + '5 5' -> 'Ship speed +5%, Protection +5%'."""
    ts = str(types or '').split()
    vs = str(values if values is not None else '').split()
    if len(ts) <= 1:
        return describe(types, values)
    return ', '.join(describe(t, vs[i] if i < len(vs) else None) for i, t in enumerate(ts))

import re, json, sys
OBF = re.compile(r'E1C60AD3_002D7417_002D4A07_002DAA68_002D58D038854728\.[A-Za-z]+\(\)')
out = {}
for name in ['Halloween', 'NewYear', 'Anniversary', 'Spring']:
    s = OBF.sub('S', open(f'/tmp/game/Common/Common/Game/{name}CalendarEvent.cs').read())
    ev = {'key': name}
    fo = s[s.find('internal void A(PlayerAccount P_0)'):]; fo = fo[:fo.find('[b(1)]')]
    ev['first_open'] = {'designs': [int(x) for x in re.findall(r'DesingElementsAtStorage\[(\d+)\]', fo)],
                        'decor': [int(x) for x in re.findall(r'EnvDecorElementsAtStorage\[(\d+)\]', fo)]}
    rw = s[s.find('internal ComplexBonus A(PlayerAccount P_0, int P_1)'):]; rw = rw[:rw.find('return complexBonus')]
    head = rw[:rw.find('switch')]
    ev['daily'] = {'items': {k: int(v) for k, v in re.findall(r'Items = \{ \[(\d+)\] = (\d+)', head)},
                   'balls': {k: int(v) for k, v in re.findall(r'Balls = \{ \[(\d+)\] = (\d+)', head)}}
    cases = {}
    for m in re.finditer(r'case (\d+):(.*?)break;', rw, re.S):
        body = m.group(2); c = {}
        for a in re.findall(r'Monets = \(Amount: (\d+)', body): c['coins'] = int(a)
        c['designs'] = [int(x) for x in re.findall(r'DesignElements\[(\d+)\]\+\+', body)]
        c['decor'] = [int(x) for x in re.findall(r'EnvDecorElements\[(\d+)\]\+\+', body)]
        for d, mo in re.findall(r'AddPremiumOrMonets\(complexBonus, P_0, (\d+), (\d+)', body): c['premium'] = [int(d), int(mo)]
        c['items'] = {k: int(v) for k, v in re.findall(r'Items\[(\d+)\] \+= (\d+)', body)}
        c['ships'] = [int(x) for x in re.findall(r'Ships?\w*\[(\d+)\]', body)]
        c['achievement'] = re.findall(r'AchievementEnum\.(\w+)', body)
        c['raw'] = ' '.join(body.split())[:300]
        cases[int(m.group(1))] = {k: v for k, v in c.items() if v}
    ev['milestones'] = cases
    cr = s[s.find('public static CalendarEventInfo Create()'):]
    d = re.search(r'StartDate = new DateTime\((\d+), (\d+), (\d+)\)', cr); ev['start'] = f'{d.group(1)}-{int(d.group(2)):02d}-{int(d.group(3)):02d}'
    ev['flags'] = re.findall(r'(\w+) = true', cr[:cr.find('Days = new')])
    m = re.search(r'DiscountAllShips = ([\d.]+)f?', cr); ev['ship_discount'] = float(m.group(1)) if m else 0
    m = re.search(r'ShipId = (\d+)', cr); ev['npc_ship'] = int(m.group(1)) if m else None
    ev['days'] = [' '.join(q.split()) for q in re.findall(r'Quest = QuestPresets\.(\w+\((?:[^()]|\([^()]*\))*\))', cr)]
    m = re.search(r'QuestForAllDays = (.*?);\s*\n', cr, re.S); ev['all_days_quest'] = ' '.join(m.group(1).split())[:400] if m else None
    out[name] = ev
json.dump(out, open(sys.argv[1], 'w'), indent=1)
for k, v in out.items(): print(k, v['start'], v['flags'], v['npc_ship'], v['ship_discount'], len(v['days']), v['milestones'].keys()); print('  ', v['days'][:14]); print('  ', {d: {kk: vv for kk, vv in c.items() if kk != 'raw'} for d, c in v['milestones'].items()})

# golden-fish trader offers: TraderOffer(price, res, gold, monets, designId, cannonId, paidSkipQuest, priceInMonets, premiumDays, allShipsXp, legendaryFlagDays, buyCooldownDays, shipId, oncePerEventId)
NAMES = ['price', 'res', 'gold', 'monets', 'design', 'cannon', 'skip', 'inmonets', 'premium', 'xp', 'flag', 'cooldown', 'ship', 'once']
def split_args(text):
    out, depth, cur = [], 0, ''
    for ch in text:
        if ch in '([{': depth += 1
        if ch in ')]}': depth -= 1
        if ch == ',' and depth == 0: out.append(cur.strip()); cur = ''
        else: cur += ch
    if cur.strip(): out.append(cur.strip())
    return out
for name in ['Halloween', 'NewYear', 'Anniversary', 'Spring']:
    s = OBF.sub('S', open(f'/tmp/game/Common/Common/Game/{name}CalendarEvent.cs').read())
    blk = s[s.find('GoldfishTrader = new List<TraderOffer>'):]
    blk = blk[blk.find('{') + 1:]
    offers = []
    pos = 0
    while True:
        j = blk.find('new TraderOffer(', pos)
        if j < 0 or (blk.find('}', pos) != -1 and blk.find('}', pos) < j and blk[blk.find('}', pos)-1] != ')'):
            break
        k = j + len('new TraderOffer('); depth = 1; e = k
        while depth: 
            if blk[e] == '(': depth += 1
            elif blk[e] == ')': depth -= 1
            e += 1
        args = split_args(blk[k:e - 1]); pos = e
        o = {}
        for idx, a in enumerate(args):
            m = re.match(r'(\w+): (.+)', a)
            key, val = (m.group(1), m.group(2)) if m else (NAMES[idx] if idx < len(NAMES) else f'arg{idx}', a)
            key = {'designId': 'design', 'cannonId': 'cannon', 'paidSkipQuest': 'skip', 'priceInMonets': 'inmonets', 'premiumDays': 'premium', 'allShipsXp': 'xp',
                   'legendaryFlagDays': 'flag', 'buyCooldownDays': 'cooldown', 'shipId': 'ship', 'oncePerEventId': 'once'}.get(key, key)
            if key == 'res':
                r = re.search(r'Resource\((\d+), (\d+)(?:, StorageAssetEnum\.(\w+))?', val)
                if r: o['res'] = [int(r.group(1)), int(r.group(2)), r.group(3) or 'Resource']
                continue
            if val in ('null', 'false', '0', '-1'): continue
            try: o[key] = int(val)
            except ValueError: o[key] = val
        offers.append(o)
    out[name]['trader'] = offers
    print(name, len(offers), offers[:5])
json.dump(out, open(sys.argv[1], 'w'), indent=1)

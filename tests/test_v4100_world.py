from PIL import Image

import site_world
import site_wording


class _DB:
    def __init__(self, rows):
        import sqlite3, json
        self.conn = sqlite3.connect(':memory:')
        self.conn.execute('CREATE TABLE records (dataset TEXT, source_root TEXT, raw_json TEXT)')
        for ds, d in rows:
            self.conn.execute('INSERT INTO records VALUES (?,?,?)', (ds, 'Steam', json.dumps(d)))


def test_shallows_rules_and_lookup():
    im = Image.new('RGB', (100, 100), (0, 0, 0))
    for x in range(50, 60):
        for y in range(20, 30):
            im.putpixel((x, y), (255, 255, 0))              # yellow = rank 4 and smaller
    sh = site_world.Shallows.from_image(im)
    assert sh is not None
    # row follows X, column follows Y: row 25, column 55
    x = (25.5 / 100 - 0.5) * site_world.WORLD_SIZE[0]; y = (55.5 / 100 - 0.5) * site_world.WORLD_SIZE[1]
    assert sh.get(x, y) == 4 and sh.get(0, 0) == 0
    assert sh.around(x + 500, y, 600) == 4
    assert site_world.rank_text(4) == 'rank 4 and smaller ships (ranks 4–7)' and site_world.rank_text(0) == 'any ship'
    assert site_world.Shallows.from_image(Image.new('RGB', (20, 20), (90, 120, 30))) is None     # not a shallows image


def test_routes_classified_like_the_game():
    rows = [('WorldPorts', {'PortName': 'p1', 'EnglishName': 'Alpha', 'Type': 'City', 'LegalFraction': 'KaiAndSeveria', 'ProducedResourceId': 'TCoal', 'Flags': 'UnitsSamurai'}),
            ('WorldPorts', {'PortName': 'p2', 'EnglishName': 'Beta', 'Type': 'City', 'ProducedResourceId': 'TWoodID', 'Flags': ''}),
            ('WorldPorts', {'PortName': 'p3', 'EnglishName': 'Hideout', 'Type': 'PirateBay', 'Flags': ''}),
            ('English_Text', {'Key': 'fraction_KaiAndSeveria', 'English': 'Kai & Severia'})]
    for name, x, y in (('p1', 0, 0), ('p2', 3000, 0), ('p3', 0, 3000)):
        rows.append(('Map_Objects', {'SceneName': 'World', 'Path': 'ports\\port_center_big_1', 'Parameters': name, 'Position0': x, 'Position1': y}))
    rows.append(('Map_Objects', {'SceneName': 'World', 'Path': 'buildings\\factory_iron', 'Position0': 1500, 'Position1': 1500}))
    rows.append(('Map_Objects', {'SceneName': 'World', 'Path': 'special\\towers\\t_mortar2', 'Position0': 100, 'Position1': 50}))
    line = lambda a, b: [f'{a[0] + (b[0] - a[0]) * t / 4} {a[1] + (b[1] - a[1]) * t / 4}' for t in range(5)]
    rows += [('TradingRoutesInfo', {'Value': line((10, 10), (2990, 10))}),          # port to port
             ('TradingRoutesInfo', {'Value': line((10, 10), (10, 2990))}),          # to a pirate bay
             ('TradingRoutesInfo', {'Value': line((10, 10), (1490, 1490))}),        # to an iron mine
             ('TradingRoutesInfo', {'Value': [f'{x} 0' for x in range(0, 7000, 1000)]})]
    w = site_world.load(_DB(rows))
    t = [r['type'] for r in w['routes']]
    assert t == ['Main', 'Smuggling', 'Supply', 'Central']
    assert w['routes'][0]['cargo'] == ['Coal', 'Wood'] and w['routes'][2]['cargo'] == ['Iron Ore']
    alpha = w['ports'][0]
    assert alpha['faction'] == 'Kai & Severia' and alpha['produces'] == 'Coal' and alpha['flags'] == ['UnitsSamurai']
    assert len(site_world.near(w['towers'], 0, 0, 300)) == 1


def test_wording_drops_tooling():
    t = site_wording.clean_html('<p>Rules are read from the game client. In WoSB Workbench run Datamining, then rebuild.</p><script>var client=1</script>')
    assert 'Rules are read from the game.' in t and 'Workbench' not in t and 'var client=1' in t
    assert site_wording.clean_text("The chance isn't in the client.") == "The chance isn't shown by the game."

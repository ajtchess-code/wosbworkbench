"""Build data/forts.json and data/worldfort{n}-coverage.webp from the world fort models (gun mounts = BuildingWeapon hardpoints).
Usage: python scripts/fort_coverage.py <folder with worldfort1.xnb ...> [placements.json]"""
import json, math, sys, tempfile
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / 'engine')]
from engine import xnb_geometry as x
from PIL import Image, ImageDraw

HALF_ARC = 45


def d(a, b):
    return abs((a - b + 180) % 360 - 180)


def fort(path):
    payload = x.unpack_xnb(Path(path).read_bytes(), return_info=True)[0]
    tag = x.parse_model_tag(payload)
    guns = [{'p': [round(v, 2) for v in h['position']], 'f': round(math.degrees(math.atan2(h['forward'][2], h['forward'][0])), 1)}
            for h in tag['hardpoints'] if h['type'] == 'BuildingWeapon']
    obj = Path(tempfile.mkstemp(suffix='.obj')[1]); x.export_obj(payload, obj)
    V, F = [], []
    for line in obj.read_text(errors='replace').splitlines():
        if line.startswith('v '):
            p = line.split(); V.append((float(p[1]), float(p[2]), float(p[3])))
        elif line.startswith('f '):
            F.append([int(t.split('/')[0]) - 1 for t in line.split()[1:]])
    obj.unlink()
    cx = sum(g['p'][0] for g in guns) / len(guns); cz = sum(g['p'][2] for g in guns) / len(guns)
    return guns, (cx, cz), V, F


def draw(guns, centre, V, F, out):
    cx, cz = centre
    reach = max(math.hypot(g['p'][0] - cx, g['p'][2] - cz) for g in guns)
    S = 1000; sc = 260 / reach; R0, R1 = 400, 470
    img = Image.new('RGBA', (S, S), (255, 255, 255, 0)); dr = ImageDraw.Draw(img)
    P = lambda X, Z: (S / 2 + (X - cx) * sc, S / 2 - (Z - cz) * sc)
    for t in range(0, 360, 3):
        n = sum(1 for g in guns if d(g['f'], t + 1.5) < HALF_ARC); k = min(1, n / 12)
        col = (int(60 + 190 * k), int(170 - 120 * k), int(70 - 30 * k), 230)
        a0, a1 = math.radians(t), math.radians(t + 3)
        dr.polygon([(S/2 + R0*math.cos(a0), S/2 - R0*math.sin(a0)), (S/2 + R1*math.cos(a0), S/2 - R1*math.sin(a0)),
                    (S/2 + R1*math.cos(a1), S/2 - R1*math.sin(a1)), (S/2 + R0*math.cos(a1), S/2 - R0*math.sin(a1))], fill=col)
    def ok(f):
        ys = [V[i][1] for i in f]; xs = [V[i][0] for i in f]; zs = [V[i][2] for i in f]
        return (min(ys) > 10 and max(ys) < 60 and max(xs) - min(xs) < 60 and max(zs) - min(zs) < 60
                and math.hypot(sum(xs) / len(xs) - cx, sum(zs) / len(zs) - cz) < reach * 1.35)
    for f in sorted((f for f in F if len(f) >= 3 and ok(f)), key=lambda f: max(V[i][1] for i in f)):
        h = max(V[i][1] for i in f); c = int(min(225, 90 + h * 2.6))
        dr.polygon([P(V[i][0], V[i][2]) for i in f], fill=(c, c - 15, c - 35, 255))
    for g in guns:
        x0, y0 = P(g['p'][0], g['p'][2]); a = math.radians(g['f'])
        dr.line([x0, y0, x0 + 26 * math.cos(a), y0 - 26 * math.sin(a)], fill=(20, 20, 20, 255), width=4)
        dr.ellipse([x0 - 6, y0 - 6, x0 + 6, y0 + 6], fill=(220, 40, 30, 255))
    img.save(out, 'WEBP', quality=88)


def main():
    src = Path(sys.argv[1]); placements = json.loads(Path(sys.argv[2]).read_text()) if len(sys.argv) > 2 else []
    data = {'half_arc': HALF_ARC, 'types': {}, 'placements': placements}
    for f in sorted(src.glob('worldfort[0-9].xnb')):
        n = f.stem[-1]
        guns, centre, V, F = fort(f)
        draw(guns, centre, V, F, ROOT / 'data' / f'worldfort{n}-coverage.webp')
        data['types'][n] = {'guns': guns, 'centre': centre,
                            'sectors': [sum(1 for g in guns if d(g['f'], t) < HALF_ARC) for t in range(0, 360, 30)]}
        print(n, len(guns), data['types'][n]['sectors'])
    (ROOT / 'data' / 'forts.json').write_text(json.dumps(data), encoding='utf-8')


if __name__ == '__main__':
    main()

# かごしま森林管理システム（試作）のデータを作る。
#   python3 tools/build_region.py                        … 目録と国有林を作り直す
#   python3 tools/build_region.py add 46203 鹿屋.geojson … 市町村の地番GeoJSON（G空間情報センター、CRS84）を data/46203/ に取り込む
# 市町村を足すときは、先に munis.json と config.js（munis）へ1件足す。
import json, os, sys, hashlib, re, zipfile, statistics
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
KG = ROOT
A45 = '/mnt/user-data/uploads/A45-24_46_GEOJSON.zip'
# 市町村コード → 名前と、地番データの置き場所（町の版のフォルダがあればそれを使う）
MUNIS = json.load(open(os.path.join(KG, 'munis.json'), encoding='utf-8'))

def dump(obj, path):
    s = json.dumps(obj, ensure_ascii=False, separators=(',', ':'))
    open(path, 'w', encoding='utf-8').write(s)
    return s

def ver(s): return hashlib.sha1(s.encode('utf-8')).hexdigest()[:10]

def coords(g):
    if g['type'] == 'Polygon': return [c for r in g['coordinates'] for c in r]
    if g['type'] == 'MultiPolygon': return [c for p in g['coordinates'] for r in p for c in r]
    return []

def bbox_of(fs):
    xs, ys = [], []
    for f in fs:
        for x, y in coords(f['geometry']): xs.append(x); ys.append(y)
    return [round(min(xs), 6), round(min(ys), 6), round(max(xs), 6), round(max(ys), 6)]

def drop_broken(fs):
    # 座標の壊れた筆（町から50km以上離れた所にあるもの）を取り除く
    cx = statistics.median([coords(f['geometry'])[0][0] for f in fs if coords(f['geometry'])])
    cy = statistics.median([coords(f['geometry'])[0][1] for f in fs if coords(f['geometry'])])
    ok, bad = [], []
    for f in fs:
        cs = coords(f['geometry'])
        if cs and all(abs(x - cx) < 0.5 and abs(y - cy) < 0.5 for x, y in cs): ok.append(f)
        else: bad.append(f)
    return ok, bad

KEEP = ['ID', '大字名', '丁目名', '小字名', '地番', '精度区分', '座標値種別']

def rnd(c):
    if isinstance(c[0], (int, float)): return [round(c[0], 6), round(c[1], 6)]
    return [rnd(x) for x in c]

def add_muni(code, src):
    g = json.load(open(src, encoding='utf-8'))
    fs = [f for f in g['features'] if f.get('geometry') and f['geometry']['type'] in ('Polygon', 'MultiPolygon')]
    fs, bad = drop_broken(fs)
    if bad: print('座標の壊れた筆を除外:', len(bad))
    by = {}
    for f in fs:
        p = f['properties']
        q = {k: p[k] for k in KEEP if p.get(k) not in (None, '')}
        f2 = {'type': 'Feature', 'properties': q, 'geometry': {'type': f['geometry']['type'], 'coordinates': rnd(f['geometry']['coordinates'])}}
        by.setdefault((p.get('大字コード') or '000', p.get('大字名') or '（大字なし）'), []).append(f2)
    out = os.path.join(KG, 'data', code); os.makedirs(out, exist_ok=True)
    for fn in os.listdir(out): os.remove(os.path.join(out, fn))
    for (oc, on), lst in sorted(by.items()):
        dump({'type': 'FeatureCollection', 'features': lst}, os.path.join(out, f'{oc}.geojson'))
        print(code, on, len(lst))
    MUNIS[code]['data'] = f'data/{code}'
    json.dump(MUNIS, open(os.path.join(KG, 'munis.json'), 'w', encoding='utf-8'), ensure_ascii=False, indent=1)

def build_index():
    out = []
    for code, m in MUNIS.items():
        folder = m.get('data')
        if not folder or not os.path.isdir(os.path.join(ROOT, folder)): continue
        for fn in sorted(f for f in os.listdir(os.path.join(ROOT, folder)) if f.endswith('.geojson')):
            p = os.path.join(ROOT, folder, fn); s = open(p, encoding='utf-8').read(); g = json.loads(s)
            if not g['features']: continue
            out.append({'m': code, 'oaza': g['features'][0]['properties'].get('大字名', ''), 'file': f'{code}/{fn}',
                        'count': len(g['features']), 'bbox': bbox_of(g['features']), 'bytes': len(s.encode('utf-8')), 'v': ver(s)})
    json.dump(out, open(os.path.join(KG, 'data', 'index.json'), 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    mb = sum(d['bytes'] for d in out) / 1e6
    print('目録:', len(out), '大字', sum(d['count'] for d in out), '筆', f'{mb:.0f}MB（このリポジトリは1GBまでが目安）')

def build_kokuyu():
    names = {m['name'] for m in MUNIS.values()}
    z = zipfile.ZipFile(A45)
    u = json.load(z.open('A45-24_46_GEOJSON/A45-24_46_SectionofUnit.geojson'))
    rd = json.load(z.open('A45-24_46_GEOJSON/A45-24_46_ForestRoad.geojson'))
    # 町の版で使っている形（n:林小班名 kn:国有林名 tan:担当区 rs:林種 kt:機能類型 ha vol ho:保安林 sp:[樹種,林齢]）にそろえる
    P = lambda p, k: p.get(k)
    units = []
    for f in u['features']:
        p = f['properties']
        if p.get('A45_015') not in names: continue
        age = lambda v: int(v) if str(v or '').isdigit() else v
        sp = [[p.get(a), age(p.get(b))] for a, b in (('A45_016', 'A45_017'), ('A45_018', 'A45_019'), ('A45_020', 'A45_021')) if p.get(a)]
        q = {'n': p.get('A45_011'), 'kn': p.get('A45_013'), 'tan': p.get('A45_014'), 'rs': p.get('A45_023'), 'kt': p.get('A45_024'),
             'ha': p.get('A45_025'), 'vol': p.get('A45_012'), 'ho': p.get('A45_026'), 'sp': sp, 'mn': p.get('A45_015'),
             'of': (p.get('A45_009') + '森林管理署') if p.get('A45_009') else None}
        q = {k: v for k, v in q.items() if v not in (None, '', [])}
        units.append({'type': 'Feature', 'properties': q, 'geometry': {'type': f['geometry']['type'], 'coordinates': rnd(f['geometry']['coordinates'])}})
    bb = bbox_of(units)
    roads = []
    for f in rd['features']:
        cs = f['geometry']['coordinates'] if f['geometry']['type'] == 'LineString' else [c for l in f['geometry']['coordinates'] for c in l]
        if any(bb[0] - .01 <= x <= bb[2] + .01 and bb[1] - .01 <= y <= bb[3] + .01 for x, y in cs):
            roads.append({'type': 'Feature', 'properties': {'name': f['properties'].get('A45_055') or ''}, 'geometry': {'type': f['geometry']['type'], 'coordinates': rnd(f['geometry']['coordinates'])}})
    os.makedirs(os.path.join(KG, 'kokuyu'), exist_ok=True)
    s1 = dump({'type': 'FeatureCollection', 'features': units}, os.path.join(KG, 'kokuyu', 'units.geojson'))
    s2 = dump({'type': 'FeatureCollection', 'features': roads}, os.path.join(KG, 'kokuyu', 'roads.geojson'))
    meta = {'source': '国土交通省 国土数値情報（国有林野データ）A45 令和6年度（林野庁「国有林GISデータ（令和6年度版）」）', 'bbox': bb,
            'units': len(units), 'roads': len(roads), 'ha': round(sum(f['properties'].get('ha') or 0 for f in units), 1), 'v': ver(s1 + s2)}
    json.dump(meta, open(os.path.join(KG, 'kokuyu', 'index.json'), 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    print('国有林:', meta)

if __name__ == '__main__':
    a = sys.argv[1:]
    if a and a[0] == 'add': add_muni(a[1], a[2])
    build_index(); build_kokuyu()

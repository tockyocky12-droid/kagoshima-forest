# かごしま森林管理システム（試作）のデータを作る。
#   python3 tools/build_region.py                        … 目録と国有林を作り直す
#   python3 tools/build_region.py add 46203 鹿屋.geojson [46214 垂水.geojson …] … 市町村の地番GeoJSON（G空間情報センター、CRS84）を data/46203/ に取り込む
# 市町村を足すときは、先に munis.json へ1件足す（config.js の munis は munis.json から自動で作る）。
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

CELL = 0.02  # 大きな市町村は、約2km四方ごとのファイルに分けて、画面に映った所だけ読む

def add_muni(code, src):
    g = json.load(open(src, encoding='utf-8'))
    fs = [f for f in g['features'] if f.get('geometry') and f['geometry']['type'] in ('Polygon', 'MultiPolygon')]
    fs, bad = drop_broken(fs)
    if bad: print('座標の壊れた筆を除外:', len(bad))
    write_cells(code, fs)

def rechunk(code):
    # 大字ごとのファイルで入れた市町村を、約2km四方のファイルに分け直す（地番の中身はそのまま）
    d = os.path.join(KG, 'data', code); fs = []
    for fn in sorted(os.listdir(d)):
        if fn.endswith('.geojson'): fs += json.load(open(os.path.join(d, fn), encoding='utf-8'))['features']
    write_cells(code, fs)

def write_cells(code, fs):
    cells = {}
    for f in fs:
        p = f['properties']
        q = {k: p[k] for k in KEEP if p.get(k) not in (None, '')}
        cs = coords(f['geometry']); cx = sum(c[0] for c in cs) / len(cs); cy = sum(c[1] for c in cs) / len(cs)
        key = (int(cx // CELL), int(cy // CELL))
        cells.setdefault(key, []).append({'type': 'Feature', 'properties': q, 'geometry': {'type': f['geometry']['type'], 'coordinates': rnd(f['geometry']['coordinates'])}})
    out = os.path.join(KG, 'data', code); os.makedirs(out, exist_ok=True)
    for fn in os.listdir(out): os.remove(os.path.join(out, fn))
    names, rows = [], []
    for (ix, iy), lst in sorted(cells.items()):
        fn = f'g{ix}_{iy}.geojson'; i = len(names); names.append(fn)
        dump({'type': 'FeatureCollection', 'features': lst}, os.path.join(out, fn))
        rows += [(f['properties'].get('大字名', ''), f['properties'].get('地番', ''), i) for f in lst]
    # 地番の検索用の一覧。1行が「大字の番号,地番,ファイルの番号」。検索で市全体を読まずに済む
    oz = sorted({r[0] for r in rows}); oi = {o: k for k, o in enumerate(oz)}
    dump({'files': names, 'oaza': oz, 'rows': '\n'.join(f'{oi[o]},{c},{i}' for o, c, i in rows)}, os.path.join(out, 'search.json'))
    print(code, MUNIS[code]['name'], len(fs), '筆', len(names), 'ファイル')
    MUNIS[code]['data'] = f'data/{code}'

def build_index():
    out, search = [], {}
    for code, m in MUNIS.items():
        folder = m.get('data')
        if not folder or not os.path.isdir(os.path.join(ROOT, folder)): continue
        oz = set()
        for fn in sorted(f for f in os.listdir(os.path.join(ROOT, folder)) if f.endswith('.geojson')):
            p = os.path.join(ROOT, folder, fn); s = open(p, encoding='utf-8').read(); g = json.loads(s)
            if not g['features']: continue
            names = [f['properties'].get('大字名', '') for f in g['features']]; oz.update(n for n in names if n)
            top = max(set(names), key=names.count)
            out.append({'m': code, 'oaza': top + (' ほか' if len(set(names)) > 1 else ''), 'file': f'{code}/{fn}',
                        'count': len(g['features']), 'bbox': bbox_of(g['features']), 'bytes': len(s.encode('utf-8')), 'v': ver(s)})
        sp = os.path.join(ROOT, folder, 'search.json')
        if os.path.exists(sp): search[code] = {'file': f'{code}/search.json', 'v': ver(open(sp, encoding='utf-8').read())}
        m['oaza'] = sorted(oz)
    idx = {'districts': out, 'search': search}
    json.dump(idx, open(os.path.join(KG, 'data', 'index.json'), 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    mb = sum(d['bytes'] for d in out) / 1e6
    print('目録:', len(out), 'ファイル', sum(d['count'] for d in out), '筆', f'{mb:.0f}MB（このリポジトリは1GBまでが目安）')
    json.dump(MUNIS, open(os.path.join(KG, 'munis.json'), 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    # config.js の munis を munis.json から作り直す（地番データの置き場所は書かない）
    cp = os.path.join(KG, 'config.js'); c = open(cp, encoding='utf-8').read()
    cfg = {k: {kk: vv for kk, vv in v.items() if kk != 'data'} for k, v in MUNIS.items() if v.get('data')}
    i = c.index('  munis:'); j = c.rindex('\n};')
    c = c[:i] + '  munis:' + json.dumps(cfg, ensure_ascii=False, separators=(',', ':')) + c[j:]
    open(cp, 'w', encoding='utf-8').write(c)

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
    kd = os.path.join(KG, 'kokuyu'); os.makedirs(kd, exist_ok=True)
    for fn in os.listdir(kd):
        if fn.endswith('.geojson'): os.remove(os.path.join(kd, fn))
    # 約5km四方ごとのファイルに分け、画面に映った所だけ読む（通信量を減らす）
    KC = 0.05; cells = {}
    for f in units:
        cs = coords(f['geometry']); cx = sum(c[0] for c in cs) / len(cs); cy = sum(c[1] for c in cs) / len(cs)
        cells.setdefault((int(cx // KC), int(cy // KC)), []).append(f)
    parts = []
    for (ix, iy), lst in sorted(cells.items()):
        fn = f'u{ix}_{iy}.geojson'; t = dump({'type': 'FeatureCollection', 'features': lst}, os.path.join(kd, fn))
        parts.append({'file': fn, 'bbox': bbox_of(lst), 'count': len(lst), 'v': ver(t)})
    s2 = dump({'type': 'FeatureCollection', 'features': roads}, os.path.join(kd, 'roads.geojson'))
    meta = {'source': '国土交通省 国土数値情報（国有林野データ）A45 令和6年度（林野庁「国有林GISデータ（令和6年度版）」）', 'bbox': bb,
            'units': len(units), 'roads': len(roads), 'ha': round(sum(f['properties'].get('ha') or 0 for f in units), 1),
            'v': ver(''.join(p['v'] for p in parts) + s2), 'rv': ver(s2), 'parts': parts}
    json.dump(meta, open(os.path.join(KG, 'kokuyu', 'index.json'), 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    print('国有林:', meta['units'], '小班', len(parts), 'ファイル')

if __name__ == '__main__':
    a = sys.argv[1:]
    if a and a[0] == 'rechunk':
        for code in a[1:]: rechunk(code)
    if a and a[0] == 'add':
        for code, src in zip(a[1::2], a[2::2]): add_muni(code, src)
    build_index(); build_kokuyu()

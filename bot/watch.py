"""賃貸の新着チェック。

SUUMO / LIFULL HOME'S / CHINTAI / at home を検索し、条件に合う新着の部屋を
LINE に送る（line.json があるとき）。条件に合う今の掲載の一覧は「メモ」の「賃貸」フォルダに書く（iCloud で iPhone に届く）。
  python watch.py              新着を探して通知し、一覧を書き直す（0・9・12・15・18・21時ごろに GitHub Actions から実行）
  python watch.py --init       今の掲載をすべて既知として記録する（通知しない）
  python watch.py --dry-run    通知せずに新着を画面に出す
  python watch.py --list       通知せずに一覧だけ書き直す
  python watch.py --test-line  LINE にテストを送る
  python watch.py --site       保存済みの list.json から一覧ページだけ作り直して公開する
"""
import json, os, re, subprocess, sys, threading, time, unicodedata, datetime, html, urllib.request
from bs4 import BeautifulSoup

HERE = os.path.dirname(os.path.abspath(__file__))
CLOUD = bool(os.environ.get('GITHUB_ACTIONS'))   # GitHub Actions で動いているとき（リポジトリの bot/ にある）
SEEN = os.path.join(HERE, 'seen.json')
VERDICTS = os.path.join(HERE, 'verdicts.json')   # 詳細ページまで見た判定の記録 {key: [残すか, 補足]}
LINE_CFG = os.path.join(HERE, 'line.json')        # {"token": ..., "user_id": ...}。line_setup.sh で作る
LOG = os.path.join(HERE, 'log.txt')
SITE = os.path.dirname(HERE) if CLOUD else os.path.join(HERE, 'site')   # 一覧ページを置く場所（リポジトリの直下）
GH = 'gh' if CLOUD else os.path.join(HERE, 'tools', 'gh')
REPO = 'nohashi325-commits/rental-list'   # 一覧ページの「いらない」は、このリポジトリに Issue として届く
NOTE_FOLDER, NOTE_TITLE = '賃貸', '賃貸の物件一覧'
NEW_DAYS = 7          # 一覧で🆕を付ける日数
LIST_URL = 'https://nohashi325-commits.github.io/rental-list/'   # LINE で知らせる一覧ページ（GitHub Pages）
UA = 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36'

RENT_MAX = 22.0       # 万円（管理費を含まない）
AREA_MIN = 45.0       # ㎡
REFORM_AGE = 30       # 築この年数以上はリフォーム・リノベの記載がある部屋だけ残す
OLD_AGE = 47          # 築この年数以上は旧耐震として詳細を見ずに除外

WARDS = {'品川区': ('shinagawa', 13109), '目黒区': ('meguro', 13110), '渋谷区': ('shibuya', 13113), '港区': ('minato', 13103),
         '新宿区': ('shinjuku', 13104), '千代田区': ('chiyoda', 13101), '中央区': ('chuo', 13102), '世田谷区': ('setagaya', 13112),
         '文京区': ('bunkyo', 13105), '江東区': ('koto', 13108)}
PRIORITY = ['品川区', '目黒区', '渋谷区', '港区']
TOWNS = {
    '港区': '愛宕 港南 芝公園 赤坂 南麻布 麻布永坂町 海岸 高輪 芝大門 台場 白金 麻布十番 元赤坂 三田 新橋 東新橋 白金台 麻布台 元麻布 芝 西新橋 東麻布 浜松町 麻布狸穴町 虎ノ門 芝浦 西麻布 南青山 北青山 六本木',
    '渋谷区': '宇田川町 恵比寿南 初台 神泉町 代々木 南平台町 円山町 元代々木町 松濤 神南 代々木神園町 幡ケ谷 猿楽町 広尾 上原 西原 大山町 鉢山町 鶯谷町 桜丘町 神宮前 千駄ケ谷 東 富ケ谷 恵比寿 渋谷 神山町 代官山町 道玄坂 本町 恵比寿西',
    '新宿区': '愛住町 細工町 市谷長延寺町 新小川町 筑土八幡町 納戸町 榎町 四谷坂町 市谷田町 神楽河岸 中町 白銀町 横寺町 三栄町 市谷八幡町 神楽坂 中里町 百人町 下宮比町 四谷 市谷本村町 須賀町 津久戸町 富久町 歌舞伎町 市谷加賀町 市谷薬王寺町 西新宿 天神町 払方町 河田町 市谷甲良町 市谷柳町 赤城下町 東榎町 片町 霞ケ丘町 市谷左内町 若宮町 赤城元町 東五軒町 弁天町 岩戸町 市谷砂土原町 若松町 早稲田町 内藤町 北山伏町 喜久井町 市谷山伏町 若葉 早稲田南町 南榎町 北町 原町 市谷船河原町 舟町 袋町 南元町 本塩町 戸山 市谷台町 住吉町 大久保 南山伏町 矢来町 荒木町 市谷鷹匠町 信濃町 大京町 南町 余丁町 左門町 市谷仲之町 新宿 箪笥町 二十騎町 揚場町',
    '千代田区': '一ツ橋 紀尾井町 三崎町 神田小川町 鍛冶町 飯田橋 一番町 九段南 三番町 神田神保町 内幸町 富士見 永田町 九段北 四番町 神田美土代町 内神田 平河町 猿楽町 五番町 神田錦町 西神田 二番町 北の丸公園 霞が関 皇居外苑 神田司町 千代田 日比谷公園 有楽町 丸の内 麹町 神田駿河台 大手町 隼町 六番町',
    '中央区': '京橋 新川 佃 日本橋室町 八重洲 豊海町 銀座 新富 日本橋 日本橋本石町 八丁堀 湊 月島 晴海 日本橋兜町 入船 浜離宮庭園 明石町 勝どき 築地 日本橋茅場町',
    '品川区': '荏原 小山 西五反田 大崎 東品川 平塚 戸越 小山台 西品川 東五反田 南品川 北品川 広町 上大崎',
    '目黒区': '下目黒 上目黒 鷹番 中町 東山 目黒本町 駒場 青葉台 中央町 中目黒 目黒 祐天寺 五本木 大橋 三田',
    '世田谷区': '下馬 三宿 太子堂 代沢 池尻 北沢',
    '文京区': '後楽',
    '江東区': '豊洲',
}
TOWNS = {w: set(v.split()) for w, v in TOWNS.items()}


def T(el):
    if el is None:
        return ''
    s = el if isinstance(el, str) else el.get_text(' ')
    return re.sub(r'\s+', ' ', s).strip()


def norm(s):
    return unicodedata.normalize('NFKC', s or '').replace('ヶ', 'ケ').replace('ヵ', 'ケ').strip()


def log(msg):
    line = '%s %s' % (datetime.datetime.now().strftime('%Y-%m-%d %H:%M'), msg)
    print(line, flush=True)
    with open(LOG, 'a', encoding='utf-8') as f:
        f.write(line + '\n')


def get(url):
    r = subprocess.run(['curl', '-sL', '-m', '40', '-A', UA, '-H', 'Accept-Language: ja', url], capture_output=True)
    return BeautifulSoup(r.stdout.decode('utf-8', 'replace'), 'html.parser') if r.stdout else None


# ---- 一覧ページの読み取り ----

def p_suumo(doc):
    out = []
    for p in doc.select('.js-property'):
        a = p.select_one('.js-cassetLinkHref')
        for d in p.select('.detailbox'):
            c = d.select('.detailbox-property-col')
            if len(c) < 5:
                continue
            c1 = c[0].find_all('div', recursive=False)
            c3 = c[2].find_all('div', recursive=False)
            c4 = c[3].find_all('div', recursive=False)
            n = d.select('.detailnote-box')
            out.append(dict(name=T(a), url='https://suumo.jp' + a['href'] if a else '',
                            rent=T(c[0].select_one('.detailbox-property-point')), fee=T(c1[1]) if len(c1) > 1 else '',
                            teiki='定期借家' in T(c[0]), layout=T(c3[0]) if c3 else '', area=T(c3[1]) if len(c3) > 1 else '',
                            age=T(c4[1]) if len(c4) > 1 else '', addr=T(c[4]),
                            st=[T(x) for x in n[0].find_all('div', recursive=False)] if n else []))
    return out


def p_homes(doc):
    out = []
    for b in doc.select('.moduleInner.prg-building'):
        spec = {T(tr.find('th')): tr.find('td') for tr in b.select('.bukkenSpec tr') if tr.find('th')}
        st = [T(x) for x in spec['交通'].select('.prg-stationText')] if spec.get('交通') else []
        cur = None
        for tr in b.select('tr.prg-roomRow'):
            if 'prg-roomInfo' in tr.get('class', []):
                pr = tr.select_one('td.price')
                ly = tr.select_one('td.layout')
                pt = pr.get_text('|', strip=True) if pr else ''
                lp = ly.get_text('|', strip=True).split('|') if ly else []
                a = tr.select_one('a.prg-detailAnchor')
                fee = re.search(r'万円\s*\|?/?\s*\|?([\d,]+円|-)', pt)
                cur = dict(name=T(b.select_one('.bukkenName')), addr=T(spec.get('所在地')), age=T(spec.get('築年数/階数')), st=st,
                           rent=(T(pr.select_one('.priceLabel')) if pr else '').replace(' ', ''), fee=fee.group(1) if fee else '',
                           layout=lp[0] if lp else '', area=lp[1] if len(lp) > 1 else '', teiki='定期借家' in T(tr),
                           url=a['href'].split('?')[0] if a else '')
                out.append(cur)
            elif cur is not None and '定期借家' in T(tr):
                cur['teiki'] = True
    return out


def p_chintai(doc):
    out = []
    for b in doc.select('section.cassette_item.build'):
        h = b.find('h2')
        ty = T(h.find('span')) if h and h.find('span') else ''
        cells = {T(th): th.find_next_sibling('td') for th in b.select('.bukken_information th')}
        ad = cells.get('住所')
        st = [T(x) for x in cells['交通'].select('li')] if cells.get('交通') else []
        for tb in b.select('tbody.js-detailLinkUrl'):
            tr = tb.select_one('tr.detail-inner')
            if not tr:
                continue
            pr = tr.select_one('td.price')
            parts = pr.get_text('|', strip=True).split('|') if pr else []
            ly = next((td for td in tr.find_all('td') if 'm²' in T(td)), None)
            lp = ly.get_text('|', strip=True).split('|') if ly else []
            out.append(dict(name=T(h).replace(ty, '', 1).strip() if h else '', addr=T(ad.contents[0]) if ad and ad.contents else '',
                            age=T(cells.get('築年')), st=st, rent=T(pr.select_one('.num')) + '万円' if pr else '',
                            fee=parts[-1] if len(parts) > 1 and '円' in parts[-1] else '-',
                            layout=lp[0] if lp else '', area=lp[1] if len(lp) > 1 else '', teiki='定期借家' in T(tb),
                            url='https://www.chintai.net' + tb.get('data-detailurl', '')))
    return out


def p_athome(doc):
    out = []
    for c in doc.select('.property-card'):
        ty = T(c.select_one('.info-item--type'))
        for r in c.select('.room-info-section'):
            a = r.select_one('a[href^="/chintai/"]')
            pr = r.select_one('.price')
            pa = pr.find_all(class_='room-info-item__text', recursive=False) if pr else []
            ly = r.select('.layout-size .room-info-item__text')
            out.append(dict(name=re.sub(r'\s*\d+階建$', '', T(c.select_one('.property-title'))), addr=T(c.select_one('.info-item--location')),
                            st=[T(x) for x in c.select('.info-item--station p')], age=ty,
                            rent=T(pr.select_one('.rent-value')) + '万円' if pr else '', fee=T(pa[1]) if len(pa) > 1 else '',
                            layout=T(ly[0]) if ly else '', area=T(ly[1]) if len(ly) > 1 else '', teiki=False,
                            url='https://www.athome.co.jp' + a['href'].split('?')[0] if a else ''))
    return out


def u_suumo(s, cd, p):
    return ('https://suumo.jp/jj/chintai/ichiran/FR301FC005/?ar=030&bs=040&ta=13&sc=%d&cb=0.0&ct=22.0&mb=45&mt=9999999'
            '&md=07&md=08&md=09&md=10&md=11&md=12&md=13&md=14&et=9999999&cn=9999999&shkr1=03&shkr2=03&shkr3=03&shkr4=03&sngz=&po1=25&pc=100&page=%d' % (cd, p))


def u_homes(s, cd, p):
    q = 'cond%5Bmonthmoneyroomh%5D=22&cond%5Bhousearea%5D=45' + ''.join('&cond%%5Bmadori%%5D%%5B%s%%5D=%s' % (m, m) for m in ['25', '32', '33', '35', '42', '43', '45-'])
    return 'https://www.homes.co.jp/chintai/tokyo/%s-city/list/?%s&page=%d' % (s, q, p)


def u_chintai(s, cd, p):
    return 'https://www.chintai.net/tokyo/area/%d/list/%s?ct=250&sf=45&m=6&m=7&m=8&m=9&m=A&m=B&m=C&m=D&m=E&n=B' % (cd, 'page%d/' % p if p > 1 else '')


def u_athome(s, cd, p):
    q = 'pref=13&cities=%s&cityCds=%d&basic=kc001,kc153,ki001,km010,km013,km014,km015,km019,km021,kt007,ke001,kn001,kj001&kod=&q=1&sort=95&limit=30' % (s, cd)
    return 'https://www.athome.co.jp/chintai/tokyo/%s-city/list/%s?%s' % (s, 'page%d/' % p if p > 1 else '', q)


# サイトごとの (URL, 読み取り, アクセス間隔秒)。HOME'S と at home は間隔を空けないと止められる。
SITES = {'SUUMO': (u_suumo, p_suumo, 2), "HOME'S": (u_homes, p_homes, 15), 'CHINTAI': (u_chintai, p_chintai, 2), 'at home': (u_athome, p_athome, 15)}


def crawl(site, rows, status):
    uf, pf, gap = SITES[site]
    empty = 0
    for w, (s, cd) in WARDS.items():
        seen, p = set(), 1
        while p <= 60:
            d = get(uf(s, cd, p))
            items = [] if d is None else [x for x in pf(d) if x['url'] and x['url'] not in seen]
            if not items and p == 1 and w in PRIORITY:
                empty += 1   # 優先4区はどのサイトにも普段は掲載があるので、0件はアクセス制限の可能性が高い
            for x in items:
                seen.add(x['url'])
                x['ward'], x['src'] = w, site
            rows.extend(items)
            if not items:
                break
            p += 1
            time.sleep(gap)
        time.sleep(gap)
    status[site] = 'ok' if empty < 2 else '一部取得できず'


# ---- 条件の判定 ----

def split_addr(addr, ward):
    a = re.sub(r'^東京都', '', norm(addr))
    a = a.split(ward, 1)[1].strip() if ward in a else a
    m = re.match(r'^(.*?)([一二三四五六七八九])丁目', a)
    if m:
        return m.group(1), str('一二三四五六七八九'.index(m.group(2)) + 1)
    m = re.match(r'^([^\d-]*)(\d+)?', a)
    return m.group(1).strip(), m.group(2) or ''


def man(s):
    m = re.search(r'([\d.]+)\s*万', norm(s))
    return float(m.group(1)) if m else None


def yen(s):
    s = norm(s).replace(',', '')
    m = re.search(r'(\d+)\s*円', s)
    return int(m.group(1)) if m and '万' not in s.split('円')[0] else 0


def layout_ok(l):
    m = re.match(r'^(\d+)([A-Z]*)$', l)
    return bool(m) and (int(m.group(1)) >= 3 or (m.group(1) == '2' and 'L' in m.group(2)))


def age_of(s):
    s = norm(s)
    if '新築' in s:
        return 0
    m = re.search(r'築\s*(\d+)\s*年', s) or re.search(r'^(\d+)\s*年', s)
    if m:
        return int(m.group(1))
    y = re.search(r'((?:19|20)\d\d)年', s)
    return max(0, datetime.date.today().year - int(y.group(1))) if y else None


def walk(st):
    v = [int(m.group(1)) for x in st for m in [re.search(r'(?:歩|徒歩)\s*(\d+)\s*分', norm(x))] if m and 'バス' not in x]
    return min(v) if v else None


POS = re.compile(r'リフォーム済|リノベーション済|リノベ済|後渡|リフォーム[：:]|リフォーム中|リフォーム予定|リフォーム履歴|リノベーション履歴|\d{4}年.{0,12}(?:リフォーム|リノベ)|[、,]\s*リノベーション|内装リフォーム|リフォームで|フルリノベ')
NEG = re.compile(r'マンション オーナー|相談可|当社に|お任せ|売買|建築|店舗|会社|一戸建て|リフォーム対応|お願いできますか|暮らしたい')


def detail(url):
    """詳細ページから竣工年月とリフォーム・リノベの記載を読む。読めなければ ym=None。"""
    d = get(url)
    if d is None:
        return None, ''
    for t in d(['script', 'style', 'noscript', 'header', 'footer', 'nav']):
        t.decompose()
    t = re.sub(r'\s+', ' ', d.get_text(' '))
    m = re.search(r'築年月?\s*[:：]?\s*(\d{4})年\s*(\d{1,2})月', t)
    rf = ''
    for h in re.finditer(r'.{0,30}(?:リフォーム|リノベ).{0,40}', t):
        s = h.group(0)
        if POS.search(s) and not NEG.search(s):
            p = POS.search(s)
            a = max([s.rfind(c, 0, p.start() + 1) for c in '、,/／。 '] + [-1]) + 1
            b = [i for i in (s.find(c, p.end()) for c in '、。／') if i > 0]
            rf = re.split(r' (?:契約|周辺|物件|入居|取引)', s[a:min(b) if b else None])[0].strip(' 、,/／')[:50]
            break
    return ((int(m.group(1)), int(m.group(2))) if m else None), rf


def qualify(rows):
    groups = {}
    for r in rows:
        if r['teiki']:
            continue
        town, chome = split_addr(r['addr'], r['ward'])
        rent = man(r['rent'])
        am = re.search(r'([\d.]+)', norm(r['area']))
        area = float(am.group(1)) if am else None
        layout = norm(r['layout']).upper().replace(' ', '')
        if town not in TOWNS[r['ward']] or rent is None or rent > RENT_MAX or area is None or area < AREA_MIN or not layout_ok(layout):
            continue
        key = '|'.join([r['ward'], town, chome, str(rent), '%.1f' % area, layout])
        g = groups.setdefault(key, dict(key=key, ward=r['ward'], town=town, chome=chome, rent=rent, fee=0, area=area, layout=layout,
                                        names=[], ages=[], walks=[], st=[], links={}))
        g['fee'] = max(g['fee'], yen(r['fee']))
        g['names'].append(norm(r['name']))
        a = age_of(r['age'])
        if a is not None:
            g['ages'].append(a)
        w = walk(r['st'])
        if w is not None:
            g['walks'].append(w)
        g['st'] = g['st'] or [norm(x) for x in r['st'][:1]]
        g['links'].setdefault(r['src'], []).append(r['url'])
    return groups


def judge(g):
    """新耐震かつ、築30年以上ならリフォーム記載ありの部屋だけ残す。(残すか, 補足)"""
    age = min(g['ages']) if g['ages'] else None
    if age is not None and age >= OLD_AGE:
        return False, ''
    if age is not None and age < REFORM_AGE:
        return True, ''
    yms, rf = [], ''
    # 1サイト2件まで詳細を読む。SUUMO と CHINTAI を先に読む（HOME'S と at home は止められやすい）
    for src in ['SUUMO', 'CHINTAI', "HOME'S", 'at home']:
        for u in g['links'].get(src, [])[:2]:
            ym, r = detail(u)
            if ym:
                yms.append(ym)
            rf = rf or r
            time.sleep(3)
    ym = min(yms) if yms else None
    if ym and ym < (1981, 6):
        return False, ''
    if not rf:
        return False, ''
    note = '%d年%d月築' % ym if ym else '築年月未確認'
    if ym and ym < (1983, 4):
        note += '・耐震要確認'
    return True, note + '・改装: ' + rf


# ---- 通知 ----

def line(text, everyone=True):
    """LINE の Messaging API で送る。everyone なら友だち全員に（broadcast）、でなければ自分だけに。
    line.json がなければ何もしない。無料プランの月200通は「通数 × 届く人数」で数える。"""
    if os.environ.get('LINE_TOKEN'):   # GitHub Actions ではリポジトリの Secrets から渡す
        cfg = {'token': os.environ['LINE_TOKEN'], 'user_id': os.environ.get('LINE_USER_ID', '')}
    elif os.path.exists(LINE_CFG):
        cfg = json.load(open(LINE_CFG, encoding='utf-8'))
    else:
        return None
    msg = {'messages': [{'type': 'text', 'text': text[:5000]}]}
    if not everyone:
        msg['to'] = cfg['user_id']
    body = json.dumps(msg).encode()
    req = urllib.request.Request('https://api.line.me/v2/bot/message/' + ('broadcast' if everyone else 'push'), data=body,
                                 headers={'Content-Type': 'application/json', 'Authorization': 'Bearer ' + cfg['token']})
    try:
        urllib.request.urlopen(req, timeout=30).read()
        return True
    except Exception as e:
        detail = e.read().decode('utf-8', 'replace')[:200] if hasattr(e, 'read') else ''
        log('LINE 送信失敗: %s %s' % (e, detail))
        return False


def line_hits(hits, failed):
    """1日1通にまとめる（無料プランは月200通まで）。長すぎる分は一覧のメモを見てもらう。"""
    head = '賃貸の新着 %d件（%s）' % (len(hits), datetime.datetime.now().strftime('%-m/%-d %-H時'))
    parts, rest = [head], 0
    for i, (g, n) in enumerate(hits):
        s = fmt(g, n)
        if len('\n\n'.join(parts + [s])) > 4700:
            rest = len(hits) - i
            break
        parts.append(s)
    if rest:
        parts.append('ほか%d件は、メモの「%s」か下の一覧で見てください' % (rest, NOTE_TITLE))
    if failed:
        parts.append('※%sは一部取得できず' % '・'.join(failed))
    parts.append('一覧: ' + LIST_URL)
    return '\n\n'.join(parts)


def dump_list(items, seen):
    """一覧を list.json にも書く（一覧ページを作り直すとき用）。d は最初に見つけた日。"""
    out = []
    for g, n in items:
        m = re.match(r'(\d{4})年(\d{1,2})月築', n or '')
        rf = n.split('改装: ', 1)[1] if '改装: ' in (n or '') else ''
        out.append(dict(w=g['ward'], t=g['town'], c=g['chome'], n=next((x for x in g['names'] if x and '駅' not in x and '階建' not in x), ''),
                        r=g['rent'], f=g['fee'], a=g['area'], l=g['layout'], ag=min(g['ages']) if g['ages'] else 0,
                        wk=min(g['walks']) if g['walks'] else None, s=g['st'], ty='', fl='', sk='-', rk='-',
                        ln={k: v[0] for k, v in g['links'].items()}, p=int(g['ward'] in PRIORITY),
                        m=int((g['ward'], g['town']) in {('目黒区', '五本木'), ('世田谷区', '下馬')}),
                        ym='%s年%s月' % m.groups() if m else '', gr=int(bool(m) and (int(m.group(1)), int(m.group(2))) < (1983, 4)), rf=rf, k=g['key'],
                        d=seen.get(g['key'], datetime.date.today().isoformat())))
    json.dump(out, open(os.path.join(HERE, 'list.json'), 'w', encoding='utf-8'), ensure_ascii=False)
    return out


def exclusions():
    """一覧ページの「いらない」「戻す」で作られた Issue（自分が作ったものだけ）から、外した部屋の key を求める。
    読めたら届いた Issue は閉じる。読めなければ None。"""
    if not (CLOUD or os.path.exists(GH)):
        return None
    r = subprocess.run([GH, 'api', '--paginate', 'repos/%s/issues?state=all&creator=%s&per_page=100' % (REPO, REPO.split('/')[0])],
                       capture_output=True, text=True)
    if r.returncode != 0:
        log('除外リストの取得失敗: ' + r.stderr.strip()[-200:])
        return None
    issues = sorted(json.loads(r.stdout.replace('][', ',')), key=lambda i: i['number'])
    ex = set()
    for i in issues:
        m = re.search(r'^key: (.+)$', i.get('body') or '', re.M)
        if not m:
            continue
        if i['title'].startswith('いらない'):
            ex.add(m.group(1).strip())
        elif i['title'].startswith('戻す'):
            ex.discard(m.group(1).strip())
        if i['state'] == 'open':
            subprocess.run([GH, 'issue', 'close', str(i['number']), '-R', REPO, '-c', '反映しました'], capture_output=True)
    return ex


def publish_site(items_json, excl=None):
    """一覧ページを作って GitHub Pages に push する。site/ が無ければ何もしない。"""
    if not (CLOUD or os.path.isdir(os.path.join(SITE, '.git'))):
        return None
    t = open(os.path.join(HERE, 'page_template.html'), encoding='utf-8').read()
    now = datetime.datetime.now()
    page = ('<!DOCTYPE html><html lang="ja"><head><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width,initial-scale=1"><meta name="robots" content="noindex,nofollow">'
            + t.replace('__DATA__', json.dumps(items_json, ensure_ascii=False, separators=(',', ':')))
               .replace('__TOTAL__', str(len(items_json))).replace('__REPO__', REPO)
               .replace('__EXCL__', json.dumps(sorted(excl or []), ensure_ascii=False)).replace('__DATE__', '%d年%d月%d日 %d:%02d' % (now.year, now.month, now.day, now.hour, now.minute))
            + '</html>')
    open(os.path.join(SITE, 'index.html'), 'w', encoding='utf-8').write(page)
    open(os.path.join(SITE, 'robots.txt'), 'w').write('User-agent: *\nDisallow: /\n')
    if CLOUD:
        return True   # commit・公開はワークフローが行う
    g = lambda *a: subprocess.run(['git', '-C', SITE] + list(a), capture_output=True, text=True)
    g('add', '-A')
    if g('diff', '--cached', '--quiet').returncode == 0:
        return True
    g('commit', '-m', now.strftime('%Y-%m-%d %H:%M 更新'))
    r = g('push', 'origin', 'HEAD')
    if r.returncode != 0:
        log('一覧ページの公開失敗: ' + r.stderr.strip()[-300:])
    return r.returncode == 0


def write_note(items, seen):
    """条件に合う今の掲載を、メモの1つのノートに区ごとに書き直す。Mac 以外では何もしない。"""
    if sys.platform != 'darwin':
        return None
    days = sorted(set(seen.values()))
    base = days[0] if days else ''   # 最初に記録した日の掲載は新着として扱わない
    since = (datetime.date.today() - datetime.timedelta(days=NEW_DAYS)).isoformat()
    isnew = lambda g: seen.get(g['key'], '') > base and seen.get(g['key'], '') >= since
    order = PRIORITY + [w for w in WARDS if w not in PRIORITY]
    items = sorted(items, key=lambda x: (order.index(x[0]['ward']), x[0]['rent'] + x[0]['fee'] / 10000))
    E = html.escape

    def entry(g, n):
        title, _, rest = fmt(g, n).partition('\n')
        lines = rest.split('\n')[:-1]   # 最後の行の URL は下のリンクに置き換える
        links = ' ・ '.join('<a href="%s">%s</a>' % (E(u[0]), E(s)) for s, u in g['links'].items())
        return '<div><b>%s%s</b></div>%s<div>%s</div><div><br></div>' % (
            '🆕 ' if isnew(g) else '', E(title), ''.join('<div>%s</div>' % E(x) for x in lines), links)

    new = [x for x in items if isnew(x[0])]
    out = ['<h1>%s</h1>' % NOTE_TITLE,
           '<div>%s更新 ・ %d件（🆕 %d日以内の新着 %d件）</div>' % (datetime.datetime.now().strftime('%-m/%-d %H:%M'), len(items), NEW_DAYS, len(new)),
           '<div>2LDK以上・%d㎡以上・家賃%d万円以下・定期借家除く・新耐震・築%d年以上は改装の記載あり</div><div><br></div>' % (AREA_MIN, RENT_MAX, REFORM_AGE)]
    if new:
        out.append('<h2>🆕 新着</h2>' + ''.join(entry(*x) for x in new))
    for w in order:
        ws = [x for x in items if x[0]['ward'] == w]
        if ws:
            out.append('<h2>%s（%d件）</h2>' % (w, len(ws)) + ''.join(entry(*x) for x in ws))
    script = '''on run argv
    with timeout of 600 seconds
    tell application "Notes"
        tell account "iCloud"
            if not (exists folder (item 3 of argv)) then make new folder with properties {name:(item 3 of argv)}
            set f to folder (item 3 of argv)
            set ns to (notes of f whose name is (item 1 of argv))
            if (count of ns) > 0 then
                set body of (item 1 of ns) to (item 2 of argv)
            else
                make new note at f with properties {body:(item 2 of argv)}
            end if
        end tell
    end tell
    end timeout
end run'''
    subprocess.run(['open', '-g', '-a', 'Notes'])   # 起動していないとタイムアウトしやすい
    time.sleep(10)
    r = subprocess.run(['osascript', '-e', script, NOTE_TITLE, ''.join(out), NOTE_FOLDER], capture_output=True, text=True)
    if r.returncode != 0:
        log('メモの更新失敗: ' + r.stderr.strip())
    return r.returncode == 0


def fmt(g, note):
    name = next((n for n in g['names'] if n and '駅' not in n and '階建' not in n), g['names'][0] if g['names'] else '')
    total = g['rent'] + g['fee'] / 10000
    age = min(g['ages']) if g['ages'] else None
    src, urls = next(iter(g['links'].items()))
    lines = ['%s%s %s%s %s' % ('★' if g['ward'] in PRIORITY else '', g['ward'], g['town'], g['chome'] + '丁目' if g['chome'] else '', name),
             '%.1f万円（管理費込 %.2f万）%s %.1f㎡ %s 駅%s分' % (g['rent'], total, g['layout'], g['area'],
                                                     '新築' if age == 0 else ('築%d年' % age if age is not None else ''),
                                                     min(g['walks']) if g['walks'] else '?')]
    if note:
        lines.append(note)
    lines.append(urls[0])
    return '\n'.join(lines)


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else ''
    if mode == '--test-line':
        ok = line('【テスト】賃貸の新着の通知です。新着があれば3時間おきにここにまとめて届きます。', everyone=False)
        log('LINE テスト送信 ' + {None: 'line.json がありません', True: '成功', False: '失敗'}[ok])
        return
    if mode == '--site':
        print(publish_site(json.load(open(os.path.join(HERE, 'list.json'), encoding='utf-8')), exclusions()))
        return
    rows, status = [], {}
    ts = [threading.Thread(target=crawl, args=(k, rows, status)) for k in SITES]
    [t.start() for t in ts]
    [t.join() for t in ts]
    groups = qualify(rows)
    seen = json.load(open(SEEN, encoding='utf-8')) if os.path.exists(SEEN) else {}
    verdicts = json.load(open(VERDICTS, encoding='utf-8')) if os.path.exists(VERDICTS) else {}

    def verdict(g):
        if g['key'] not in verdicts:
            verdicts[g['key']] = list(judge(g))
        return verdicts[g['key']]

    log('取得 %d件 / 条件内 %d件 / 状態 %s' % (len(rows), len(groups), status))
    if mode == '--init' or not seen:
        for k in groups:
            seen.setdefault(k, datetime.date.today().isoformat())
        json.dump(seen, open(SEEN, 'w', encoding='utf-8'), ensure_ascii=False, indent=0)
        log('既知として %d件を記録（通知なし）' % len(groups))
        return
    new = [g for k, g in groups.items() if k not in seen]
    hits = []
    for g in new if mode != '--list' else []:
        ok, note = verdict(g)
        seen[g['key']] = datetime.datetime.now().isoformat(timespec='minutes')  # 判定済みは条件外でも次回以降は見ない。新着順に使う
        if ok:
            hits.append((g, note))
    excl = exclusions()
    excl_known = excl is not None
    excl = excl or set()
    hits = [h for h in hits if h[0]['key'] not in excl]   # 一覧で「いらない」にした部屋は知らせない
    hits.sort(key=lambda x: (x[0]['ward'] not in PRIORITY, x[0]['rent'] + x[0]['fee'] / 10000))
    failed = [k for k, v in status.items() if v != 'ok']
    log('新しい掲載 %d件 / 通知対象 %d件 / 取得できなかったサイト %s' % (len(new), len(hits), failed or 'なし'))
    if hits and mode not in ('--dry-run', '--list'):
        line(line_hits(hits, failed))
    if hits and mode == '--dry-run':
        note = '※%sは一部取得できず' % '・'.join(failed) if failed else ''
        for g, n in hits:
            print(fmt(g, n) + ('\n' + note if note else '') + '\n')
    if not hits and len(failed) >= 3 and mode not in ('--dry-run', '--list'):
        msg = '今日は%sの取得に失敗しました。明日また確認します。' % '・'.join(failed)
        line('賃貸の新着: ' + msg)
    if mode == '--dry-run':
        return
    json.dump(seen, open(SEEN, 'w', encoding='utf-8'), ensure_ascii=False, indent=0)
    # 一覧。取得に失敗したサイトがあっても、ほかのサイトに載っていれば一覧に残る
    items = [(g, v[1]) for g in groups.values() for v in [verdict(g)] if v[0]]
    shown = [x for x in items if x[0]['key'] not in excl]
    json.dump(verdicts, open(VERDICTS, 'w', encoding='utf-8'), ensure_ascii=False, indent=0)
    if publish_site(dump_list(items, seen), excl if excl_known else None):
        log('一覧ページを公開 %d件' % len(items))
    if write_note(shown, seen):
        log('メモの一覧を更新 %d件（外した部屋 %d件を除く）' % (len(shown), len(items) - len(shown)))


if __name__ == '__main__':
    main()

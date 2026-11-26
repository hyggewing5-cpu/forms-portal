"""แปลงหน้าแบบฟอร์ม PDF เป็นข้อมูลสำหรับพอร์ทัลแบบฟอร์มออนไลน์
ต้องใช้: Python 3 และ  pip install pdfplumber
ตัวอย่าง: python pdf2form.py add แบบฟอร์ม.pdf --pages 1 --slug my-form --title "ชื่อฟอร์ม"
"""
import pdfplumber, json, re, statistics, collections, os

SP = 3.456
DOTS = set('.…')
COMB = lambda ch: len(ch) == 1 and (ch == '\u0e31' or '\u0e34' <= ch <= '\u0e3a' or '\u0e47' <= ch <= '\u0e4e')
MEMO = re.compile(r'^[ก-ฮ]\.[ก-ฮ]\.[๐-๙]{2}$')

def clusters(vals, tol):
    out = []
    for v in sorted(vals):
        if out and v - out[-1][-1] <= tol: out[-1].append(v)
        else: out.append([v])
    return out

def page_model(pg):
    allc = [c for c in pg.chars if c['text'] != ' ']
    cnt = collections.Counter(round(c['size']) for c in allc if c['text'] not in '.…_' and 'Wingdings' not in c['fontname'])
    base = cnt.most_common(1)[0][0] if cnt else 16
    deco, tiny, boxes, seen = [], [], [], set()
    def add(key, item):
        if key not in seen: seen.add(key); deco.append(item)
    for r in pg.rects:
        w = r['x1'] - r['x0']; h = r['bottom'] - r['top']
        if w < 2.6 and h < 1.2: tiny.append(r)
        elif h < 1.6 and w >= 2.6: add(('h', round(r['x0']), round(r['top'])), ['h', round(r['x0'], 1), round(r['top'], 1), round(w, 1)])
        elif w < 1.6 and h >= 2.6: add(('v', round(r['x0']), round(r['top'])), ['v', round(r['x0'], 1), round(r['top'], 1), round(h, 1)])
        elif 8 <= w <= 18 and 8 <= h <= 18 and abs(w - h) <= 2.5:
            k = (round(r['x0']), round(r['top']))
            if ('b',) + k not in seen: seen.add(('b',) + k); boxes.append((r['x0'], r['x1'], r['top'], r['bottom']))
        elif (w >= 19 or h >= 19) and r.get('stroke') and not r.get('fill'):
            add(('r', round(r['x0']), round(r['top']), round(w)), ['r', round(r['x0'], 1), round(r['top'], 1), round(w, 1), round(h, 1)])
    dashed = []
    # a row of 6+ adjacent boxes = digit boxes (e.g. ID number), not tick boxes
    boxes.sort(key=lambda b: (b[2], b[0])); rowsb = []
    for bx in boxes:
        if rowsb and abs(rowsb[-1][0][2] - bx[2]) <= 2.5: rowsb[-1].append(bx)
        else: rowsb.append([bx])
    plain, idruns = [], []
    for r in rowsb:
        r.sort(key=lambda b: b[0]); run = [r[0]]; runs = []
        for bx in r[1:]:
            if bx[0] - run[-1][1] <= 14: run.append(bx)
            else: runs.append(run); run = [bx]
        runs.append(run)
        for run in runs:
            if len(run) >= 6: idruns.append(run)
            else: plain += run
    boxes = plain
    for l in pg.lines:
        if abs(l['bottom'] - l['top']) < 1 and l.get('dash'): dashed.append([l['x0'], l['x1'], l['top']])
        elif abs(l['bottom'] - l['top']) < 1: add(('h', round(l['x0']), round(l['top'])), ['h', round(l['x0'], 1), round(l['top'], 1), round(l['x1'] - l['x0'], 1)])
        elif abs(l['x1'] - l['x0']) < 1: add(('v', round(l['x0']), round(l['top'])), ['v', round(l['x0'], 1), round(l['top'], 1), round(l['bottom'] - l['top'], 1)])
    # dotted underlines (tiny dot rectangles or dashed lines) -> spans
    spans, byy = list(dashed), {}
    for r in tiny: byy.setdefault(round(r['top'], 1), []).append(r)
    for y, rs in byy.items():
        rs.sort(key=lambda r: r['x0']); cur = None
        for r in rs:
            if cur and r['x0'] - cur[1] < 2.2: cur[1] = r['x1']
            else:
                if cur: spans.append(cur)
                cur = [r['x0'], r['x1'], y]
        if cur: spans.append(cur)
    spans = [sp for sp in spans if sp in dashed or sp[1] - sp[0] >= 8]
    # character lines (cluster by bottom edge so mixed font sizes share a line)
    cl = clusters([round(c['bottom'], 1) for c in allc], 3.0)
    lines = [{'atoms': [], 'cb': statistics.mean(g)} for g in cl]
    nearest = lambda b: min(range(len(lines)), key=lambda i: abs(lines[i]['cb'] - b)) if lines else -1
    for c in allc:
        k = 'K' if ('Wingdings' in c['fontname'] and c['text'] not in ('✓', '\uf0fc')) else 'c'
        lines[nearest(c['bottom'])]['atoms'].append((k, c['x0'], c['x1'], c['text'], c['fontname'], c['top'], False, round(c['size'], 1)))
    def dom(L):
        ok = [a for a in L['atoms'] if a[0] == 'c' and a[3] not in DOTS and a[3] != '_']
        reg = [a for a in ok if 'Bold' not in a[4]]
        sz = collections.Counter(a[7] for a in (reg or ok))
        return sz.most_common(1)[0][0] if sz else base
    for L in lines: L['z'] = dom(L)
    # offset of dotted underline below the text bottom
    ds = []
    for x0, x1, y in spans:
        i = nearest(y + 1.7)
        if i >= 0 and abs(lines[i]['cb'] - (y + 1.7)) < 4: ds.append(lines[i]['cb'] - y)
    Db = statistics.median(ds) if ds else 1.7
    for x0, x1, y in spans:
        b = y + Db; i = nearest(b)
        if i >= 0 and abs(lines[i]['cb'] - b) < 3.5: lines[i]['atoms'].append(('B', x0, x1, '', '', y, False, 0))
        else: lines.append({'atoms': [('B', x0, x1, '', '', y, False, 0)], 'cb': b, 'z': base})
    for x0, x1, top, bot in boxes:
        cy = (top + bot) / 2
        best = min(range(len(lines)), key=lambda i: abs(lines[i]['cb'] - lines[i]['z'] * 0.35 - cy), default=-1)
        if best >= 0 and abs(lines[best]['cb'] - lines[best]['z'] * 0.35 - cy) < 8:
            lines[best]['atoms'].append(('K', x0, x1, '\u25a1', 'rect', top, False, round(x1 - x0, 1)))
        else:
            lines.append({'atoms': [('K', x0, x1, '\u25a1', 'rect', top, False, round(x1 - x0, 1))], 'cb': bot + lines[0]['z'] * 0.2 if lines else bot, 'z': base})
    lines.sort(key=lambda l: l['cb'])
    out = []
    for L in lines:
        z = L['z']
        base_atoms = [a for a in L['atoms'] if a[0] != 'B']
        bspans = [a for a in L['atoms'] if a[0] == 'B']
        # (1) typed text drawn over leader dots (different baseline)
        dots = [a for a in base_atoms if a[3] in DOTS and a[0] == 'c']
        if len(dots) >= 4:
            tt = [round(a[5], 1) for a in dots]; dt = max(set(tt), key=tt.count)
            leader = [a for a in dots if abs(a[5] - dt) <= 0.3]
            if len(leader) >= 4:
                lx0 = min(a[1] for a in leader); lx1 = max(a[2] for a in leader)
                ovs = [a for a in base_atoms if a not in leader and a[0] == 'c' and abs(a[5] - dt) >= 0.5 and lx0 - 2 <= (a[1] + a[2]) / 2 <= lx1 + 2]
                if ovs:
                    ox0 = min(a[1] for a in ovs); ox1 = max(a[2] for a in ovs); ids = set(id(a) for a in ovs)
                    base_atoms = [(a[:6] + (True,) + a[7:]) if id(a) in ids else a for a in base_atoms
                                  if not (a in leader and ox0 - 1.5 <= (a[1] + a[2]) / 2 <= ox1 + 1.5)]
        # (2) dotted underline that already carries typed text -> keep as a decoration, make the text editable
        keepB = []; uls = []
        for b in bspans:
            sx0, sx1 = b[1], b[2]
            cov = [a for a in base_atoms if a[0] == 'c' and not COMB(a[3]) and a[3] not in DOTS and a[3] != '_' and sx0 - 0.5 <= (a[1] + a[2]) / 2 <= sx1 + 0.5]
            if cov:
                uls.append((sx0, sx1))
                tag = ('S', sx0, sx1)
                reg = [a for a in cov if 'Bold' not in a[4]]
                if reg:
                    lo = min(a[1] for a in reg); hi = max(a[2] for a in reg)
                    cid = set(id(a) for a in base_atoms if a[0] == 'c' and not COMB(a[3]) and 'Bold' not in a[4] and lo - 0.5 <= (a[1] + a[2]) / 2 <= hi + 0.5)
                else: cid = set()
                base_atoms = [(a[:6] + (tag,) + a[7:]) if id(a) in cid else a for a in base_atoms]
            else: keepB.append(b)
        groups = []
        for a in base_atoms:
            if COMB(a[3]) and groups: groups[-1].append(a)
            else: groups.append([a])
        groups.sort(key=lambda g: g[0][1])
        flat = [a for g in groups for a in ([g[0]] + [(m[:6] + (g[0][6],) + m[7:]) for m in g[1:]])]
        bs = sorted(keepB, key=lambda a: a[1]); atoms = []
        for a in flat:
            while bs and bs[0][1] <= a[1] and not COMB(a[3]): atoms.append(bs.pop(0))
            atoms.append(a)
        atoms += bs
        if not atoms: continue
        segs, sxs, state = [], [], {'text': '', 'st': None, 'x0': None, 'x1': None}
        def put(sg, a, b):
            segs.append(sg); sxs.append((a, b))
        def flush():
            if state['text']:
                s, b = state['st']
                put(['t', state['text'], 0 if abs(s - z) < 0.6 else s, 1 if b else 0], state['x0'], state['x1']); state['text'] = ''; state['x0'] = None
        def addtext(t, st, xa=None, xb=None):
            if state['text'] and state['st'] != st: flush()
            state['st'] = st; state['text'] += t
            if xa is not None:
                if state['x0'] is None: state['x0'] = xa
                state['x1'] = xb
        prev = None; xmax = max(a[2] for a in atoms); i = 0
        while i < len(atoms):
            k, x0, x1, ch, fn, top, ov, sz = atoms[i]
            gap = (x0 - prev) if prev is not None else 0
            if ov is True:
                flush(); j = i; vt = ''; pv = None
                while j < len(atoms) and atoms[j][6] is True:
                    aa = atoms[j]
                    if pv is not None and not COMB(aa[3]) and aa[1] - pv >= 2.0: vt += ' ' * max(1, round((aa[1] - pv) / SP))
                    vt += aa[3]
                    if not COMB(aa[3]): pv = aa[2]
                    j += 1
                if pv is None: pv = atoms[j - 1][2]
                put(['v', vt, round(pv - x0, 1)], x0, pv); prev = pv; i = j; continue
            if isinstance(ov, tuple):
                flush(); j = i; vt = ''; pv = None; sx1 = ov[2]; szs = []; fx = None
                while j < len(atoms) and atoms[j][6] == ov:
                    aa = atoms[j]
                    if not COMB(aa[3]):
                        szs.append(aa[7])
                        if fx is None: fx = aa[1]
                    if pv is not None and not COMB(aa[3]) and aa[1] - pv >= 2.0: vt += ' ' * max(1, round((aa[1] - pv) / SP))
                    vt += aa[3]
                    if not COMB(aa[3]): pv = aa[2]
                    j += 1
                if pv is None: pv = atoms[j - 1][2]
                left = prev if prev is not None else x0
                osz = collections.Counter(szs).most_common(1)[0][0] if szs else z
                meta = {'sz': osz, 'pl': round(max(0, (fx if fx is not None else left) - left), 1)}
                nxt = atoms[j] if j < len(atoms) else None
                right = nxt[1] if (nxt and nxt[0] != 'B' and nxt[1] < sx1 + 1) else sx1
                right = max(right, pv)
                if MEMO.match(vt.strip()): put(['f', round(pv - left, 1), 'm:' + vt.strip(), meta], left, pv); prev = pv
                else: put(['f', round(right - left, 1), 'o:' + vt.strip(), meta], left, right); prev = right
                xmax = max(xmax, prev); i = j; continue
            if k == 'B':
                flush(); put(['f', round(x1 - x0, 1), 'u'], x0, x1); prev = x1; i += 1; continue
            if k == 'K':
                flush()
                if prev is not None and gap > 14: put(['g', round(gap, 1)], prev, x0)
                elif prev is not None and gap >= 2.0 and segs and segs[-1][0] == 't': segs[-1][1] += ' ' * max(1, round(gap / SP))
                put(['c', round(x1 - x0, 1)], x0, x1); prev = x1; i += 1; continue
            if ch in DOTS or ch == '_':
                j = i; rx1 = x1
                while j + 1 < len(atoms) and ((atoms[j + 1][3] in DOTS) if ch in DOTS else atoms[j + 1][3] == ch) and atoms[j + 1][6] is False and atoms[j + 1][1] - rx1 <= 4.6:
                    j += 1; rx1 = atoms[j][2]
                n = j - i + 1
                if ch == '_':
                    flush()
                    if prev is not None and gap > 14: put(['g', round(gap, 1)], prev, x0)
                    put(['r', round(rx1 - x0, 1)], x0, rx1); prev = rx1; i = j + 1; continue
                if n >= 4:
                    flush()
                    if prev is not None and gap > 14: put(['g', round(gap, 1)], prev, x0)
                    put(['f', round(rx1 - x0, 1), 'd'], x0, rx1); prev = rx1; i = j + 1; continue
            if COMB(ch):
                addtext(ch, state['st'] or (sz, 'Bold' in fn)); i += 1; continue
            st = (sz, 'Bold' in fn)
            if prev is not None:
                if gap > 14: flush(); put(['g', round(gap, 1)], prev, x0)
                elif gap >= 2.0: addtext(' ' * max(1, round(gap / SP)), state['st'] or st)
            addtext(ch, st, x0, x1); prev = x1; i += 1
        flush()
        if not segs: continue
        # "(ลงชื่อ) พ.อ.อ.      (เจ้าหน้าที่ตรวจสอบ)": the blank gap becomes a dotted, fillable line
        for k2 in range(1, len(segs) - 1):
            if (segs[k2][0] == 'g' and segs[k2][1] >= 14 and segs[k2 - 1][0] == 't' and segs[k2 + 1][0] == 't'
                    and 'เจ้าหน้าที่ตรวจสอบ' in segs[k2 + 1][1] and any('ลงชื่อ' in q[1] for q in segs[:k2] if q[0] == 't')):
                segs[k2] = ['f', segs[k2][1], 'd']
        # blank parentheses "(      )" -> editable field
        for k2 in range(1, len(segs) - 1):
            if segs[k2][0] == 'g' and segs[k2][1] >= 14 and segs[k2 - 1][0] == 't' and segs[k2 - 1][1].rstrip().endswith('(') and segs[k2 + 1][0] == 't' and segs[k2 + 1][1].lstrip().startswith(')'):
                segs[k2] = ['f', segs[k2][1], 'p']
        # split into independent chunks at wide gaps / before check boxes so columns stay aligned with the PDF
        chunks, cur = [], []
        for idx, sg in enumerate(segs):
            if sg[0] == 'g':
                if cur: chunks.append(cur); cur = []
                continue
            if sg[0] == 'c' and cur: chunks.append(cur); cur = []
            cur.append(idx)
        if cur: chunks.append(cur)
        main = [a for a in atoms if a[0] == 'c' and abs(a[7] - z) < 0.6 and a[3] not in DOTS]
        ytop = statistics.mean(a[5] for a in main) if main else L['cb'] - z
        made = []
        for ch_ in chunks:
            cx0 = sxs[ch_[0]][0]; cx1 = max(sxs[ch_[-1]][1], cx0 + 1)
            made.append({'x': round(cx0, 1), 'y': round(ytop, 1), 'w': round(cx1 - cx0, 1), 'z': z, 's': [segs[q] for q in ch_]})
        for a, b in uls:
            tgt = next((m for m in made if m['x'] - 2 <= a <= m['x'] + m['w'] + 2), made[0])
            tgt.setdefault('ul', []).append([round(a - tgt['x'], 1), round(b - a, 1)])
        out.extend(made)
    words = pg.extract_words()
    for gi, run in enumerate(idruns):
        cy = (run[0][2] + run[0][3]) / 2
        lab = 'เลขประจำตัวประชาชน' if any('เลขประจำตัว' in w['text'] and abs((w['top'] + w['bottom']) / 2 - cy) < 9 for w in words) else 'หมายเลข'
        for i, bx in enumerate(run):
            w_, h_ = bx[1] - bx[0], bx[3] - bx[2]
            out.append({'x': round(bx[0], 1), 'y': round(bx[2], 1), 'w': round(w_, 1), 'z': base, 'box': {'w': round(w_, 1), 'h': round(h_, 1)},
                        's': [['x', round(w_, 1), 'g%d' % gi, i, {'label': lab, 'n': len(run)}]]})
    hl = [d for d in deco if d[0] == 'h']; vl = [d for d in deco if d[0] == 'v']
    nums = []
    for ci in range(len(allc) - 1):
        c, d = allc[ci], allc[ci + 1]
        if c['text'] in '๑๒๓๔๕๖๗๘๙' and d['text'] == '.' and d['x0'] - c['x1'] < 3:
            nums.append(((c['x0'] + d['x1']) / 2, (c['top'] + c['bottom']) / 2, c['text']))
    def cell_bounds(cx, cy):
        ha = [q[2] for q in hl if q[2] < cy - 2 and q[1] - 1 <= cx <= q[1] + q[3] + 1]
        hb = [q[2] for q in hl if q[2] > cy + 2 and q[1] - 1 <= cx <= q[1] + q[3] + 1]
        if not ha or not hb: return None
        y0, y1 = max(ha), min(hb)
        if y1 - y0 > 45: return None
        xs = sorted(q[1] for q in vl if q[2] - 1 <= cy <= q[2] + q[3] + 1)
        mx = []
        for x in xs:
            if not mx or x - mx[-1] > 1.2: mx.append(x)
        return y0, y1, mx
    def colx(mx, cx):
        for i in range(len(mx) - 1):
            if mx[i] <= cx <= mx[i + 1]: return i
        return None
    def header_text(x0, x1, ytop):
        near = [c for c in allc if x0 - 2 <= (c['x0'] + c['x1']) / 2 <= x1 + 2 and ytop - 90 < (c['top'] + c['bottom']) / 2 < ytop - 1 and c['text'] not in '.๑๒๓๔๕๖๗๘๙']
        if not near: return ''
        yb = max((c['top'] + c['bottom']) / 2 for c in near)
        return ''.join(c['text'] for c in near if abs((c['top'] + c['bottom']) / 2 - yb) < 5).strip()
    titles = [w for w in words if 'รถยนต์' in w['text'] or 'รถจักรยานยนต์' in w['text']]
    for cx, cy, dg in nums:
        cb_ = cell_bounds(cx, cy)
        if not cb_: continue
        y0, y1, mx = cb_; i0 = colx(mx, cx)
        if i0 is None or mx[i0 + 1] - mx[i0] > 40: continue
        stop = len(mx) - 1
        for cx2, cy2, _ in nums:
            if cx2 > cx and abs(cy2 - cy) < 6:
                j = colx(mx, cx2)
                if j is not None: stop = min(stop, j)
        for k2 in range(i0 + 1, stop):
            x0, x1 = mx[k2], mx[k2 + 1]
            if x1 - x0 < 8: continue
            if any(x0 < (c['x0'] + c['x1']) / 2 < x1 and y0 < (c['top'] + c['bottom']) / 2 < y1 for c in allc): continue
            side = ''
            if titles:
                tw = min(titles, key=lambda w: abs((w['x0'] + w['x1']) / 2 - (x0 + x1) / 2))
                side = 'รถจักรยานยนต์' if 'จักรยาน' in tw['text'] else 'รถยนต์'
            lab = (side + ' ' + dg + ' ' + header_text(x0, x1, y0)).replace('  ', ' ').strip()
            out.append({'x': round(x0 + 1.5, 1), 'y': round((y0 + y1) / 2 - base * 0.55, 1), 'w': round(x1 - x0 - 3, 1), 'z': base,
                        's': [['f', round(x1 - x0 - 3, 1), 'p', {'label': lab, 'grp': side or 'ตาราง'}]]})
    images = [{'x': round(im['x0'], 1), 'y': round(im['top'], 1), 'w': round(im['width'], 1), 'h': round(im['height'], 1)} for im in pg.images]
    return out, deco, images


def build_fields(lines, pref):
    norm = lambda t: re.sub(r'[.\s]', '', t)
    def split_parens(segs0):
        out = []
        for sg in segs0:
            if sg[0] == 't' and re.search(r'\(\s?\)', sg[1]):
                for q in re.split(r'(\(\s?\))', sg[1]):
                    if not q: continue
                    out.append(['k', 0] if re.fullmatch(r'\(\s?\)', q) else ['t', q, sg[2], sg[3]])
            else: out.append(sg)
        return out
    for l in lines: l['s'] = split_parens(l['s'])
    for l in lines:
        for sg in l['s']:
            if sg[0] == 't': sg[1] = re.sub(r'พ\.ศ(?!\.)', 'พ.ศ.', sg[1])
        if any(s[0] == 't' and 'ทำเครื่องหมาย' in s[1] for m in lines if abs(m['y'] - l['y']) < 2 for s in m['s']):
            l['s'] = [['t', '\u2610', 0, 0] if s[0] == 'c' else s for s in l['s']]
    ysplit = next((l['y'] for l in lines if any(s[0] == 't' and ('ควรมิควรแล้วแต่จะกรุณา' in s[1] or 'จึงเรียนมา' in s[1]) for s in l['s'])), 9999)
    # typed text over leader dots -> one field with a default value
    for l in lines:
        s_ = l['s']; i = 0
        while i < len(s_):
            if s_[i][0] == 'v':
                lo = hi = i; w = s_[i][2]
                if lo > 0 and s_[lo - 1][0] == 'f': lo -= 1; w += s_[lo][1]
                if hi + 1 < len(s_) and s_[hi + 1][0] == 'f': hi += 1; w += s_[hi][1]
                if hi + 1 < len(s_) and s_[hi + 1][0] == 't' and not s_[hi + 1][1].strip(' .'): hi += 1
                val = re.sub(r'^ผบ\s*บน\s*๕$', 'ผบ.บน.๕', s_[i][1])
                s_[lo:hi + 1] = [['f', round(w, 1), 'd:' + val]]; i = lo + 1
            else: i += 1
    grp_at, cur_g, cur_sub = [], '', ''
    for li_, l in enumerate(lines):
        s0 = l['s']
        if len(s0) == 1 and s0[0][0] == 't' and re.fullmatch(r'\(?\d+\)', s0[0][1].strip()):
            cur_sub = s0[0][1].strip()
        if len(s0) == 1 and s0[0][0] == 't' and re.fullmatch(r'\d+\.', s0[0][1].strip()):
            cur_sub = ''
            nx = next((m for m in lines[li_ + 1: li_ + 4] if abs(m['y'] - l['y']) < 2), None)
            if nx:
                tx = next((sg[1] for sg in nx['s'] if sg[0] == 't' and norm(sg[1])), '')
                cur_g = 'ข้อ %s %s' % (s0[0][1].strip().rstrip('.'), tx.strip()[:26])
        grp_at.append(cur_g + (' ' + cur_sub if cur_sub else ''))
    def plabel(li_):
        ys = [m['y'] for m in lines if m['y'] < lines[li_]['y'] - 3]
        txts = []
        if ys:
            py = max(ys); txts = [sg[1].strip() for m in lines if abs(m['y'] - py) < 2 for sg in m['s'] if sg[0] == 't' and norm(sg[1])]
        if any('ลงชื่อ' in t for t in txts):
            role = [t for t in txts if 'ลงชื่อ' not in t and len(t) > 2]
            return 'ชื่อ-สกุล' + (' ' + role[-1][:30] if role else '')
        return 'จำนวนเงินเป็นตัวอักษร'
    toks = [(li, si) for li, l in enumerate(lines) for si, _ in enumerate(l['s'])]
    S = lambda k: lines[toks[k][0]]['s'][toks[k][1]]
    N = len(toks); fields = []; n = 0; used = set(); dategroups = 0; digit_ids = {}
    def label_before(k):
        j = k - 1
        while j >= 0:
            sg = S(j)
            if sg[0] == 't' and norm(sg[1]): return sg[1].strip(' .')
            j -= 1
        return ''
    def text_after(k):
        j = k + 1
        while j < N:
            sg = S(j)
            if sg[0] == 't' and norm(sg[1]): return sg[1].strip(' .')
            if sg[0] in 'fck': return ''
            j += 1
        return ''
    isT = lambda x, w: x < N and S(x)[0] == 't' and norm(S(x)[1]) == w
    isF = lambda x: x < N and S(x)[0] == 'f' and len(S(x)) < 5
    k = 0
    while k < N:
        sg = S(k); li = toks[k][0]; sec = 1 if lines[li]['y'] > ysplit else 0
        if isF(k) and isT(k + 1, 'เดือน') and isF(k + 2) and isT(k + 3, 'พศ') and isF(k + 4):
            lab = label_before(k); fid = 'd%d' % n; n += 1
            for part, kk in zip('dmy', (k, k + 2, k + 4)): S(kk).extend([fid, part])
            key = None
            if not re.search(r'ตั้งแต่|ถึง|เมื่อ|เกิด|กลับ', lab) and 'docdate' not in used and lab.endswith('วันที่') and not any(x in lab for x in ('ในวันที่',)) and dategroups == 0: key = 'docdate'
            elif 'ตั้งแต่' in lab and 'start' not in used: key = 'start'
            elif 'ถึง' in lab and 'end' not in used and 'start' in used: key = 'end'
            elif 'กลับ' in lab and 'back' not in used: key = 'back'
            elif 'ในวันที่' in lab and 'go' not in used: key = 'go'
            elif 'คลอดบุตรเมื่อ' in lab: key = 'birth'
            elif lab.endswith('วันที่') and 'docdate' not in used and 'ตั้งแต่' not in lab: key = 'docdate'
            dategroups += 1
            if key: used.add(key)
            fields.append({'li': li, 'id': fid, 'type': 'date', 'label': lab[-30:] or 'วันที่', 'key': key, 'sec': sec}); k += 5; continue
        if isF(k) and isT(k + 1, '/') and isF(k + 2) and isT(k + 3, '/') and isF(k + 4):
            fid = 'd%d' % n; n += 1
            for part, kk in zip(('dn', 'mn', 'y'), (k, k + 2, k + 4)): S(kk).extend([fid, part])
            fields.append({'li': li, 'id': fid, 'type': 'date', 'label': (label_before(k)[-30:] or 'วันที่ลงความเห็น'), 'key': None, 'sec': sec, 'short': True}); k += 5; continue
        if isF(k):
            meta = sg.pop(3) if len(sg) > 3 and isinstance(sg[3], dict) else {}
            lab = label_before(k); fid = 'f%d' % n; n += 1; sg.append(fid)
            style = sg[2]; L = lab.strip(); nxt = text_after(k); key = None
            if style.startswith('m:'):
                sg[2] = 'm'; sg.append('memo')
                kk2 = 'docdate' if ('docdate' not in used and L.endswith('วันที่')) else None
                if kk2: used.add(kk2)
                fields.append({'li': li, 'id': fid, 'type': 'date', 'label': L[-30:] or 'วันที่', 'key': kk2, 'sec': sec, 'memo': True, **meta}); k += 1; continue
            if (L.endswith('ดิฉัน') or L.endswith('กระผม') or L.endswith('ข้าพเจ้า')) and 'name' not in used and sec == 0: key = 'name'
            if L.endswith('ในปีงบประมาณนี้') and nxt.startswith('ได้ลา'): key = 'name'
            if L.endswith('ประจำปีของ'): key = 'name'
            if L.endswith('ตำแหน่ง') and sec == 0 and 'pos' not in used: key = 'pos'
            if L.endswith('สังกัด') and sec == 0 and 'unit' not in used: key = 'unit'
            if 'มีกำหนด' in L and 'days' not in used: key = 'days'
            if L.endswith('จังหวัด') and 'prov' not in used: key = 'prov'
            if L.endswith('เพื่อ') and 'reason' not in used: key = 'reason'
            if L.endswith('ไปที่') and 'place' not in used: key = 'place'
            if L.endswith('ป่วยเป็น') and 'illness' not in used: key = 'illness'
            if L.endswith('เขียนที่'): key = 'writtenat'
            if key and key != 'name': used.add(key)
            if key == 'name': used.add('name')
            labtxt = (L if len(L) <= 26 else L[-26:].split(' ', 1)[-1]) or 'ช่องที่ %d' % n
            if nxt.lstrip().startswith(('(เจ้าหน้าที่', 'เจ้าหน้าที่')): labtxt = 'ชื่อ' + nxt.strip(' ()')[:30]
            elif style == 'p' or L == '(' or L.endswith('('): labtxt = plabel(li)
            elif L.startswith('(ลงชื่อ') or L == 'ลงชื่อ' or L.endswith('ลงชื่อ)'):
                labtxt = 'ลงชื่อ' + (' ' + nxt[:30] if nxt and 'ลงชื่อ' not in nxt and len(nxt) > 2 and not nxt.startswith('(') else '')
            fld = {'li': li, 'id': fid, 'type': 'text', 'label': labtxt, 'key': key, 'sec': sec}
            if style[:2] in ('d:', 'o:'): fld['def'] = style[2:]; sg[2] = style[0]
            fld.update(meta)
            fields.append(fld); k += 1; continue
        if sg[0] == 'x':
            meta = sg.pop(4) if len(sg) > 4 and isinstance(sg[4], dict) else {}
            if sg[2] not in digit_ids:
                digit_ids[sg[2]] = 'n%d' % n; n += 1
                fields.append({'li': li, 'id': digit_ids[sg[2]], 'type': 'digits', 'label': meta.get('label', 'ตัวเลข'), 'key': None, 'sec': sec, 'n': meta.get('n', 13)})
            sg[2] = digit_ids[sg[2]]; k += 1; continue
        if sg[0] in ('c', 'k'):
            fid = 'c%d' % n; n += 1; sg.append(fid)
            fields.append({'li': li, 'id': fid, 'type': 'check', 'label': (text_after(k)[:60] or label_before(k)[-30:] or 'ช่องทำเครื่องหมาย'), 'key': None, 'sec': sec}); k += 1; continue
        k += 1
    for l in lines:
        for sg in l['s']:
            if sg[0] == 'f' and len(sg) >= 4: sg[3] = pref + sg[3]
            if sg[0] in ('c', 'k', 'x') and len(sg) >= 3: sg[2] = pref + sg[2]
    for f in fields:
        g0 = grp_at[f.pop('li')]; f['grp'] = f.get('grp') or g0
        f['id'] = pref + f['id']
        f['label'] = re.sub(r'^[\u0e31\u0e34-\u0e3a\u0e47-\u0e4e]+', '', f['label']).strip()
    return lines, fields


# ---------------------------------------------------------------------------
# คำสั่งใช้งาน: เพิ่ม/ลบ/แสดงรายการแบบฟอร์มใน ../data/forms.js
# ---------------------------------------------------------------------------
import argparse, sys

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, '..', 'data', 'forms.js')
ASSETS = os.path.join(HERE, '..', 'assets')

def load_data():
    if not os.path.exists(DATA): return []
    t = open(DATA, encoding='utf-8').read()
    return json.loads(t[t.index('['): t.rindex(']') + 1])

def save_data(items):
    os.makedirs(os.path.dirname(DATA), exist_ok=True)
    with open(DATA, 'w', encoding='utf-8') as f:
        f.write('window.FORMS_DATA=' + json.dumps(items, ensure_ascii=False, separators=(',', ':')) + ';\n')

def convert(pdf_path, page_nos, slug):
    pages, fields = [], []
    with pdfplumber.open(pdf_path) as pdf:
        for idx, no in enumerate(page_nos):
            pg = pdf.pages[no - 1]
            lines, deco, images = page_model(pg)
            lines, fl = build_fields(lines, 'p%d_' % idx)
            deco = [d for d in deco if not (d[0] == 'h' and d[2] < 120 and d[3] < 300)]   # ตัดเส้นใต้หัวข้อใบลาออก
            for j, im in enumerate(images):
                os.makedirs(ASSETS, exist_ok=True)
                fn = '%s-p%d-%d.png' % (slug, idx + 1, j + 1)
                pg.crop((im['x'], im['y'], im['x'] + im['w'], im['y'] + im['h'])).to_image(resolution=300).save(os.path.join(ASSETS, fn))
                im['src'] = 'assets/' + fn
            pages.append({'lines': lines, 'deco': deco, 'images': images}); fields += fl
    seen = {}
    for f in fields:
        k_ = (f.get('grp'), f['label']); c = seen.get(k_, 0); seen[k_] = c + 1
        if c: f['label'] += ' (%d)' % (c + 1)
    return pages, fields

def main():
    ap = argparse.ArgumentParser(description='จัดการแบบฟอร์มในพอร์ทัล')
    sub = ap.add_subparsers(dest='cmd', required=True)
    a = sub.add_parser('add', help='เพิ่ม/แทนที่แบบฟอร์มจากหน้าของไฟล์ PDF')
    a.add_argument('pdf'); a.add_argument('--pages', default='1', help='เลขหน้าใน PDF คั่นด้วยจุลภาค เช่น 1 หรือ 3,4 (แบบฟอร์มหลายหน้า)')
    a.add_argument('--slug', required=True, help='ชื่อสั้นภาษาอังกฤษ ใช้ในลิงก์ เช่น leave-sick')
    a.add_argument('--title', required=True); a.add_argument('--group', default='การลา')
    a.add_argument('--desc', default=''); a.add_argument('--all-days', action='store_true', help='นับเสาร์-อาทิตย์เป็นวันลาด้วย (เช่น ลาคลอด)')
    sub.add_parser('list', help='แสดงรายการแบบฟอร์ม')
    r = sub.add_parser('remove', help='ลบแบบฟอร์ม'); r.add_argument('slug')
    args = ap.parse_args(); items = load_data()
    if args.cmd == 'list':
        for i, f in enumerate(items, 1): print(i, f['slug'], '-', f['title'], '(%d หน้า, %d ช่อง)' % (len(f['pages']), len(f['fields'])))
    elif args.cmd == 'remove':
        n = len(items); items = [f for f in items if f['slug'] != args.slug]; save_data(items); print('ลบแล้ว' if len(items) < n else 'ไม่พบ slug นี้')
    else:
        pages, fields = convert(args.pdf, [int(x) for x in args.pages.split(',')], args.slug)
        with pdfplumber.open(args.pdf) as _p:
            fcnt = collections.Counter(c['fontname'].split('+')[-1] for q in [int(x) for x in args.pages.split(',')] for c in _p.pages[q - 1].chars if c['text'] != ' ')
        fontname = fcnt.most_common(1)[0][0] if fcnt else ''
        ar = sum(len(re.findall(r'[0-9]', sg[1])) for p in pages for l in p['lines'] for sg in l['s'] if sg[0] == 't')
        th = sum(len(re.findall(r'[๐-๙]', sg[1])) for p in pages for l in p['lines'] for sg in l['s'] if sg[0] == 't')
        entry = {'slug': args.slug, 'title': args.title, 'group': args.group, 'desc': args.desc, 'allDays': args.all_days,
                 'digits': 'ar' if ar > th else 'th', 'font': ('TH SarabunIT๙' if 'IT' in fontname else ''), 'pages': pages, 'fields': fields}
        for i, f in enumerate(items):
            if f['slug'] == args.slug: items[i] = entry; break
        else: items.append(entry)
        save_data(items)
        keyed = sorted({x['key'] for x in fields if x['key']})
        print('เพิ่มแล้ว: %s (%d หน้า, %d ช่อง, ช่องที่ระบบรู้จัก: %s)' % (args.title, len(pages), len(fields), ', '.join(keyed) or '-'))

if __name__ == '__main__':
    main()

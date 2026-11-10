"""Extract per-model layouts and default keymaps from the Antler web bundle."""
import json, re, sys

src = open(sys.argv[1], encoding="utf-8").read()

def args_of(text, start):
    """Parse a JS argument list starting just after '(' -> (list, end)."""
    out, cur, i, depth = [], "", start, 0
    while i < len(text):
        c = text[i]
        if c in "\"'`":
            j = i + 1
            while text[j] != c:
                j += 2 if text[j] == "\\" else 1
            cur += text[i:j + 1]; i = j + 1; continue
        if c == "(":
            depth += 1
        elif c == ")":
            if depth == 0:
                out.append(cur.strip()); return out, i
            depth -= 1
        elif c == "," and depth == 0:
            out.append(cur.strip()); cur = ""; i += 1; continue
        cur += c; i += 1
    raise ValueError

def lit(a):
    if a[:1] in "\"'`":
        return a[1:-1].replace("\\\\", "\\")
    try:
        return int(a)
    except ValueError:
        return a

def class_body(name):
    i = src.find(f"class {name} extends")
    if i < 0:
        return None
    j = src.find("initKeyCodeArrays(){", i)
    return src[i:src.find("while(!1)", j) if j > 0 else src.find("class ", i + 10)]

i = src.find("yC=function"); body = src[i:i + 14000]
models, last = [], 0
for m in re.finditer(r"this\.profileObject=new (\w+)\(this\),this\.keyboard_type=(\d+),this\.colourObject=new \w+\(this\),this\.remapObject=new (\w+)", body):
    pre = body[last:m.start()]; last = m.end()
    ids = re.findall(r"Q===(\d+)&&A===(\d+)&&e===(\d+)", pre)
    prof, ktype, remap = m.group(1), int(m.group(2)), m.group(3)
    pb, rb = class_body(prof), class_body(remap)
    lay = re.search(r"this\.m_kbdLayout=(\[[^\]]*\])", pb or "")
    layout = json.loads(lay.group(1)) if lay else None
    defaults = {}
    for L in (0, 1, 2):
        key = f"keyCodeLayer{L}.push(new g("
        pos, entries = 0, []
        while True:
            k = rb.find(key, pos)
            if k < 0:
                break
            a, end = args_of(rb, k + len(key)); pos = end
            a = [lit(x) for x in a]
            idx, cmd, text, icon, code = a[:5]
            typ = a[5] if len(a) > 5 else 0
            if cmd:
                entries.append({"i": idx, "cmd": cmd, "code": code, "type": typ, "text": text})
        defaults[L] = entries
    nm = re.search(r'super\(A,"ddeer(\w+?)Profile"', pb or "")
    for L in defaults:
        seen, ded = set(), []
        for e in defaults[L]:
            if e["i"] not in seen:
                seen.add(e["i"]); ded.append(e)
        defaults[L] = ded
    models.append({"name": nm.group(1) if nm else prof, "ids": [list(map(int, t)) for t in ids], "ktype": ktype,
                   "profile": prof, "remap": remap, "layout": layout, "defaults": defaults})

# command groups
k = src.find("initializeFuncArea(){do"); fb = src[k:src.find("while(!1)", k)]
groups = {}
for m in re.finditer(r"command_array_group(\d)\.push\(new g\(", fb):
    a, _ = args_of(fb, m.end()); a = [lit(x) for x in a]
    groups.setdefault(int(m.group(1)), []).append(
        {"cmd": a[1], "text": a[2], "icon": a[3], "code": a[4], "type": a[5] if len(a) > 5 else 0})
json.dump({"models": models, "groups": groups}, open(sys.argv[2], "w"), ensure_ascii=False, indent=1)
for m in models:
    print(m["name"],m["ktype"], m["ids"], m["profile"], len(m["layout"] or []), {k: len(v) for k, v in m["defaults"].items()})

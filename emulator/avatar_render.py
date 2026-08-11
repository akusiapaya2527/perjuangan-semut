"""Flattened ant renderer for the admin avatar preview."""
import hashlib
import os
import re

import png as Png

CHAR_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                         "runtime", "res", "textures", "0.5x", "CHAR")
CACHE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                          "data", "img_cache")

_WANTED = {"shadow", "rightantenna", "lefttantenna", "head", "eye", "mouth",
           "eyebrow", "hat", "clothes", "body"}

_GEAR_SLOTS = {"shadow", "rightantenna", "lefttantenna", "head", "eye", "mouth",
               "eyebrow", "hat", "clothes", "body", "tail",
               "rightleg", "leftleg", "rightshoe", "leftshoe",
               "righthand", "lefthand", "rightglove", "leftglove",
               "rightwing", "leftwing", "stone"}

_GEAR_PREFIX = {
    1: {"clothes": "Clothes"},
    2: {"leftshoe": "Shoes", "rightshoe": "Shoes"},
    6: {"hat": "Helm"},
    7: {"leftglove": "Glove", "rightglove": "Glove_Sec"},
    8: {"leftwing": "wing", "rightwing": "wing"},
    11: {"stone": "weapon"},
    12: {"stone": "weapon"},
    14: {"stone": "weapon"},
}

_PROFILE_SCALE = (-0.7, 0.7)

_CACHE = {}


def _armature(atlas_root):
    return "ant_girl" if "girl" in atlas_root else "ant_boy"


def _load_atlas(base):
    atlas = base + ".png"
    xml = base + ".xml"
    if not os.path.isfile(atlas) or not os.path.isfile(xml):
        return None
    AW, AH, atlas_rgba = Png.decode_png(open(atlas, "rb").read())
    rects = {}
    for m in re.finditer(r'<SubTexture name="([^"]+)" x="(\d+)" y="(\d+)" width="(\d+)" height="(\d+)"',
                         open(xml, encoding="utf-8", errors="replace").read()):
        rects[m.group(1)] = [int(v) for v in m.groups()[1:]]
    return atlas_rgba, AW, rects


def _parse_skeleton(atlas_root):
    sk = os.path.join(CHAR_DIR, "skeleton_" +
                      ("girl" if "girl" in atlas_root else "boy") + ".xml")
    if not os.path.isfile(sk):
        return None, None, None
    xml = open(sk, encoding="utf-8", errors="replace").read()
    arm = re.search(r'<armature name="%s">(.*?)</armature>' % _armature(atlas_root), xml, re.S)
    if arm is None:
        return None, None, None
    arm = arm.group(1)
    bones = {}
    for m in re.finditer(r'<bone name="([^"]+)"([^>]*)>.*?<transform x="([-\d.]+)" y="([-\d.]+)"[^>]*scX="([\d.]+)" scY="([\d.]+)"', arm, re.S):
        name, attrs, x, y, sx, sy = m.groups()
        par = re.search(r'parent="([^"]+)"', attrs)
        bones[name] = (par.group(1) if par else None, float(x), float(y), float(sx), float(sy))
    slots = []
    for m in re.finditer(r'<slot name="([^"]+)" parent="([^"]+)" z="(\d+)">.*?<display name="([^"]+)" type="image">.*?<transform x="([-\d.]+)" y="([-\d.]+)"[^>]*?scX="([\d.]+)" scY="([\d.]+)"', arm, re.S):
        name, parent, z, disp, dx, dy, sx, sy = m.groups()
        t = m.group(0)
        pm = re.search(r'pX="([-\d.]+)"[^>]*?pY="([-\d.]+)"', t) or re.search(r'pY="([-\d.]+)"[^>]*?pX="([-\d.]+)"', t)
        px, py = (float(pm.group(1)), float(pm.group(2))) if pm else (0.0, 0.0)
        slots.append((int(z), name, parent, disp, float(dx), float(dy),
                      float(sx), float(sy), px, py))
    anim_poses = {}
    idx = xml.find('<animation name="shot"')
    if idx >= 0:
        end = xml.find('</animation>', idx) + 12
        anim = xml[idx:end]
        for tm in re.finditer(r'<timeline name="([^"]+)"[^>]*>.*?<frame[^>]*>.*?<transform x="([-\d.]+)" y="([-\d.]+)"[^>]*scX="([\d.]+)" scY="([\d.]+)"', anim, re.S):
            bname, x, y, sx, sy = tm.groups()
            t = tm.group(0)
            pm = re.search(r'pX="([-\d.]+)"[^>]*?pY="([-\d.]+)"', t) or re.search(r'pY="([-\d.]+)"[^>]*?pX="([-\d.]+)"', t)
            px, py = (float(pm.group(1)), float(pm.group(2))) if pm else (0.0, 0.0)
            anim_poses[bname] = (float(x), float(y), float(sx), float(sy), px, py)
    return bones, slots, anim_poses


def _world_transforms(bones, anim_poses):
    wb = {}

    def world(b):
        if b in wb:
            return wb[b]
        p, x, y, sx, sy = bones[b]
        if b in anim_poses:
            ax, ay, asx, asy, apx, apy = anim_poses[b]
            x, y, sx, sy = ax, ay, asx, asy
        if p:
            wx, wy, wsx, wsy = world(p)
            wbx, wwy = wx + x * wsx, wy + y * wsy
            wsx, wsy = wsx * sx, wsy * sy
        else:
            wbx, wwy, wsx, wsy = x, y, sx, sy
        wb[b] = (wbx, wwy, wsx, wsy)
        return wbx, wwy, wsx, wsy

    for b in bones:
        world(b)
    return wb


def _collect_parts(slots, wb, all_rects, overrides, wanted):
    parts = []
    for z, name, parent, disp, dx, dy, sx, sy, px, py in slots:
        if name in overrides:
            disp = overrides[name]
        elif name not in wanted:
            continue
        if disp not in all_rects:
            continue
        wx, wy, wsx, wsy = wb[parent]
        cx, cy = wx + dx * wsx, wy + dy * wsy
        ws = ((wsx * wsy) ** 0.5) * sx * sy
        parts.append((z, name, (cx, cy), ws, disp, px, py))
    return parts


def _blit_parts(parts, rects, src_for):
    if not parts:
        return None
    boxes = []
    for _, _, (cx, cy), ws, disp, px, py in parts:
        x, y, w, h = rects[disp]
        ox = cx - px * ws
        oy = cy - py * ws
        boxes.append((ox, oy, ox + w * ws, oy + h * ws))
    minx = min(b[0] for b in boxes); miny = min(b[1] for b in boxes)
    maxx = max(b[2] for b in boxes); maxy = max(b[3] for b in boxes)
    W = int(maxx - minx) + 5; H = int(maxy - miny) + 5
    canvas = bytearray(W * H * 4)

    for z, _, (cx, cy), ws, disp, px, py in sorted(parts, key=lambda p: p[0]):
        atlas_rgba, AW = src_for[disp]
        x, y, w, h = rects[disp]
        part = Png.crop(atlas_rgba, AW, x, y, w, h)
        ow, oh = int(w * ws), int(h * ws)
        ox = int(cx - px * ws - minx + 2)
        oy = int(cy - py * ws - miny + 2)
        for yy in range(oh):
            syi = min(int(yy / ws), h - 1) if ws != 1 else yy
            base = syi * w * 4
            for xx in range(ow):
                sxi = min(int(xx / ws), w - 1) if ws != 1 else xx
                oi = base + sxi * 4
                if part[oi + 3] == 0:
                    continue
                tx, ty = ox + xx, oy + yy
                if 0 <= tx < W and 0 <= ty < H:
                    canvas[(ty * W + tx) * 4:(ty * W + tx) * 4 + 4] = part[oi:oi + 4]

    sx, sy = _PROFILE_SCALE
    W2 = max(1, int(W * abs(sx)))
    H2 = max(1, int(H * sy))
    scaled = bytearray(W2 * H2 * 4)
    for y2 in range(H2):
        y1 = min(int(y2 / sy), H - 1)
        for x2 in range(W2):
            x1 = W - 1 - min(int(x2 / abs(sx)), W - 1)
            i1 = (y1 * W + x1) * 4
            i2 = (y2 * W2 + x2) * 4
            scaled[i2:i2 + 4] = canvas[i1:i1 + 4]
    return Png.encode_png(W2, H2, scaled)


def _render(atlas_root, equipped, wanted):
    base = os.path.join(CHAR_DIR, atlas_root)
    ch = _load_atlas(base)
    hats = _load_atlas(os.path.join(CHAR_DIR, "hats"))
    if ch is None:
        return None
    atlas_rgba, AW, rects = ch
    bones, slots, anim_poses = _parse_skeleton(atlas_root)
    if bones is None:
        return None
    wb = _world_transforms(bones, anim_poses)

    all_rects = dict(rects)
    src_for = {disp: (atlas_rgba, AW) for disp in rects}
    if hats:
        hats_rgba, hats_AW, hats_rects = hats
        for disp, rect in hats_rects.items():
            all_rects[disp] = rect
            src_for[disp] = (hats_rgba, hats_AW)

    overrides = {}
    for g in equipped:
        tid = int(g.get("typeID", 0))
        fid = int(g.get("frameID", 0)) // 10
        mapping = _GEAR_PREFIX.get(tid)
        if not mapping:
            continue
        for slot, prefix in mapping.items():
            name = "part/%s_%d_%d" % (prefix, tid, fid)
            if tid == 8 and fid in (101, 102):
                continue
            overrides[slot] = name

    parts = _collect_parts(slots, wb, all_rects, overrides, wanted)
    return _blit_parts(parts, all_rects, src_for)


def _cached(key, renderer):
    if key in _CACHE:
        return _CACHE[key]
    try:
        os.makedirs(CACHE_DIR, exist_ok=True)
        fp = os.path.join(CACHE_DIR, hashlib.md5(str(key).encode("utf-8")).hexdigest() + ".png")
        if os.path.isfile(fp):
            data = open(fp, "rb").read()
            _CACHE[key] = data
            return data
    except OSError:
        fp = None
    data = renderer()
    if data is not None and fp:
        try:
            open(fp, "wb").write(data)
        except OSError:
            pass
    _CACHE[key] = data
    return data


def avatar_png(atlas_root):
    return _cached(atlas_root, lambda: _render(atlas_root, [], _WANTED))


def avatar_png_with_gear(atlas_root, equipped):
    key = (atlas_root, tuple(sorted(
        (int(g.get("typeID", 0)), int(g.get("frameID", 0)))
        for g in equipped)))
    return _cached(key, lambda: _render(atlas_root, equipped, _GEAR_SLOTS))

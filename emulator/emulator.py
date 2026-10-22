#!/usr/bin/env python3
"""Localhost backend emulator for Perjuangan Semut (Ant Wars, Boyaa FB-Indonesia).

Serves:
  HTTP  :8080  mobile/devicelogin.php, api/flashapi.php, version/facebookid/*
  SOCKET:9001  GameServer  (boot: login -> goods -> body -> HALL)
  SOCKET:9002  BattleServer (login/room; robot fight minimal)

Client expects base URL http://127.0.0.1:8080/antwarsmobile/ when patched to
isLocal=true. See README.md for the SWF patch + ADL runtime notes.
"""
import json
import hashlib
import mimetypes
import os
import re
import secrets
import copy
import socket
import sqlite3
import struct
import threading
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import protocol as P
import png as Png
import avatar_render

HOST = os.environ.get("EMU_HOST", "127.0.0.1")  # "0.0.0.0" for Docker/remote
HTTP_PORT = 8080
GAME_PORT = 9001
BATTLE_PORT = 9002
COPY_PORT = 9003
BASE = "/antwarsmobile"
# Bundled resources served as the ResUrl webroot. Client builds
# ResUrl + "/<path>" for every static asset (xml.data, textures/, ...).
RES_ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "runtime", "res")
AUTH_ASSET_ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..",
                               "antwarsmobilestarling.swf-decompile", "src", "_assets",
                               "assets-decompiled", "images")


def res_root(rel):
    """Resolve a client resource path against the res webroot, denying traversal."""
    if not rel or rel.startswith(("/", "\\")):
        return None
    full = os.path.normpath(os.path.join(RES_ROOT, rel))
    if not full.startswith(RES_ROOT + os.sep):
        return None
    return full


def res_manifest():
    """Newline list of every bundled res file relative to RES_ROOT (Ruffle loads res by URL)."""
    out = []
    for root, _dirs, files in os.walk(RES_ROOT):
        for fn in sorted(files):
            if fn == ".DS_Store":
                continue
            full = os.path.join(root, fn)
            rel = os.path.relpath(full, RES_ROOT)
            out.append(rel.replace(os.sep, "/"))
    return "\n".join(out) + "\n"

# ---------------------------------------------------------------------------
# Texture-atlas icon server — crops Starling subtextures for admin previews.
# Atlas layout is mirror of the client: textures/0.5x/<CAT>/<name>.png + .xml.
# ---------------------------------------------------------------------------
ATLAS_DIR = os.path.join(RES_ROOT, "textures", "0.5x")
ASSET_INDEX = {}        # subtexture name -> (atlas_png, (x,y,w,h))
ATLAS_FULL = {}         # atlas root name (whole image) -> png path
GOODS_ICON = {}         # (typeID, frameID//10) -> part/<...> subtexture name
_ATLAS_CACHE = {}
IMG_CACHE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "img_cache")


def _build_asset_index():
    import glob
    for xml in sorted(glob.glob(os.path.join(ATLAS_DIR, "*", "*.xml"))):
        atlas = xml[:-4] + ".png"
        if not os.path.isfile(atlas):
            continue
        skel = "skeleton_" in os.path.basename(xml)
        try:
            txt = open(xml, encoding="utf-8", errors="replace").read()
        except OSError:
            continue
        for m in re.finditer(r'<TextureAtlas name="([^"]+)"', txt):
            if not skel and m.group(1) not in ATLAS_FULL:
                ATLAS_FULL[m.group(1)] = atlas
        for m in re.finditer(r'<SubTexture name="([^"]+)" x="(\d+)" y="(\d+)" width="(\d+)" height="(\d+)"', txt):
            name = m.group(1)
            rect = (int(m.group(2)), int(m.group(3)), int(m.group(4)), int(m.group(5)))
            cur = ASSET_INDEX.get(name)
            if cur is None or (skel and not cur[2]):
                ASSET_INDEX[name] = (atlas, rect, not skel)
    for name, (_atlas, _rect, _pref) in ASSET_INDEX.items():
        tail = name[len("part/"):] if name.startswith("part/") else None
        if tail:
            bits = tail.rsplit("_", 2)
            if len(bits) == 3 and bits[1].isdigit() and bits[2].isdigit():
                GOODS_ICON[(int(bits[1]), int(bits[2]))] = name


def goods_icon_name(typeID, frameID):
    """Client logic (ResAssetManager.getGoodsImage): typeID 26 special-cased,
    otherwise frameID floored to /10. Returns subtexture name or None."""
    typeID, frameID = int(typeID), int(frameID)
    if typeID == 26:
        fid = 100 + frameID if frameID in (1, 2, 3) else frameID // 10
    else:
        fid = frameID // 10
    return GOODS_ICON.get((typeID, fid))


def _slot_for_type(typeID):
    return {1: "coat", 2: "shoes", 4: "weddingRing", 6: "hat",
            7: "glove", 8: "wing", 11: "weapon", 12: "weapon", 14: "weapon"}.get(int(typeID), "")


EQUIPMENT_SLOTS = {
    "coat", "shoes", "glasses", "leftring", "rightleft", "necklace",
    "hat", "glove", "wing", "chatframe", "dbexpcard", "weapon",
    "weddingRing", "normalRing",
}


def equipment_slot_for_good(good):
    """Return the canonical body slot for an equipment record, or empty string."""
    explicit = str(good.get("slot", "") or "")
    if explicit in EQUIPMENT_SLOTS:
        return explicit
    return _slot_for_type(good.get("typeID", 0))


def normalize_user_goods(user):
    """Keep all goods, but allow only the newest record per slot to be equipped.

    Older duplicates are moved back to the bag instead of being deleted, so an
    admin-created or reward-granted item remains visible to the player.
    """
    goods = user.setdefault("goods", [])
    equipped_by_slot = {}
    for good in sorted(goods, key=lambda item: int(item.get("onlyID", 0))):
        slot = equipment_slot_for_good(good)
        if int(good.get("position", 0)) != 1 or not slot:
            if slot and int(good.get("position", 0)) == 1:
                good["position"] = 0
            continue
        previous = equipped_by_slot.get(slot)
        if previous is not None:
            previous["position"] = 0
        good["slot"] = slot
        equipped_by_slot[slot] = good
    for good in goods:
        if int(good.get("position", 0)) == 1:
            slot = equipment_slot_for_good(good)
            if slot:
                good["slot"] = slot
    return goods


def equipped_goods(user):
    """Return the normalized, one-per-slot equipment records for a user."""
    goods = normalize_user_goods(user)
    return [g for g in goods if int(g.get("position", 0)) == 1 and equipment_slot_for_good(g)]


def avatar_gear_for_user(user):
    """Return only wearable goods in the canonical order used by the renderer."""
    wearable = {1, 2, 6, 7, 8, 11, 12, 14}
    return [g for g in equipped_goods(user) if int(g.get("typeID", 0)) in wearable]


def set_equipment_state(user, slot, position, only_id):
    """Equip or unequip one good and return the changed record."""
    slot = str(slot or "")
    target = None
    for good in user.setdefault("goods", []):
        if int(good.get("onlyID", 0)) == int(only_id):
            target = good
            break
    if target is None:
        return None
    if int(position):
        for good in user["goods"]:
            if good is not target and int(good.get("position", 0)) == 1 \
                    and equipment_slot_for_good(good) == slot:
                good["position"] = 0
        target["position"] = 1
        target["slot"] = slot or equipment_slot_for_good(target)
    else:
        target["position"] = 0
    normalize_user_goods(user)
    return target


def _category_for_type(typeID):
    t = int(typeID)
    if t in (11, 12, 14):
        return "weapon"
    if t == 1:
        return "clothes"
    if t == 2:
        return "shoes"
    if t == 6:
        return "helm"
    if t == 7:
        return "glove"
    if t == 8:
        return "wing"
    if t in (16, 17, 18, 19, 20):
        return "stats"
    if t in (25, 26, 34, 36, 42):
        return "consumable"
    return "other"


def _name_for_type(typeID):
    return {1: "Clothes", 2: "Shoes", 4: "Ring", 6: "Helm", 7: "Glove",
            8: "Wing", 11: "Weapon", 12: "Weapon", 14: "Weapon",
            16: "Strength", 17: "Agility", 18: "Constitution", 19: "Luck",
            20: "Bonus", 25: "GiftBag", 26: "Treasure", 34: "Mission",
            36: "SuitCard", 42: "Energy"}.get(int(typeID), "Item")


def item_catalog():
    """All catalog entries derived from texture atlas part/* subtextures.
    Returns sorted list of {typeID, frameID, fid, name, category, slot, icon}."""
    if not GOODS_ICON:
        _build_asset_index()
    items = []
    for (typeID, fid), subtex in sorted(GOODS_ICON.items(),
                                        key=lambda kv: (kv[0][0], kv[0][1])):
        if not subtex.startswith("part/"):
            continue
        frameID = fid * 10 + 1
        items.append({
            "typeID": typeID,
            "frameID": frameID,
            "fid": fid,
            "name": "%s #%d" % (_name_for_type(typeID), fid),
            "category": _category_for_type(typeID),
            "slot": _slot_for_type(typeID),
            "icon": "/goods_icon?typeID=%d&frameID=%d" % (typeID, frameID),
        })
    return items


def _atlas_rgba(path):
    data = _ATLAS_CACHE.get(path)
    if data is None:
        with open(path, "rb") as f:
            data = Png.decode_png(f.read())
        _ATLAS_CACHE[path] = data
    return data


def icon_png(name):
    """Return PNG bytes for a subtexture (or whole atlas) by name, else None."""
    hit = ASSET_INDEX.get(name)
    if hit:
        atlas, (x, y, w, h), _ = hit
        try:
            W, H, rgba = _atlas_rgba(atlas)
        except Exception:
            return None
        crop = Png.crop(rgba, W, x, y, w, h)
        return Png.encode_png(w, h, crop)
    full = ATLAS_FULL.get(name)
    if full:
        with open(full, "rb") as f:
            return f.read()
    return None


def icon_png_cached(name):
    """icon_png with on-disk cache under data/img_cache/."""
    import hashlib
    key = hashlib.md5(name.encode("utf-8")).hexdigest()
    try:
        os.makedirs(IMG_CACHE_DIR, exist_ok=True)
        fp = os.path.join(IMG_CACHE_DIR, key + ".png")
        if os.path.isfile(fp):
            with open(fp, "rb") as f:
                return f.read()
    except OSError:
        fp = None
    data = icon_png(name)
    if data is not None and fp:
        try:
            with open(fp, "wb") as f:
                f.write(data)
        except OSError:
            pass
    return data


def icon_png_scoped(atlas_root, name):
    """Crop a subtexture scoped to ONE atlas (basename atlas_root.png).

    Needed because names like part/head exist in BOTH charcher_boy and
    charcher_girl atlases with different rects; ASSET_INDEX is last-write-wins
    and can't tell them apart. Avatar preview asks for the right atlas + part.
    """
    base = atlas_root + ".png"
    hit = None
    for n, (atlas, rect, pref) in ASSET_INDEX.items():
        if n == name and os.path.basename(atlas) == base:
            if hit is None or pref:
                hit = (atlas, rect)
    if hit is None:
        return None
    atlas, (x, y, w, h) = hit
    try:
        W, H, rgba = _atlas_rgba(atlas)
    except Exception:
        return None
    return Png.encode_png(w, h, Png.crop(rgba, W, x, y, w, h))


def icon_png_scoped_cached(atlas_root, name):
    """icon_png_scoped with on-disk cache keyed by both atlas + name."""
    import hashlib
    key = hashlib.md5((atlas_root + "/" + name).encode("utf-8")).hexdigest()
    try:
        os.makedirs(IMG_CACHE_DIR, exist_ok=True)
        fp = os.path.join(IMG_CACHE_DIR, key + ".png")
        if os.path.isfile(fp):
            with open(fp, "rb") as f:
                return f.read()
    except OSError:
        fp = None
    data = icon_png_scoped(atlas_root, name)
    if data is not None and fp:
        try:
            with open(fp, "wb") as f:
                f.write(data)
        except OSError:
            pass
    return data

# ---------------------------------------------------------------------------
# CopyGame stage catalog — parsed once from the bundled xml.data (zlib at rest).
# COPY_INFO maps cpdtlid -> {cpid, difficulty, stage, mapid}; drives
# getCopyGrade unlock + getMobileCopyPrize reward lookup.
# ---------------------------------------------------------------------------
COPY_COST = 15  # copygame energy per stage (copylist coste)
COPY_INFO = {}
COPY_CPDTLIDS = []
COPY_STAGE_COST = COPY_COST


def _load_copylist():
    import zlib
    try:
        raw = open(os.path.join(RES_ROOT, "xml.data"), "rb").read()
        txt = zlib.decompress(raw).decode("utf-8", "replace")
    except Exception:
        txt = ""
    for b in re.finditer(r"<copy\b.*?</copy>", txt, re.S):
        cm = re.search(r'cpid="(\d+)"', b.group(0))
        if not cm:
            continue
        cpid = int(cm.group(1))
        for d in re.finditer(r"<detail\b.*?</detail>", b.group(0), re.S):
            dd = re.search(r'cpdtlid="(\d+)"\s+difficulty="(\d+)"\s+stage="(\d+)"\s+mapid="(\d+)"', d.group(0))
            if not dd:
                continue
            cdt, diff, stage, mapid = (int(v) for v in dd.groups())
            roles = [(int(r), int(q)) for r, q in
                     re.findall(r'roleid="(\d+)"\s+qty="(\d+)"', d.group(0))]
            COPY_INFO[cdt] = {"cpid": cpid, "difficulty": diff, "stage": stage,
                              "mapid": mapid, "roles": roles}
    COPY_CPDTLIDS[:] = sorted(COPY_INFO)


def goods_array(g):
    """readGoods() 13-field JSON array (same order as write_goods)."""
    return [int(g.get("onlyID", 0)), int(g.get("typeID", 0)), int(g.get("frameID", 0)),
            int(g.get("count", 0)), str(g.get("attribute", "")), str(g.get("synthesis", "")),
            int(g.get("expiration", 0)), int(g.get("strengthen", 0)),
            int(g.get("position", 0)), int(g.get("term", 0)), int(g.get("amount", 0)),
            int(g.get("isbind", 0)), str(g.get("color", 0))]


def is_weapon(g):
    return int(g.get("typeID", 0)) in (11, 12, 14) or g.get("slot") == "weapon"


def fight_box(u):
    """The player's fight box (≤8 weapons, used by BtSkillDlg). Client renders
    exactly 8 slots (_rightItems); more weapons crash updateWeaponShow with
    RangeError #1125 index out of range. Seeded with the equipped weapons."""
    box = [g["onlyID"] for g in u.get("goods", []) if is_weapon(g) and
           int(g.get("position", 0)) == 1]
    return u.setdefault("fight_box", box)[:8]


ENERGY_MAX = 100
ENERGY_REGEN_SEC = 300   # 1 energy regenerated per 5 minutes


# exp threshold at each level, straight from the client's bundled xml.data
# (memlevelattr experience) so the emulator's mlevel matches BaseValues.getLevel.
LEVEL_EXPS = [0, 600, 1560, 3000, 4980, 7680, 11340, 16320, 23040, 31980, 43800,
              59280, 79380, 105240, 138180, 179760, 231720, 295980, 374640, 469980,
              584340, 720960, 883500, 1076100, 1303320, 1570260, 1882560, 2246340,
              2668320, 3155700, 3716160, 4357860, 5089380, 5919600, 6857700, 7913040,
              9094980, 10412820, 11875620, 13491960, 15269880, 17216700, 19338720,
              21641100, 24127620, 26800620, 29660700, 32706660, 35935320, 39341520,
              42918000, 46655400, 50542260, 54584580, 58788540, 63160620, 67707540,
              72436320, 77354220, 82468800]


def level_from_exp(exp):
    """exp -> level, mirroring client BaseValues.getLevel: first index i where
    exp < LEVEL_EXPS[i] (level_score[0]=0 never matches), else max level 45."""
    exp = int(exp or 0)
    for i, need in enumerate(LEVEL_EXPS):
        if exp < need:
            return i or 1
    return 45


QUEST_MSID_BASE = 500000


def walkthrough_quests():
    """Starter missions using action codes emitted by the actual game client."""
    return [
        {"id": 1, "name": "Selamat datang, Semut!", "description": "Capai level 1 untuk memulai petualangan.",
         "mtype": 1, "actioncode": 117, "target": "Capai level 1", "pcate": 0, "pframe": 0,
         "times": 1, "level": 1, "reward_coin": 25, "reward_exp": 10,
         "reward_typeID": 0, "reward_frameID": 0, "reward_count": 0, "enabled": True, "tutorial": True},
        {"id": 2, "name": "Periksa senjata awal", "description": "Pastikan senjata awal ada di tasmu.",
         "mtype": 1, "actioncode": 115, "target": "Miliki senjata awal", "pcate": 11, "pframe": 1091,
         "times": 1, "level": 1, "reward_coin": 25, "reward_exp": 10,
         "reward_typeID": 0, "reward_frameID": 0, "reward_count": 0, "enabled": True, "tutorial": True},
        {"id": 3, "name": "Pakai senjatamu", "description": "Equip senjata dari menu Tas.",
         "mtype": 1, "actioncode": 180, "target": "Pakai 1 alat/equipment", "pcate": 0, "pframe": 0,
         "times": 1, "level": 1, "reward_coin": 50, "reward_exp": 15,
         "reward_typeID": 0, "reward_frameID": 0, "reward_count": 0, "enabled": True, "tutorial": True},
        {"id": 4, "name": "Pertempuran pertama", "description": "Selesaikan satu pertempuran.",
         "mtype": 1, "actioncode": 176, "target": "Selesaikan 1 pertempuran", "pcate": 0, "pframe": 0,
         "times": 1, "level": 1, "reward_coin": 100, "reward_exp": 25,
         "reward_typeID": 0, "reward_frameID": 0, "reward_count": 0, "enabled": True, "tutorial": True},
        {"id": 5, "name": "Kenalan dengan semut lain", "description": "Tambahkan seorang teman.",
         "mtype": 1, "actioncode": 170, "target": "Miliki 1 teman", "pcate": 0, "pframe": 0,
         "times": 1, "level": 1, "reward_coin": 75, "reward_exp": 20,
         "reward_typeID": 0, "reward_frameID": 0, "reward_count": 0, "enabled": True, "tutorial": True},
    ]


def quest_msid(quest_id):
    return QUEST_MSID_BASE + int(quest_id)


def _quest_int(body, key, default=0):
    try:
        return int(body.get(key, default) or default)
    except (TypeError, ValueError):
        return int(default)


def create_quest(db, body):
    items = db.setdefault("quests", [])
    qid = max([int(q.get("id", 0)) for q in items] or [0]) + 1
    quest = {
        "id": qid,
        "name": str(body.get("name", "Quest %d" % qid)),
        "description": str(body.get("description", "")),
        "mtype": _quest_int(body, "mtype", 1),
        "actioncode": _quest_int(body, "actioncode", 176),
        "target": str(body.get("target", body.get("description", "Selesaikan tugas"))),
        "pcate": _quest_int(body, "pcate"),
        "pframe": _quest_int(body, "pframe"),
        "times": max(1, _quest_int(body, "times", 1)),
        "level": max(1, _quest_int(body, "level", 1)),
        "reward_coin": max(0, _quest_int(body, "reward_coin")),
        "reward_exp": max(0, _quest_int(body, "reward_exp")),
        "reward_typeID": _quest_int(body, "reward_typeID"),
        "reward_frameID": _quest_int(body, "reward_frameID"),
        "reward_count": max(0, _quest_int(body, "reward_count")),
        "enabled": bool(body.get("enabled", True)),
    }
    items.append(quest)
    return quest


def update_quest(db, quest_id, body):
    for quest in db.setdefault("quests", []):
        if int(quest.get("id", 0)) == int(quest_id):
            for key in ("name", "description", "target"):
                if key in body:
                    quest[key] = str(body[key])
            for key in ("mtype", "actioncode", "pcate", "pframe", "times", "level",
                        "reward_coin", "reward_exp", "reward_typeID", "reward_frameID",
                        "reward_count"):
                if key in body:
                    quest[key] = max(0, _quest_int(body, key))
            if "times" in body:
                quest["times"] = max(1, quest["times"])
            if "level" in body:
                quest["level"] = max(1, quest["level"])
            if "enabled" in body:
                quest["enabled"] = bool(body["enabled"])
            return quest
    return None


def delete_quest(db, quest_id):
    before = len(db.setdefault("quests", []))
    db["quests"] = [q for q in db["quests"] if int(q.get("id", 0)) != int(quest_id)]
    return len(db["quests"]) != before


def _quest_definition(quest):
    q = dict(quest)
    q["msid"] = quest_msid(q["id"])
    q["smsid"] = quest_msid(q["id"]) * 10 + 1
    return q


def _quest_item_count(user, type_id, frame_id):
    return sum(int(g.get("amount", g.get("count", 0)) or 0)
               for g in user.get("goods", [])
               if int(g.get("typeID", 0)) == int(type_id)
               and int(g.get("frameID", 0)) == int(frame_id))


def _quest_progress(db, user, quest):
    action = int(quest.get("actioncode", 0))
    if action == 117:
        return int(user.get("level", 1))
    if action == 115:
        return _quest_item_count(user, quest.get("pcate", 0), quest.get("pframe", 0))
    if action == 163:
        return 1 if any(int(g.get("typeID", 0)) == int(quest.get("pcate", 0))
                        and int(g.get("frameID", 0)) == int(quest.get("pframe", 0))
                        for g in avatar_gear_for_user(user)) else 0
    if action == 170:
        return len(friend_list_for_user(db, user["id"]))
    return int(user.setdefault("quest_progress", {}).get(str(quest["id"]), 0))


def quest_states_for_user(db, uid):
    user = get_user(db, uid)
    if user is None:
        return []
    rows = []
    for quest in db.get("quests", []):
        if not quest.get("enabled", True):
            continue
        definition = _quest_definition(quest)
        progress = min(_quest_progress(db, user, quest), int(quest.get("times", 1)))
        rewarded = str(quest["id"]) in user.setdefault("quest_rewarded", {})
        status = 2 if rewarded else (1 if progress >= int(quest.get("times", 1)) else 0)
        rows.append([int(quest["id"]), definition["msid"], status, 0,
                     [[0, definition["smsid"], progress]], definition])
    rows.sort(key=lambda row: (0 if row[5].get("tutorial") else 1, row[0]))
    return rows


def advance_quests(db, uid, actioncode, pcate=0, pframe=0, amount=1):
    user = get_user(db, uid)
    if user is None:
        return
    progress = user.setdefault("quest_progress", {})
    for quest in db.get("quests", []):
        if not quest.get("enabled", True) or int(quest.get("actioncode", 0)) != int(actioncode):
            continue
        if int(quest.get("pcate", 0)) not in (0, int(pcate)) or int(quest.get("pframe", 0)) not in (0, int(pframe)):
            continue
        qid = str(quest["id"])
        if qid not in user.setdefault("quest_rewarded", {}):
            progress[qid] = min(int(quest.get("times", 1)), int(progress.get(qid, 0)) + int(amount))


def claim_quest_reward(db, uid, quest_id):
    user = get_user(db, uid)
    quest = next((q for q in db.get("quests", []) if int(q.get("id", 0)) == int(quest_id)), None)
    if user is None or quest is None:
        return {"error": "quest not found"}
    if str(quest["id"]) in user.setdefault("quest_rewarded", {}):
        return {"error": "quest already rewarded"}
    if _quest_progress(db, user, quest) < int(quest.get("times", 1)):
        return {"error": "quest not finished"}
    coin = int(quest.get("reward_coin", 0)); exp = int(quest.get("reward_exp", 0))
    user["currency"] = int(user.get("currency", 0)) + coin
    user["exp"] = int(user.get("exp", 0)) + exp
    user["level"] = level_from_exp(user["exp"])
    props = []
    tid = int(quest.get("reward_typeID", 0)); fid = int(quest.get("reward_frameID", 0))
    for _ in range(max(0, int(quest.get("reward_count", 0)))):
        if tid and fid:
            give_good(db, uid, tid, fid, 1)
    if tid and fid:
        props = [goods_array(g) for g in user.get("goods", [])
                 if int(g.get("typeID", 0)) == tid and int(g.get("frameID", 0)) == fid]
    user.setdefault("quest_rewarded", {})[str(quest["id"])] = int(time.time())
    log_entry(db, "quest", uid, coin, "quest %s" % quest.get("name", quest_id))
    save_db(db)
    return [{"mid": uid, "mrolename": user.get("name", NAME), "mgender": user.get("sex", SEX),
             "mlevel": user["level"], "mpoint": user["exp"], "mwinning": user.get("wins", 0),
             "mfailure": user.get("losses", 0)},
            {"currency": user["currency"], "boyaacurrency": user.get("boyaa_coin", 0), "excertificate": 0},
            props]


def energy_now(u, now=None):
    """Current energy including time-based regen since last commit."""
    if u is None:
        return ENERGY_MAX
    en = int(u.get("energy", ENERGY_MAX))
    ts = int(u.get("energy_ts", 0))
    n = int(now or time.time())
    if ts and n > ts:
        en = min(ENERGY_MAX, en + (n - ts) // ENERGY_REGEN_SEC)
    return en


def energy_commit(u, en, now=None):
    """Persist energy + regen timestamp so regen counts from now."""
    u["energy"] = en
    u["energy_ts"] = int(now or time.time())


# Stable pseudo-identity; uid == mid.
UID = 1000001
NAME = "Semut"
GAME_SRV = None  # GameServer instance (set in start_sockets) for chat relay
SEX = 1
SESSION_KEY = "local-emulator-session"
GAME_SVIP = "127.0.0.1"
GAME_SVPORT = GAME_PORT
BATTLE_SVIP = "127.0.0.1"
BATTLE_SVPORT = BATTLE_PORT
COPY_SVIP = "127.0.0.1"
COPY_SVPORT = COPY_PORT

# ---------------------------------------------------------------------------
# Admin data store (persistent JSON) — users, goods, equipment
# ---------------------------------------------------------------------------

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
SQLITE_FILE = os.path.join(DATA_DIR, "db.sqlite3")
# Kept as a read-only migration/export backup for older local installations.
DATA_FILE = os.path.join(DATA_DIR, "db.json")
DATA_LOCK = threading.RLock()  # reentrant: load_db -> save_db on same thread

# readGoods() field order fed to the client socket:
# onlyID,typeID,frameID,count,attribute,synthesis,expiration,strengthen,
# position,term,amount,isbind,colorString
GOOD_FIELDS = ("onlyID", "typeID", "frameID", "count", "attribute", "synthesis",
               "expiration", "strengthen", "position", "term", "amount", "isbind", "color")


# resources manageable from the admin dashboard, besides users
RESOURCES = ("guilds", "shop", "friends", "monsters", "stages", "quests")


def resource_defaults():
    return {
        "guilds": [
            {"id": 1, "name": "Komando Semut", "leader": "Semut", "level": 3, "members": 12},
            {"id": 2, "name": "Pasukan Rerumput", "leader": "Ratu", "level": 2, "members": 8},
        ],
        "shop": [
            {"id": 1, "typeID": 11, "frameID": 1091, "name": "Pedang Semut", "price": 500},
            {"id": 2, "typeID": 26, "frameID": 1001, "name": "Pisau Madu", "price": 1200},
            {"id": 3, "typeID": 12, "frameID": 1102, "name": "Jubah Daun", "price": 3000},
            {"id": 4, "typeID": 14, "frameID": 1201, "name": "Topi Acorn", "price": 800},
        ],
        "friends": [
            {"id": 1, "name": "Kawan Kumbang", "level": 4, "online": True},
            {"id": 2, "name": "Teman Jangkrik", "level": 2, "online": False},
        ],
        "monsters": [
            # babySex 0=jantan 1=betina (shape ant in robot battle); props = item yang dikenakan
            {"id": 1, "name": "Laba Kuning", "level": 1, "hp": 50, "mapID": 1001,
             "babySex": 0, "props": [{"typeID": 11, "frameID": 1091}]},
            {"id": 2, "name": "Semut Api", "level": 3, "hp": 120, "mapID": 1001,
             "babySex": 1, "props": [{"typeID": 11, "frameID": 1102}, {"typeID": 5, "frameID": 1001}]},
            {"id": 3, "name": "Belalang Raja", "level": 8, "hp": 400, "mapID": 1001,
             "babySex": 0, "props": [{"typeID": 12, "frameID": 1102}]},
        ],
        "stages": [
            # copygame stages: reward relates monster + item (via typeID/frameID ke shop)
            {"id": 1, "name": "Kota Langit", "level": 1, "mapID": 1001, "monster_id": 1,
             "reward_coin": 60, "reward_exp": 20, "reward_typeID": 0, "reward_frameID": 0, "reward_count": 0},
            {"id": 2, "name": "Kota Langit", "level": 2, "mapID": 1001, "monster_id": 2,
             "reward_coin": 120, "reward_exp": 45, "reward_typeID": 11, "reward_frameID": 1091, "reward_count": 1},
            {"id": 3, "name": "Kota Laba-Laba", "level": 1, "mapID": 1002, "monster_id": 3,
             "reward_coin": 200, "reward_exp": 90, "reward_typeID": 12, "reward_frameID": 1102, "reward_count": 1},
            {"id": 4, "name": "Kota Peri", "level": 1, "mapID": 1003, "monster_id": 1,
             "reward_coin": 160, "reward_exp": 70, "reward_typeID": 0, "reward_frameID": 0, "reward_count": 0},
        ],
        "quests": walkthrough_quests(),
    }


def default_db():
    db = {"users": {}, "auth_users": {}, "auth_sessions": {},
          "admin_users": {}, "admin_sessions": {}}
    db.update(resource_defaults())
    db["users"][str(UID)] = {
        "id": UID,
        "name": NAME,
        "sex": SEX,
        "level": 1,
        "currency": 10000,
        "boyaa_coin": 0,
        "energy": 100,
        "exp": 0,
        "wins": 0,
        "losses": 0,
        "goods": [
            # tutorial starter weapon pre-equipped (slot weapon) so copygame /
            # robot battle stage entry passes the getWeapon().place==1 gate
            {"onlyID": 1, "typeID": 11, "frameID": 1091, "count": 1,
             "attribute": "", "synthesis": "", "expiration": 0, "strengthen": 0,
             "position": 1, "term": 0, "amount": 1, "isbind": 0, "color": 0,
             "slot": "weapon"},
            {"onlyID": 2, "typeID": 26, "frameID": 1001, "count": 5,
             "attribute": "", "synthesis": "", "expiration": 0, "strengthen": 0,
             "position": 0, "term": 0, "amount": 5, "isbind": 0, "color": 0},
        ],
    }
    db["ledger"] = []
    db["friendships"] = []
    db["friend_requests"] = []
    db["walkthrough_seeded"] = True
    return db


def _sqlite_create_schema(conn):
    conn.executescript("""
    PRAGMA foreign_keys=ON;
    CREATE TABLE IF NOT EXISTS users (
      id INTEGER PRIMARY KEY, name TEXT NOT NULL, sex INTEGER NOT NULL,
      level INTEGER NOT NULL, currency INTEGER NOT NULL, boyaa_coin INTEGER NOT NULL,
      energy INTEGER NOT NULL, exp INTEGER NOT NULL, wins INTEGER NOT NULL,
      losses INTEGER NOT NULL, born INTEGER NOT NULL DEFAULT 0, place TEXT NOT NULL DEFAULT '',
      extra_json TEXT NOT NULL DEFAULT '{}'
    );
    CREATE TABLE IF NOT EXISTS goods (
      only_id INTEGER NOT NULL, user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
      type_id INTEGER NOT NULL, frame_id INTEGER NOT NULL, count INTEGER NOT NULL,
      attribute TEXT NOT NULL, synthesis TEXT NOT NULL, expiration INTEGER NOT NULL,
      strengthen INTEGER NOT NULL, position INTEGER NOT NULL, term INTEGER NOT NULL,
      amount INTEGER NOT NULL, isbind INTEGER NOT NULL, color INTEGER NOT NULL,
      slot TEXT, extra_json TEXT NOT NULL DEFAULT '{}', PRIMARY KEY(user_id, only_id)
    );
    CREATE TABLE IF NOT EXISTS auth_users (
      id INTEGER PRIMARY KEY, email TEXT NOT NULL UNIQUE, password_hash TEXT NOT NULL,
      created INTEGER NOT NULL, gender TEXT NOT NULL, game_uid INTEGER NOT NULL REFERENCES users(id)
    );
    CREATE TABLE IF NOT EXISTS auth_sessions (
      token TEXT PRIMARY KEY, user_id INTEGER NOT NULL, email TEXT NOT NULL, created INTEGER NOT NULL
    );
    CREATE TABLE IF NOT EXISTS admin_users (
      id INTEGER PRIMARY KEY, email TEXT NOT NULL UNIQUE, password_hash TEXT NOT NULL, created INTEGER NOT NULL
    );
    CREATE TABLE IF NOT EXISTS admin_sessions (
      token TEXT PRIMARY KEY, admin_id INTEGER NOT NULL, email TEXT NOT NULL, created INTEGER NOT NULL
    );
    CREATE TABLE IF NOT EXISTS friendships (
      a INTEGER NOT NULL, b INTEGER NOT NULL, status TEXT NOT NULL, PRIMARY KEY(a,b)
    );
    CREATE TABLE IF NOT EXISTS friend_requests (
      id INTEGER PRIMARY KEY, from_id INTEGER NOT NULL, to_id INTEGER NOT NULL, status TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS resources (
      collection TEXT NOT NULL, item_id INTEGER NOT NULL, payload TEXT NOT NULL,
      PRIMARY KEY(collection,item_id)
    );
    CREATE TABLE IF NOT EXISTS ledger (
      id INTEGER PRIMARY KEY, payload TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS chat (
      id INTEGER PRIMARY KEY, ts INTEGER NOT NULL, kind TEXT NOT NULL, type INTEGER NOT NULL,
      uid INTEGER NOT NULL, name TEXT NOT NULL, message TEXT NOT NULL, to_uid INTEGER, payload TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL);
    """)


def _sqlite_migrate_goods_key(conn):
    columns = conn.execute("PRAGMA table_info(goods)").fetchall()
    primary = [row[1] for row in columns if row[5]]
    if primary != ["only_id"]:
        return
    conn.execute("ALTER TABLE goods RENAME TO goods_legacy")
    conn.execute("""CREATE TABLE goods (
      only_id INTEGER NOT NULL, user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
      type_id INTEGER NOT NULL, frame_id INTEGER NOT NULL, count INTEGER NOT NULL,
      attribute TEXT NOT NULL, synthesis TEXT NOT NULL, expiration INTEGER NOT NULL,
      strengthen INTEGER NOT NULL, position INTEGER NOT NULL, term INTEGER NOT NULL,
      amount INTEGER NOT NULL, isbind INTEGER NOT NULL, color INTEGER NOT NULL,
      slot TEXT, extra_json TEXT NOT NULL DEFAULT '{}', PRIMARY KEY(user_id, only_id)
    )""")
    conn.execute("""INSERT INTO goods SELECT only_id,user_id,type_id,frame_id,count,attribute,
      synthesis,expiration,strengthen,position,term,amount,isbind,color,slot,extra_json
      FROM goods_legacy""")
    conn.execute("DROP TABLE goods_legacy")


def _sqlite_load_db(conn):
    db = {"users": {}, "auth_users": {}, "auth_sessions": {}, "admin_users": {},
          "admin_sessions": {}, "friendships": [], "friend_requests": [], "ledger": [], "chat": []}
    user_rows = conn.execute("SELECT id,name,sex,level,currency,boyaa_coin,energy,exp,wins,losses,born,place,extra_json FROM users").fetchall()
    if not user_rows:
        return None
    for row in user_rows:
        (uid, name, sex, level, currency, boyaa_coin, energy, exp, wins, losses,
         born, place, extra_json) = row
        user = json.loads(extra_json or "{}")
        user.update({"id": uid, "name": name, "sex": sex, "level": level, "currency": currency,
                     "boyaa_coin": boyaa_coin, "energy": energy, "exp": exp, "wins": wins,
                     "losses": losses, "born": born, "place": place, "goods": []})
        db["users"][str(uid)] = user
    for row in conn.execute("SELECT only_id,user_id,type_id,frame_id,count,attribute,synthesis,expiration,strengthen,position,term,amount,isbind,color,slot,extra_json FROM goods"):
        (only_id, user_id, type_id, frame_id, count, attribute, synthesis, expiration, strengthen,
         position, term, amount, isbind, color, slot, extra_json) = row
        good = json.loads(extra_json or "{}")
        good.update({"onlyID": only_id, "typeID": type_id, "frameID": frame_id, "count": count,
                     "attribute": attribute, "synthesis": synthesis, "expiration": expiration,
                     "strengthen": strengthen, "position": position, "term": term, "amount": amount,
                     "isbind": isbind, "color": color})
        if slot is not None:
            good["slot"] = slot
        if str(user_id) in db["users"]:
            db["users"][str(user_id)]["goods"].append(good)
    for row in conn.execute("SELECT id,email,password_hash,created,gender,game_uid FROM auth_users"):
        db["auth_users"][row[1]] = {"id": row[0], "email": row[1], "password_hash": row[2], "created": row[3], "gender": row[4], "game_uid": row[5]}
    for row in conn.execute("SELECT token,user_id,email,created FROM auth_sessions"):
        db["auth_sessions"][row[0]] = {"user_id": row[1], "email": row[2], "created": row[3]}
    for row in conn.execute("SELECT id,email,password_hash,created FROM admin_users"):
        db["admin_users"][row[1]] = {"id": row[0], "email": row[1], "password_hash": row[2], "created": row[3]}
    for row in conn.execute("SELECT token,admin_id,email,created FROM admin_sessions"):
        db["admin_sessions"][row[0]] = {"admin_id": row[1], "email": row[2], "created": row[3]}
    db["friendships"] = [{"a": r[0], "b": r[1], "status": r[2]} for r in conn.execute("SELECT a,b,status FROM friendships")]
    db["friend_requests"] = [{"id": r[0], "from_id": r[1], "to_id": r[2], "status": r[3]} for r in conn.execute("SELECT id,from_id,to_id,status FROM friend_requests")]
    for collection, item_id, payload in conn.execute("SELECT collection,item_id,payload FROM resources"):
        db.setdefault(collection, []).append(json.loads(payload))
    db["ledger"] = [json.loads(r[0]) for r in conn.execute("SELECT payload FROM ledger ORDER BY id")]
    db["chat"] = [json.loads(r[0]) for r in conn.execute("SELECT payload FROM chat ORDER BY id")]
    db["walkthrough_seeded"] = conn.execute("SELECT value FROM metadata WHERE key='walkthrough_seeded'").fetchone() == ("1",)
    return db


def _normalize_loaded_db(db):
    changed = False
    if str(UID) not in db.setdefault("users", {}):
        db["users"][str(UID)] = {"id": UID, "name": NAME, "sex": SEX,
                                   "level": 1, "currency": 10000, "boyaa_coin": 0,
                                   "energy": 100, "exp": 0, "wins": 0, "losses": 0,
                                   "goods": []}
        changed = True
    for key in RESOURCES:
        if key not in db:
            db[key] = resource_defaults()[key]
            changed = True
    for key, default in (("ledger", []), ("auth_users", {}), ("auth_sessions", {}),
                         ("admin_users", {}), ("admin_sessions", {}),
                         ("friendships", []), ("friend_requests", []), ("chat", [])):
        if key not in db:
            db[key] = default
            changed = True
    for user in db.get("users", {}).values():
        if not user.get("goods"):
            user["goods"] = [{"onlyID": 1, "typeID": 11, "frameID": 1091,
                               "count": 1, "attribute": "", "synthesis": "",
                               "expiration": 0, "strengthen": 0, "position": 1,
                               "term": 0, "amount": 1, "isbind": 0, "color": 0,
                               "slot": "weapon"}]
            changed = True
    existing = {(int(q.get("actioncode", 0)), str(q.get("target", "")))
                for q in db.get("quests", [])}
    next_id = max([int(q.get("id", 0)) for q in db.get("quests", [])] or [0]) + 1
    for quest in walkthrough_quests():
        signature = (int(quest["actioncode"]), str(quest["target"]))
        if signature not in existing:
            item = dict(quest)
            item["id"] = next_id
            next_id += 1
            db.setdefault("quests", []).append(item)
            existing.add(signature)
            changed = True
        else:
            for current in db.get("quests", []):
                if (int(current.get("actioncode", 0)), str(current.get("target", ""))) == signature \
                        and not current.get("tutorial"):
                    current["tutorial"] = True
                    changed = True
    if not db.get("walkthrough_seeded"):
        db["walkthrough_seeded"] = True
        changed = True
    return changed


def _sqlite_save_db(conn, db):
    _sqlite_create_schema(conn)
    # Delete dependent rows before their parent rows; auth_users and goods
    # reference users through foreign keys.
    for table in ("goods", "auth_users", "auth_sessions", "admin_sessions", "admin_users",
                  "friend_requests", "friendships", "users", "resources", "ledger", "chat", "metadata"):
        conn.execute("DELETE FROM " + table)
    user_columns = {"id", "name", "sex", "level", "currency", "boyaa_coin", "energy", "exp", "wins", "losses", "born", "place", "goods"}
    for uid, user in db.get("users", {}).items():
        extra = {k: v for k, v in user.items() if k not in user_columns}
        conn.execute("INSERT INTO users VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)", (int(user.get("id", uid)), user.get("name", "Semut"), int(user.get("sex", 1)), int(user.get("level", 1)), int(user.get("currency", 0)), int(user.get("boyaa_coin", 0)), int(user.get("energy", 0)), int(user.get("exp", 0)), int(user.get("wins", 0)), int(user.get("losses", 0)), int(user.get("born", 0) or 0), str(user.get("place", "")), json.dumps(extra, ensure_ascii=False)))
        for good in user.get("goods", []):
            known = {"onlyID", "typeID", "frameID", "count", "attribute", "synthesis", "expiration", "strengthen", "position", "term", "amount", "isbind", "color", "slot"}
            extra_good = {k: v for k, v in good.items() if k not in known}
            conn.execute("INSERT INTO goods VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (int(good.get("onlyID", 0)), int(user.get("id", uid)), int(good.get("typeID", 0)), int(good.get("frameID", 0)), int(good.get("count", 0)), str(good.get("attribute", "")), str(good.get("synthesis", "")), int(good.get("expiration", 0)), int(good.get("strengthen", 0)), int(good.get("position", 0)), int(good.get("term", 0)), int(good.get("amount", 0)), int(good.get("isbind", 0)), int(good.get("color", 0)), good.get("slot"), json.dumps(extra_good, ensure_ascii=False)))
    for email, account in db.get("auth_users", {}).items():
        conn.execute("INSERT INTO auth_users VALUES(?,?,?,?,?,?)", (int(account["id"]), email, account.get("password_hash", ""), int(account.get("created", 0)), account.get("gender", "female"), int(account.get("game_uid", 0))))
    for token, session in db.get("auth_sessions", {}).items():
        conn.execute("INSERT INTO auth_sessions VALUES(?,?,?,?)", (token, int(session.get("user_id", 0)), session.get("email", ""), int(session.get("created", 0))))
    for email, account in db.get("admin_users", {}).items():
        conn.execute("INSERT INTO admin_users VALUES(?,?,?,?)", (int(account["id"]), email, account.get("password_hash", ""), int(account.get("created", 0))))
    for token, session in db.get("admin_sessions", {}).items():
        conn.execute("INSERT INTO admin_sessions VALUES(?,?,?,?)", (token, int(session.get("admin_id", 0)), session.get("email", ""), int(session.get("created", 0))))
    conn.executemany("INSERT INTO friendships VALUES(?,?,?)", [(int(r.get("a", 0)), int(r.get("b", 0)), r.get("status", "accepted")) for r in db.get("friendships", [])])
    conn.executemany("INSERT INTO friend_requests VALUES(?,?,?,?)", [(int(r.get("id", i + 1)), int(r.get("from_id", 0)), int(r.get("to_id", 0)), r.get("status", "pending")) for i, r in enumerate(db.get("friend_requests", []))])
    for collection in RESOURCES:
        for i, item in enumerate(db.get(collection, []), 1):
            conn.execute("INSERT INTO resources VALUES(?,?,?)", (collection, int(item.get("id", i)), json.dumps(item, ensure_ascii=False)))
    conn.executemany("INSERT INTO ledger VALUES(?,?)", [(i, json.dumps(row, ensure_ascii=False)) for i, row in enumerate(db.get("ledger", []), 1)])
    conn.executemany("INSERT INTO chat VALUES(?,?,?,?,?,?,?,?,?)", [(i, int(row.get("ts", 0)), row.get("kind", "world"), int(row.get("type", 0)), int(row.get("uid", 0)), row.get("name", ""), row.get("str", ""), row.get("to"), json.dumps(row, ensure_ascii=False)) for i, row in enumerate(db.get("chat", []), 1)])
    conn.execute("INSERT INTO metadata VALUES('walkthrough_seeded', ?)", ("1" if db.get("walkthrough_seeded") else "0",))
    conn.execute("DROP TABLE IF EXISTS app_state")


def load_db():
    with DATA_LOCK:
        os.makedirs(DATA_DIR, exist_ok=True)
        try:
            with sqlite3.connect(SQLITE_FILE, timeout=30) as conn:
                conn.execute("PRAGMA journal_mode=WAL")
                conn.execute("PRAGMA synchronous=NORMAL")
                _sqlite_create_schema(conn)
                _sqlite_migrate_goods_key(conn)
                db = _sqlite_load_db(conn)
                if db is not None:
                    if _normalize_loaded_db(db):
                        _sqlite_save_db(conn, db)
                    return db
                old = conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='app_state'").fetchone()
                if old:
                    payload = conn.execute("SELECT payload FROM app_state WHERE id=1").fetchone()
                    if payload:
                        db = json.loads(payload[0])
                        _normalize_loaded_db(db)
                        _sqlite_save_db(conn, db)
                        return db
        except (OSError, sqlite3.Error, TypeError, ValueError, json.JSONDecodeError):
            pass
        if os.path.isfile(DATA_FILE):
            try:
                with open(DATA_FILE) as f:
                    db = json.load(f)
                _normalize_loaded_db(db)
                save_db(db)
                return db
            except (OSError, TypeError, ValueError, json.JSONDecodeError):
                pass
        db = default_db()
        save_db(db)
        return db


def save_db(db):
    with DATA_LOCK:
        os.makedirs(DATA_DIR, exist_ok=True)
        with sqlite3.connect(SQLITE_FILE, timeout=30) as conn:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA synchronous=NORMAL")
            _sqlite_save_db(conn, db)


AUTH_ITERATIONS = 310000


def _auth_hash(password):
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", str(password).encode("utf-8"), salt, AUTH_ITERATIONS)
    return "pbkdf2_sha256$%d$%s$%s" % (AUTH_ITERATIONS, salt.hex(), digest.hex())


def _auth_verify(password, stored):
    stored = str(stored or "")
    if stored.startswith("pbkdf2_sha256$"):
        try:
            _, iterations, salt_hex, digest_hex = stored.split("$", 3)
            candidate = hashlib.pbkdf2_hmac(
                "sha256", str(password).encode("utf-8"), bytes.fromhex(salt_hex), int(iterations)
            ).hex()
            return secrets.compare_digest(candidate, digest_hex)
        except (ValueError, TypeError):
            return False
    # Compatibility for accounts created by the first local prototype.
    return secrets.compare_digest(stored, hashlib.sha256(str(password).encode("utf-8")).hexdigest())


def _auth_public(account):
    return {"id": int(account["id"]), "email": account["email"],
            "name": account.get("name", account["email"].split("@")[0]),
            "gender": account.get("gender", "female"),
            "game_uid": int(account.get("game_uid", 0))}


def _create_game_user(db, account_id, name, gender="female"):
    users = db.setdefault("users", {})
    game_uid = max([int(uid) for uid in users] or [1000000]) + 1
    template = copy.deepcopy(users.get(str(UID), {}))
    user = {
        "id": game_uid, "name": str(name), "sex": 0 if gender == "male" else 1,
        "level": 1, "currency": 10000, "boyaa_coin": 0, "energy": 100,
        "exp": 0, "wins": 0, "losses": 0,
        "goods": copy.deepcopy(template.get("goods", [])),
    }
    if not user["goods"]:
        user["goods"] = [{"onlyID": 1, "typeID": 11, "frameID": 1091,
                           "count": 1, "amount": 1, "position": 1,
                           "slot": "weapon", "attribute": "", "synthesis": "",
                           "expiration": 0, "strengthen": 0, "term": 0,
                           "isbind": 0, "color": 0}]
    users[str(game_uid)] = user
    return game_uid


def auth_register(db, email, password, name="", gender="female"):
    email = str(email or "").strip().lower()
    password = str(password or "")
    name = str(name or "").strip() or email.split("@")[0]
    gender = str(gender or "").strip().lower()
    if not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", email):
        return {"ok": False, "error": "email tidak valid"}
    if len(password) < 6:
        return {"ok": False, "error": "password minimal 6 karakter"}
    if gender not in ("male", "female"):
        return {"ok": False, "error": "gender tidak valid"}
    accounts = db.setdefault("auth_users", {})
    if email in accounts:
        return {"ok": False, "error": "email sudah terdaftar"}
    next_id = max([int(a.get("id", 0)) for a in accounts.values()] or [0]) + 1
    account = {"id": next_id, "email": email, "name": name,
               "password_hash": _auth_hash(password), "created": int(time.time()),
               "gender": gender}
    account["game_uid"] = _create_game_user(db, next_id, name, gender)
    accounts[email] = account
    return {"ok": True, "user": _auth_public(account)}


def auth_login(db, email, password):
    email = str(email or "").strip().lower()
    account = db.setdefault("auth_users", {}).get(email)
    if account is None or not _auth_verify(password, account.get("password_hash")):
        return {"ok": False, "error": "email atau password salah"}
    if not account.get("game_uid"):
        account["game_uid"] = _create_game_user(
            db, account["id"], account.get("name", email.split("@")[0]), account.get("gender", "female")
        )
    token = secrets.token_urlsafe(32)
    db.setdefault("auth_sessions", {})[token] = {"user_id": int(account["id"]),
                                                  "email": email,
                                                  "created": int(time.time())}
    return {"ok": True, "token": token, "user": _auth_public(account)}


def auth_me(db, token):
    session = db.setdefault("auth_sessions", {}).get(str(token or ""))
    if session is None:
        return None
    account = next((a for a in db.setdefault("auth_users", {}).values()
                    if int(a.get("id", 0)) == int(session.get("user_id", 0))), None)
    return _auth_public(account) if account else None


def auth_logout(db, token):
    return db.setdefault("auth_sessions", {}).pop(str(token or ""), None) is not None


def ensure_admin_auth(db):
    """Create one local bootstrap admin, without ever storing its plaintext password."""
    admins = db.setdefault("admin_users", {})
    db.setdefault("admin_sessions", {})
    email = os.environ.get("ADMIN_EMAIL", "admin@local.test").strip().lower()
    password = os.environ.get("ADMIN_PASSWORD", "admin12345")
    if not admins:
        admins[email] = {"id": 1, "email": email,
                         "password_hash": _auth_hash(password),
                         "created": int(time.time())}
        save_db(db)
    return admins


def admin_login(db, email, password):
    email = str(email or "").strip().lower()
    account = db.setdefault("admin_users", {}).get(email)
    if account is None or not _auth_verify(password, account.get("password_hash")):
        return {"ok": False, "error": "email atau password admin salah"}
    token = secrets.token_urlsafe(32)
    db.setdefault("admin_sessions", {})[token] = {"admin_id": int(account["id"]),
                                                  "email": email,
                                                  "created": int(time.time())}
    return {"ok": True, "token": token, "admin": {"id": int(account["id"]), "email": email}}


def admin_me(db, token):
    session = db.setdefault("admin_sessions", {}).get(str(token or ""))
    if not session:
        return None
    return {"id": int(session.get("admin_id", 0)), "email": session.get("email", "")}


def admin_logout(db, token):
    return db.setdefault("admin_sessions", {}).pop(str(token or ""), None) is not None


def get_user(db, uid):
    u = db["users"].get(str(uid))
    if u is None:
        return None
    normalize_user_goods(u)
    # keep every good's onlyID within the user unique
    have = {g["onlyID"] for g in u.get("goods", [])}
    nx = 1
    while nx in have:
        nx += 1
    u["_nextOnlyID"] = nx
    return u


def give_good(db, uid, typeID, frameID, count, place=0, slot=None):
    u = db["users"].get(str(uid))
    if u is None:
        return False
    g = {"onlyID": get_user(db, uid)["_nextOnlyID"], "typeID": int(typeID),
         "frameID": int(frameID), "count": int(count), "attribute": "",
         "synthesis": "", "expiration": 0, "strengthen": 0, "position": int(place),
         "term": 0, "amount": int(count), "isbind": 0, "color": 0}
    if slot:
        g["slot"] = str(slot)
    u["goods"].append(g)
    normalize_user_goods(u)
    save_db(db)
    return True


def cat_price(db, tid, fid):
    """Authoritative shop price/name for a goods tuple (sync admin toko -> game)."""
    for it in db.get("shop", []):
        if int(it.get("typeID", 0)) == tid and int(it.get("frameID", 0)) == fid:
            return int(it.get("price", 0)), it.get("name", "")
    return None, None


LEDGER_LIMIT = 300


def log_entry(db, kind, uid, delta, note):
    """Append a coin ledger entry (economy module); trim to LEDGER_LIMIT."""
    entries = db.setdefault("ledger", [])
    entries.append({"ts": int(time.time()), "kind": kind, "uid": uid,
                    "delta": int(delta), "note": note})
    del entries[:-LEDGER_LIMIT]


def grant_reward(db, uid, coin, exp, gtype, gfid, gcount, note):
    """Shared reward grant (copy prize, admin stage grant). Returns post-state
    dict or None when the user is missing."""
    u = get_user(db, uid)
    if u is None:
        return None
    u["currency"] = int(u.get("currency", 0)) + int(coin)
    u["exp"] = int(u.get("exp", 0)) + int(exp)
    u["level"] = level_from_exp(u["exp"])
    advance_quests(db, uid, 176, amount=1)
    props = []
    if gtype and gfid and gcount > 0:
        for _ in range(max(1, int(gcount))):
            give_good(db, uid, gtype, gfid, 1)
        props = [goods_array(g) for g in u["goods"]
                 if int(g.get("typeID", 0)) == gtype and int(g.get("frameID", 0)) == gfid]
    log_entry(db, "grant", uid, int(coin), note)
    save_db(db)
    return {"currency": u["currency"], "exp": u["exp"], "level": u["level"], "props": props}


def write_goods(w, g):
    """Emit one readGoods() array in the client's expected field order."""
    w.int(int(g.get("onlyID", 0)))
    w.int(int(g.get("typeID", 0)))
    w.int(int(g.get("frameID", 0)))
    w.int(int(g.get("count", 0)))
    w.string(str(g.get("attribute", "")))
    w.string(str(g.get("synthesis", "")))
    w.int(int(g.get("expiration", 0)))
    w.int(int(g.get("strengthen", 0)))
    w.int(int(g.get("position", 0)))   # 0 bag / 1 equipped
    w.int(int(g.get("term", 0)))
    w.int(int(g.get("amount", 0)))
    w.int(int(g.get("isbind", 0)))
    w.string(str(g.get("color", 0)))


def admin_state(db):
    users = []
    for uid, u in db["users"].items():
        normalize_user_goods(u)
        users.append({
            "id": int(uid),
            "name": u.get("name", ""),
            "sex": u.get("sex", 0),
            "level": u.get("level", 1),
            "currency": u.get("currency", 0),
            "boyaa_coin": u.get("boyaa_coin", 0),
            "exp": u.get("exp", 0),
            "energy": u.get("energy", 0),
            "wins": u.get("wins", 0),
            "losses": u.get("losses", 0),
            "goods": u.get("goods", []),
        })
    state = {"users": users}
    for k in RESOURCES:
        state[k] = db.get(k, [])
    state["totals"] = {
        "users": len(users),
        "goods": sum(len(u.get("goods", [])) for u in db["users"].values()),
        **{k: len(state[k]) for k in RESOURCES},
    }
    return state




DB = load_db()
ensure_admin_auth(DB)


log_lock = threading.Lock()


def log(tag, msg):
    with log_lock:
        print("[%s] %s" % (tag, msg), flush=True)


# ---------------------------------------------------------------------------
# Request stats — rolling per-minute buckets for the admin dashboard charts.
# ---------------------------------------------------------------------------
REQ_LOCK = threading.Lock()
REQ_TOTALS = {}   # category -> count
REQ_BUCKETS = {}  # minute_ts -> {category: count}


def req_cat(path):
    p = urllib.parse.urlparse(path).path
    if p.startswith("/admin/api/"):
        return "admin api"
    if p.startswith("/admin"):
        return "admin page"
    if p in ("/asset_img", "/goods_icon", "/map_img", "/avatar_img"):
        return "gambar"
    if p.startswith(BASE):
        rel = p[len(BASE):]
        if rel.startswith("/mobile/"):
            return "mobile api"
        if rel.startswith("/api/flashapi"):
            return "flashapi"
        if rel.startswith("/version/"):
            return "aset game"
        return "resource"
    return "lainnya"


def track_req(path):
    now = int(time.time())
    m = now // 60
    with REQ_LOCK:
        c = req_cat(path)
        REQ_TOTALS[c] = REQ_TOTALS.get(c, 0) + 1
        b = REQ_BUCKETS.setdefault(m, {})
        b[c] = b.get(c, 0) + 1
        for old in [k for k in REQ_BUCKETS if k < m - 60]:
            del REQ_BUCKETS[old]


def req_stats():
    with REQ_LOCK:
        minutes = sorted(REQ_BUCKETS)[-60:]
        per_min = []
        for m in minutes:
            b = REQ_BUCKETS[m]
            per_min.append({"t": m * 60, "total": sum(b.values()), **b})
        return {"total": sum(REQ_TOTALS.values()),
                "by_cat": dict(REQ_TOTALS),
                "per_min": per_min}


# ---------------------------------------------------------------------------
# HTTP
# ---------------------------------------------------------------------------

def role_payload():
    """GameMember.load response (see ReadSelfData.setLoadData)."""
    now = int(time.time())
    u = get_user(DB, UID)
    if u is None:
        u = default_db()["users"][str(UID)]
    name = u.get("name", NAME)
    sex = u.get("sex", SEX)
    lvl = level_from_exp(u.get("exp", 0))
    return {
        "user": [
            UID,        # 0 uid
            name,       # 1 name
            sex,        # 2 sex
            "", "", "",  # 3-5
            now - 86400,  # 6 firstLogTime
            1, 1,       # 7, 8 hasRole == 1 (skip CreateRole)
            "",         # 9
            0,          # 10 webSid
            0, "",      # 11,12
            "Lokal",    # 13 reside
            "", 1,      # 14,15 loginDays
        ],
        "role": {
            "mrolename": name,
            "mgender": sex,
            "mlevel": lvl,
            "mwinning": u.get("wins", 0),
            "mfailure": u.get("losses", 0),
            "mpoint": u.get("exp", 0),
            "mflee": 0,
            "appearance": 0,
            "freshpack": 1,  # 0 => client force-enters FRESHGAMEWORLD tutorial (Game.as:378)
        },
        "account": {
            "currency": u.get("currency", 0),
            "boyaacurrency": u.get("boyaa_coin", 0),
            "excertificate": 0,
            "auctecoin": 0,
        },
        "sessionkey": SESSION_KEY,
        "time": now,
        "luckdraw": 0,
        "hashouse": 0,
    }


# --- Teman / Serikat (friends & union) serializers -------------------------
# Field shapes pinned to the client (FriendData.readPHPData,
# UnionListItemModel.createData, PlayerData.addData). All sourced from DB.


def self_guild():
    """Guild owned by the player: leader name matches, else the first guild."""
    gs = DB.get("guilds", [])
    for g in gs:
        if str(g.get("leader", "")) == str(NAME):
            return g
    return gs[0] if gs else None


def guild_obj(g):
    """UnionListItemModel.createData field map (camelCase, from client)."""
    gid = int(g.get("id", 0))
    return {
        "cid": gid,
        "cname": g.get("name", ""),
        "captainmid": int(g.get("leader_id", UID) or UID),
        "memnum": int(g.get("members", 1) or 1),
        "reqlevel": int(g.get("reqlevel", 1) or 1),
        "reqcap": 0,
        "cdevote": int(g.get("devote", 0) or 0),
        "chonour": int(g.get("honour", 0) or 0),
        "clevel": int(g.get("level", 1) or 1),
        "smithylevel": 0,
        "shoplevel": 0,
        "storelevel": 0,
        "ctime": int(g.get("created", 0) or 0),
        "statue": 0,
        "vcaptain": g.get("leader", g.get("name", "")),
        "conf": {"1": "Ketua", "2": "Wakil", "8": "Anggota Baik", "9": "Anggota"},
        "cdesc": g.get("notice", "") or g.get("intro", ""),
        "total": int(g.get("build", 0) or 0),
        "applynum": 0,
    }


def friend_array(f):
    """FriendData.readPHPData: [antId, level, nickName, sex, marrayState]."""
    return [int(f.get("id", 0)), int(f.get("level", 1) or 1),
            f.get("name", ""), int(f.get("sex", 1) or 1), 0]


def search_users(db, uid, query=""):
    needle = str(query or "").strip().lower()
    rows = []
    for user in db.get("users", {}).values():
        if int(user.get("id", 0)) == int(uid):
            continue
        haystack = "%s %s" % (user.get("name", ""), user.get("id", ""))
        if not needle or needle in haystack.lower():
            rows.append({"id": int(user["id"]), "name": user.get("name", "Semut"),
                         "level": int(user.get("level", 1)), "sex": int(user.get("sex", 1))})
    return sorted(rows, key=lambda row: (row["name"].lower(), row["id"]))


def _friend_key(a, b):
    return tuple(sorted((int(a), int(b))))


def friend_list_for_user(db, uid):
    friends = []
    for relation in db.setdefault("friendships", []):
        if relation.get("status") != "accepted":
            continue
        if int(relation.get("a", 0)) == int(uid):
            friend_id = int(relation.get("b", 0))
        elif int(relation.get("b", 0)) == int(uid):
            friend_id = int(relation.get("a", 0))
        else:
            continue
        user = db.get("users", {}).get(str(friend_id))
        if user:
            friends.append({"id": friend_id, "name": user.get("name", "Semut"),
                            "level": int(user.get("level", 1)), "sex": int(user.get("sex", 1))})
    return sorted(friends, key=lambda row: (row["name"].lower(), row["id"]))


def pending_friend_requests(db, uid):
    return [r for r in db.setdefault("friend_requests", [])
            if r.get("status") == "pending" and int(r.get("to_id", 0)) == int(uid)]


def request_friend(db, from_id, to_id):
    from_id, to_id = int(from_id), int(to_id)
    if from_id == to_id or str(to_id) not in db.get("users", {}):
        return {"ok": False, "error": "user tidak ditemukan"}
    if _friend_key(from_id, to_id) in {
        _friend_key(r.get("a", 0), r.get("b", 0)) for r in db.setdefault("friendships", [])
    }:
        return {"ok": False, "error": "sudah berteman"}
    for request in pending_friend_requests(db, to_id):
        if int(request.get("from_id", 0)) == from_id:
            return request
    for request in pending_friend_requests(db, from_id):
        if int(request.get("from_id", 0)) == to_id:
            accept_friend(db, from_id, to_id)
            return {"ok": True, "status": "accepted"}
    request = {"id": len(db.setdefault("friend_requests", [])) + 1,
               "from_id": from_id, "to_id": to_id, "status": "pending"}
    db["friend_requests"].append(request)
    return request


def accept_friend(db, uid, from_id):
    for request in db.setdefault("friend_requests", []):
        if (request.get("status") == "pending" and int(request.get("to_id", 0)) == int(uid)
                and int(request.get("from_id", 0)) == int(from_id)):
            request["status"] = "accepted"
            db.setdefault("friendships", []).append({"a": min(int(uid), int(from_id)),
                                                      "b": max(int(uid), int(from_id)),
                                                      "status": "accepted"})
            return True
    return False


def delete_friend(db, uid, friend_id):
    key = _friend_key(uid, friend_id)
    before = len(db.setdefault("friendships", []))
    db["friendships"] = [r for r in db["friendships"]
                          if _friend_key(r.get("a", 0), r.get("b", 0)) != key]
    return len(db["friendships"]) < before


def player_array(u, cid=0, cname=""):
    """PlayerData.addData 16-field member array (union member / rank rows)."""
    return [int(u.get("id", UID)), u.get("name", NAME), int(u.get("sex", SEX)),
            "", "", 0, "1|1|1|1", int(u.get("exp", 0)), int(u.get("wins", 0)),
            int(u.get("losses", 0)), 0, 1, int(u.get("born", 0) or 0), "", "",
            {"cid": cid, "cname": cname}]


def handle_flashapi(body: dict):
    global UID
    request_uid = body.get("mid")
    if request_uid is not None and str(request_uid) in DB.get("users", {}):
        UID = int(request_uid)
    method = body.get("method", "")
    log("HTTP", "flashapi method=%s" % method)
    if method == "GameMember.load":
        return role_payload()
    if method == "GameMember.create":
        payload = role_payload()
        payload["ret"] = 1
        return payload
    if method == "GameSAR.getCenterSever":
        return {
            "ret": 0,
            "list": [{
                "mgid": 1,
                "svtype": 2,
                "svip": GAME_SVIP,
                "svport": GAME_SVPORT,
                "startRoomId": 1,
                "endRoomId": 100,
                "svid": 1,
            }],
        }
    if method == "GameMember.getMission":
        return quest_states_for_user(DB, UID)
    if method == "GameMember.getMissionPrize":
        param = body.get("param") or []
        quest_id = param[0] if isinstance(param, list) and param else 0
        return claim_quest_reward(DB, UID, quest_id)
    if method == "GameMember.getNewWeapon":
        # FreshGameWorld callback dereferences data.role + data.prop; missing
        # fields NPE and abort the tutorial startup (ctrlStart never runs).
        # goods: [onlyID,typeID,frameID,stutas,attribute,synthesis,expiration,
        #         strengthenExp,position,termofvalidity,amount,isbind]
        return {
            "ret": 0,
            "role": {
                "mid": UID,
                "mrolename": NAME,
                "mgender": SEX,
                "mlevel": 1,
                "mwinning": 0,
                "mfailure": 0,
                "mpoint": 0,
                "mflee": 0,
                "mkill": 0,
                "appearance": 0,
            },
            "prop": [[1, 11, 1091, 0, "", "", 0, 0, 0, 0, 1, 0]],
        }
    param = body.get("param")
    if method == "GameFriends.getFrds":
        # Client callback does addData(rawArray) — return only this user's friends.
        return [friend_array(f) for f in friend_list_for_user(DB, UID)]
    if method == "GameFriends.addFriend":
        fid = int(param[0]) if isinstance(param, list) and param else 0
        result = request_friend(DB, UID, fid)
        if result.get("status") == "accepted":
            advance_quests(DB, UID, 170, amount=1)
        save_db(DB)
        return {"ret": 0 if result.get("ok", True) else 1, "status": result.get("status", "pending"),
                "error": result.get("error", "")}
    if method == "GameFriends.deleteFriend":
        fid = int(param[0]) if isinstance(param, list) and param else 0
        delete_friend(DB, UID, fid)
        save_db(DB)
        return {"ret": 0}
    if method == "GameFriends.searchUsers":
        query = param[0] if isinstance(param, list) and param else ""
        return {"ret": 0, "users": search_users(DB, UID, query)}
    if method == "GameFriends.getRequests":
        requests = []
        for request in pending_friend_requests(DB, UID):
            row = dict(request)
            sender = get_user(DB, int(request.get("from_id", 0))) or {}
            row.update({"name": sender.get("name", "Semut"),
                        "level": int(sender.get("level", 1)),
                        "sex": int(sender.get("sex", 1))})
            requests.append(row)
        return {"ret": 0, "requests": requests}
    if method == "GameFriends.acceptFriend":
        fid = int(param[0]) if isinstance(param, list) and param else 0
        ok = accept_friend(DB, UID, fid)
        if ok:
            advance_quests(DB, UID, 170, amount=1)
            save_db(DB)
        return {"ret": 0 if ok else 1}
    if method == "GameFriends.rejectFriend":
        fid = int(param[0]) if isinstance(param, list) and param else 0
        before = len(pending_friend_requests(DB, UID))
        DB["friend_requests"] = [r for r in DB.get("friend_requests", [])
                                  if not (r.get("status") == "pending" and int(r.get("to_id", 0)) == UID
                                          and int(r.get("from_id", 0)) == fid)]
        save_db(DB)
        return {"ret": 0 if len(pending_friend_requests(DB, UID)) < before else 1}
    if method == "GameConsortion.getConsortion":
        # UnionManager.isHaveUnionHandel: cinfo present => player in a union.
        g = self_guild()
        if not g:
            return {"ret": 0}
        return {"ret": 0, "cinfo": guild_obj(g),
                "minfo": {"position": 1, "mdevote": 0, "mhonour": 0}}
    if method == "GameConsortion.getConsortionList":
        return {"ret": 0, "list": [guild_obj(g) for g in DB.get("guilds", [])]}
    if method == "GameConsortion.getConsortionMembers":
        g = self_guild()
        gid = int(g["id"]) if g else 0
        gname = g["name"] if g else ""
        rows = [player_array(u, gid, gname) for u in DB["users"].values()]
        for f in DB.get("friends", []):   # friends shown as fellow members
            rows.append([int(f.get("id", 0)), f.get("name", ""), 1, "", "", 0,
                         "1|1|1|1", 0, 0, 0, 0, 1, 0, "", "",
                         {"cid": gid, "cname": gname}])
        return {"ret": 0, "list": rows}
    if method == "GameConsortion.getPublicNotice":
        g = self_guild()
        return {"ret": 0, "notice": (g or {}).get("notice", "") or ""}
    if method == "GameConsortion.editPublicNotice":
        g = self_guild()
        if g and isinstance(param, str):
            g["notice"] = param
            save_db(DB)
        return {"ret": 0}
    if method == "GameConsortion.createConsortion":
        # createUnion callback: ret 0 -> selfUnionData(info). Only one guild in
        # DB is the player's; report it as created.
        g = self_guild()
        return {"ret": 0, "info": {"cinfo": guild_obj(g), "minfo": {"position": 1, "mdevote": 0, "mhonour": 0}}} if g else {"ret": 0}
    if method == "GameConsortion.checkConsortionName":
        return {"ret": 0}
    if method == "GameConsortion.getConsortionMsgLists":
        return {"ret": 0, "list": []}
    if method == "GameConsortion.getApplyInfo":
        return {"ret": 0, "clist": []}
    if method == "GameConsortion.getWorship":
        return {"ret": 0, "isWorship": 0}
    if method == "GameCopys.getCopyGrade":
        # CopyList.setGradeData: owner_grade != -1 => stage unlocked. Return 3
        # for every cpdtlid (sum >= 20 unlocks hero difficulty).
        return {"ret": 0, "info": {str(cdt): 3 for cdt in COPY_CPDTLIDS}}
    if method == "GameCopys.getMobileCopyPrize":
        return copy_prize(body.get("param") or {})
    if method == "GameCopys.backProp":
        # Hall callback: GoodsList.payPorpIdArr = ret.props.split("|")
        return {"ret": 0, "props": ""}
    if method == "GameSignin.get_v2sign_info":
        # Game.onGetSignInfo does selfData.signData = ret.data (an Array);
        # set signData reads [0]=date,[1],[2]=counts and NPEs if data is null.
        return {"ret": 0, "data": ["", 0, 0], "signlist": []}
    if method == "GameMember.getNotice":
        return {"ret": 0, "notice": []}
    if method == "GameMember.getAccount":
        return {"ret": 0}
    if method in ("GameMember.checkRepeatRole", "GameMember.mobileUpdate"):
        return {"ret": 0}
    if method == "GameProps.get_fight_weapons":
        # WeaponChangeManager.initWeapon reads param1.weapon.length — a missing
        # key throws TypeError #1010. The dialog renders exactly 8 slots, so
        # never return more than 8 weapons or updateWeaponShow throws
        # RangeError #1125 (index out of range).
        u = get_user(DB, UID)
        weapons = []
        if u:
            by_id = {g["onlyID"]: g for g in u.get("goods", [])}
            weapons = [goods_array(by_id[oid]) for oid in fight_box(u)
                       if oid in by_id]
        return {"ret": 0, "weapon": weapons}
    if method == "GameProps.handle_fight_weapons":
        # [0, onlyID] add weapon to fight box, [1, onlyID] remove it.
        p = body.get("param") or []
        op = int(p[0]) if len(p) > 0 else -1
        oid = int(p[1]) if len(p) > 1 else 0
        u = get_user(DB, UID)
        if u:
            box = u.setdefault("fight_box", fight_box(u))
            if op == 0 and oid not in box and len(box) < 8:
                box.append(oid)
                save_db(DB)
            elif op == 1 and oid in box:
                box.remove(oid)
                save_db(DB)
        return {"ret": 0}
    if method == "GameProps.exchange_fight_weapons":
        # battle weapon switch: [oldOnlyID, newOnlyID]
        p = body.get("param") or []
        old_id = int(p[0]) if len(p) > 0 else 0
        new_id = int(p[1]) if len(p) > 1 else 0
        u = get_user(DB, UID)
        if u:
            box = u.setdefault("fight_box", fight_box(u))
            if old_id in box:
                box.remove(old_id)
            if new_id not in box and len(box) < 8:
                box.append(new_id)
            save_db(DB)
        return {"ret": 0}
    # Permissive default for anything else (flag unknowns so a GUI pass can
    # spot methods the client expects real data from).
    log("HTTP", "flashapi method=%s (permissive {ret:0})" % method)
    return {"ret": 0}


def copy_prize(param):
    """GameCopys.getMobileCopyPrize — reward grant for a cleared copy stage.

    Response shape the client reads (CopyGameWorld win callback):
      account.currency = NEW total gold (delta vs AccountData.gameGold)
      role.{mid,mrolename,mgender,mflee,mkill,appearance,mfailure,mwinning,
            mpoint,mlevel,vipmpoint} — merged via PlayerData.addOtherInfo
      props = array of readGoods() 13-field arrays (GoodsList.addGoodsByStr)
    """
    u = get_user(DB, UID)
    if u is None:
        return {"ret": 0, "account": {"currency": 0},
                "role": {"mid": UID, "mrolename": NAME, "mgender": SEX,
                         "mflee": 0, "mkill": 0, "appearance": 0, "mfailure": 0,
                         "mwinning": 0, "mpoint": 0, "mlevel": 1, "vipmpoint": 0},
                "props": []}
    cdt = int(param.get("cpdtlid") or 0)
    info = COPY_INFO.get(cdt)
    stage = int(param.get("stage") or 1)
    if info:
        cpid, difficulty = info["cpid"], info["difficulty"]
        stage, mapid = info["stage"], info["mapid"]
    else:
        cpid = int(param.get("cpid") or 1)
        difficulty = int(param.get("difficulty") or 1)
        mapid = None
    # reward config: admin 'stages' resource matched by copylist mapid, else by
    # stage level, else a plain per-stage default.
    row = None
    if mapid is not None:
        for s in DB.get("stages", []):
            if int(s.get("mapID", 0)) == mapid:
                row = s
                break
    if row is None:
        for s in DB.get("stages", []):
            if int(s.get("level", 0)) == stage:
                row = s
                break
    if row:
        coin = int(row.get("reward_coin", 0) or 0)
        exp = int(row.get("reward_exp", 0) or 0)
        gtype = int(row.get("reward_typeID", 0) or 0)
        gfid = int(row.get("reward_frameID", 0) or 0)
        gcount = int(row.get("reward_count", 0) or 0)
    else:
        coin, exp, gtype, gfid, gcount = stage * 40, stage * 8, 0, 0, 0
    res = grant_reward(DB, UID, coin, exp, gtype, gfid, gcount,
                       "copy cpid%d stage%d diff%d +%d koin +%d exp" % (cpid, stage, difficulty, coin, exp))
    props = res["props"] if res else []
    return {
        "ret": 0,
        "account": {"currency": u["currency"]},
        "role": {
            "mid": UID, "mrolename": u.get("name", NAME), "mgender": u.get("sex", SEX),
            "mflee": 0, "mkill": 0, "appearance": 0,
            "mfailure": u.get("losses", 0), "mwinning": u.get("wins", 0),
            "mpoint": u.get("exp", 0), "mlevel": u.get("level", 1),
            "vipmpoint": 0,
        },
        "props": props,
    }


class HttpHandler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_POST(self):
        path = urllib.parse.urlparse(self.path).path
        log("HTTP", "POST %s" % self.path)
        track_req(self.path)
        if path in ("/auth/register", "/auth/login", "/auth/logout"):
            global DB, UID
            body = self._read_json()
            if path == "/auth/register":
                result = auth_register(DB, body.get("email"), body.get("password"),
                                       body.get("name"), body.get("gender"))
                if result.get("ok"):
                    # Registration is also the first login: the newly created
                    # character must enter the game with its own session/UID.
                    session = auth_login(DB, body.get("email"), body.get("password"))
                    result["token"] = session["token"]
                    UID = int(result["user"].get("game_uid") or UID)
                    save_db(DB)
                self._send_json(200 if result.get("ok") else 400, result)
                return
            if path == "/auth/login":
                result = auth_login(DB, body.get("email"), body.get("password"))
                if result.get("ok"):
                    UID = int(result["user"].get("game_uid") or UID)
                    save_db(DB)
                self._send_json(200 if result.get("ok") else 401, result)
                return
            self._send_json(200, {"ok": auth_logout(DB, body.get("token"))})
            save_db(DB)
            return
        if path == "/admin/login":
            body = self._read_json()
            result = admin_login(DB, body.get("email"), body.get("password"))
            if result.get("ok"):
                save_db(DB)
                self.send_response(200)
                self.send_header("Set-Cookie", "antwars_admin=%s; HttpOnly; SameSite=Lax; Path=/admin" % result["token"])
                self.send_header("Content-Type", "application/json; charset=utf-8")
                data = json.dumps(result).encode("utf-8")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)
            else:
                self._send_json(401, result)
            return
        if path == "/admin/logout":
            admin_logout(DB, self._admin_token())
            save_db(DB)
            self.send_response(200)
            self.send_header("Set-Cookie", "antwars_admin=; Max-Age=0; HttpOnly; SameSite=Lax; Path=/admin")
            self.send_header("Content-Type", "application/json; charset=utf-8")
            data = b'{"ok":true}'
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
            return
        if path.startswith("/admin/api/"):
            if not admin_me(DB, self._admin_token()):
                self._send_json(401, {"error": "admin login diperlukan"})
                return
            self._admin_api(path[len("/admin/api/"):])
            return
        if not path.startswith(BASE):
            self._send_json(404, {"error": "not found"})
            return
        rel = path[len(BASE):]
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b""
        qs = urllib.parse.parse_qs(raw.decode("utf-8", "replace"))
        if rel.startswith("/mobile/devicelogin.php"):
            sid = qs.get("sid", ["0"])[0]
            name = qs.get("name", ["player"])[0]
            channel = qs.get("channel", ["0"])[0]
            sign = qs.get("sign", [""])[0]
            log("HTTP", "devicelogin sid=%s name=%s channel=%s" % (sid, name, channel))
            self._send_json(200, {"data": {"mid": UID, "key": SESSION_KEY}})
            return
        if rel.startswith("/api/flashapi.php"):
            win_param = qs.get("win_param", [None])[0]
            try:
                body = json.loads(win_param) if win_param else {}
            except Exception:
                body = {}
            self._send_json(200, handle_flashapi(body))
            return
        if rel.startswith("/mobile/"):
            # Every /mobile/*.php the client polls must answer with parseable
            # JSON, or its URLLoader throws an unhandled ioError (#2044).
            # ponytail: no real payments offline; empty payloads are enough,
            # client guards with hasOwnProperty and shows a clean message.
            if rel.startswith("/mobile/get_products.php"):
                self._send_json(200, {"productInfo": {}})
            else:
                self._send_json(200, {})
            return
        if rel.startswith("/version/facebookid/"):
            if rel.endswith("ChangerLog.xml"):
                # version 0 => no resource downloads; update empty => no force-update
                self._send_text(200, '<?xml version="1.0"?><xml version="0" update=""></xml>')
                return
            self._send_json(404, {"error": "no such resource"})
            return
        self._send_json(404, {"error": "not found"})

    def do_GET(self):
        path = urllib.parse.urlparse(self.path).path
        log("HTTP", "GET %s" % self.path)
        track_req(self.path)
        if path == "/auth/me":
            global UID
            query = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            token = query.get("token", [""])[0]
            user = auth_me(DB, token)
            if user:
                UID = int(user.get("game_uid") or UID)
            self._send_json(200, {"ok": bool(user), "user": user} if user else {"ok": False})
            return
        if path.startswith("/auth-assets/"):
            asset = os.path.basename(urllib.parse.unquote(path[len("/auth-assets/"):]))
            full = os.path.abspath(os.path.join(AUTH_ASSET_ROOT, asset))
            if os.path.isfile(full) and full.startswith(os.path.abspath(AUTH_ASSET_ROOT) + os.sep):
                self._send_file(full)
            else:
                self._send_json(404, {"error": "asset not found"})
            return
        if path == "/admin/login":
            ah = os.path.join(os.path.dirname(os.path.abspath(__file__)), "admin-login.html")
            if os.path.isfile(ah):
                with open(ah) as f:
                    self._send_html(200, f.read())
            else:
                self._send_html(200, "<h1>Admin login</h1>")
            return
        if path == "/admin":
            if not admin_me(DB, self._admin_token()):
                self.send_response(302)
                self.send_header("Location", "/admin/login")
                self.end_headers()
                return
            ah = os.path.join(os.path.dirname(os.path.abspath(__file__)), "admin.html")
            if os.path.isfile(ah):
                with open(ah) as f:
                    self._send_html(200, f.read())
                return
            self._send_html(200, "<h1>admin.html hilang</h1>")
            return
        if path.startswith("/admin/api/"):
            if not admin_me(DB, self._admin_token()):
                self._send_json(401, {"error": "admin login diperlukan"})
                return
            self._admin_api(path[len("/admin/api/"):], GET=True)
            return
        if path in ("/asset_img", "/goods_icon", "/map_img", "/avatar_img"):
            self._serve_image(path)
            return
        # Client resolves static resources against ResUrl (HTTP webroot).
        # Serve the bundled res/ directory, tolerating any slash runs between
        # the version root and the resource path.
        pre = BASE + "/version/facebookid"
        if path.startswith(pre):
            rel = urllib.parse.unquote(path[len(pre):]).lstrip("/")
            if rel == "ChangerLog.xml":
                # version 0 => no incremental downloads, update empty => no force-update
                self._send_text(200, '<?xml version="1.0"?><xml version="0" update=""></xml>')
                return
            if rel == "files.txt":
                # Ruffle: manifest of every bundled res file, one rel path per line.
                self._send_text(200, res_manifest())
                return
            self._send_file(res_root(rel))
            return
        if path.startswith(BASE) and path[len(BASE):].endswith("ChangerLog.xml"):
            self._send_text(200, '<?xml version="1.0"?><xml version="0" update=""></xml>')
            return
        if path == "/crossdomain.xml":
            self._send_text(200, '<?xml version="1.0"?><!DOCTYPE cross-domain-policy SYSTEM "http://www.adobe.com/xml/dtds/cross-domain-policy.dtd"><cross-domain-policy><site-control permitted-cross-domain-policies="all"/><allow-access-from domain="*"/><allow-http-request-headers-from domain="*" headers="*"/></cross-domain-policy>')
            return
        self._send_json(404, {"error": "not found"})

    def _send_file(self, fullpath):
        # Missing stage maps (map_202/203) render as map_201 so PvE visuals don't
        # blank out; client logs a load failure but the stage still runs.
        if fullpath and not os.path.isfile(fullpath):
            name = os.path.basename(fullpath)
            if name.startswith("map_") and name.endswith(".png"):
                fallback = os.path.join(os.path.dirname(fullpath), "map_201.png")
                if fallback != fullpath and os.path.isfile(fallback):
                    log("HTTP", "map fallback %s -> map_201.png" % name)
                    fullpath = fallback
        if not fullpath or not os.path.isfile(fullpath):
            self._send_json(404, {"error": "no such resource: %s" % os.path.basename(fullpath or "")})
            return
        with open(fullpath, "rb") as f:
            data = f.read()
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Content-Type", mimetypes.guess_type(fullpath)[0] or "application/octet-stream")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _serve_image(self, route):
        from urllib.parse import parse_qs
        if not ASSET_INDEX:
            _build_asset_index()
        qs = parse_qs(urllib.parse.urlparse(self.path).query)
        data = None
        if route == "/goods_icon":
            tid = qs.get("typeID", [""])[0]
            fid = qs.get("frameID", [""])[0]
            if tid.isdigit() and fid.isdigit():
                name = goods_icon_name(tid, fid)
                if name:
                    data = icon_png_cached(name)
        elif route == "/asset_img":
            name = qs.get("name", [""])[0]
            atlas = qs.get("atlas", [""])[0]
            if name:
                if atlas:
                    data = icon_png_scoped_cached(atlas, name)
                else:
                    data = icon_png_cached(name)
        elif route == "/avatar_img":
            # flattened ant avatar from armature + charcher/hats atlas.
            # ?atlas=charcher_boy -> bare bust (backward compat).
            # ?uid=<id> -> avatar wearing that user's equipped gear.
            atlas = qs.get("atlas", [""])[0]
            uid = qs.get("uid", [""])[0]
            if uid:
                u = get_user(DB, int(uid))
                if u:
                    sex = int(u.get("sex", 0))
                    # Client convention: any non-zero sex = girl (ant_girl).
                    atlas = "charcher_girl" if sex != 0 else "charcher_boy"
                    equipped = avatar_gear_for_user(u)
                    data = avatar_render.avatar_png_with_gear(atlas, equipped)
            elif atlas:
                data = avatar_render.avatar_png(atlas)
        elif route == "/map_img":
            mid = qs.get("mapID", [""])[0]
            for cand in ("map_%s.png" % mid, "map_%s_bg.png" % mid):
                fp = res_root(os.path.join("MAP_SMALL", cand))
                if fp and os.path.isfile(fp):
                    with open(fp, "rb") as f:
                        data = f.read()
                    break
        if data is None:
            self._send_json(404, {"error": "no image for %s" % route})
            return
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Content-Type", "image/png")
        self.send_header("Cache-Control", "max-age=86400")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _send_json(self, code, obj):
        data = json.dumps(obj).encode("utf-8")
        self.send_response(code)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _send_text(self, code, text):
        data = text.encode("utf-8")
        self.send_response(code)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Content-Type", "text/xml; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _send_html(self, code, text):
        data = text.encode("utf-8")
        self.send_response(code)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _admin_token(self):
        authorization = self.headers.get("Authorization", "")
        if authorization.lower().startswith("bearer "):
            return authorization[7:].strip()
        cookies = {}
        for item in self.headers.get("Cookie", "").split(";"):
            if "=" in item:
                key, value = item.strip().split("=", 1)
                cookies[key] = value
        return cookies.get("antwars_admin", "")

    def _admin_api(self, route, GET=False):
        """REST-ish admin API:
        GET  /admin/api/state                  -> full JSON {users:[...]}
        GET  /admin/api/state?reload=1         -> re-open DB first
        POST /admin/api/user/<id>              {name?,level?,currency?,boyaa_coin?,energy?,wins?,losses?,delete?}
        POST /admin/api/user/<id>/goods        {typeID,frameID,count,slot?}
        POST /admin/api/user/<id>/goods/<onlyID> {position?,slot?,delete?}
        """
        global DB
        if not admin_me(DB, self._admin_token()):
            self._send_json(401, {"error": "admin login diperlukan"})
            return
        r = urllib.parse.urlparse(self.path)
        parts = route.split("/")
        if route == "state":
            if any(k == "reload" for k, _ in urllib.parse.parse_qsl(r.query)):
                DB = load_db()
            self._send_json(200, admin_state(DB))
            return
        if route == "export":
            if any(k == "reload" for k, _ in urllib.parse.parse_qsl(r.query)):
                DB = load_db()
            self._send_json(200, DB)
            return
        if route == "stats":
            if any(k == "reload" for k, _ in urllib.parse.parse_qsl(r.query)):
                DB = load_db()
            self._send_json(200, req_stats())
            return
        if route == "catalog":
            self._send_json(200, {"items": item_catalog()})
            return
        if route == "reset":
            if GET:
                self._send_json(405, {"error": "POST /admin/api/reset"})
                return
            DB = default_db()
            save_db(DB)
            self._send_json(200, {"ok": True, "users": [u["id"] for u in admin_state(DB)["users"]]})
            return
        if route == "import":
            if GET:
                self._send_json(405, {"error": "POST /admin/api/import"})
                return
            body = self._read_json()
            if not isinstance(body, dict) or "users" not in body or \
                    not isinstance(body["users"], dict):
                self._send_json(400, {"error": "butuh JSON {users:{...}} dari ekspor"})
                return
            for k, u in body["users"].items():
                if not isinstance(u, dict) or "goods" not in u:
                    self._send_json(400, {"error": "format user %s salah" % k})
                    return
            DB = body
            save_db(DB)
            self._send_json(200, {"ok": True, "users": [u["id"] for u in admin_state(DB)["users"]]})
            return
        if route == "economy":
            if any(k == "reload" for k, _ in urllib.parse.parse_qsl(r.query)):
                DB = load_db()
            self._send_json(200, {"ledger": DB.get("ledger", [])})
            return
        if route == "chat":
            if any(k == "reload" for k, _ in urllib.parse.parse_qsl(r.query)):
                DB = load_db()
            self._send_json(200, {"chat": DB.get("chat", [])})
            return
        if route == "online":
            self._send_json(200, {"online": online_game_users()})
            return
        if route == "chat/send":  # POST {kind,str,name?,uid?,type?,to?}
            if GET:
                self._send_json(405, {"error": "POST /admin/api/chat/send"})
                return
            body = self._read_json()
            kind = str(body.get("kind", "world"))
            msg = str(body.get("str", ""))
            uid = int(body.get("uid", 0) or 0) or UID
            to = int(body.get("to", 0) or 0) or None
            name = body.get("name") or None
            u = get_user(DB, uid)
            if name is None:
                name = u["name"] if u else NAME
            if not msg:
                self._send_json(400, {"error": "str kosong"})
                return
            if kind == "private":
                ctype = int(body.get("type", 0))
                push_private(uid, ctype, msg, to_uid=to, name=name)
            else:
                ctype = int(body.get("type", 3 if kind == "room" else 1))
                push_loudspeaker(ctype, msg, uid, name=name)
            self._send_json(200, {"ok": True})
            return
        if route == "battle/sim":  # POST {uid, win:0|1} -> apply battle outcome
            if GET:
                self._send_json(405, {"error": "POST /admin/api/battle/sim"})
                return
            body = self._read_json()
            u = get_user(DB, int(body.get("uid", UID)))
            if u is None:
                self._send_json(404, {"error": "no user"})
                return
            win = int(body.get("win", 0)) == 0  # 0 == robot loses => player wins
            reward = 100 if win else 20
            exp = 20 if win else 5
            if win:
                u["wins"] = int(u.get("wins", 0)) + 1
            else:
                u["losses"] = int(u.get("losses", 0)) + 1
            u["currency"] = int(u.get("currency", 0)) + reward
            u["exp"] = int(u.get("exp", 0)) + exp
            u["level"] = level_from_exp(u["exp"])
            log_entry(DB, "battle", int(u["id"]), reward,
                      "simulasi menang +%d/+%d exp" % (reward, exp)
                      if win else "simulasi kalah +%d/+%d exp" % (reward, exp))
            save_db(DB)
            self._send_json(200, {"ok": True, "win": win, "currency": u["currency"],
                                  "exp": u["exp"], "level": u["level"]})
            return
        if len(parts) == 3 and parts[0] == "stages" and parts[2] == "grant":
            # POST /admin/api/stages/<id>/grant {uid} -> grant stage reward to user
            if GET:
                self._send_json(405, {"error": "POST .../stages/<id>/grant"})
                return
            body = self._read_json()
            row = None
            for s in DB.get("stages", []):
                if int(s.get("id", 0)) == int(parts[1]):
                    row = s
                    break
            if row is None:
                self._send_json(404, {"error": "no stage"})
                return
            res = grant_reward(DB, int(body.get("uid", UID)),
                               row.get("reward_coin", 0), row.get("reward_exp", 0),
                               row.get("reward_typeID", 0), row.get("reward_frameID", 0),
                               row.get("reward_count", 0),
                               "admin grant stage %s" % row.get("name", parts[1]))
            if res is None:
                self._send_json(404, {"error": "no user"})
                return
            self._send_json(200, {"ok": True, **res})
            return
        # generic resource CRUD: /admin/api/guilds|shop|friends|monsters|stages[/<id>]
        if len(parts) >= 1 and parts[0] in RESOURCES:
            res = parts[0]
            items = DB.setdefault(res, [])
            if GET:
                self._send_json(200, {"items": items})
                return
            body = self._read_json()
            if len(parts) == 1:
                nid = max([int(it.get("id", 0)) for it in items] or [0]) + 1
                rec = {"id": nid}
                for k, v in body.items():
                    rec[k] = v
                items.append(rec)
                save_db(DB)
                self._send_json(200, {"ok": True, "id": nid})
                return
            rid = int(parts[1])
            for it in items:
                if int(it.get("id", 0)) == rid:
                    if body.get("delete"):
                        items.remove(it)
                    else:
                        for k, v in body.items():
                            it[k] = v
                    save_db(DB)
                    self._send_json(200, {"ok": True})
                    return
            self._send_json(404, {"error": "no item %s/%s" % (res, rid)})
            return
        if len(parts) == 1 and parts[0] == "user":  # POST /admin/api/user (create only)
            if GET:
                self._send_json(405, {"error": "use /state"})
                return
            body = self._read_json()
            nid = max([int(k) for k in DB["users"].keys()] or [0]) + 1
            DB["users"][str(nid)] = {
                "id": nid, "name": body.get("name", "Pemain%d" % nid),
                "sex": 1, "level": 1, "currency": 0, "energy": 100,
                "wins": 0, "losses": 0, "boyaa_coin": 0, "goods": [],
            }
            save_db(DB)
            self._send_json(200, {"ok": True, "id": nid})
            return
        if len(parts) >= 2 and parts[0] == "user" and parts[1].isdigit():
            uid = parts[1]
            sub = parts[2:] if len(parts) > 2 else []
            if not sub:
                if GET:
                    self._send_json(405, {"error": "use /state"})
                    return
                body = self._read_json()
                u = get_user(DB, int(uid))
                if u is None:
                    self._send_json(404, {"error": "no user"})
                    return
                if body.get("delete"):
                    DB["users"].pop(str(uid), None)
                    save_db(DB)
                else:
                    for k in ("name", "sex", "level", "currency", "energy", "wins", "losses",
                              "boyaa_coin"):
                        if k in body:
                            u[k] = int(body[k]) if k != "name" else str(body[k])
                    if "exp" in body:
                        u["exp"] = int(body["exp"])
                        u["level"] = level_from_exp(u["exp"])
                    save_db(DB)
                self._send_json(200, {"ok": True})
                return
            if sub[0] == "goods" and GET:
                u = get_user(DB, int(uid))
                self._send_json(200, {"goods": (u["goods"] if u else [])})
                return
            if sub[0] == "goods" and len(sub) == 1:
                g = self._read_json()
                slot = g.get("slot") if g.get("slot") else _slot_for_type(g.get("typeID", 1))
                place = int(g.get("position", 0)) if "position" in g else (1 if g.get("equip") else 0)
                if not give_good(DB, int(uid), g.get("typeID", 1), g.get("frameID", 1001),
                                 g.get("count", 1), place=place, slot=slot):
                    self._send_json(404, {"error": "no user"})
                    return
                self._send_json(200, {"ok": True})
                return
            if sub[0] == "goods" and len(sub) == 2:
                only = int(sub[1])
                body = self._read_json()
                u = get_user(DB, int(uid))
                if u is None:
                    self._send_json(404, {"error": "no user"})
                    return
                for g in u["goods"]:
                    if int(g.get("onlyID", 0)) == only:
                        if body.get("delete"):
                            u["goods"].remove(g)
                            normalize_user_goods(u)
                            save_db(DB)
                            self._send_json(200, {"ok": True})
                            return
                        if "position" in body or "slot" in body:
                            requested_slot = body.get("slot") or g.get("slot") or equipment_slot_for_good(g)
                            changed = set_equipment_state(
                                u, requested_slot, body.get("position", g.get("position", 0)), only
                            )
                            if changed is None:
                                self._send_json(404, {"error": "no such good"})
                                return
                        if "count" in body:
                            g["count"] = int(body["count"])
                            g["amount"] = int(body["count"])
                        if "typeID" in body:
                            g["typeID"] = int(body["typeID"])
                        if "frameID" in body:
                            g["frameID"] = int(body["frameID"])
                        normalize_user_goods(u)
                        save_db(DB)
                        self._send_json(200, {"ok": True})
                        return
                self._send_json(404, {"error": "no such good"})
                return
        self._send_json(404, {"error": "unknown route"})

    def _read_json(self):
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b""
        try:
            return json.loads(raw or b"{}")
        except Exception:
            return {}


def start_http():
    srv = ThreadingHTTPServer((HOST, HTTP_PORT), HttpHandler)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    log("HTTP", "listening http://%s:%d%s" % (HOST, HTTP_PORT, BASE))


# ---------------------------------------------------------------------------
# Socket servers ("IC" framing)
# ---------------------------------------------------------------------------

class SocketServer(threading.Thread):
    def __init__(self, port, name):
        super().__init__(daemon=True)
        self.port = port
        self.name = name
        self.lock = threading.Lock()
        self.clients = set()  # active conns, used for chat relay/broadcast
        self.client_uids = {}

    def run(self):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            s.bind((HOST, self.port))
            s.listen(8)
            log(self.name, "listening tcp://%s:%d" % (HOST, self.port))
            while True:
                try:
                    conn, addr = s.accept()
                except OSError:
                    break
                threading.Thread(target=self.handle_conn, args=(conn, addr), daemon=True).start()

    def recv_frame(self, conn):
        buf = b""
        while len(buf) < P.HEADER:
            chunk = conn.recv(P.HEADER - len(buf))
            if not chunk:
                return None
            buf += chunk
        hdr = P.parse_header(buf)
        if hdr is None:
            return None
        cmd, ver, subver, body_len, code = hdr
        while len(buf) < P.HEADER + body_len:
            chunk = conn.recv(body_len + P.HEADER - len(buf))
            if not chunk:
                return None
            buf += chunk
        body = buf[P.HEADER:]
        return cmd, body

    def send_cmd(self, conn, cmd, writer):
        frame = writer.frame(cmd)
        try:
            with self.lock:
                conn.sendall(frame)
        except OSError:
            pass
        log(self.name, "-> cmd %d (%d bytes)" % (cmd, len(frame)))

    def handle_conn(self, conn, addr):
        self.clients.add(conn)
        try:
            self.session(conn, addr)
        except Exception as e:
            log(self.name, "session error: %r" % e)
        finally:
            self.clients.discard(conn)
            self.client_uids.pop(conn, None)
            try:
                conn.close()
            except OSError:
                pass


class GameServer(SocketServer):
    def _buy_reply(self, uid, ret, game_gold, goods):
        """3013 toBuy reply: uid, ret:short, then on ok money + new goods."""
        w = P.Writer()
        w.int(uid)
        w.short(ret)
        if ret == 0:
            w.int(game_gold)   # gameGold
            w.int(0)           # freeGold
            w.int(0)           # boyaaCoin
            w.int(0)           # aucteCoin
            w.int(0)           # contribute
            w.int(len(goods))
            for g in goods:
                write_goods(w, g)
        return w

    def session(self, conn, addr):
        log("GAME", "client connected %s" % (addr,))
        session_uid = UID
        while True:
            fr = self.recv_frame(conn)
            if fr is None:
                break
            cmd, body = fr
            r = P.Reader(body)
            if len(body) >= 4:
                incoming_uid = r.int()
                if cmd == 1001 and incoming_uid > 0:
                    session_uid = int(incoming_uid)
                    self.client_uids[conn] = session_uid
                    log("GAME", "session bound uid=%d" % session_uid)
                log("GAME", "<- cmd %d uid=%s" % (cmd, incoming_uid))
            else:
                log("GAME", "<- cmd %d (no body)" % cmd)
            if cmd == 1001:  # login
                w = P.Writer()
                w.int(0)       # count
                w.string("")   # ignored
                w.int(0)       # online seconds / 60
                self.send_cmd(conn, 1008, w)
            elif cmd == 3014:  # getAllGoods
                u = get_user(DB, session_uid)
                goods = u["goods"] if u else []
                w = P.Writer()
                w.int(session_uid)     # uid
                w.short(2)     # mode 2 => callback (GoodsList.getAllGoodsCB)
                w.int(len(goods))
                for g in goods:
                    write_goods(w, g)
                self.send_cmd(conn, 3014, w)
            elif cmd == 3016:  # getMemBody
                # 13 equipment slots: coat,shoes,glasses,leftring,rightleft,
                # necklace,hat,glove,wing,chatframe,dbexpcard,weapon,weddingring
                slots = [0] * 13
                place = ""
                u = get_user(DB, session_uid)
                if u:
                    for g in equipped_goods(u):
                        idx = {
                            "coat": 0, "shoes": 1, "glasses": 2,
                            "leftring": 3, "rightleft": 4, "necklace": 5,
                            "hat": 6, "glove": 7, "wing": 8,
                            "chatframe": 9, "dbexpcard": 10,
                            "weapon": 11, "weddingring": 12,
                        }.get(equipment_slot_for_good(g), 11)
                        slots[idx] = int(g.get("onlyID", 0))
                    place = str(u.get("place", ""))
                w = P.Writer()
                w.int(session_uid)     # uid
                w.short(0)     # flag 0 => ok
                for s in slots:
                    w.int(s)   # onlyID of equipped good, or 0
                w.string(place)
                self.send_cmd(conn, 3016, w)
            elif cmd == 1:  # getServerList
                w = P.Writer()
                w.int(session_uid)     # ignored
                w.int(2)       # count: battle + copy
                # serverID 1, svtype 1 (BATTLE)
                w.int(1); w.int(1)
                w.string(BATTLE_SVIP)
                w.int(BATTLE_SVPORT)
                w.int(1); w.int(100)   # startRoomId, endRoomId
                # serverID 2, svtype 3 (COPY)
                w.int(2); w.int(3)
                w.string(COPY_SVIP)
                w.int(COPY_SVPORT)
                w.int(0); w.int(0)     # startRoomId, endRoomId
                self.send_cmd(conn, 1, w)
            elif cmd == 4:  # getServerIDByType: [uid, level, svtype] -> [uid, svid]
                sub = P.Reader(body)
                sub.int()        # uid
                if sub.pos < len(body):
                    sub.int()    # level
                svtype = 1
                if sub.pos < len(body):
                    svtype = sub.int()
                svid = 2 if svtype == 3 else 1
                w = P.Writer()
                w.int(session_uid)     # uid
                w.int(svid)    # svid -> CopyServer for svtype3, else BattleServer
                self.send_cmd(conn, 4, w)
            elif cmd == 3052:  # consumeEnergy: [uid] -> [userId, type:short, energy:short]
                u = get_user(DB, session_uid)
                en = energy_now(u)
                if en < COPY_COST:
                    w = P.Writer()
                    w.int(session_uid); w.short(-1); w.short(en)
                else:
                    energy_commit(u, en - COPY_COST)
                    save_db(DB)
                    w = P.Writer()
                    w.int(session_uid); w.short(0); w.short(en - COPY_COST)
                self.send_cmd(conn, 3052, w)
            elif cmd == 3110:  # someOneVipLevel broadcast
                # ProcessCmd reads self:int, who:int, level:int (3 ints)
                w = P.Writer()
                w.int(session_uid)     # self
                w.int(session_uid)     # who
                w.int(0)       # level (no vip)
                self.send_cmd(conn, 3110, w)
            elif cmd == 3111:  # getVipViewInfo
                w = P.Writer()
                w.int(session_uid)     # mid
                for _ in range(7):
                    w.int(0)   # vipLevel..failreason
                w.int(0)       # giftNum
                self.send_cmd(conn, 3111, w)
            elif cmd in (3118, 3120):  # deleteOvertimeRentalGoods / nobodyRentBacktoMystore
                w = P.Writer()
                w.int(0)
                w.int(0)
                self.send_cmd(conn, cmd, w)
            elif cmd == 3051:  # getEnergy: reply userId/type/energy
                u = get_user(DB, session_uid)
                w = P.Writer()
                w.int(session_uid)                    # userId
                w.short(0)                    # type
                w.short(energy_now(u))        # energy incl. time regen
                self.send_cmd(conn, 3051, w)
            elif cmd == 3114:  # getAutoFightTimes: reply mid/todayCount
                w = P.Writer()
                w.int(session_uid)     # mid
                w.int(0)       # todayCount
                self.send_cmd(conn, 3114, w)
            elif cmd == 3119:  # getBagItemRentStatus
                w = P.Writer()
                w.int(0)       # ignored
                w.int(0)       # count
                self.send_cmd(conn, 3119, w)
            elif cmd == 1009:  # getInviteList -> online players, then end marker 1022
                rows = online_game_users(exclude_uid=session_uid)
                w = P.Writer()
                w.int(len(rows))
                for row in rows:
                    w.int(row["id"])
                    w.string(row["name"])
                    w.int(row["level"])
                    w.int(0)  # invited flag
                    w.int(0)  # marriage state
                self.send_cmd(conn, 1013, w)
                self.send_cmd(conn, 1022, P.Writer())
            elif cmd == 3005:  # setMemBody: client equips/unequips a good
                sub = P.Reader(body)
                sub.int()        # skip uid
                place = ""
                flag = 0
                only = 0
                try:
                    place = sub.string()
                    flag = sub.short() if sub.pos + 2 <= len(body) else 0
                    only = sub.int() if sub.pos + 4 <= len(body) else 0
                except Exception:
                    pass
                u = get_user(DB, session_uid)
                done = None
                if u and only:
                    done = set_equipment_state(u, place, flag, only)
                    if done:
                        if flag:
                            advance_quests(DB, session_uid, 180, int(done.get("typeID", 0)),
                                           int(done.get("frameID", 0)), 1)
                        save_db(DB)
                # reply: uid, flag 0 => ok, place, equip status (1 on / 0 off).
                # Client readGoods() only when status != 0, so goods only when equipped.
                w = P.Writer()
                w.int(session_uid)     # uid
                w.short(0)     # flag 0 => ok
                w.string(place)
                w.int(1 if flag else 0)
                if flag and done:
                    write_goods(w, done)
                self.send_cmd(conn, 3005, w)
            elif cmd == 3013:  # toBuy: {uid} {buyType:short} {count:short} then count x [buyType,int,typeID,int,frameID,int,price,int,num,int,name:string]
                sub = P.Reader(body)
                buy_uid = sub.int()
                sub.short()          # buyType (shop-type index)
                n = sub.short()
                u = get_user(DB, buy_uid)
                if not u:
                    self.send_cmd(conn, 3013, self._buy_reply(buy_uid, -1, 0, []))
                    continue
                cost = 0
                buys = []  # (tid, fid, num, unit_price, name)
                for _ in range(max(0, n)):
                    try:
                        sub.int()    # serverBuyType / pay-channel
                        tid = sub.int()
                        fid = sub.int()
                        offered = sub.int()
                        num = sub.int()
                        sub.string()  # name
                        if num < 0:
                            continue
                        price, name = cat_price(DB, tid, fid)
                        if price is None:      # not in toko -> trust client offer
                            price = max(0, offered)
                        cost += max(0, int(price)) * num
                        buys.append((tid, fid, num, int(price), name or ""))
                    except Exception:
                        break
                if cost > int(u.get("currency", 0)):
                    self.send_cmd(conn, 3013, self._buy_reply(buy_uid, -1, int(u.get("currency", 0)), []))
                    continue
                new_goods = []
                for (tid, fid, num, price, name) in buys:
                    give_good(DB, buy_uid, tid, fid, num)
                u = get_user(DB, buy_uid)
                u["currency"] = max(0, int(u.get("currency", 0)) - cost)
                for (tid, fid, num, price, name) in buys:
                    log_entry(DB, "buy", buy_uid, -price * num, "%d x %s" % (num, name or ("type%d-ff%d" % (tid, fid))))
                # reply carries the newly owned goods (dedupe by onlyID)
                seen = set()
                for tup in buys:
                    for g in u["goods"]:
                        oid = int(g.get("onlyID", 0))
                        if oid in seen:
                            continue
                        if int(g.get("typeID", 0)) == tup[0] and int(g.get("frameID", 0)) == tup[1]:
                            new_goods.append(g)
                            seen.add(oid)
                save_db(DB)
                self.send_cmd(conn, 3013, self._buy_reply(buy_uid, 0, u["currency"], new_goods))
            elif cmd == 1007:  # sendLoudSpeaker: [type:int, msg:string, param:int]
                sub = P.Reader(body)
                try:
                    ctype = sub.int() if sub.pos < len(body) else 0
                    msg = sub.string() if sub.pos < len(body) else ""
                except Exception:
                    ctype, msg = 0, ""
                if msg:
                    push_loudspeaker(ctype, msg, session_uid, conn=conn)
            elif cmd == 1002:  # sendChatToFriend: [toUid:int, type:int, str:string]
                sub = P.Reader(body)
                try:
                    to_uid = sub.int() if sub.pos < len(body) else 0
                    ctype = sub.int() if sub.pos < len(body) else 0
                    msg = sub.string() if sub.pos < len(body) else ""
                except Exception:
                    to_uid, ctype, msg = 0, 0, ""
                if msg:
                    push_private(session_uid, ctype, msg, to_uid=to_uid, conn=conn)
            elif cmd == 30001:  # heartbeat — no reply
                pass
            else:
                log("GAME", "unhandled cmd %d body=%s" % (cmd, body.hex()))


class BattleServer(SocketServer):
    def _room_state(self):
        if not hasattr(self, "rooms"):
            self.rooms = {}
            self.room_seq = 0
        return self.rooms

    @staticmethod
    def _room_capacity(room):
        # Practice rooms have one real player; site 1 is reserved for the robot.
        if int(room.get("mode", 0)) == 0:
            return 1
        return 2 if int(room.get("ptype", 0)) == 0 else 4

    @staticmethod
    def _room_site_count(room):
        if int(room.get("mode", 0)) == 0 or int(room.get("ptype", 0)) == 0:
            return 2
        return 4

    def _player_uid(self, conn):
        return int(getattr(self, "client_uids", {}).get(conn, UID))

    def _player_name(self, uid):
        user = get_user(DB, uid) or {}
        return user.get("babyName") or user.get("name") or ("Player %d" % uid)

    def _room_enter_packet(self, room, player):
        w = P.Writer()
        w.int(room["id"]); w.int(player["siteID"]); w.int(player["team"])
        w.int(1 if player.get("owner") else 0)
        w.int(room["mode"]); w.int(room["ptype"])
        count = self._room_site_count(room)
        w.int(count)
        occupied = {p["siteID"] for p in room["players"].values()}
        for site in range(count):
            w.int(1 if site in occupied else 0)
        w.int(room.get("mapID", 1001)); w.string(room.get("pw", ""))
        return w

    def _player_packet(self, room, player):
        uid = player["uid"]
        user = get_user(DB, uid) or {}
        sex = int(user.get("gender", user.get("babySex", 0)) or 0)
        name = self._player_name(uid)
        char_info = json.dumps({"babySex": sex, "babyName": name,
                                "mgender": sex, "mrolename": name}, ensure_ascii=False)
        props = [goods_array(g) for g in equipped_goods(user)]
        prop_info = json.dumps([0, props], ensure_ascii=False) if props else ""
        w = P.Writer()
        w.int(uid); w.int(player["siteID"]); w.int(player["team"])
        w.int(1 if player.get("ready") else 0); w.int(1 if player.get("owner") else 0)
        w.string(char_info); w.string(prop_info)
        w.int(int(user.get("exp", 0) or 0)); w.int(int(user.get("losses", 0) or 0))
        w.int(int(user.get("wins", 0) or 0)); w.int(0)
        return w

    def room_list_rows(self, mode_filter=0):
        rows = []
        for room in self._room_state().values():
            if mode_filter and int(room.get("mode", 0)) != int(mode_filter):
                continue
            current = len(room["players"])
            rows.append([room["id"], room["ownerUid"], self._player_name(room["ownerUid"]),
                         room["mode"], room["ptype"], current, self._room_capacity(room),
                         1 if room.get("fighting") else 0,
                         1 if current < self._room_capacity(room) and not room.get("fighting") else 0,
                         room.get("pw", "")])
        return rows

    def send_room_list(self, conn, mode_filter=0):
        w = P.Writer(); rows = self.room_list_rows(mode_filter); w.int(len(rows))
        for row in rows:
            w.int(row[0]); w.int(row[1]); w.string(row[2]); w.int(row[3]); w.int(row[4])
            w.int(row[5]); w.int(row[6]); w.int(row[7]); w.int(row[8]); w.string(row[9])
        self.send_cmd(conn, 3007, w)

    def _pvp_required_players(self, room):
        return self._room_capacity(room)

    def send_all_ready(self, room):
        w = P.Writer()
        w.int(room.get("mapID", 1001)); w.string(""); w.string(""); w.int(0)
        for x, y in [(200, 600), (1100, 600), (200, 150), (1100, 150)]:
            w.int(x); w.int(y)
        for player in room["players"].values():
            self.send_cmd(player["conn"], 24, w)

    def send_game_start(self, room):
        w = P.Writer()
        w.int(1)  # deterministic seed for the local emulator
        w.int(len(room["players"]))
        for player in room["players"].values():
            w.int(player["siteID"]); w.int(300)
        for player in room["players"].values():
            self.send_cmd(player["conn"], 1005, w)
        room["started"] = True

    def maybe_start_pvp(self, room):
        required = self._pvp_required_players(room)
        if (int(room.get("mode", 0)) != 1 or room.get("started") or
                room.get("awaiting_load") or len(room["players"]) < required or
                not all(p.get("ready") for p in room["players"].values())):
            return False
        room["awaiting_load"] = True
        room["loaded"] = set()
        self.send_all_ready(room)
        return True

    def create_room(self, conn, pw, mode, ptype):
        """cmd 3008 createRoom [pw, type(player count mode), mode]:
        -> cmd 5 enterRoom so the lobby shows the room UI with the owner.
        mode 0 = practice vs robot (pk_type 0, playable solo), mode 1 = PvP 2v2."""
        rooms = self._room_state()
        self.room_seq += 1
        rid = self.room_seq
        uid = self._player_uid(conn)
        player = {"conn": conn, "uid": uid, "siteID": 0, "team": 0,
                  "owner": True, "ready": False}
        rooms[rid] = {"id": rid, "pw": pw, "mode": int(mode), "ptype": int(ptype),
                      "mapID": 1001, "ownerUid": uid, "fighting": False,
                      "players": {conn: player}, "started": False,
                      "awaiting_load": False, "loaded": set()}
        w = self._room_enter_packet(rooms[rid], player)
        self.send_cmd(conn, 5, w)
        log("BATTLE", "room %d dibuat mode=%d type=%d pw='%s'" % (rid, mode, ptype, pw))
        return rid

    def join_room(self, conn, room_id, pw):
        room = self._room_state().get(int(room_id))
        if not room:
            w = P.Writer(); w.int(0); self.send_cmd(conn, 3000, w); return False
        if room.get("pw", "") != pw:
            w = P.Writer(); w.int(4); self.send_cmd(conn, 12, w); return False
        if room.get("fighting") or len(room["players"]) >= self._room_capacity(room):
            w = P.Writer(); w.int(2); self.send_cmd(conn, 12, w); return False
        if conn in room["players"]:
            self.send_cmd(conn, 5, self._room_enter_packet(room, room["players"][conn]))
            return True
        used = {p["siteID"] for p in room["players"].values()}
        site = next(i for i in range(self._room_capacity(room)) if i not in used)
        player = {"conn": conn, "uid": self._player_uid(conn), "siteID": site,
                  "team": site % 2, "owner": False, "ready": False}
        room["players"][conn] = player
        self.send_cmd(conn, 5, self._room_enter_packet(room, player))
        for other in room["players"].values():
            if other is player:
                continue
            self.send_cmd(conn, 6, self._player_packet(room, other))
            self.send_cmd(other["conn"], 6, self._player_packet(room, player))
        return True

    def leave_room(self, conn):
        for room_id, room in list(self._room_state().items()):
            player = room["players"].pop(conn, None)
            if player is None:
                continue
            w = P.Writer(); w.int(player["uid"])
            for other in room["players"].values():
                self.send_cmd(other["conn"], 7, w)
            if not room["players"]:
                del self.rooms[room_id]
            elif player.get("owner"):
                next_player = next(iter(room["players"].values()))
                next_player["owner"] = True
                room["ownerUid"] = next_player["uid"]
            return

    def arena_monster(self):
        """Monster yang tampil di robot duel (mapID 1001 = arena), fallback pertama."""
        mons = DB.get("monsters", [])
        for m in mons:
            if int(m.get("mapID", 0)) == 1001:
                return m
        return mons[0] if mons else None

    def send_robot_come(self, conn):
        """Push cmd 38 onRobotCome: shape robot = monster DB (babySex + props),
        so the in-game robot duel shows the admin-configured appearance.
        Must arrive BEFORE cmd 39 onStartRobot -> showRobotBt -> getRobotData()."""
        m = self.arena_monster()
        if m is None:
            return
        sex = int(m.get("babySex", 0))
        char_info = json.dumps({
            "babySex": sex, "babyName": m.get("name", ""),
            "mgender": sex, "mrolename": m.get("name", ""),
        }, ensure_ascii=False)
        props = []
        for i, p in enumerate(m.get("props") or []):
            if isinstance(p, dict):
                tid, fid = p.get("typeID", 0), p.get("frameID", 0)
            else:
                tid, fid = p[0], p[1]
            # [onlyID, typeID, frameID, status, attr, synth, expiration,
            #  strengthenExp, position(1=worn), term, amount, isbind]
            props.append([100001 + i, int(tid), int(fid), 0, "", "", 0, 0, 1, 0, 1, 0])
        prop_info = json.dumps([0, props]) if props else ""
        w = P.Writer()
        w.int(9001)        # mid (client overrides to siteID+1000)
        w.int(1)           # siteID: practice room reserves slot 1 for robot
        w.int(1)           # team
        w.int(1)           # ready
        w.int(0)           # isHouseOwner
        w.string(char_info)
        w.string(prop_info)
        w.int(0)           # exp
        w.int(0)           # fail
        self.send_cmd(conn, 38, w)

    def send_start_robot(self, conn):
        # onStartRobot: mapID, mapURL, musicURL, mapType, born(4 x int,int)
        # Client (BtRoom.onStartRobot, pk_type==0) loads res/MAP_SMALL/map_1001.png,
        # then dispatches "showRobotBt" -> ROBOTBATTLEFIELD robot duel.
        w = P.Writer()
        w.int(1001)                  # mapID
        w.string("")                 # mapURL (unused on robot path)
        w.string("")                 # musicURL
        w.int(0)                     # mapType
        # Titik spawn harus di atas tanah padat map 1001 (1024x768):
        # daftar lama memuat x=1100 (di luar lebar map) -> semut yang
        # kebagian titik itu jatuh ke kekosongan dan mati ~1 detik
        # setelah battlefield tampil (robotOver instan, tanpa tembakan).
        # Permukaan tanah utama: y~537 di x=200, y~553 di x=850.
        for (x, y) in [(200, 480), (850, 490), (350, 480), (700, 495)]:
            w.int(x)
            w.int(y)
        self.send_cmd(conn, 39, w)

    def send_robot_sequence(self, conn, first_delay=0.0, gap=0.35):
        """Kirim onRobotCome (38) lalu onStartRobot (39) dengan jeda.

        Client mengikat handler 38/39 saat layar BtRoom selesai dibuat
        setelah paket enterRoom (cmd 5). ProcessCmd.callUserFun membuang
        paket yang tiba sebelum handler terikat, jadi 38/39 yang dikirim
        menempel tepat setelah cmd 5 hilang dan battle tidak pernah
        mulai (teramati di Ruffle: room diam di slot "waiting").
        Jeda antar-paket memberi client waktu membangun layar.
        """
        if first_delay > 0:
            time.sleep(first_delay)
        self.send_robot_come(conn)
        time.sleep(gap)
        self.send_start_robot(conn)

    def session(self, conn, addr):
        log("BATTLE", "client connected %s" % (addr,))
        session_uid = self.client_uids.get(conn, UID)
        while True:
            fr = self.recv_frame(conn)
            if fr is None:
                break
            cmd, body = fr
            r = P.Reader(body)
            log("BATTLE", "<- cmd %d" % cmd)
            if cmd == 0 or (cmd == 1001 and body):  # legacy/real battle login
                if cmd == 1001 and r.pos < len(body):
                    session_uid = r.int()
                    self.client_uids[conn] = session_uid
                w = P.Writer()
                w.string("")   # versions
                w.int(0)       # exp
                w.string("")   # btprop
                w.string("")   # goodsStr
                w.int(0)       # rank
                self.send_cmd(conn, 1, w)  # loginBTSuccessful, ret=0 hardcoded client-side
            elif cmd == 3007:  # getFightList -> shared room list
                mode_filter = r.int() if r.pos < len(body) else 0
                self.send_room_list(conn, mode_filter)
            elif cmd == 3008:  # createRoom [pw, type, mode] -> enter room (cmd 5)
                pw = r.string() if r.pos < len(body) else ""
                ptype = r.int() if r.pos < len(body) else 0
                mode = r.int() if r.pos < len(body) else 0
                self.create_room(conn, pw, mode, ptype)
            elif cmd == 13:  # seekRoom [roomId, password]
                room_id = r.int() if r.pos < len(body) else 0
                pw = r.string() if r.pos < len(body) else ""
                self.join_room(conn, room_id, pw)
            elif cmd == 8:  # tolerate clients that send the response command back
                ready = r.int() if r.pos < len(body) else 1
                for room in self._room_state().values():
                    player = room["players"].get(conn)
                    if player is None:
                        continue
                    player["ready"] = bool(ready)
                    for other in room["players"].values():
                        ready_packet = P.Writer()
                        ready_packet.int(player["siteID"])
                        ready_packet.int(1 if player["ready"] else 0)
                        self.send_cmd(other["conn"], 8, ready_packet)
                    self.maybe_start_pvp(room)
                    break
            elif cmd == 7:  # selfReady(1) dari pemilik kamar -> mulai practice robot
                ready = r.int() if r.pos < len(body) else 1
                found_room = False
                for room in self._room_state().values():
                    player = room["players"].get(conn)
                    if player is None:
                        continue
                    found_room = True
                    player["ready"] = bool(ready)
                    ready_packet = P.Writer()
                    ready_packet.int(player["siteID"])
                    ready_packet.int(1 if player["ready"] else 0)
                    for other in room["players"].values():
                        self.send_cmd(other["conn"], 8, ready_packet)
                    if room["mode"] == 0 and ready:
                        self.send_robot_sequence(conn, gap=0.2)
                    else:
                        self.maybe_start_pvp(room)
                        break
                if not found_room:
                    self.send_robot_sequence(conn, first_delay=0.4)
            elif cmd == 34:  # map loading progress
                progress = r.int() if r.pos < len(body) else 0
                for room in self._room_state().values():
                    player = room["players"].get(conn)
                    if player is None:
                        continue
                    player["progress"] = max(0, min(100, progress))
                    packet = P.Writer(); packet.int(player["siteID"]); packet.int(player["progress"])
                    for other in room["players"].values():
                        self.send_cmd(other["conn"], 30, packet)
                    break
            elif cmd == 1001:  # client finished loading the PvP map
                for room in self._room_state().values():
                    player = room["players"].get(conn)
                    if player is None or not room.get("awaiting_load"):
                        continue
                    room.setdefault("loaded", set()).add(player["siteID"])
                    if len(room["loaded"]) >= self._pvp_required_players(room):
                        self.send_game_start(room)
                    break
            elif cmd == 6:  # quickJoin -> enterRoom (cmd 5) then startRobot (cmd 39)
                # enterRoom: roomid, siteID, team, isHouseOwner, pk_type, pk_mode,
                #            siteStatusArr(count+ints), mapID, password
                w = P.Writer()
                w.int(1)       # roomid
                w.int(0)       # siteID (self)
                w.int(0)       # team
                w.int(1)       # isHouseOwner
                w.int(0)       # pk_type 0 = robot duels (client-local)
                w.int(0)       # pk_mode
                w.int(2)       # siteStatusArr count
                w.int(0)       # site 0 free
                w.int(0)       # site 1 free
                w.int(1001)    # mapID -> res/MAP_SMALL/map_1001.png
                w.string("")   # password
                self.send_cmd(conn, 5, w)
                self.send_robot_sequence(conn, first_delay=0.5)
            elif cmd == 1024:  # overFlop (empty body) -> start a fresh robot fight
                self.send_robot_sequence(conn, gap=0.2)
            elif cmd == 4:  # sendFace/emote: body = [faceId:int] -> broadcast [uid, faceId]
                face_id = r.int() if r.pos < len(body) else 0
                w = P.Writer()
                w.int(UID)      # uid
                w.int(face_id)  # type
                self.send_cmd(conn, 4, w)
            elif cmd == 29:  # buyPayProp: body = [frame:int] -> cmd 1019 [propID=frame, type]
                # type 0 = success (client deducts its own display gold), 1 = fail
                frame = r.int() if r.pos < len(body) else 0
                w = P.Writer()
                w.int(frame)   # propID (StaticFightGoods matches by frame)
                w.int(0)       # type = success
                self.send_cmd(conn, 1019, w)
            elif cmd == 41:  # robotOver body = [winner:int, myhurt:int, robothurt:int]
                # winner: 0 = robot lost (player won), 1 = player died
                win = r.int()
                # onGameOver(1006): data.winner:int, count:int,
                #                  count x [uid,?,?,?,?,?,?,?], isDoubleExp:int
                # client checks data.winner == selfData.team (team set to 0 by enterRoom),
                # and data.list for the scoreboard / result view.
                # persist rewards: win -> wins+1, +100 coins; lose -> losses+1, +20.
                reward = 100 if win == 0 else 20
                exp_gain = 20 if win == 0 else 5
                u = get_user(DB, UID)
                if u:
                    if win == 0:
                        u["wins"] = int(u.get("wins", 0)) + 1
                    else:
                        u["losses"] = int(u.get("losses", 0)) + 1
                    u["currency"] = int(u.get("currency", 0)) + reward
                    u["exp"] = int(u.get("exp", 0)) + exp_gain
                    u["level"] = level_from_exp(u["exp"])
                    log_entry(DB, "battle", UID, reward,
                              "menang robot +%d/+%d exp" % (reward, exp_gain)
                              if win == 0 else "kalah robot +%d/+%d exp" % (reward, exp_gain))
                    save_db(DB)
                # Client reads winner,count then count x 8 ints, building
                # list[i]=[r0,r1,r4,r3,r5,r6,0,r7,r2] and calls
                # getDataBySiteID(list[i][0]) -> first int MUST be a siteID
                # (0=self in a robot match), NOT the uid. Sending the uid made
                # getDataBySiteID(1000001) return null -> Error #1009 in
                # RobotBattlefield.showResultView. 8 ints/entry keeps the
                # stream aligned with the client's parser.
                w = P.Writer()
                w.int(win)        # winner == player team (0 = self wins)
                w.int(1)          # count
                w.int(0)          # list[0] siteID (self)
                w.int(exp_gain)   # list[1] exp gained
                w.int(0)          # list[8] bonus-exp display
                w.int(0)          # list[3]
                w.int(0)          # list[2]
                w.int(0)          # list[4]
                w.int(0)          # list[5]
                w.int(0)          # list[7]
                w.int(0)          # isDoubleExp
                self.send_cmd(conn, 1006, w)  # onGameOver
            else:
                log("BATTLE", "unhandled cmd %d body=%s" % (cmd, body.hex()))
        self.leave_room(conn)
        self.client_uids.pop(conn, None)


class CopyServer(SocketServer):
    """svtype3 CopyGame server. Solo PvE flow needs only login + free-relive
    counters; the stage itself runs client-side and rewards arrive via HTTP
    GameCopys.getMobileCopyPrize."""

    def session(self, conn, addr):
        log("COPY", "client connected %s" % (addr,))
        while True:
            fr = self.recv_frame(conn)
            if fr is None:
                break
            cmd, body = fr
            r = P.Reader(body)
            log("COPY", "<- cmd %d" % cmd)
            if cmd == 4001:  # login: [uid, key, babyName] -> [ret]
                w = P.Writer()
                w.int(0)      # ret ok
                self.send_cmd(conn, 4001, w)
            elif cmd == 4122:  # getFreeReliveTimesInCopy -> [freeleft]
                w = P.Writer()
                w.int(3)      # freeleft (must be >0 to allow relive)
                self.send_cmd(conn, 4122, w)
            elif cmd == 4123:  # useFreeReliveInCopy -> [flag, freeleft]
                w = P.Writer()
                w.int(0)      # flag ok
                w.int(2)      # freeleft after use
                self.send_cmd(conn, 4123, w)
            elif cmd == 4120:  # playerReliveInNormal -> [flag, boyaaCoin]
                w = P.Writer()
                w.int(0)      # flag ok
                w.int(0)      # boyaaCoin cost
                self.send_cmd(conn, 4120, w)
            elif cmd == 4009:  # leaveRoom: no reply
                pass
            else:
                log("COPY", "unhandled cmd %d body=%s" % (cmd, body.hex()))


def start_sockets():
    global GAME_SRV
    GAME_SRV = GameServer(GAME_PORT, "GAME")
    GAME_SRV.start()
    BattleServer(BATTLE_PORT, "BATTLE").start()
    CopyServer(COPY_PORT, "COPY").start()


# ---------------------------------------------------------------------------
# Chat relay — mirrors the client ChatRoomDlg wire protocol.
# 1007 sendLoudSpeaker [type,msg,param] -> 1026 push [uid,type,onlyId,name,str]
#    broadcast to ALL conns (client renders loudspeaker only from the push,
#    incl. its own message — no local echo).
# 1002 sendChatToFriend [uid,type,str] -> 1002 push [userId,type,str,name]
#    relay to OTHER conns only (sender renders private messages locally,
#    echoing back would double-render).
# ---------------------------------------------------------------------------
def chat_log(kind, ctype, uid, name, msg, to=None):
    L = DB.setdefault("chat", [])
    now = int(time.time())
    L.append({"ts": now, "timestamp": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(now)),
              "kind": kind, "type": int(ctype), "uid": int(uid), "name": name,
              "str": msg, "to": to})
    if len(L) > 500:
        del L[:len(L) - 500]
    save_db(DB)


def online_game_users(exclude_uid=None):
    """Return users with an authenticated, currently active game socket."""
    if GAME_SRV is None:
        return []
    result = []
    seen = set()
    for conn in list(GAME_SRV.clients):
        uid = GAME_SRV.client_uids.get(conn)
        if uid is None or int(uid) in seen or (exclude_uid is not None and int(uid) == int(exclude_uid)):
            continue
        user = get_user(DB, int(uid))
        if user:
            result.append({"id": int(uid), "name": user.get("name", "Semut"),
                           "level": int(user.get("level", 1)), "sex": int(user.get("sex", 1)),
                           "online": True})
            seen.add(int(uid))
    return sorted(result, key=lambda row: (row["name"].lower(), row["id"]))


def broadcast_cmd(cmd, writer, conn=None):
    """Send frame to all game conns; conn given is excluded (private relay)."""
    for c in list(getattr(GAME_SRV, "clients", ()) or ()):
        if c is not conn:
            GAME_SRV.send_cmd(c, cmd, writer)


def push_loudspeaker(ctype, msg, uid, name=None, onlyid=0, conn=None):
    u = get_user(DB, uid)
    if name is None:
        name = u["name"] if u else NAME
    kind = "room" if int(ctype) == 3 else "world"
    chat_log(kind, ctype, uid, name, msg)
    w = P.Writer()
    w.int(uid); w.int(ctype); w.int(onlyid); w.string(name); w.string(msg)
    broadcast_cmd(1026, w, conn=None)


def push_private(from_uid, ctype, msg, to_uid=None, name=None, conn=None):
    u = get_user(DB, from_uid)
    if name is None:
        name = u["name"] if u else NAME
    chat_log("private", ctype, from_uid, name, msg, to=to_uid)
    w = P.Writer()
    w.int(from_uid); w.int(ctype); w.string(msg); w.string(name)
    recipients = [c for c in list(getattr(GAME_SRV, "clients", ()) or [])
                  if c is not conn and (to_uid is None or GAME_SRV.client_uids.get(c) == int(to_uid))]
    for recipient in recipients:
        GAME_SRV.send_cmd(recipient, 1002, w)


if __name__ == "__main__":
    _load_copylist()
    start_http()
    start_sockets()
    log("EMU", "ready. client base URL: http://%s:%d%s/" % (HOST, HTTP_PORT, BASE))
    try:
        while True:
            time.sleep(3600)
    except KeyboardInterrupt:
        pass

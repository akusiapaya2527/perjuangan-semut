#!/usr/bin/env python3
"""Client-side boot simulation against the emulator.

Replays exactly what the AS3 client does (mySocket framing + ProcessCmd reads)
and asserts every response parses cleanly. Run after starting emulator.py.
"""
import json
import socket
import sys
import urllib.request
import urllib.parse

import protocol as P

BASE = "http://127.0.0.1:8080/antwarsmobile"
GAME_PORT = 9001

failures = 0
ADMIN_TOKEN = None


def admin_headers(extra=None):
    global ADMIN_TOKEN
    if ADMIN_TOKEN is None:
        req = urllib.request.Request(
            "http://127.0.0.1:8080/admin/login",
            data=json.dumps({"email": "admin@local.test", "password": "admin12345"}).encode(),
            method="POST", headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req) as resp:
            ADMIN_TOKEN = json.loads(resp.read().decode())["token"]
    headers = {"Authorization": "Bearer " + ADMIN_TOKEN}
    if extra:
        headers.update(extra)
    return headers


def check(name, ok, detail=""):
    global failures
    status = "PASS" if ok else "FAIL"
    print("  [%s] %s %s" % (status, name, detail))
    if not ok:
        failures += 1


def http_post(url, fields):
    data = urllib.parse.urlencode(fields).encode()
    req = urllib.request.Request(url, data=data, method="POST")
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read().decode())


def http_get(url):
    with urllib.request.urlopen(url) as resp:
        return resp.read().decode()


def recv_frame(sock):
    buf = b""
    while len(buf) < P.HEADER:
        buf += sock.recv(P.HEADER - len(buf))
    cmd, ver, subver, body_len, code = P.parse_header(buf)
    while len(buf) < P.HEADER + body_len:
        buf += sock.recv(body_len + P.HEADER - len(buf))
    return cmd, buf[P.HEADER:]


def send(sock, cmd, writer):
    sock.sendall(writer.frame(cmd))


def main():
    print("== HTTP ==")
    dl = http_post(BASE + "/mobile/devicelogin.php", {
        "sid": "111", "name": "semut", "loginMethod": 1, "channel": 100, "sign": "x"
    })
    check("devicelogin {data:{mid,key}}", "data" in dl and "mid" in dl["data"] and "key" in dl["data"], json.dumps(dl))

    wp = json.dumps({"mid": dl["data"]["mid"], "sitekey": None, "group": "", "mnick": "",
                     "key": dl["data"]["key"], "method": "GameMember.load", "param": None})
    load = http_post(BASE + "/api/flashapi.php", {"sid": "111", "win_param": wp})
    check("load has user[]", "user" in load, json.dumps(load)[:120])
    check("load user[8]==1 (skip CreateRole)", load["user"][8] == 1)
    check("load has role+account+sessionkey", all(k in load for k in ("role", "account", "sessionkey")))

    wp = json.dumps({"mid": dl["data"]["mid"], "sitekey": None, "group": "", "mnick": "",
                     "key": dl["data"]["key"], "method": "GameSAR.getCenterSever", "param": None})
    gs = http_post(BASE + "/api/flashapi.php", {"sid": "111", "win_param": wp})
    check("getCenterSever ret==0", gs.get("ret") == 0, json.dumps(gs)[:120])
    found = [s for s in gs.get("list", []) if s["mgid"] == 1 and s["svtype"] == 2]
    check("getCenterSever has svtype==2 mgid==1", len(found) == 1)

    ch = http_get(BASE + "/version/facebookid/ChangerLog.xml")
    check("ChangerLog.xml served", "<xml" in ch)

    print("== Avatar render ==")
    import urllib.request as _ureq
    for root in ("charcher_boy", "charcher_girl"):
        with _ureq.urlopen("http://127.0.0.1:8080/avatar_img?atlas=" + root) as resp:
            png = resp.read()
        check("avatar_img %s PNG" % root, png[:8] == b"\x89PNG\r\n\x1a\n" and len(png) > 1000, "len=%d" % len(png))

    print("== Socket GameServer ==")
    s = socket.create_connection(("127.0.0.1", GAME_PORT), timeout=5)
    mid, key = dl["data"]["mid"], dl["data"]["key"]

    def wlogin():
        w = P.Writer()
        w.int(mid)
        w.string(key)
        w.int(1)       # level
        w.string("Semut")
        return w
    send(s, 1001, wlogin())
    cmd, body = recv_frame(s)
    r = P.Reader(body)
    n = r.int()
    for _ in range(n):
        r.int()
    ver_s = r.string()
    online = r.int()
    check("cmd1008 loginSuccessful parses", cmd == 1008 and r.done(), "cmd=%d" % cmd)

    def w3014():
        w = P.Writer(); w.int(mid); return w
    send(s, 3014, w3014())
    cmd, body = recv_frame(s)
    r = P.Reader(body)
    uid = r.int(); mode = r.short()
    cnt = r.int() if mode in (0, 2) else None
    goods = []
    for _ in range(cnt or 0):
        g = [r.int() for _ in range(4)] + [r.string() for _ in range(2)] + [r.int() for _ in range(6)] + [r.string()]
        goods.append(g)
    check("cmd3014 getAllGoods mode==2", cmd == 3014 and mode == 2 and r.done(), "mode=%d cnt=%d" % (mode, cnt))

    def w3016():
        w = P.Writer(); w.int(mid); return w
    send(s, 3016, w3016())
    cmd, body = recv_frame(s)
    r = P.Reader(body)
    uid = r.int(); flag = r.short()
    equips = [r.int() for _ in range(13)] if flag == 0 else None
    place = r.string() if flag == 0 else ""
    check("cmd3016 getMemBody flag==0", cmd == 3016 and flag == 0 and len(equips) == 13 and r.done())

    def w1():
        w = P.Writer(); w.int(mid); return w
    send(s, 1, w1())
    cmd, body = recv_frame(s)
    r = P.Reader(body)
    r.int(); cnt = r.int()
    servers = []
    for _ in range(cnt):
        servers.append((r.int(), r.int(), r.string(), r.int(), r.int(), r.int()))
    has_battle = any(sv[1] == 1 for sv in servers)
    has_copy = any(sv[1] == 3 and sv[3] == 9003 for sv in servers)
    check("cmd1 getServerList battle+copy", cmd == 1 and has_battle and has_copy and r.done(), json.dumps(servers))

    def w4():
        w = P.Writer(); w.int(mid); w.int(1); w.int(1); return w
    send(s, 4, w4())
    cmd, body = recv_frame(s)
    r = P.Reader(body)
    r.int(); svid = r.int()
    check("cmd4 getServerIDByType svid", cmd == 4 and r.done(), "svid=%d" % svid)

    def w3111():
        w = P.Writer(); w.int(mid); w.int(mid); return w
    send(s, 3111, w3111())
    cmd, body = recv_frame(s)
    r = P.Reader(body)
    vals = [r.int() for _ in range(8)]
    gnum = r.int()
    for _ in range(gnum):
        r.int(); r.int(); r.int()
    check("cmd3111 onVipViewInfo parses", cmd == 3111 and r.done())

    for req_cmd, resp_cmd in ((3119, 3119), (3118, 3118), (3120, 3120)):
        w = P.Writer(); w.int(mid)
        send(s, req_cmd, w)
        cmd, body = recv_frame(s)
        r = P.Reader(body)
        r.int()
        cnt = r.int()
        for _ in range(cnt):
            r.int()
        check("cmd%d rental/vip parses" % resp_cmd, cmd == resp_cmd and r.done())

    # heartbeat — server must NOT reply (client sends every 9s)
    send(s, 30001, P.Writer())
    s.settimeout(1.0)
    try:
        extra = recv_frame(s)
        check("heartbeat gets no reply", False, "unexpected reply cmd=%d" % extra[0])
    except socket.timeout:
        check("heartbeat gets no reply", True)

    # 3005 setMemBody: equip good onlyID 1 to slot 'weapon' (uid, place, flag short, onlyID)
    def w3005():
        w = P.Writer(); w.int(mid); w.string("weapon"); w.short(1); w.int(1); return w
    send(s, 3005, w3005())
    cmd, body = recv_frame(s)
    r = P.Reader(body)
    uid = r.int(); flag = r.short(); place = r.string(); status = r.int()
    # equip status == 1 => server appends the equipped readGoods() (13 fields)
    if status != 0:
        for _ in range(4):
            r.int()
        for _ in range(2):
            r.string()
        for _ in range(6):
            r.int()
        r.string()
    check("cmd3005 setMemBody flag==0 place=weapon status=1",
          cmd == 3005 and flag == 0 and place == "weapon" and status == 1 and r.done(),
          "status=%d" % status)

    # 3013 toBuy: 1x Pedang Semut (typeID 11, frameID 1091, catalog price 500)
    def w3013():
        w = P.Writer()
        w.int(mid); w.short(0); w.short(1)
        w.int(1); w.int(11); w.int(1091); w.int(500); w.int(1); w.string("")
        return w
    send(s, 3013, w3013())
    cmd, body = recv_frame(s)
    r = P.Reader(body)
    uid = r.int(); ret = r.short()
    gold = None
    if ret == 0:
        gold = r.int()
        for _ in range(4):
            r.int()
        cnt = r.int()
        for _ in range(cnt):
            for _ in range(4):
                r.int()
            for _ in range(2):
                r.string()
            for _ in range(6):
                r.int()
            r.string()
        check("cmd3013 toBuy ret==0 w/ goods", r.done(), "gold=%s cnt=%d" % (gold, cnt))
    else:
        check("cmd3013 toBuy ret==0", False, "ret=%d" % ret)
    s.close()

    print("== Socket BattleServer ==")
    s2 = socket.create_connection(("127.0.0.1", 9002), timeout=5)
    before = admin_user(mid)["currency"]
    send(s2, 0, P.Writer())
    cmd, body = recv_frame(s2)
    r = P.Reader(body)
    # battle login reply: [ver string, exp int, btprop string, goodsStr string, rank int]
    r.string(); r.int(); r.string(); r.string(); r.int()
    check("battle login cmd1", cmd == 1 and r.done(), "cmd=%d" % cmd)
    send(s2, 6, P.Writer())
    cmd5, _ = recv_frame(s2)
    cmd38, _ = recv_frame(s2)
    cmd39, _ = recv_frame(s2)
    check("quickJoin -> enterRoom5 + robotCome38 + startRobot39", cmd5 == 5 and cmd38 == 38 and cmd39 == 39, "got %d,%d,%d" % (cmd5, cmd38, cmd39))
    w = P.Writer(); w.int(0); w.int(0); w.int(0)
    send(s2, 41, w)
    cmd, body = recv_frame(s2)
    r = P.Reader(body)
    winner = r.int(); cnt = r.int()
    site0 = None
    for _ in range(cnt):
        # client reads 8 ints/entry -> list[i]=[r0,r1,r4,r3,r5,r6,0,r7,r2];
        # list[i][0] must be a siteID (0=self), not the uid
        entry = [r.int() for _ in range(8)]
        if site0 is None:
            site0 = entry[0]
    r.int()  # isDoubleExp
    check("robotOver -> gameOver1006 parses", cmd == 1006 and winner == 0 and r.done(), "cmd=%d winner=%d" % (cmd, winner))
    check("gameOver1006 list[0][0] is siteID (not uid)", site0 == 0, "siteID=%s" % site0)
    after = admin_user(mid)["currency"]
    check("battle win grants coins (+100)", after - before == 100, "%d -> %d" % (before, after))
    s2.close()

    print("== Admin API ==")
    st = admin_state()
    check("state totals has stages", "stages" in st["totals"] and st["totals"]["stages"] >= 1, json.dumps(st["totals"]))
    check("state resources present", all(k in st for k in ("guilds", "shop", "friends", "monsters", "stages")))

    # stages CRUD roundtrip
    import urllib.request as urlreq
    def api_post(path, body):
        req = urlreq.Request("http://127.0.0.1:8080" + path,
                             data=json.dumps(body).encode(), method="POST",
                             headers=admin_headers({"Content-Type": "application/json"}))
        with urlreq.urlopen(req) as resp:
            return json.loads(resp.read().decode())
    cr = api_post("/admin/api/stages", {"name": "test_stage", "level": 1})
    st2 = admin_state()
    sid = [s for s in st2["stages"] if s["name"] == "test_stage"]
    check("stage create", cr.get("ok") and sid, "id=%s" % cr)
    if sid:
        api_post("/admin/api/stages/%d" % sid[0]["id"], {"delete": True})
        st3 = admin_state()
        check("stage delete", not [s for s in st3["stages"] if s["name"] == "test_stage"])

    eco_req = urlreq.Request("http://127.0.0.1:8080/admin/api/economy?reload=1",
                             headers=admin_headers())
    eco = json.loads(urlreq.urlopen(eco_req).read().decode())
    kinds = {e["kind"] for e in eco["ledger"]}
    check("economy ledger has battle+buy", "battle" in kinds and "buy" in kinds, str(kinds))

    # admin: sim battle + stage reward grant
    su = admin_user(mid)
    cur0 = su["currency"]; exp0 = su.get("exp", 0)
    sim = api_post("/admin/api/battle/sim", {"uid": mid, "win": 0})
    su1 = admin_user(mid)
    check("admin sim battle win +100", sim.get("ok") and su1["currency"] - cur0 == 100, str(sim))
    gr = api_post("/admin/api/stages/1/grant", {"uid": mid})
    su2 = admin_user(mid)
    st_row = [s for s in st["stages"] if s["id"] == 1][0]
    expect = int(st_row.get("reward_coin", 0) or 0)
    check("admin stage grant +%d" % expect, gr.get("ok") and su2["currency"] - su1["currency"] == expect, str(gr))

    # admin: grant booya cash -> account.boyaacurrency (AccountData.boyaaCoin)
    bb0 = admin_user(mid).get("boyaa_coin", 0)
    gb = api_post("/admin/api/user/%d" % mid, {"boyaa_coin": bb0 + 250})
    bb1 = admin_user(mid).get("boyaa_coin", 0)
    check("admin grant boyaa_coin +250", gb.get("ok") and bb1 - bb0 == 250, "%s -> %s" % (bb0, bb1))
    wp2 = json.dumps({"mid": mid, "sitekey": None, "group": "", "mnick": "",
                      "key": key, "method": "GameMember.load", "param": None})
    load2 = http_post(BASE + "/api/flashapi.php", {"sid": "111", "win_param": wp2})
    check("load account.boyaacurrency reflects grant", load2.get("account", {}).get("boyaacurrency") == bb1,
          str(load2.get("account", {}).get("boyaacurrency")))

    print("== CopyGame (PvE) ==")
    grade = http_post(BASE + "/api/flashapi.php", {
        "sid": "111",
        "win_param": json.dumps({"mid": mid, "sitekey": None, "group": "", "mnick": "",
                                 "key": key, "method": "GameCopys.getCopyGrade", "param": []}),
    })
    check("getCopyGrade ret==0 info{}", grade.get("ret") == 0 and isinstance(grade.get("info"), dict) and len(grade["info"]) > 0, str(grade)[:120])

    cdt1 = sorted((int(k) for k in grade["info"]))[0]
    # GameServer cmd4 getServerIDByType(3) -> svid 2 (CopyServer)
    sg = socket.create_connection(("127.0.0.1", GAME_PORT), timeout=5)
    def wc4():
        w = P.Writer(); w.int(mid); w.int(1); w.int(3); return w
    send(sg, 4, wc4())
    cmd, body = recv_frame(sg)
    r = P.Reader(body)
    r.int(); svid = r.int()
    check("cmd4 svtype3 -> svid2", cmd == 4 and svid == 2 and r.done(), "svid=%d" % svid)
    # energy: 3051 read -> 3052 consume 15 -> 3051 lower
    send(sg, 3051, P.Writer())
    cmd, body = recv_frame(sg)
    r = P.Reader(body)
    r.int(); r.short(); en_before = r.short()
    send(sg, 3052, P.Writer())
    cmd, body = recv_frame(sg)
    r = P.Reader(body)
    r.int(); etype = r.short(); en_after = r.short()
    check("cmd3052 consume 15 energy", cmd == 3052 and etype == 0 and en_before - en_after == 15,
          "%d -> %d type=%d" % (en_before, en_after, etype))
    send(sg, 3051, P.Writer())
    cmd, body = recv_frame(sg)
    r = P.Reader(body)
    r.int(); r.short(); en_verify = r.short()
    check("cmd3051 energy persisted", en_verify == en_after, "got %d want %d" % (en_verify, en_after))
    sg.close()
    # CopyServer socket: 4001 login -> [ret], 4122 freeRelive -> [freeleft]
    sc = socket.create_connection(("127.0.0.1", 9003), timeout=5)
    def wc4001():
        w = P.Writer(); w.int(mid); w.string(key); w.string("Semut"); return w
    send(sc, 4001, wc4001())
    cmd, body = recv_frame(sc)
    r = P.Reader(body)
    check("copy login cmd4001 ret==0", cmd == 4001 and r.int() == 0 and r.done(), "cmd=%d" % cmd)
    send(sc, 4122, P.Writer())
    cmd, body = recv_frame(sc)
    r = P.Reader(body)
    freeleft = r.int()
    check("copy freeRelive cmd4122 freeleft>0", cmd == 4122 and freeleft > 0 and r.done(), "freeleft=%d" % freeleft)
    send(sc, 4009, P.Writer())   # leaveRoom: no reply expected
    sc.settimeout(0.8)
    try:
        extra = recv_frame(sc)
        check("copy leaveRoom(4009) silent", False, "unexpected cmd=%d" % extra[0])
    except socket.timeout:
        check("copy leaveRoom(4009) silent", True)
    sc.close()

    # stage1: cpid1 diff1 stage1 -> cpdtlid 1; server must also accept via info.
    b = admin_user(mid)
    cur_before = b["currency"]
    exp_before = b.get("exp", 0)
    prize = http_post(BASE + "/api/flashapi.php", {
        "sid": "111",
        "win_param": json.dumps({"mid": mid, "sitekey": None, "group": "", "mnick": "",
                                 "key": key, "method": "GameCopys.getMobileCopyPrize",
                                 "param": {"cpdtlid": cdt1, "cpid": 1, "stage": 1,
                                           "difficulty": 1, "grade": 3}}),
    })
    ok_prize = prize.get("ret") == 0
    coin_gain = 0
    exp_gain = 0
    if ok_prize:
        coin_gain = prize["account"]["currency"] - cur_before
        rp = prize.get("role") or {}
        exp_gain = rp.get("mpoint", exp_before) - exp_before
        ok_prize = all(k in rp for k in ("mid", "mrolename", "mgender", "mflee",
                                         "mkill", "appearance", "mfailure", "mwinning",
                                         "mpoint", "mlevel", "vipmpoint"))
    check("getMobileCopyPrize ret==0 + role fields", ok_prize, str(prize)[:200])
    check("copy prize grants coins (>0)", coin_gain > 0, "gain=%d" % coin_gain)
    check("copy prize grants exp (>0)", exp_gain > 0, "gain=%d" % exp_gain)
    props = prize.get("props") or []
    if props:
        g = props[0]
        check("copy prize goods 13-field", len(g) == 13, "len=%d" % len(g))

    print("== Teman / Serikat (friends & union) ==")
    def wp(method, p):
        return http_post(BASE + "/api/flashapi.php", {
            "sid": "111",
            "win_param": json.dumps({"mid": mid, "sitekey": None, "group": "", "mnick": "",
                                     "key": key, "method": method, "param": p}),
        })
    frds = wp("GameFriends.getFrds", 1)
    ok_frds = isinstance(frds, list) and all(isinstance(f, list) and len(f) == 5 for f in frds)
    check("getFrds -> raw 5-field array list", ok_frds, str(frds)[:160])
    con = wp("GameConsortion.getConsortion", None)
    cinfo = con.get("cinfo") if con.get("ret") == 0 else None
    check("getConsortion cinfo cid==1 (leader Semut)", cinfo is not None and cinfo.get("cid") == 1 and "minfo" in con,
          str(con)[:160])
    cl = wp("GameConsortion.getConsortionList", None)
    ok_cl = cl.get("ret") == 0 and isinstance(cl.get("list"), list) and len(cl["list"]) >= 1
    ok_fields = ok_cl and all(k in cl["list"][0] for k in ("cid", "cname", "clevel", "memnum", "captainmid", "vcaptain"))
    check("getConsortionList ret==0 list+fields", ok_cl and ok_fields, str(cl)[:160])
    mem = wp("GameConsortion.getConsortionMembers", None)
    ok_mem = mem.get("ret") == 0 and isinstance(mem.get("list"), list) and len(mem["list"]) >= 1 \
        and all(len(row) >= 16 for row in mem["list"])
    check("getConsortionMembers 16-field rows", ok_mem, str(mem)[:160])
    notice = wp("GameConsortion.getPublicNotice", None)
    check("getPublicNotice has notice", notice.get("ret") == 0 and "notice" in notice, str(notice)[:120])

    print("== Level / XP ==")
    # client BaseValues.getLevel table, copied from bundled xml.data memlevelattr
    LEVEL_EXPS = [0, 600, 1560, 3000, 4980, 7680, 11340, 16320, 23040, 31980, 43800,
                  59280, 79380, 105240, 138180, 179760, 231720, 295980, 374640, 469980,
                  584340, 720960, 883500, 1076100, 1303320, 1570260, 1882560, 2246340,
                  2668320, 3155700, 3716160, 4357860, 5089380, 5919600, 6857700, 7913040,
                  9094980, 10412820, 11875620, 13491960, 15269880, 17216700, 19338720,
                  21641100, 24127620, 26800620, 29660700, 32706660, 35935320, 39341520,
                  42918000, 46655400, 50542260, 54584580, 58788540, 63160620, 67707540,
                  72436320, 77354220, 82468800]

    def client_level(exp):
        for i, need in enumerate(LEVEL_EXPS):
            if exp < need:
                return i or 1
        return 45

    def api_patch_user(uid, patch):
        req = urlreq.Request("http://127.0.0.1:8080/admin/api/user/%d" % uid,
                             data=json.dumps(patch).encode(), method="POST",
                             headers=admin_headers({"Content-Type": "application/json"}))
        with urlreq.urlopen(req) as resp:
            return json.loads(resp.read().decode())

    def level_via_load():
        ld = http_post(BASE + "/api/flashapi.php", {
            "sid": "111",
            "win_param": json.dumps({"mid": mid, "sitekey": None, "group": "", "mnick": "",
                                     "key": key, "method": "GameMember.load", "param": None}),
        })
        return int(ld["role"]["mlevel"]), int(ld["role"]["mpoint"])

    for exp in (0, 599, 600, 31979, 31980, 24127620, 26800620, 99999999):
        api_patch_user(mid, {"exp": exp})
        mlevel, mpoint = level_via_load()
        want = client_level(exp)
        check("exp %d -> level %d" % (exp, want),
              mlevel == want and mpoint == exp and admin_user(mid)["level"] == want,
              "got %d mpoint=%d" % (mlevel, mpoint))
    # spider city (ngarai) gate is client-side selfData.level >= 10 <=> exp >= 31980
    api_patch_user(mid, {"exp": 31980, "energy": 100})
    check("exp 31980 = level 10 (ngarai unlocked)", level_via_load()[0] == 10)

    # copy prize still reports the same exp/level table back (level-up consistency)
    exp_before = level_via_load()[1]
    prize2 = http_post(BASE + "/api/flashapi.php", {
        "sid": "111",
        "win_param": json.dumps({"mid": mid, "sitekey": None, "group": "", "mnick": "",
                                 "key": key, "method": "GameCopys.getMobileCopyPrize",
                                 "param": {"cpdtlid": 21, "cpid": 2, "stage": 1,
                                           "difficulty": 1, "grade": 3}}),
    })
    rp2 = prize2.get("role") or {}
    check("spider city stage prize role.mlevel == client_level(mpoint)",
          prize2.get("ret") == 0 and client_level(rp2.get("mpoint", 0)) == rp2.get("mlevel"),
          str(prize2)[:160])
    check("spider city stage prize grants exp", int(rp2.get("mpoint", exp_before)) > exp_before,
          "%d -> %s" % (exp_before, rp2.get("mpoint")))

    # every goods the client can render needs a part/* subtexture in a loaded atlas
    import emulator
    emulator._build_asset_index()
    icon_combos = [(11, 109), (26, 100), (12, 110), (14, 120),
                   (15, 101), (40, 101)]
    icon_combos += [(t, 105) for t in (16, 17, 18, 19)]
    icon_combos += [(20, f) for f in (101, 102, 103, 104)]
    bad = [(t, f) for t, f in icon_combos
           if emulator.goods_icon_name(t, f * 10) is None]
    check("all goods/forge icons have part/* subtexture",
          not bad, "missing=%s" % (bad or []))

    # every /mobile/*.php must answer JSON (no unhandled ioError in client)
    for ep in ("get_products.php", "create_order.php", "check_pay_order.php"):
        r = http_post(BASE + "/mobile/%s?sid=111" % ep,
                      {"mid": "1000001", "pmodes": "[]"})
        ok = isinstance(r, dict)
        if ep == "get_products.php":
            ok = ok and "productInfo" in r
        check("mobile %s answers JSON" % ep, ok, str(r)[:80])

    print("== result: %s ==" % ("ALL PASS" if failures == 0 else "%d FAILURES" % failures))
    return 0 if failures == 0 else 1


def admin_user(uid):
    for u in admin_state()["users"]:
        if u["id"] == uid:
            return u
    return {}


def admin_state():
    req = urllib.request.Request("http://127.0.0.1:8080/admin/api/state?reload=1",
                                 headers=admin_headers())
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read().decode())


if __name__ == "__main__":
    sys.exit(main())

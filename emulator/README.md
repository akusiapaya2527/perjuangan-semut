# Perjuangan Semut — Emulator Offline

Revival server emulator untuk **Perjuangan Semut (Ant Wars)** — build FB-Indonesia
(`com.boyaa.WARSFACEBOOKID`, `lanVersion=3`). Game client AS3/Starling dijalankan via
**Adobe AIR desktop (ADL)** di host, semua server (HTTP gateway, socket game, socket
battle) diemulasi lokal supaya game **bisa dimainkan sepenuhnya offline**.

```
┌──────────────  host (macOS)  ────────────────────────────┐
│  AIR client (via ADL) ──socket──► GameServer :9001       │
│       │                              BattleServer :9002  │
│       └────HTTP────► emulator.py :8080 (flashapi, res, /admin)│
└──────────────────────────────────────────────────────────┘
```

---

## 1. Prasyarat

| Kebutuhan | Versi / catatan |
|---|---|
| macOS | tested pada Darwin 25 (Apple Silicon OK) |
| Python 3 | `>=3.10` (tested 3.14), tanpa dependency eksternal |
| AIR SDK | Harman **51.1.3.12** (`emulator/sdk/AIRSDK51/`) |
| Docker (opsional) | hanya untuk menjalankan server-emulator dalam container |

Tidak butuh Java di runtime normal. FFDec hanya untuk *patching/extract* SWF, bukan
untuk menjalankan.

## 2. Struktur folder

```
emulator/
├── emulator.py          # server: HTTP :8080 + GAME :9001 + BATTLE :9002
├── protocol.py          # framing IC (9-byte header, little-endian)
├── admin.html           # dashboard admin (single-file, di-*serve* oleh emulator)
├── run.sh               # boot emulator + jalankan client AIR
├── Dockerfile / docker-compose.yml / .dockerignore
├── README.md
├── data/db.sqlite3      # database utama SQLite (state game + admin auth)
├── data/db.json         # backup/migrasi legacy JSON
├── runtime/
│   ├── app.xml          # descriptor AIR desktop (renderMode direct)
│   ├── antwarsmobilestarling.swf   # client yang sudah dipatch
│   └── res/             # webroot resource client (xml.data, audio, dst)
├── sdk/AIRSDK51/        # Harman AIR SDK (adl, runtimes)
└── seed/                # app seed auto-login: tulis SharedObject LoginData lalu exit
```

## 3. Jalankan server emulator

### Opsi A — native (rekomendasi)

```bash
cd emulator
python3 emulator.py            # foreground
# atau background:
nohup python3 emulator.py > emu.log 2>&1 &
```

Output sehat:

```
[HTTP]  listening http://127.0.0.1:8080/antwarsmobile
[GAME]  listening tcp://127.0.0.1:9001
[BATTLE] listening tcp://127.0.0.1:9002
[EMU]   ready. client base URL: http://127.0.0.1:8080/antwarsmobile/
```

Tiga layanan:

| Port | Layanan | Dipakai untuk |
|---|---|---|
| 8080 | HTTP | `mobile/devicelogin.php`, `api/flashapi.php` (JSON-RPC), webroot resource, `/admin` |
| 9001 | GameServer | socket IC/AS3 — login, goods, memBody, energy |
| 9002 | BattleServer | robot battle (quickJoin → enterRoom → robotOver) |
| 9003 | CopyServer | CopyGame PvE (login 4001, freeRelive 4122, relive) |

### Opsi B — Docker (server saja; client tetap di host)

```bash
cd emulator
docker compose up -d --build
# cek: curl http://127.0.0.1:8080/admin
docker compose logs -f emulator     # ikuti log
docker compose down                  # stop
```

Container bind `0.0.0.0` (via `EMU_HOST`), port di-*publish* ke `127.0.0.1` host, jadi
client AIR di host bisa connect langsung ke `127.0.0.1` seperti biasa. `data/db.json`
di-mount sebagai volume → database persist di host.

> ⚠️ Client AIR butuh GPU/Stage3D → **tidak** dijalankan dalam Docker. Docker hanya
> untuk server-emulator.

## 4. Jalankan client game

```bash
./run.sh
```

`run.sh` otomatis: (1) start emulator bila belum jalan, (2) lauch `runtime/app.xml`
via ADL. Client akan buka window game.

Flow login (auto): `run.sh` (1) jalankan seed (`seed/app.xml`) yang menulis
SharedObject `Antwars/LoginData` `{sid:"seed_auto_login",method:1}` lalu exit,
(2) launch client. SWF sudah dipatch (`LoginData.init` baca SO tanpa syarat
`Constants.debug`) → `LoginManager.login()` auto `sidToMid` → **langsung HALL,
nol klik**. Seed idempotent — dijalankan tiap boot, aman diulang.

### Alur main (ditargetkan 100% playable)

1. Masuk **HALL**.
2. Buka **RobotBattlefield** → **quick join** → server stubs masuk ruang + robot.
3. Selesaikan pertempuran → **robotOver** → hasil dikembalikan ke client.
4. Cek barang: buka **bag/persona** → barang dari `getAllGoods` (3014), yang
   `position=1` terpasang di slot memBody.

### Main via browser (streaming)

Buka **http://127.0.0.1:8090** — window game di-stream ke tab browser
(ScreenCaptureKit → MJPEG), mouse & keyboard dibalikkan ke game (CGEvent).
Client **tetap jalan via AIR/ADL** — SWF tidak diubah sama sekali.

```bash
./web.sh
```

`web.sh` otomatis: (1) compile bridge bila perlu, (2) pastikan emulator jalan,
(3) launch client kalau belum, (4) start `webbridge.py` + `bridge/streamer`,
(5) buka browser. **Ctrl-C** menghentikan streaming saja (client & emulator tetap jalan).

> **Kenapa bukan Ruffle?** SWF render via **Stage3D/Starling** (`Main.as` →
> `new Starling(Game, stage, viewPort)`, 21 file referensi `Context3D`) + API
> AIR-only (`flash.filesystem.File`, `flash.desktop.NativeApplication`). Ruffle
> **tidak mendukung Stage3D/AGAL** — di browser hasilnya layar hitam / crash.
> Streaming window ADL adalah satu-satunya cara memainkan game ini di browser
> tanpa port ulang.

#### Izin macOS (wajib sekali, tiap terminal baru)

Streaming butuh 2 permission untuk aplikasi terminal:

- **Screen Recording** — System Settings → Privacy & Security → Screen Recording
  (kalau tidak: stream hitam)
- **Accessibility** — System Settings → Privacy & Security → Accessibility
  (kalau tidak: klik / keyboard diabaikan)

Setelah memberi izin, **restart terminal**, jalankan `./web.sh` lagi.

#### Struktur file

| File | Fungsi |
|---|---|
| `bridge/streamer.swift` | capture window via ScreenCaptureKit + input CGEvent ke pid ADL |
| `bridge/build.sh` | compile → `bridge/streamer` |
| `webbridge.py` | HTTP :8090 — `/` page, `/stream` MJPEG, `/ws` input relay; terima frame (TCP :8091), kirim input balik (:8092) |
| `webbridge.html` | page kontrol: pointer + keyboard → WebSocket |

Port dipakai: **8090** (browser), **8091** (frame), **8092** (input) — tidak
mengganggu 8080/9001/9002 emulator.

## 5. Dashboard Admin

Buka **http://127.0.0.1:8080/admin** — login admin lalu dashboard gaya Adminator, dark/light theme,
semua CRUD + relasi.

### Seksi

| Menu | Isi |
|---|---|
| **Dashboard** | stat cards: users, barang, serikat, toko, teman, monster |
| **Users** | edit nama/lv/koin/energi/menang-kalah inline, +User, hapus, lompat barang |
| **Barang & Pakaian** | per-user goods: edit slot, **toggle pakai** (`position` 0↔1), +beri alat, hapus — **ikon barang** (crop dari atlas texture) |
| **Serikat / Guild** | CRUD guild (nama, leader, level, member) |
| **Toko** | katalog item (typeID, frameID, nama, harga) + **ikon item** |
| **Teman** | CRUD friends |
| **Monster** | CRUD monster (mapID 1001 = arena) + **gambar monster** (sprite atlas) |
| **Stages & Reward** | resource stage → monster + reward, **peta preview** (`mapID`) |
| **Relasi** | graf relasi: user→barang dipakai (slot), barang↔katalog toko (cocok typeID+frameID), guild→leader-user, teman→user, monsters di arena |

Toolbar global: ⭳ **Ekspor** (download `db.json`), ⭱ **Impor** (upload file hasil
ekspor), ⟲ **Reset** (kembali ke DB default).

> **Gambar/ikon**: emulator me-*crop* subtexture dari atlas texture client
> (`runtime/res/textures/0.5x/`) secara on-the-fly. Endpoint:
> `/goods_icon?typeID=&frameID=` (ikon barang sesuai aturan
> `ResAssetManager.getGoodsImage`), `/asset_img?name=<subtexture|atlas>` (karakter,
> monster), `/map_img?mapID=`, `/avatar_img?atlas=charcher_boy|charcher_girl`
> (potret semut utuh — armature `skeleton_boy/girl.xml` di-flatten per z-order,
> `avatar_render.py`). Tidak ada dependency gambar eksternal — murni
> `zlib` stdlib (`emulator/png.py`). Item tanpa ikon di atlas 0.5x menampilkan
> kosong.

### Manage database (mudah)

- DB utama = SQLite `data/db.sqlite3` (bukan PostgreSQL/MySQL). Semua perubahan langsung disimpan dalam transaksi SQLite dengan WAL.
- Skema relasional: `users`, `goods`, `auth_users`, `auth_sessions`, `admin_users`, `admin_sessions`, `friendships`, `friend_requests`, `resources`, `quests` (di `resources`), `ledger`, dan `chat`.
- `data/db.json` hanya dipakai sebagai sumber migrasi lama/backup; saat server pertama kali dijalankan, isinya otomatis dipindahkan ke SQLite.
- Dashboard `/admin` dan endpoint `/admin/api/*` memerlukan sesi admin berbasis cookie.
- Akun bootstrap: `admin@local.test` / `admin12345`. Ganti sebelum server pertama kali dijalankan dengan environment `ADMIN_EMAIL` dan `ADMIN_PASSWORD`.
- Password admin disimpan sebagai hash PBKDF2-SHA256, bukan plaintext.
- **Lokasi & format**: `{"users": { "<id>": {name,level,currency,energy,wins,losses,goods[],...} },
  "guilds":[], "shop":[], "friends":[], "monsters":[] }`.
- **Goods** — satu barang = 13 field (urutan wire `readGoods`):
  `onlyID,typeID,frameID,count,attribute,synthesis,expiration,strengthen,position,term,amount,isbind,color`.
  `position=1` = terpasang (dibaca slot) ; `slot` = nama slot memBody.
- **Slot memBody (13)**: `coat, shoes, glasses, leftring, rightleft, necklace, hat,
  glove, wing, chatframe, dbexpcard, weapon, weddingring`.
- Beri barang ke user: di seksi Barang → pilih user → isi `typeID` `frameID` `count`.

### 5b. Top-up / Pembayaran (#11)

Offline = **top-up TIDAK jalan lewat UI** (dibuat begitu):

- ANE pembayaran (`SystemProperties` → `ExtensionContext com.boyaa.ane`) adalah
  *dead-code* di desktop: semua pemanggil di-gate `lanVersion==2` / `isAndroid()`,
  jadi tidak pernah crash. Tidak ada yang perlu di-stub di sisi SWF.
- Tombol top-up in-game (dlg "充值"/boayaCoin) membuka `PaymentWebDlg` →
  `StageWebView` ke `https://paycn.boyaa.com/...` (web asli Boyaa) → offline = dialog
  kosong, bisa ditutup. Tidak ada kredit.
- **Cara grant koin premium (boyaaCoin, kolom `account[3]`)**: lewat admin
  (`/admin/api/user/<id>` POST `{"boyaa_coin":N}`) atau kolom **BB** di dashboard
  Admin → Users. Nilai ini ikut payload `GameMember.load` → `account.boyaacurrency`
  dan muncul di dlg top-up setelah refresh account.
- `currency` = koin biasa (gameGold, dipakai toko/battle) — grant via kolom **Koin**.

## 6. Protocol (ringkas)

- Frame IC 9-byte: `"IC"` + cmd(short LE) + ver + subver + bodyLen(short) + code;
  body per-field **little-endian**, string = `uint(len+1)` + utf-8 + NUL.
- Game flow: `1001 login→1008`, `3014 getAllGoods`, `3016 getMemBody`, `3005 setMemBody`
  (persist pakai), `3051 getEnergy`, `3114`, heartbeat `30001`.
- Battle: login `cmd 0→1`, `6 quickJoin→5 enterRoom` + `39 onStartRobot`,
  `41 robotOver→1006`.
- CopyGame (PvE): CopyServer `4001 login→ret`, `4122 freeRelive→freeleft`,
  `4123 useFreeRelive`, `4120 relive`, `4009 leaveRoom`. HTTP `GameCopys.getCopyGrade`
  → semua stage grade3 (unlock penuh), `GameCopys.getMobileCopyPrize` → koin+exp+goods
  digrant ke DB (ledger `grant`). Energi per stage dipotong via socket `3052`.
- HTTP gateway: `POST api/flashapi.php` `{sid, win_param:{method,param,...}}`; sign
  MD5 untuk `devicelogin` = MD5(sid+name+`fcc2f629-817b-4955-94be-ba1da73b3164`).
- Chat (mirror `ChatRoomDlg`): klien kirim `sendLoudSpeaker` `1007 [type,msg,param]`
  → server broadcast `1026 [uid,type,onlyId,name,str]` ke SEMUA koneksi (termasuk
  pengirim; klien render dari push saja). Kirim `sendChatToFriend` `1002
  [toUid,type,str]` → relay `1002 [uid,type,str,name]` ke koneksi lain (kecuali
  pengirim — sender render lokal). `type==3` = ruangan (tab Current), selain = dunia
  (tab World). Terjadi percobaan `db["chat"]` (cap 500). Admin: tab **Chat** menu
  Sosial — lihat + kirim via `GET/POST /admin/api/chat[/send]`.

## 7. Troubleshooting

| Gejala | Solusi |
|---|---|
| `Address already in use` | `lsof -ti tcp:8080 \| xargs kill -9` (ulangi 9001, 9002); `pkill -9 -f emulator.py` |
| Admin: "StartTag invalid element name" | pastikan `/admin` di-*serve* via `_send_html` (Content-Type `text/html`), bukan `text/xml` |
| HALL kosong / barang tidak muncul | cek DB ada goods; restart client; goods muncul dari `3014` |
| Client minta download resources terus | webroot `runtime/res` harus lengkap (`xml.data`, audio), `ChangerLog` special-case version 0 |
| Login stuck di layar | seed harus pernah jalan (`run.sh` otomatis); kalau layar login muncul = SO belum ter-seed → jalankan `seed/app.xml` sekali; server terima sid apa pun |
| Dalam Docker, client tak bisa connect | EMU_HOST harus `0.0.0.0` di container; client di host pakai `127.0.0.1` |
| Update resource | sesuaikan `RES_ROOT` / letakkan file di `runtime/res` lalu restart |
| Browser: stream hitam | Screen Recording belum diizinkan ke terminal (lihat §4 Main via browser) |
| Browser: klik tidak masuk game | Accessibility belum diizinkan; atau streamer berhenti — cek `emulator/streamer.log` |
| `:8090` tak bisa dibuka | `lsof -ti tcp:8090 \| xargs kill -9`, cek `web.log`, jalankan `./web.sh` lagi |
| Streamer: "window not found" | client belum launch / pid salah — pastikan ADL jalan (`pgrep -f adl`), jalankan ulang `web.sh` |

## 8. Status fitur

| Fitur | Status |
|---|---|
| HTTP gateway + login (devicelogin) | ✅ |
| Socket GameServer (goods, memBody, energy) | ✅ + persist DB |
| BATTLE server | ✅ masuk ruang + robot + hasil (1006) |
| Reward pertempuran → wins/losses/koin | ✅ mengalir ke DB (menang +100, kalah +20) |
| CopyGame PvE (stage1-9) | ✅ CopyServer :9003 + getCopyGrade unlock + reward grant koin/exp/goods + energi (3052) |
| Map PvE hilang (202/203) | ✅ fallback ke map_201 (visual, stage tetap jalan) |
| Progresi: exp→level | ✅ exp dari battle+copy, `level_from_exp` (threshold 100 naik 50/lv), level di role payload |
| Energi: consume + regen | ✅ 3052 potong 15/stage, regen 1/5 mnt (energy_ts), 3051 baca dengan regen |
| Layar Teman (Friends) | ✅ `GameFriends.getFrds` → array `[antId,level,nickName,sex,marrayState]` dari DB friends; add/delete mutasi DB |
| Layar Serikat (Union) | ✅ `GameConsortion.getConsortion/List/Members/PublicNotice` dari DB guilds (cid,cname,clevel,member 16-field) |
| Admin: sim battle + grant stage | ✅ tombol ⚔ menang/kalah per user (`/admin/api/battle/sim`), tombol beri per stage (`/admin/api/stages/<id>/grant`) — koin/exp/level/ledger sinkron |
| Beli item toko in-game | ✅ cmd 3013 (`toBuy`) — harga otoritatif dari katalog toko, potong koin, tambah barang |
| Modul Ekonomi admin | ✅ ledger (buku kas) singkron dari aksi game: beli/battle/grant + stok koin per user |
| Relasi reward ↔ level stage | ✅ resource `stages` (monster_id→monster, reward_typeID/frameID→toko) + panel relasi |
| Admin dashboard + CRUD + relasi + DB JSON | ✅ |
| Chat panel admin (mirror ChatRoomDlg) | ✅ percakapan dunia/ruangan/pribadi dari klien tersimpan di DB + tampil di admin; admin bisa kirim sebagai user → broadcast ke klien (`1026`/`1002`) |
| Avatar user di admin = semut (bukan UV atlas) | ✅ `/avatar_img` flatten armature (`skeleton_boy/girl.xml` + charcher atlas, per z-order) render potret penuh — cached di `data/img_cache` |
| Docker | ✅ server |
| Auto-login tanpa klik | ✅ patch SWF (`LoginData.init` baca SO tanpa gate `Constants.debug`) + seed (`seed/app.xml` → `Antwars/LoginData`) → HALL tanpa klik; `run.sh` seed dulu tiap boot |
| Top-up / Pembayaran (#11) | ✅ ANE dead-code di desktop (aman); top-up UI = dialog web kosong (tutup); koin premium via admin — lihat §5b |
| Main via browser (streaming) | ✅ window ADL → MJPEG + input CGEvent (`web.sh`, §4b) |

Loop gameplay (server): **HALL → RobotBattle → quickJoin → fight → robotOver → hasil &
koin masuk DB → beli di toko dengan koin → barang masuk tas → pakai/di-slot** semuanya
terhubung ke `data/db.json` dan terlihat di admin.

*(lokasi file: semua path relatif folder `emulator/`)*

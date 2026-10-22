# Deploy Perjuangan Semut — perjuangansemut.akusiapaya.web.id

Menjalankan fork ini online di VPS Ubuntu (tanpa Docker, hemat RAM):
front-end Ruffle di `web/` + emulator Python + ws_bridge, satu domain lewat Caddy.

## Arsitektur

| Lalu lintas browser | Ditangani oleh |
|---|---|
| `/` dan file statis (SWF, Ruffle WASM) | Caddy file_server dari `/var/www/perjuangansemut` (= isi `web/`) |
| `/auth`, `/auth-assets`, `/antwarsmobile/*` | Caddy reverse_proxy → emulator `127.0.0.1:8080` |
| `/game`, `/battle`, `/copy` (WebSocket) | Caddy reverse_proxy → ws_bridge `127.0.0.1:8081` → TCP 9001/9002/9003 |

Backend hanya bind localhost. Port game tidak dibuka ke internet dan firewall tidak diubah.

## Kenapa SWF-nya dipatch?

Client original (cabang `isLocal`) memakai base HTTP `http://127.0.0.1:8080/antwarsmobile/`
yang tertanam di dalam SWF — dari browser pengunjung itu akan menunjuk ke mesin
pengunjung sendiri. `deploy/patch-swf.sh` mengganti satu baris itu menjadi
`https://perjuangansemut.akusiapaya.web.id/antwarsmobile/` memakai FFDec (Java),
meniru cara pemilik repo membangun SWF spike-nya. Sumber hasil patch tersimpan
di `deploy/swf-src/Constants.as`. Socket game sengaja tetap `127.0.0.1:9001-9003`
karena `socketProxy` Ruffle di `web/index.html` mencegat alamat itu dan
meneruskannya lewat `wss://<domain>/game|battle|copy` ke ws_bridge.

## Instalasi

Di VPS: clone repo (branch `deploy-vps`), lalu jalankan `deploy/install.sh`,
isi `/opt/perjuangansemut/perjuangansemut.env` (admin emulator — ganti dari
default!), tempel `deploy/Caddyfile.snippet` ke Caddyfile, validasi, reload Caddy.
Prasyarat DNS: A record `perjuangansemut.akusiapaya.web.id` → IP VPS.

## Operasional

```bash
systemctl status perjuangansemut-emulator perjuangansemut-bridge
journalctl -u perjuangansemut-emulator -f
sudo systemctl restart perjuangansemut-emulator perjuangansemut-bridge
```

Dashboard admin emulator tidak diekspos publik; akses lewat tunnel:
`ssh -L 8080:127.0.0.1:8080 ubuntu@<IP VPS>` lalu buka `http://127.0.0.1:8080/admin`.

Data persisten (akun, chat, quest): SQLite di `app/emulator/data/` di server —
backup cukup salin folder itu. Rollback: matikan kedua service dan hapus blok
Caddy situs ini, reload Caddy; service lain (Hermes/9Router) tidak terpengaruh.

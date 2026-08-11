# Backend Authentication Gate Design

## Goal

Require visitors to authenticate before using the browser game page, persist the authenticated session across refreshes, and provide a working logout action backed by the existing Python service and JSON database.

## Context

The browser entry point is `emulator/webbridge.html`, served by `emulator/webbridge.py`. The game data database is `emulator/data/db.json`. The webbridge port is configurable through `WEBBRIDGE_HTTP` and may be run on port 8099.

## Architecture

The webbridge will expose a small cookie-based authentication API. Registration stores a new web account in the JSON database with a PBKDF2 password hash and salt. Login creates an in-memory server session identified by a cryptographically random token and sends it as an HttpOnly cookie. The browser calls the session endpoint on startup; a valid cookie displays the game page, while an unauthenticated visitor sees the login/register gate.

The existing stream and WebSocket endpoints will require the same authenticated session. Logout deletes the server session and expires the cookie. The account database is persistent; sessions intentionally live in the running webbridge process and are renewed only through explicit login.

## HTTP API

- `POST /api/auth/register` accepts `{ "username": string, "password": string }`, creates an account, and starts a session. It returns `201` with a safe user object or `409` for a duplicate username and `400` for invalid input.
- `POST /api/auth/login` accepts the same fields, starts a session, and returns `200` with a safe user object. Invalid credentials return `401`.
- `GET /api/auth/session` returns `200` with the current safe user object or `401` when no valid session exists.
- `POST /api/auth/logout` deletes the current session, expires the cookie, and returns `200`.
- `/stream` and `/ws` reject unauthenticated requests with `401`.

Usernames are trimmed, case-insensitive for uniqueness, and limited to a practical local-web length. Passwords must be non-empty and meet a minimum length. Error responses are JSON and never expose password hashes or salts.

## Browser behavior

On load, the page checks `/api/auth/session` before opening the stream or WebSocket. The gate has Login and Register modes, inline error/status text, and disabled submit state while a request is pending. A successful login or registration reveals the existing remote-play UI. Logout closes active stream/WebSocket activity, returns to the gate, and prevents further game input until the user authenticates again.

## Security and persistence

Passwords use Python's standard-library PBKDF2-HMAC with a per-user random salt. Session tokens use `secrets.token_urlsafe`, are stored only server-side, and are sent with `HttpOnly` and `SameSite=Strict` cookie attributes. The database writes are serialized under the existing database lock and use an atomic temporary-file replacement so a registration cannot leave a partially-written JSON file.

## Testing

Backend tests will exercise registration success and duplicate rejection, password hashing behavior, valid and invalid login, session lookup, logout invalidation, and protected endpoint rejection. Browser behavior will be verified through a lightweight static/endpoint check and a manual run against the configured webbridge port: first visit shows the gate, successful login shows the game, refresh keeps the game visible, and logout returns to the gate.

## Scope

This feature does not change the AIR/SWF login flow, game accounts used by the emulator protocol, or admin authentication. It adds web-access accounts specifically for the browser remote-play entry point.

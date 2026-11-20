# Personal Device Authentication (Patch 2 + 3)

Aariya now proves **which device** is connecting, not just that someone knows the
shared `WS_SECRET_TOKEN`. Each device is paired once, keeps a long-lived
credential in secure OS storage, and opens WebSockets with a **one-use,
path-bound, 30-second ticket**.

## 1. Choose the owner identity

Device auth is enabled by setting `AARIYA_OWNER_ID`. Every paired device
resolves to this single owner. On this installation the real history belongs to
**`u1`**, and `.env` has been set to `AARIYA_OWNER_ID=u1` (the server loads
`.env` at startup):

```
conversation_messages: u1=872, voice_test=116, user_default=102,
                       __smoke_user__=32, seg_user=10, smoke=6
```

A backup was taken before this work:
`data/backups/brain_v4.db.pre-device-auth-<timestamp>`.

Set it only after confirming that `u1` is the identity you want to keep:

```dotenv
AARIYA_OWNER_ID=u1
```

If your history is split across several ids, stop and plan an explicit,
backed-up migration; do not merge test/smoke records silently.

## 2. Create a pairing code (server machine only)

Pairing codes are created by a local CLI — never by an HTTP endpoint — expire
after five minutes, and work once.

```bash
# this computer
server/.venv/bin/python -m server.tools.create_device_pairing_code --role dashboard

# the phone
server/.venv/bin/python -m server.tools.create_device_pairing_code --role mobile
```

The command prints four five-character groups (`XXXXX-XXXXX-XXXXX-XXXXX`,
100 bits of randomness) and its expiry time. Enrollment is throttled to five
failed guesses per source and twenty attempts globally per 15 minutes; exceeded
limits return HTTP 429 with `Retry-After`.

## 3. Pair the devices

* **Dashboard / Electron** — System Health → *Pair this computer*; enter the
  code. The credential is encrypted by Electron `safeStorage` in the main
  process (`userData/device-credential.bin`), never in renderer
  `localStorage`. In a plain browser dev session it is memory-only: pairing is
  repeated after a reload.
* **Flutter** — the phone icon in the chat app bar opens *Trusted Device*.
  Enter the code there; `DeviceAuthService.pair(...)` stores the credential in
  Android Keystore / iOS Keychain via `flutter_secure_storage`. A revoked
  credential shows a red "no longer trusted" banner that opens the same screen.
  For a phone reaching a LAN server, enable *HTTPS / WSS* in Server Settings (a
  TLS reverse proxy is required off-loopback).
* **Unity** — set `AARIYA_DEVICE_CREDENTIAL` (or the Inspector field) to a
  paired dashboard credential; the client requests `/api/auth/ws-ticket` and
  offers the ticket subprotocol on `/ws/brain`.

Both devices resolve to `AARIYA_OWNER_ID`; the phone cannot claim dashboard
authority, and neither device can select another owner with `?user_id=`.

## 4. Transport

Non-loopback device auth requires HTTPS/WSS. For a trusted LAN development
setup only, set:

```dotenv
AARIYA_ALLOW_INSECURE_DEVICE_AUTH=1
```

Without it, plain HTTP/WS pairing and tickets are refused outside loopback so
credentials and tickets are not exposed in transit.

## 5. Revocation

```http
DELETE /api/auth/devices/{device_id}
Authorization: Bearer <a DASHBOARD device credential of the same owner>
```

Only a dashboard device may revoke devices. Revocation immediately deletes the
target's outstanding tickets, rejects its credential, sends live sockets a
`{"type":"device.revoked"}` frame, and closes them with code `4001`. Flutter and
the Electron dashboard clear the local credential and show the pairing screen
instead of reconnecting. The other device is unaffected.

## Endpoints

| Method | Path | Purpose |
| --- | --- | --- |
| POST | `/api/auth/device/enroll` | redeem a one-use pairing code |
| POST | `/api/auth/ws-ticket` | issue a path-bound WS ticket |
| GET | `/api/auth/me` | owner + device identity |
| GET | `/api/auth/devices` | trusted devices for this owner |
| DELETE | `/api/auth/devices/{device_id}` | revoke one device |

## Migration notes

* With `AARIYA_OWNER_ID` unset, the server keeps the legacy shared-token
  behaviour so an existing installation is not locked out before pairing.
* In strict mode, `?user_id=` is ignored on the private WebSocket routes
  (including `/ws/collab/{room}`), `/ingest/device`, analytics,
  emotion-predictor, SDK trust/memory endpoints, and compliance
  export/delete/consent mutations. Collaboration REST reads/writes and all
  MCP/tooling endpoints (`/api/tools/*`, `/api/knowledge/*`) also require a
  device credential; collab note/task authors are stamped with the device
  label rather than a caller-supplied name. System Health REST now requires a
  dashboard device in strict mode (the legacy shared-token guard remains only
  when device auth is not configured).
* Dashboard-only authority includes `/api/fs/*`, `/api/sandbox/*`,
  `/api/vision/*`, autonomy writes, memory import/push, security scans,
  compliance mutations, device revocation, `/api/tools/call`, MCP sync,
  code indexing, and SDK kill-switch/shutdown operations. Both device roles may
  read autonomy state, events, memory export/ledger, tool listings, knowledge
  graph queries, and compliance read-only views.
* Set `AARIYA_DEVICE_AUTH_REQUIRED=1` to refuse startup when
  `AARIYA_OWNER_ID` is missing, preventing an accidental legacy-mode
deployment.
* `WS_SECRET_TOKEN` remains useful as a transport-level shared secret, but it
  no longer establishes device ownership.
* `AARIYA_TRUSTED_PROXIES` must contain your reverse proxy for
  `X-Forwarded-Proto: https` to be believed.

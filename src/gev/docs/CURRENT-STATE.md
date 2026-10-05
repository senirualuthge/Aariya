# GEV — current state

Living notes for the parts of the geospatial app where the *current* behaviour is a
deliberate decision rather than an accident. Each entry names the code that owns the
decision, so a reader can check the claim instead of trusting it.

Historical context and rationale live in the QA harnesses under `scripts/gev/` and in
the source comments themselves. This file only records "what is true now, and why we
are not changing it".

---

## 1. Map / terrain datum

### 1a. Height-datum contract

Terrain is keyless global ellipsoidal (Re:Earth Terrain / Mapterhorn, CC BY 4.0, EGM2008
geoid via NGA), constructed with `EllipsoidTerrainProvider.fromUrl()` — never a
hand-built `{z}/{x}/{y}.terrain` URL. See `src/gev/js/mapStackController.js`.

Consequences that are contract, not accident:

- Anything positioned from a surveyed altitude (vessel drafts, port approaches, flight
  ground snaps) is placed against the geoid, not against a flat ellipsoid. Vessel
  billboards must be sea-surface anchored, not ellipsoid anchored.
- Camera coordinates are batched through the terrain provider before they are used for
  picking and framing (`src/gev/js/data/cctv.js`), so a camera resolved against the
  wrong datum does not silently jump.
- The OpenSky flights layer polls on its own ~30 s interval. QA that waits for live
  aircraft samples must allow a full poll interval (`scripts/gev/qa-height-datum.mjs`).

Assertion harness: `scripts/gev/qa-height-datum.mjs` (flights/ground snap),
`scripts/gev/qa-vessel-datum.mjs` (AIS vertical datum, per-port, against the live feed).

---

## 2. Camera

The camera model is deliberately a "spy satellite simulator": one motion at a time,
driven per clock tick, with bounded `once` nudges and `continuous` moves that any manual
canvas input or navigation tool cancels. See `src/gev/js/cameraVerbs.js`.

Camera ownership is explicit — a layer acquires the camera for a track and releases it,
with a single owner at a time (`src/gev/js/camera.js`, `src/gev/js/cockpitTracking.js`).
The release ordering relative to scene/context switches is pinned by
`src/gev/js/cameraHandoff.test.mjs` and `src/gev/js/cockpitMarkup.test.mjs`.

---

## 3. First-run launcher — accepted no-shows

**A surface class that never clears means no launcher for that page load.**

None of the four first-run classes is restored at startup; each is set by a live action
(cockpit entry, a scene run, the recording toggle, the clean-view toggle). So a
first-run block that is already engaged at startup is an error path, while a genuinely
long recording or clean-view session is completely ordinary.

A "reveal the launcher anyway after N seconds" timer was considered and **rejected**:
it would trade a benign no-show for the launcher punching through a recording in
progress, which is the worse of the two failures. The no-show is benign — the card stays
hidden, the key handler is inert (`isTopmost()` is false), no session flag is written,
and the observer is disconnected.

The governing function is `syncToExclusiveSurfaces()` in
`src/gev/js/firstRunExperience.js`; the note sits directly above it so the next editor
reads the decision before adding a timer. Pinned by
`src/gev/js/firstRunExperience.test.mjs` ("a surface class that never clears is an
ACCEPTED no-show, not a timer"). Mutation harness:
`scripts/gev/qa-firstrun-mutations.mjs`.

---

## 4. Voice missions

First-run missions ride **existing** tools. `GEV_REALTIME_TOOLS` in
`vite.gev.config.js` is a frozen literal — its byte length and SHA-256 are pinned by
`src/gev/js/firstRunExperience.test.mjs`, so a schema edit or a cache bust is a test
failure, not a silent change.

Reachability comes from one instruction string (the `NAMED VIEWS are shorthand` entry),
whose rollback is deleting that string. Every layer a mission drives must already be an
allowed value in the shipped `set_layer_visibility` enum.
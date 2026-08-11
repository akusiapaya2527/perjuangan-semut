# Equipment Rendering and Admin Quests Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Synchronize equipment rendering and interaction across backend, admin, and game, and add database-backed quests that appear and complete in-game.

**Architecture:** Keep `emulator/emulator.py` as the authoritative JSON-backed HTTP/game gateway, extract equipment normalization into focused helpers, and keep avatar composition in `emulator/avatar_render.py`. Extend the existing ActionScript mission pipeline with a server-defined dynamic mission conversion path while preserving built-in XML missions.

**Tech Stack:** Python 3 standard library, JSON database, HTML/CSS/JavaScript admin dashboard, ActionScript 3/Starling client, existing AIR SDK build.

## Global Constraints

- Preserve existing built-in mission definitions and game protocol behavior.
- Use `onlyID` plus `slot` as the equipment identity; do not infer equipped state only from `typeID/frameID`.
- Keep persistence in `emulator/data/db.json` and use existing save/load helpers.
- Do not add third-party runtime dependencies.
- Verify every production change with focused tests before claiming completion.

### Task 1: Lock down equipment normalization

**Files:**
- Modify: `emulator/emulator.py`
- Test: `emulator/test_equipment.py`

**Interfaces:**
- Produce `equipment_slot_for_good(good)`, `normalize_user_goods(user)`, and `equipped_goods(user)` helpers used by avatar, admin state, and game payloads.

- [ ] Write failing tests for duplicate equipped goods, supported slot mapping, inventory retention, and stable `onlyID` selection.
- [ ] Run `python3 -m unittest emulator/test_equipment.py -v` and confirm the failures are caused by missing helpers/behavior.
- [ ] Implement minimal normalization and slot mapping using existing `_slot_for_type` conventions.
- [ ] Run the focused tests and the existing `python3 -m unittest discover -s emulator -p 'test*.py' -v` command.

### Task 2: Fix avatar renderer and backend payloads

**Files:**
- Modify: `emulator/avatar_render.py`
- Modify: `emulator/emulator.py`
- Test: `emulator/test_avatar_render.py`

- [ ] Write failing tests proving an equipped coat, shoes, wing, helm, and weapon are composed once and that missing assets do not blank the base avatar.
- [ ] Run the focused tests and verify the expected failure.
- [ ] Implement the shared slot-to-atlas mapping and use normalized equipped goods in `/avatar_img`, admin state, and relevant game response builders.
- [ ] Run renderer tests and inspect generated PNG dimensions/content metadata.

### Task 3: Make Tas state exclusive and item actions correct

**Files:**
- Modify: `antwarsmobilestarling.swf-decompile/src/com/boyaa/antwars/view/screen/backpack/Backpack.as`
- Modify: `antwarsmobilestarling.swf-decompile/src/com/boyaa/antwars/view/screen/backpack/EquipedListFrame.as`
- Modify: `antwarsmobilestarling.swf-decompile/src/com/boyaa/antwars/view/screen/backpack/BackpackItemRenderer.as`
- Modify: `emulator/emulator.py` action endpoint/payloads
- Test: `emulator/test_equipment_actions.py`

- [ ] Identify the exact Tas dialog class and write failing tests for equip/unequip state transitions and one active category.
- [ ] Run tests to confirm red state.
- [ ] Implement tab reset/selection and single-card click behavior in the client; make backend actions persist `position` and `slot` together.
- [ ] Rebuild the SWF through the existing AIR configuration and run focused backend tests.

### Task 4: Add persistent quest definitions and server state

**Files:**
- Modify: `emulator/emulator.py`
- Modify: `emulator/data/db.json` only through runtime/default migration logic
- Test: `emulator/test_quests.py`

- [ ] Write failing tests for quest create/update/delete, default progress for a user, matching action-code progress, level gating, and one-time reward claims.
- [ ] Run the focused tests and confirm red state.
- [ ] Implement `quests` defaults/migration, admin CRUD, per-user progress persistence, game state serialization matching `MissionDataList.reviseData`, and atomic reward validation.
- [ ] Run quest tests plus the full emulator test suite.

### Task 5: Add quest editor to the admin dashboard

**Files:**
- Modify: `emulator/admin.html`

- [ ] Add a Quest navigation entry, table, create form, edit/delete controls, and count/state rendering.
- [ ] Connect controls to `/admin/api/quests` and refresh shared state after writes.
- [ ] Verify the dashboard can create a quest with an action code, target, and reward, then reload it from the backend.

### Task 6: Render and progress dynamic quests in the game client

**Files:**
- Modify: `antwarsmobilestarling.swf-decompile/src/com/boyaa/antwars/data/MissionDataList.as`
- Create: `antwarsmobilestarling.swf-decompile/bin/swf-decompile.swf` as the generated build artifact, if the AIR build succeeds
- Modify: `antwarsmobilestarling.swf-decompile/src/com/boyaa/antwars/net/php/GameTable.as` only if request serialization needs the dynamic payload
- Test: `emulator/test_quest_wire.py`

- [ ] Write failing wire-format tests for a dynamic quest definition and its state array.
- [ ] Run tests and verify red state.
- [ ] Add conversion from server-defined quest records into `MissionData`, `SubMissionData`, and `RewardData` without removing XML missions.
- [ ] Ensure the existing mission dialog lists the new record, progress hooks update it, and claim calls the existing reward endpoint.
- [ ] Rebuild the SWF, launch the emulator, and manually verify create → refresh → progress → claim.

### Task 7: Final regression verification

**Files:**
- Verify: `emulator/emulator.py`, `emulator/avatar_render.py`, `emulator/admin.html`, changed ActionScript sources

- [ ] Run all Python tests and any available ActionScript/AIR build command.
- [ ] Run a live smoke test against the emulator admin endpoint and game HTTP gateway.
- [ ] Check the diff for accidental generated/binary changes and document any toolchain limitation.

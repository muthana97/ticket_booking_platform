# Personal Information (Settings) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a "Personal Information" section to the Settings hub so every signed-in role can edit their `full_name`, `phone_number`, and `national_id`.

**Architecture:** Backend adds a single `PATCH /auth/me` endpoint that partial-updates the three columns already on `User` (no migration). Frontend adds one pillow-styled section between Language and Commissions, wired to the new endpoint. Autofill behavior on the booking screen stays exactly as it is today.

**Tech Stack:** FastAPI + Pydantic v2 · SQLAlchemy ORM · pytest + FastAPI TestClient · Vanilla JS + pillow CSS (v2) inside `frontend/index.html`.

**Spec:** `docs/superpowers/specs/2026-07-28-personal-information-design.md`

## Global Constraints

- Backend never breaks the `min_length=2, max_length=120` bound on `full_name` (matches `RegisterRequest`). `phone_number` ≤ 20, `national_id` ≤ 40.
- `full_name` is required on the User row — cannot be cleared. `phone_number` and `national_id` are nullable and can be cleared by sending explicit `null`.
- Forward-only: profile edits never touch existing `passengers` rows or ticket data.
- Autofill code path (`renderPax()` in `frontend/index.html`, currently at line ~9853) MUST NOT be modified.
- Every new user-visible string gets both EN and AR entries in the `I18N` table. Numeric inputs (phone, national ID) get `dir="ltr"` under RTL.
- Follow pillow (v2) primitives — `.settings-section`, `.panel`, `.field-block`, `.cta`. No new visual language.
- Follow the existing auth-router pattern: return the ORM `User` directly (Pydantic serializes via `schemas.UserOut` with `from_attributes = True`); use `Depends(deps.get_current_user)`.
- Commits: no `--no-verify`, no `--amend`. Small commits per task.

---

## File Structure

**Backend files touched:**
- Modify `backend/src/auth/schemas.py` — add `ProfileUpdate` model.
- Modify `backend/src/auth/service.py` — add `update_profile()`.
- Modify `backend/src/auth/router.py` — add `PATCH /auth/me` endpoint.
- Create `backend/tests/auth/test_profile_update.py` — 6 tests.

**Frontend files touched:**
- Modify `frontend/index.html` — new markup section (near line 7177, after the Language section), CSS rule for `.field-hint`, JS refresh + save handlers, EN + AR i18n keys, event wiring in `paintChrome()` / `refreshAdminSettings()`.

Two independent tasks, one per side.

---

## Task 1: Backend — `PATCH /auth/me`

**Files:**
- Modify: `backend/src/auth/schemas.py` — add `ProfileUpdate` model after the existing `UserOut` block (around line 55).
- Modify: `backend/src/auth/service.py` — add `update_profile()` function.
- Modify: `backend/src/auth/router.py` — add `patch_me` endpoint below the existing `me` endpoint (line 79).
- Test: `backend/tests/auth/test_profile_update.py` (new file).

**Interfaces:**
- Consumes: existing `deps.get_current_user`, `models.User`, `schemas.UserOut`, `get_db` from `..database`.
- Produces:
  - `schemas.ProfileUpdate(BaseModel)` — Pydantic v2 partial-update payload.
  - `service.update_profile(db, user, *, full_name, phone_number, national_id, phone_provided, id_provided) -> User` — persists partial patch; the two `*_provided` booleans distinguish "field absent" from "field present with null" (Pydantic collapses both to `None` in the parsed model, so the router derives them from `payload.model_fields_set`).
  - `PATCH /auth/me` — accepts `ProfileUpdate`, returns `UserOut` for the authenticated user.

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/auth/test_profile_update.py`:

```python
"""PATCH /auth/me — self-service profile edits.

Six scenarios: full replace, partial patch (name only), clearing nullable
fields with explicit null, no-op empty payload, min-length rejection at
the schema layer, and auth-required guard.
"""
from src.auth import models, utils


def _seed_customer(db, email="alice@example.com", password="Pass#2026"):
    user = models.User(
        email=email,
        password_hash=utils.hash_password(password),
        full_name="Alice Old",
        phone_number="+249000000000",
        national_id="OLD-ID",
        role="customer",
        status="active",
        email_verified=True,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def _login_headers(client, email, password):
    r = client.post("/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def test_patch_me_updates_all_fields(client, db):
    _seed_customer(db)
    headers = _login_headers(client, "alice@example.com", "Pass#2026")

    r = client.patch(
        "/auth/me",
        headers=headers,
        json={
            "full_name": "Alice New",
            "phone_number": "+249111111111",
            "national_id": "NEW-ID",
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["full_name"] == "Alice New"
    assert body["phone_number"] == "+249111111111"
    assert body["national_id"] == "NEW-ID"

    # Persisted to DB
    db.expire_all()
    row = db.query(models.User).filter_by(email="alice@example.com").one()
    assert row.full_name == "Alice New"
    assert row.phone_number == "+249111111111"
    assert row.national_id == "NEW-ID"


def test_patch_me_partial_updates_only_name(client, db):
    _seed_customer(db)
    headers = _login_headers(client, "alice@example.com", "Pass#2026")

    r = client.patch("/auth/me", headers=headers, json={"full_name": "Alice Renamed"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["full_name"] == "Alice Renamed"
    assert body["phone_number"] == "+249000000000"
    assert body["national_id"] == "OLD-ID"


def test_patch_me_clears_phone_and_id_with_null(client, db):
    _seed_customer(db)
    headers = _login_headers(client, "alice@example.com", "Pass#2026")

    r = client.patch(
        "/auth/me",
        headers=headers,
        json={"phone_number": None, "national_id": None},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["phone_number"] is None
    assert body["national_id"] is None

    db.expire_all()
    row = db.query(models.User).filter_by(email="alice@example.com").one()
    assert row.phone_number is None
    assert row.national_id is None
    # Name unchanged
    assert row.full_name == "Alice Old"


def test_patch_me_empty_payload_is_noop(client, db):
    _seed_customer(db)
    headers = _login_headers(client, "alice@example.com", "Pass#2026")

    r = client.patch("/auth/me", headers=headers, json={})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["full_name"] == "Alice Old"
    assert body["phone_number"] == "+249000000000"
    assert body["national_id"] == "OLD-ID"


def test_patch_me_rejects_short_name(client, db):
    _seed_customer(db)
    headers = _login_headers(client, "alice@example.com", "Pass#2026")

    r = client.patch("/auth/me", headers=headers, json={"full_name": "A"})
    assert r.status_code == 422

    # Nothing persisted
    db.expire_all()
    row = db.query(models.User).filter_by(email="alice@example.com").one()
    assert row.full_name == "Alice Old"


def test_patch_me_requires_auth(client, db):
    _seed_customer(db)
    r = client.patch("/auth/me", json={"full_name": "Whoever"})
    assert r.status_code == 401
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd backend && python -m pytest tests/auth/test_profile_update.py -v
```

Expected: All 6 tests FAIL with `404 Not Found` on the PATCH call (endpoint doesn't exist yet), or `AttributeError: module 'src.auth.schemas' has no attribute 'ProfileUpdate'` depending on collection order.

- [ ] **Step 3: Add the `ProfileUpdate` schema**

In `backend/src/auth/schemas.py`, insert this class after the `UserOut` block (after line 55, before `class TokenResponse`):

```python
# ---------------------------------------------------------------------------
# Profile self-edit (Settings → Personal Information)
# ---------------------------------------------------------------------------

class ProfileUpdate(BaseModel):
    """Partial update payload for PATCH /auth/me.

    Every field is optional in the wire format:
      - absent    → don't touch the column
      - null      → set the column to NULL (phone_number, national_id only)
      - string    → set the column to that value

    `full_name` cannot be cleared: sending null is treated as "absent" by
    the service layer since the ORM column is NOT NULL. min_length matches
    RegisterRequest so any name that was valid at signup stays valid on edit.
    """
    full_name: Optional[str] = Field(default=None, min_length=2, max_length=120)
    phone_number: Optional[str] = Field(default=None, max_length=20)
    national_id: Optional[str] = Field(default=None, max_length=40)
```

- [ ] **Step 4: Add the `update_profile` service function**

In `backend/src/auth/service.py`, append at the end of the file (or place next to the other user-mutation helpers if there is a natural cluster):

```python
def update_profile(
    db: Session,
    user: User,
    *,
    full_name: str | None,
    phone_number: str | None,
    national_id: str | None,
    phone_provided: bool,
    id_provided: bool,
) -> User:
    """Partial update of the three self-editable profile columns.

    `phone_provided` / `id_provided` are the router's proof that the caller
    actually included the field in the JSON body (via
    `payload.model_fields_set`). Without them we can't distinguish "leave
    alone" from "set to null" — Pydantic v2 gives us the same `None` for both.
    """
    if full_name is not None:
        user.full_name = full_name.strip()
    if phone_provided:
        user.phone_number = phone_number  # may be None to clear
    if id_provided:
        user.national_id = national_id    # may be None to clear
    db.commit()
    db.refresh(user)
    return user
```

If `User` and `Session` are not yet imported at that scope, verify the existing imports at the top of `service.py` cover them — they should, since `register_user()` already uses both. Add nothing extra unless the import list is missing them.

- [ ] **Step 5: Add the `PATCH /auth/me` route**

In `backend/src/auth/router.py`, insert this handler directly below the existing `me` handler (after line 79, before the `password_reset_request` block):

```python
@router.patch("/me", response_model=schemas.UserOut)
def patch_me(
    payload: schemas.ProfileUpdate,
    db: Session = Depends(get_db),
    current_user=Depends(deps.get_current_user),
):
    """Self-service edit of the three profile columns (full_name,
    phone_number, national_id). Any field can be omitted; phone_number
    and national_id accept explicit null to clear the column."""
    return service.update_profile(
        db,
        current_user,
        full_name=payload.full_name,
        phone_number=payload.phone_number,
        national_id=payload.national_id,
        phone_provided="phone_number" in payload.model_fields_set,
        id_provided="national_id" in payload.model_fields_set,
    )
```

- [ ] **Step 6: Run tests to verify they pass**

```bash
cd backend && python -m pytest tests/auth/test_profile_update.py -v
```

Expected: All 6 tests PASS.

- [ ] **Step 7: Run the full backend suite to check for regressions**

```bash
cd backend && python -m pytest -q
```

Expected: All previously-passing tests still pass (168 → 174).

- [ ] **Step 8: Commit**

```bash
git add backend/src/auth/schemas.py backend/src/auth/service.py backend/src/auth/router.py backend/tests/auth/test_profile_update.py
git commit -m "$(cat <<'EOF'
feat(auth): PATCH /auth/me — self-service profile edit

New endpoint lets any signed-in user edit their full_name, phone_number,
and national_id. Partial-update semantics: absent field = leave alone;
explicit null on phone/id clears the column; full_name is required so
null there is a no-op. Six new tests cover happy path, partial patch,
clearing to null, no-op empty payload, min-length rejection, and the
auth guard.

Foundation for the upcoming Settings → Personal Information UI.
EOF
)"
```

---

## Task 2: Frontend — Personal Information section in Settings

**Files:**
- Modify: `frontend/index.html` — five discrete edits (markup section, CSS rule, i18n EN block, i18n AR block, JS handlers + wiring).

**Interfaces:**
- Consumes: `PATCH /auth/me` returning `UserOut` (from Task 1), existing `api()` helper, `STATE.auth.user` shape, `t()` i18n helper, `toast()`, `paintChrome()`, `$()` DOM helper — all already present in `frontend/index.html`.
- Produces: new DOM ids `#settings-personal-info-section`, `#pi-name`, `#pi-phone`, `#pi-id`, `#personal-info-save`; new i18n keys `settings.section.personal_info`, `settings.personal_info.lead`, `settings.personal_info.full_name`, `settings.personal_info.name_hint`, `settings.personal_info.phone`, `settings.personal_info.national_id`, `settings.personal_info.save`, `toast.profile_saved`, `toast.profile_name_too_short`, `toast.profile_save_failed`; new JS functions `refreshPersonalInfo()` and `savePersonalInfo()`.

- [ ] **Step 1: Insert the markup section**

In `frontend/index.html`, find the Language section closing tag (search for the exact line `</section>` that follows `<div class="role-pick" id="settings-lang-pick">` — currently ends around line 7177). Insert this new section directly after it, BEFORE the Commissions section (which starts with `<section class="settings-section">` containing `settings.section.commissions`):

```html
        <section class="settings-section" id="settings-personal-info-section">
          <h3 data-i18n="settings.section.personal_info">Personal Information</h3>
          <div class="settings-body">
            <div class="panel">
              <p class="lead" data-i18n="settings.personal_info.lead">Update the details we use to prefill your bookings.</p>
              <div class="field-block full">
                <label for="pi-name" data-i18n="settings.personal_info.full_name">Full name</label>
                <input type="text" id="pi-name" autocomplete="name">
                <p class="field-hint" data-i18n="settings.personal_info.name_hint">Best to include a first and family name — passenger names on tickets must have at least two words.</p>
              </div>
              <div class="field-block full">
                <label for="pi-phone" data-i18n="settings.personal_info.phone">Phone (optional)</label>
                <input type="tel" id="pi-phone" autocomplete="tel">
              </div>
              <div class="field-block full">
                <label for="pi-id" data-i18n="settings.personal_info.national_id">National ID (optional)</label>
                <input type="text" id="pi-id" autocomplete="off">
              </div>
              <button type="button" class="cta" id="personal-info-save" data-i18n="settings.personal_info.save">Save changes</button>
            </div>
          </div>
        </section>
```

- [ ] **Step 2: Add the CSS rule for the field hint**

Find the existing pillow settings CSS scope (search for `body[data-screen="admin-settings"].pillow .settings-section .account-note` around line 5913 — the last account-related rule). Directly after that rule's closing brace, insert:

```css
  /* Personal Info — helper text under the full-name input. */
  body[data-screen="admin-settings"].pillow #settings-personal-info-section .field-hint {
    margin: 6px 0 0;
    font-size: 12px;
    color: var(--ink-mute);
    line-height: 1.4;
  }

  /* Numeric inputs force LTR in RTL mode (matches the pattern used for
     phone/id in the register form). */
  html[lang="ar"] #pi-phone,
  html[lang="ar"] #pi-id {
    direction: ltr;
    text-align: right;
  }
```

- [ ] **Step 3: Add the English i18n keys**

Locate the English `I18N.en` block (contains `'settings.section.account': 'Account'` around line 7852). Add these keys nearby — group them under a `settings.personal_info.*` comment if that style is used in the file, otherwise just insert as sibling entries:

```javascript
    'settings.section.personal_info': 'Personal Information',
    'settings.personal_info.lead': 'Update the details we use to prefill your bookings.',
    'settings.personal_info.full_name': 'Full name',
    'settings.personal_info.name_hint': 'Best to include a first and family name — passenger names on tickets must have at least two words.',
    'settings.personal_info.phone': 'Phone (optional)',
    'settings.personal_info.national_id': 'National ID (optional)',
    'settings.personal_info.save': 'Save changes',
    'toast.profile_saved': 'Profile updated.',
    'toast.profile_name_too_short': 'Full name must be at least 2 characters.',
    'toast.profile_save_failed': "Couldn't save. Try again.",
```

- [ ] **Step 4: Add the Arabic i18n keys**

Locate the Arabic `I18N.ar` block (search for `'settings.section.account': 'الحساب'` — the AR counterpart of the block edited in Step 3). Add these keys as siblings:

```javascript
    'settings.section.personal_info': 'المعلومات الشخصية',
    'settings.personal_info.lead': 'حدّث البيانات التي نستخدمها لتعبئة حجوزاتك تلقائياً.',
    'settings.personal_info.full_name': 'الاسم الكامل',
    'settings.personal_info.name_hint': 'يُفضّل إدخال اسم أول ولقب — يجب أن يتكوّن اسم الراكب على التذكرة من كلمتين على الأقل.',
    'settings.personal_info.phone': 'رقم الهاتف (اختياري)',
    'settings.personal_info.national_id': 'الرقم الوطني (اختياري)',
    'settings.personal_info.save': 'حفظ التغييرات',
    'toast.profile_saved': 'تم تحديث الملف الشخصي.',
    'toast.profile_name_too_short': 'يجب أن يتكون الاسم الكامل من حرفين على الأقل.',
    'toast.profile_save_failed': 'تعذّر الحفظ. حاول مرة أخرى.',
```

- [ ] **Step 5: Add the JS refresh + save handlers**

Find `refreshAdminSettings` (search for `function refreshAdminSettings`). Right AFTER that function's closing brace, insert both new functions:

```javascript
  function refreshPersonalInfo() {
    const u = STATE.auth?.user;
    if (!u) return;
    const n = $('#pi-name');
    const p = $('#pi-phone');
    const i = $('#pi-id');
    if (n) n.value = u.full_name || '';
    if (p) p.value = u.phone_number || '';
    if (i) i.value = u.national_id || '';
  }

  async function savePersonalInfo() {
    const u = STATE.auth?.user;
    if (!u) return;
    const nameEl = $('#pi-name');
    const phoneEl = $('#pi-phone');
    const idEl = $('#pi-id');
    if (!nameEl || !phoneEl || !idEl) return;

    const nextName  = (nameEl.value  || '').trim();
    const nextPhone = (phoneEl.value || '').trim();
    const nextId    = (idEl.value    || '').trim();

    if (nextName.length < 2) {
      toast(t('toast.profile_name_too_short'), true);
      return;
    }

    const body = {};
    if (nextName !== (u.full_name || '')) body.full_name = nextName;
    // Phone / ID: send explicit null when the user cleared a previously-set value;
    // send the string when it changed to a non-empty value; omit when unchanged.
    const curPhone = u.phone_number || '';
    if (nextPhone !== curPhone) body.phone_number = nextPhone === '' ? null : nextPhone;
    const curId = u.national_id || '';
    if (nextId !== curId) body.national_id = nextId === '' ? null : nextId;

    // Nothing to send → no-op.
    if (Object.keys(body).length === 0) {
      toast(t('toast.profile_saved'));
      return;
    }

    const saveBtn = $('#personal-info-save');
    if (saveBtn) saveBtn.disabled = true;
    try {
      const updated = await api('/auth/me', { method: 'PATCH', body: JSON.stringify(body) });
      STATE.auth.user = updated;
      if (typeof tazStore?.saveAuth === 'function') tazStore.saveAuth(STATE.auth);
      refreshPersonalInfo();
      if (typeof paintChrome === 'function') paintChrome();
      toast(t('toast.profile_saved'));
    } catch (err) {
      toast(t('toast.profile_save_failed'), true);
    } finally {
      if (saveBtn) saveBtn.disabled = false;
    }
  }
```

Note the `tazStore?.saveAuth` call is defensive — if the project's persistence helper has a different function name, verify against the actual `tazStore` surface (search for `tazStore.` earlier in the file) and adjust. If no such helper exists, drop that line — the native persistence usually re-runs through `paintChrome()`'s side effects.

- [ ] **Step 6: Verify tazStore helper name**

Before shipping Step 5, quickly grep to confirm the exact tazStore write API:

```bash
grep -n "tazStore\." frontend/index.html | head -20
```

If the pattern is `tazStore.saveAuth(...)` — keep the line as written. If it's something different (e.g. `tazStore.set('auth', ...)` or `tazStore.persist()`), replace that one line in `savePersonalInfo` accordingly. If tazStore has no explicit save method (some Preferences wrappers auto-save on state mutation), delete the line.

- [ ] **Step 7: Wire up the Save button + entry-refresh**

Find the existing settings-btn click wiring (search for `$('#settings-btn')?.addEventListener` around line 11782). Directly under that block, add:

```javascript
  $('#personal-info-save')?.addEventListener('click', savePersonalInfo);
```

Then find `refreshAdminSettings()` call sites — the gear button already triggers it on entry. Right where `refreshAdminSettings()` is invoked when navigating INTO the settings screen (there are usually 1-2 call sites; the gear-button click handler is one), add a paired call:

```javascript
  refreshPersonalInfo();
```

If `refreshAdminSettings` is called from multiple places, add `refreshPersonalInfo()` next to each so entering the screen from any path prefills the fields.

- [ ] **Step 8: Manual smoke test — English + editing + persistence**

Serve the frontend against a local backend (or against the deployed Neon backend), sign in as any of the three seed roles (admin, provider, or customer), then:

1. Click the gear icon → Settings opens.
2. Scroll to the new "Personal Information" section. Confirm the three inputs are prefilled with the current user's name / phone / national ID.
3. Change the name to something new. Click "Save changes". Toast reads "Profile updated." No console errors.
4. Reload the page. Sign in again. Reopen Settings. New name is still there.
5. Clear the Phone input completely. Click Save. Reload. Phone field is now empty (persisted as NULL server-side — verify via a quick `GET /auth/me` call in the network inspector or by checking Neon).
6. Enter a single-character name ("A"). Click Save. Toast reads "Full name must be at least 2 characters." No PATCH request fires (network tab confirms).

- [ ] **Step 9: Manual smoke test — Arabic + RTL**

Still in the browser, toggle the language to Arabic. Confirm:

1. Section title reads "المعلومات الشخصية".
2. All three labels + placeholders + hint + save button are in Arabic.
3. Direction is RTL (labels align right, section arrow indicators mirror).
4. Phone and National ID inputs stay LTR internally so the digits read left-to-right even though the label is on the right.
5. Save still works; toast shows the Arabic string "تم تحديث الملف الشخصي.".

- [ ] **Step 10: Manual smoke test — autofill is unchanged**

Sign in as the customer (`passenger@tazkirati.app` / `Passenger#2026` per seed defaults). In Personal Information, set the name to something distinctive like "Autofill Check". Save.

Search for any trip, pick a single seat, advance to the passenger row. The passenger name should be prefilled with "Autofill Check" (proves autofill still reads from the profile). Phone and national ID rows should still be empty (proves autofill scope did NOT expand).

- [ ] **Step 11: Commit**

```bash
git add frontend/index.html
git commit -m "$(cat <<'EOF'
feat(v2): Personal Information section in Settings

New pillow-styled section between Language and Commissions lets any
signed-in role edit their name, phone, and national ID via
PATCH /auth/me. Advisory helper under the name input mirrors the GEN-1
≥2-words rule as guidance (not a hard block — matches register).

Booking-screen autofill code path is unchanged: single-seat customer
flow still autofills the first passenger's name from the profile,
phone and ID are still typed in per booking (deliberate — expanding
autofill risks leaking the buyer's ID into other passengers' rows).

i18n: 10 new keys, EN + AR. Numeric inputs force LTR under RTL.
EOF
)"
```

---

## Verification (post-both-tasks)

- [ ] **Backend suite green**

```bash
cd backend && python -m pytest -q
```

Expected: 174 passed (was 168 before Task 1).

- [ ] **Frontend JS syntax check**

```bash
cd frontend && node --check <(awk '/<script>/{p=1;next}/<\/script>/{p=0}p' index.html)
```

Expected: no output (success). Catches any accidental syntax breakage in the inline `<script>` block — this project has been bitten by that before (2026-07-13, `12e4f09`).

- [ ] **Deploy**

Push to `feat/mobile-scaffold` (Render auto-deploys from this branch). Wait for Render "Deploy live", then smoke-test on the deployed URL:

1. Sign in as any role.
2. Open Settings → edit name → Save → reload → confirm persisted.
3. Confirm no regression in existing Settings sections (Language toggle still works, Commissions section still renders for admin, Account section still shows email).

- [ ] **Update CLAUDE.md**

Add a "Recent fixes" entry at the top of that section in `CLAUDE.md` summarizing what shipped: date, endpoint, UI location, i18n keys added, autofill deliberately-unchanged. Match the existing entry style (one paragraph, prefixed with the date in bold).

```bash
git add CLAUDE.md
git commit -m "docs: log Personal Information ship in CLAUDE.md"
```

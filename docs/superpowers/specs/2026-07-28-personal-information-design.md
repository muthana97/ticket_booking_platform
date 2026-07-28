# Personal Information (Settings) — Design Spec

**Date:** 2026-07-28
**Status:** Approved (brainstorming) — pending implementation plan
**Spec author:** Claude (with user)
**Branch:** `feat/mobile-scaffold` (v2/pillow surface; backend changes branch-agnostic)
**Related:** Settings hub landed 2026-06-21 (commissions) and evolved through 2026-07-18 (pillow); this spec adds the first identity-mutation surface for end users.

## 1. Goal

Give every signed-in role (customer, provider, admin) a place in the Settings hub to edit the profile fields they originally supplied at registration: **full name**, **phone number**, **national ID**. The primary payoff is downstream: name/phone/ID on the user record is what the booking screen autofills into passenger rows today (name only, single-seat customer flow). Letting users keep those values current means the autofill stays useful over time — a user who typoed their name at signup, or switched phones, can fix it once instead of correcting every booking.

The three fields already exist on the `User` model (`full_name`, `phone_number`, `national_id`) — this spec adds a self-service editor, not a schema change.

## 2. Out of scope

- **Expanding autofill behavior.** The booking screen's autofill logic (`renderPax()` in `frontend/index.html`, line ~9853) stays exactly as it is today: only the single-seat customer flow autofills the first passenger's name; phone + national ID are still typed in per booking. Changing autofill scope was considered and deliberately rejected during brainstorming — it risks leaking the buyer's ID into other passengers' rows and leaking the provider's own info into walk-in bookings.
- **Retroactive edits to existing bookings.** Passenger records (`booking/models.py :: Passenger`) are snapshotted at seat-lock time. A profile edit does not rewrite the name/phone/ID on any existing booking (`pending` / `committed_pending` / `confirmed` / `expired`). Tickets are receipts of what was true when they were issued — same principle as `Booking.commission_amount` being frozen at confirm time.
- **Email editing.** The email address is the login identifier and is intentionally read-only in this spec. Changing it would need a re-verification flow (send OTP to the new address, confirm) that is worth its own spec if we ever want it. The Account section already surfaces the current email as `Signed in as ...`.
- **Password reset entry point.** The Account section still shows the "Password reset and more coming soon" note. Password reset ships via the sign-in flow (2026-07-22) but hasn't been surfaced in Settings yet. Not part of this spec — will be a small follow-up.
- **Audit-log emission.** The `audit_events` table (2026-07-23) is scoped to provider-facing admin actions. A user editing their own profile doesn't fit that lens. If we ever add a user-activity view, we can hook `record_event()` in at that point.
- **Notifications.** No bell ping fires when a user edits their own profile — self-initiated, not worth surfacing.

## 3. Architecture overview

```
                    Settings hub  (#screen-admin-settings)
                    ┌─────────────────────────────────────┐
                    │  §  Language           (existing)   │
                    │  §  Personal Information  ← NEW     │
                    │       ├─ Full name         [input]  │
                    │       ├─ Phone (optional)  [input]  │
                    │       ├─ National ID       [input]  │
                    │       ├─ advisory helper text       │
                    │       └─ [ Save changes ] amber CTA │
                    │  §  Commissions        (admin only) │
                    │  §  Promos             (admin only) │
                    │  §  Account            (existing)   │
                    └─────────────────────────────────────┘
                                    │
                                    │  amber CTA click
                                    ▼
                    PATCH /auth/me   { full_name?, phone_number?, national_id? }
                                    │
                                    ▼
                    auth/service.py :: update_profile(db, user, patch)
                                    │
                                    ▼
                    UserResponse  →  refresh STATE.auth.user client-side
```

Everything runs through the existing auth guard — `Depends(current_user)` — so no route-level access work is needed.

## 4. Backend

### 4.1 Schema (`backend/src/auth/schemas.py`)

Add one Pydantic model. Keep the field constraints identical to what `RegisterRequest` already accepts, so a value that was valid at signup is valid on edit:

```python
class ProfileUpdate(BaseModel):
    full_name: Optional[str] = Field(default=None, min_length=2, max_length=120)
    phone_number: Optional[str] = Field(default=None, max_length=20)
    national_id: Optional[str] = Field(default=None, max_length=40)
```

All three fields are optional in the payload — this is a partial-update model. A missing field means "don't touch this column." An explicit `null` on `phone_number` or `national_id` means "clear this column." An explicit `null` on `full_name` is not accepted (falls through to "don't touch," see 4.2).

### 4.2 Service (`backend/src/auth/service.py`)

Add one function next to the existing `register_user` / `verify_email_otp` helpers:

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

The `phone_provided` / `id_provided` booleans exist because Pydantic doesn't natively distinguish "field absent" from "field present with null" once it's been dumped to a dict. The router captures this with `payload.model_fields_set` before calling the service.

### 4.3 Router (`backend/src/auth/router.py`)

Add one endpoint, mirroring how `GET /auth/me` returns the ORM `User` directly (Pydantic serializes it via `schemas.UserOut`):

```python
@router.patch("/me", response_model=schemas.UserOut)
def patch_me(
    payload: schemas.ProfileUpdate,
    db: Session = Depends(get_db),
    current_user=Depends(deps.get_current_user),
):
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

No new dependencies, no new middleware. `deps.get_current_user` is the same guard already used by `GET /auth/me` and the rest of the authenticated surface.

### 4.4 Tests (`backend/tests/auth/`)

New file `test_profile_update.py`. Six cases:

1. `test_patch_me_updates_all_fields` — all three fields sent, all persist, `UserResponse` returns the new values.
2. `test_patch_me_partial_updates_only_name` — send only `full_name`, verify `phone_number` and `national_id` unchanged.
3. `test_patch_me_clears_phone_and_id_with_null` — send `{"phone_number": null, "national_id": null}` explicitly, verify columns become `NULL`.
4. `test_patch_me_absent_field_untouched` — send `{}`, verify no columns change.
5. `test_patch_me_rejects_short_name` — send `{"full_name": "A"}`, expect 422 (Pydantic `min_length=2`).
6. `test_patch_me_requires_auth` — no `Authorization` header → 401.

Aligns with the existing `backend/tests/auth/test_*.py` file layout (single-topic module, one class per endpoint or free functions).

## 5. Frontend

### 5.1 Markup

Insert a new `<section class="settings-section">` inside `#screen-admin-settings` (line 7156), between the Language section and the Commissions section. Structure mirrors the surrounding pillow-styled sections — `.settings-section > h3 + .settings-body > .panel > .field-block × 3 + advisory + .cta`.

Sketch:
```html
<section class="settings-section" id="settings-personal-info-section">
  <h3 data-i18n="settings.section.personal_info">Personal Information</h3>
  <div class="settings-body">
    <div class="panel">
      <p class="lead" data-i18n="settings.personal_info.lead">
        Update the details we use to prefill your bookings.
      </p>
      <div class="field-block full">
        <label for="pi-name" data-i18n="settings.personal_info.full_name">Full name</label>
        <input type="text" id="pi-name" autocomplete="name">
        <p class="field-hint" data-i18n="settings.personal_info.name_hint">
          Best to include a first and family name — passenger names on tickets must have at least two words.
        </p>
      </div>
      <div class="field-block full">
        <label for="pi-phone" data-i18n="settings.personal_info.phone">Phone (optional)</label>
        <input type="tel" id="pi-phone" autocomplete="tel">
      </div>
      <div class="field-block full">
        <label for="pi-id" data-i18n="settings.personal_info.national_id">National ID (optional)</label>
        <input type="text" id="pi-id" autocomplete="off">
      </div>
      <button type="button" class="cta" id="personal-info-save"
              data-i18n="settings.personal_info.save">Save changes</button>
    </div>
  </div>
</section>
```

The advisory text under the name input reuses the same `.field-hint` class the Reports and Commissions modals use (small muted paragraph).

### 5.2 JS wiring

Add a small refresh-and-save pair, placed alongside `refreshAdminSettings()` in the settings block:

- `refreshPersonalInfo()` — reads from `STATE.auth.user`, populates `#pi-name` / `#pi-phone` / `#pi-id`. Called on `paintChrome()` when entering `admin-settings`, and after a successful save.
- `savePersonalInfo()` — reads the three inputs, trims, builds a diff against `STATE.auth.user`, PATCHes `/auth/me`, updates `STATE.auth.user` with the response, toasts success. On 4xx surfaces the server error message (translated when possible via `tStatus()`-style lookup, English fallback otherwise).

Client-side guard: `full_name.trim().length >= 2` — matches Pydantic. No other client-side validation (word-count is advisory only).

The advisory helper does NOT hard-block a single-word name at save time — the ≥ 2 words rule is a GEN-1 constraint enforced at booking-lock time, not at profile time. That distinction is deliberate: register accepts single-word names today, existing users have them, and we don't want to prevent them from saving other edits.

### 5.3 State refresh

After a successful save the response body is a `UserResponse`. Overwrite `STATE.auth.user` with it and re-call `paintChrome()` so any downstream UI that renders the full name (welcome toast wording, admin-settings email row's neighbour, notifications templates, etc) picks up the new value on next render.

Do NOT persist the updated user via `tazStore` — that store keys off `STATE.auth` as a whole; the standard code path already re-saves it when `paintChrome()` runs on native.

### 5.4 i18n

Add ~10 keys under `settings.personal_info.*` and 2 toast keys, in both `I18N.en` and `I18N.ar`:

| Key | English | Arabic (approx) |
|---|---|---|
| `settings.section.personal_info` | Personal Information | المعلومات الشخصية |
| `settings.personal_info.lead` | Update the details we use to prefill your bookings. | حدّث البيانات التي نستخدمها لتعبئة حجوزاتك تلقائياً. |
| `settings.personal_info.full_name` | Full name | الاسم الكامل |
| `settings.personal_info.name_hint` | Best to include a first and family name — passenger names on tickets must have at least two words. | يُفضّل إدخال اسم أول ولقب — يجب أن يتكوّن اسم الراكب على التذكرة من كلمتين على الأقل. |
| `settings.personal_info.phone` | Phone (optional) | رقم الهاتف (اختياري) |
| `settings.personal_info.national_id` | National ID (optional) | الرقم الوطني (اختياري) |
| `settings.personal_info.save` | Save changes | حفظ التغييرات |
| `toast.profile_saved` | Profile updated. | تم تحديث الملف الشخصي. |
| `toast.profile_name_too_short` | Full name must be at least 2 characters. | يجب أن يتكون الاسم الكامل من حرفين على الأقل. |
| `toast.profile_save_failed` | Couldn't save. Try again. | تعذّر الحفظ. حاول مرة أخرى. |

Numeric inputs (phone, national ID) get `dir="ltr"` under RTL, matching the existing pattern for numeric inputs in the register form.

### 5.5 CSS

Minimal — the existing pillow section primitives (`.settings-section`, `.panel`, `.field-block`, `.cta`) already give the right look. Only new rule: `.field-hint { margin: 6px 0 0; font-size: 12px; color: var(--ink-mute); }` scoped under `#settings-personal-info-section` so it doesn't leak. If the token already exists elsewhere (audit during implementation), reuse.

## 6. Access control

Every signed-in role sees the section. The route uses the same `current_user` guard as the rest of `/auth/*` — a user can only edit their own record, and unauthenticated calls 401. No admin-editing-another-user semantics in this spec (admin editing a provider's identity is a different feature; today admin can only toggle capabilities on a provider).

## 7. Rollout notes

- No database migration — the three columns are pre-existing.
- No env var changes.
- No mobile-specific work — Capacitor wrap loads the same `frontend/index.html`; the new section renders on iOS + Android automatically after `npx cap sync`.
- Backwards compatible: users who never touch Settings keep the values they registered with. The register form is unchanged.

## 8. Success criteria

1. Each role (customer, provider, admin) can open Settings, see their current name/phone/ID prefilled, edit them, hit Save, and see the toast + persisted change on reload.
2. Clearing phone or national ID (blanking the input and saving) sets the column to `NULL` server-side.
3. The advisory helper is visible under the name input in both English and Arabic; RTL flip works.
4. Existing tickets and bookings are untouched by a profile edit — the passenger name on a booking made before the edit still reads the pre-edit value.
5. Single-seat customer booking autofill still uses the profile's `full_name` (this is a regression check — the autofill code path is not modified but must still work).
6. `PATCH /auth/me` unit tests pass (six cases described in §4.4).

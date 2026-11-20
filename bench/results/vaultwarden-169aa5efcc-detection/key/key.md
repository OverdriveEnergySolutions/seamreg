# Answer key: vaultwarden at 169aa5efcc

- **Repo:** https://github.com/dani-garcia/vaultwarden
- **Snapshot:** `169aa5efcc8d94684ff3bc813a00e6bcc0cc537a`, 2026-07-08
- **Window end:** `baff1cabae39f55fd5111d0724d1389d08d00a63`, 2026-11-19
- **Commits in the window:** 114. All are squash merges with one parent, so no merge commit hides other commits.
- **Fixes read:** I read all 114 commit messages. I read the diffs of 47 commits that fix something, plus every `.env.template` change in the window (22 commits).
- **Seams:** 20 (14 with drift, 6 that held at the snapshot). One seam with drift is held back from this
  public copy until its fix ships in a vaultwarden release, so 19 appear below.
- **Drift rows:** 17, of which 16 appear below. Row 16 is held back.

For every drift row I read both sides at the snapshot with `git show 169aa5efcc:<path>`. For every fix, `git merge-base --is-ancestor <fix> 169aa5efcc` fails, so no fix is already in the snapshot.

Two seams in this copy have a check script in `key/`. Each script takes a commit and reads the clone in `full/`:

| Script | Snapshot | Fix parent | Fix |
|---|---|---|---|
| `check_feature_flags.sh` | 1 violation | 2 at `b723afe0^` (one born in the window) | 0 at `b723afe0` |
| `check_schedules.sh` | 2 violations | 2 at `415df400^` | 0 at `415df400` |

Both scripts give 0 at the window end, `baff1cab`.

---

## Seams with drift

### client-feature-flags

- **What must agree:** the client feature flags that the server accepts, and the documented list of those flags. Each flag needs a one-line description.
- **Copies:**
  - `src/config.rs`, `SUPPORTED_FEATURE_FLAGS` (snapshot line 1393). This list is enforced by `validate_config`.
  - `.env.template`, the `## - "flag": description` list above `# EXPERIMENTAL_CLIENT_FEATURE_FLAGS=` (snapshot lines 376-391).
- **Risk:** low. The result is missing or empty operator documentation.
- **Tie today:** none in the repo. `key/check_feature_flags.sh` counts the violations.
- **Note:** this seam drifted again inside the window. `cb89088b` added `windows-native-credential-sync` to the code only, and `863395f5` did the same for `fill-assist-targeting-rules`. Those drifts were born after the snapshot, so they are not rows (see "Not counted").

### collection-group-manage-json

- **What must agree:** the `manage` flag of a collection-group link, in every JSON view that reports it. The web vault saves back what it reads.
- **Copies:**
  - `src/db/models/group.rs`, `Group::to_json_details`, which serves `groups/<id>/details` (snapshot line 98). It returns the stored `entry.manage`.
  - `src/db/models/group.rs`, `CollectionGroup::to_json_details_for_group`, which serves `collections/details` (snapshot line 149).
  - `src/db/models/organization.rs` returns the stored value for collection-user links (snapshot lines 673 and 690).
- **Risk:** high. "Can edit items" is reported as "Can manage". Saving the access dialog then stores `manage=true`, which silently widens permissions.
- **Tie today:** none.

### cron-schedule-validation

- **What must agree:** every cron-schedule setting must be parsed in `validate_config`, because `schedule_jobs` parses each one with `.parse().unwrap()`.
- **Copies:**
  - `src/config.rs`, the schedule keys in `make_config!` (snapshot lines 545-569).
  - `src/config.rs`, `validate_config` parse checks (snapshot lines 1213-1243).
  - `src/main.rs`, `schedule_jobs` (snapshot lines 680-746).
- **Risk:** medium. A bad value passes startup, then panics the job thread, and all scheduled jobs stop.
- **Tie today:** none. `key/check_schedules.sh` counts the violations.

### attachment-v2-reservation-checks

- **What must agree:** the checks on a declared upload size before the server stores a record: the per-file cap (525 MB) and the user or organization quota.
- **Copies:**
  - `src/api/core/ciphers.rs`, `save_attachment`. This is the v1 upload and the v2 data upload. It has the quota arithmetic (snapshot lines 1212-1258).
  - `src/api/core/ciphers.rs`, `post_attachment_v2`, which stores the record from the client's `fileSize` (snapshot lines 1126-1150).
  - `src/api/core/sends.rs`, `post_send_file` and `post_send_file_v2`, with `SIZE_525_MB` and the send quota (snapshot lines 42, 238-270, 310-344).
  - `src/main.rs`, the Rocket `Limits` `file` and `data-form` at 525 MB (snapshot lines 579-580).
- **Risk:** high. A writer can reserve quota or declare files of any size through metadata alone, and fill the user's or the organization's quota.
- **Tie today:** none. `a96912bf` moved the quota arithmetic into one helper, `attachment_size_limit`.

### user-delete-cascade

- **What must agree:** `User::delete` must remove the rows of every table that has a foreign key to `users`.
- **Copies:**
  - `src/db/models/user.rs`, `User::delete` (snapshot lines 324-343).
  - The table definitions in `migrations/*/` and `src/db/schema.rs`. For example, `auth_requests.user_uuid REFERENCES users(uuid)` is at `migrations/sqlite/2023-09-01-170620_update_auth_request_table/up.sql:18`.
- **Risk:** medium. When a user has a pending login-with-device request, the delete fails on the foreign key.
- **Tie today:** none.

### member-status-access-filter

- **What must agree:** every query that grants a user access to organization ciphers or collections must require a **Confirmed** membership, as the sync queries do. `users_collections` and `groups_users` rows remain when a member is revoked.
- **Copies:**
  - Reference: `src/db/models/cipher.rs`, `Cipher::find_by_user` (snapshot lines 808-873). This filters `MembershipStatus::Confirmed`.
  - Reference: `src/db/models/collection.rs`, `find_by_user_uuid` (snapshot lines 225-289).
  - `src/db/models/cipher.rs`: `get_access_restrictions` (601), `get_collections` (975), `get_admin_collections` (1050), `get_collections_with_cipher_by_user` (1129).
  - `src/db/models/group.rs`, `Group::is_in_full_access_group` (269).
  - `src/db/models/collection.rs`: `find_by_uuid_and_user` (344), `is_writable_by_user` (426), `hide_passwords_for_user` (506), `is_manageable_by_user` (623), and others.
- **Risk:** high. Revoked and unconfirmed members kept access to organization ciphers.
- **Tie today:** none.

### email-2fa-login-credential-check

- **What must agree:** `POST /two-factor/send-email-login` accepts the same credentials as the token endpoint. It must apply the same checks and log failures in the same `IP: x. Username: y.` form, which fail2ban rules read.
- **Copies:**
  - `src/api/identity.rs`, `password_login`. The auth request checks are at snapshot lines 397-424, and the wrong-password log is at 377 and 426-428.
  - `src/api/core/two_factor/email.rs`, `send_email_login` (snapshot lines 64-100).
- **Risk:** high. An auth request that was not approved, was expired, or belonged to another user was accepted to trigger a 2FA email. Failures were not logged with the client IP.
- **Tie today:** none.

### user-removal-logout-notify

- **What must agree:** every path that ends a user's sessions must send the logout notification over WebSocket and the push relay.
- **Copies:**
  - These paths send the notification: `src/api/admin.rs`, `deauth_user` (snapshot line 467) and `disable_user` (492), and `src/api/core/accounts.rs`, password, KDF and key changes (637, 735, 1004, 1019, 1142).
  - These paths do not: `src/api/admin.rs`, `delete_user` (419-424), and `src/api/core/accounts.rs`, `post_delete_recover_token` (1227-1241) and `delete_account` (1250-1256).
- **Risk:** medium. Clients of a deleted user stay logged in and show stale data until their token fails.
- **Tie today:** none.

### account-recovery-requires-mail

- **What must agree:** account recovery (reset password) is unavailable when mail is disabled. Every check of the reset-password policy must follow that rule.
- **Copies:**
  - `src/api/core/organizations.rs`, `check_reset_password_applicable` (snapshot lines 3074-3077). This refuses when `!CONFIG.mail_enabled()`.
  - `src/db/models/org_policy.rs`, `org_is_reset_password_auto_enroll` (snapshot lines 318-330). This had no mail check.
- **Risk:** medium. On a server without mail, invites to an organization with auto-enroll fail, because the client must supply a reset-password key.
- **Tie today:** none.

### send-access-validity

- **What must agree:** the check that a Send can still be opened (not disabled, not expired, not past deletion), at every access path.
- **Copies:**
  - `src/auth/send.rs`, `SendTokens`, at token issue (snapshot lines 88-100).
  - `src/api/core/sends.rs`, `post_access_legacy` (snapshot lines 484-497) and `post_access_file_legacy` (563-576).
  - `src/api/core/sends.rs`, `post_access` (452-456) and `post_access_file` (530-540). These are the token-based paths, and they had no check.
- **Risk:** high. A Send that was disabled or expired after a token was issued could still be read with that token.
- **Tie today:** none. The fix moved the rule into `Send::is_accessible`.

### membership-restore-policy-check

- **What must agree:** every path that activates or restores a membership must call `OrgPolicy::check_user_allowed` after the status change. The comment at the reference copy lists the paths.
- **Copies:**
  - `src/api/core/organizations.rs`, `_restore_member` (snapshot lines 2412-2415). Its comment names `accept_invite`, `_confirm_invite`, `_activate_member`, `edit_member` and `admin::update_membership_type`.
  - `src/api/core/public.rs`, `ldap_import` restore (snapshot lines 85-90). This had no policy check.
- **Risk:** high. A Directory Connector import restored members whom the Single Organization or 2FA policy forbids.
- **Tie today:** none.

### collections-update-response

- **What must agree:** the response of the user and admin variants of "update a cipher's collections". Newer clients expect a `cipherDetails` body from both.
- **Copies:**
  - `src/api/core/ciphers.rs`, `put_collections_update` and `post_collections_update` (snapshot lines 785-861). These return the cipher JSON.
  - `src/api/core/ciphers.rs`, `put_collections_admin` and `post_collections_admin` (snapshot lines 865-941). These return `EmptyResult` and `Ok(())`.
- **Risk:** medium. The web vault shows an error and stops processing the update.
- **Tie today:** none.

### sso-token-log-gate

- **What must agree:** OIDC tokens go to the log only when `SSO_DEBUG_TOKENS` is on.
- **Copies:**
  - `src/config.rs`, `sso_debug_tokens` (snapshot line 831), documented as "Log all tokens".
  - `src/sso_client.rs`, the token logs under `if CONFIG.sso_debug_tokens()` (snapshot lines 254-259).
  - `src/sso.rs`, `exchange_code`: `debug!("Authenticated user {authenticated_user:?}")` (snapshot line 310). `OIDCAuthenticatedUser` derives `Debug` (`src/db/models/sso_auth.rs:28-30`) and holds the access and refresh tokens.
- **Risk:** high. With debug logging on, access and refresh tokens went to the log while the setting was off.
- **Tie today:** none.

---

## Seams that held at the snapshot

### rust-toolchain-version

- **What must agree:** the Rust version used by local builds and Docker builds.
- **Copies:** `rust-toolchain.toml` `channel`, `docker/DockerSettings.yaml` `rust_version`, `docker/Dockerfile.debian` (line 39) and `docker/Dockerfile.alpine` (lines 35-38). All were 1.96.1 at the snapshot.
- **Risk:** low.
- **Tie today:** `de7abaaa` (2026-09-09) now reads the version from `rust-toolchain.toml` in `docker/render_template`.

### dockerfile-render

- **What must agree:** the rendered Dockerfiles and their template and settings, for example the web-vault image digest.
- **Copies:** `docker/Dockerfile.j2` and `docker/DockerSettings.yaml` (`vault_image_digest`, line 3), against `docker/Dockerfile.debian` and `docker/Dockerfile.alpine` (line 30). These matched at the snapshot.
- **Risk:** medium.
- **Tie today:** `.github/workflows/check-templates.yml` runs `make` and then `git diff --exit-code`.

### db-migrations-per-backend

- **What must agree:** each schema change exists for SQLite, MySQL and PostgreSQL, and in `src/db/schema.rs`.
- **Copies:** `migrations/sqlite/`, `migrations/mysql/`, `migrations/postgresql/`. Since 2024-04 the three folder lists are identical at the snapshot (same md5 of the names). Older folders differ by name only.
- **Risk:** high.
- **Tie today:** CI builds and tests each backend. I did not check whether the tests run the migrations against all three backends (unverified).

### email-template-pairs

- **What must agree:** each mail template has a text version (`*.hbs`) and an HTML version (`*.html.hbs`).
- **Copies:** `src/static/templates/email/`. At the snapshot every template has both versions, except the shared partials `email_header`, `email_footer` and `email_footer_text`.
- **Risk:** low.
- **Tie today:** none found.

### email-verified-rule

- **What must agree:** the rule "the email counts as verified when mail is disabled or `verified_at` is set".
- **Copies:** `src/auth.rs`, `LoginJwtClaims` `email_verified`, and `src/db/models/user.rs`, `to_json` `emailVerified`. These were identical at the snapshot.
- **Risk:** medium.
- **Tie today:** `1c89e177` (2026-10-03) moved the rule into `User::verified()`.

### config-doc-env-template

- **What must agree:** the description and default of each setting in `make_config!`, and in `.env.template`.
- **Copies:** `src/config.rs`, the `///` doc strings and defaults, and `.env.template`, the comments and the commented defaults.
- **Risk:** low.
- **Tie today:** none. In the window, `29659900` and `b71cb7a8` changed both sides in the same commit, which shows the copies were kept in step.

---

## Drift table

| # | Seam id | What differed at the snapshot | Fix | Date |
|---|---|---|---|---|
| 1 | client-feature-flags | `src/config.rs:1415` accepts `"pm-30529-webauthn-related-origins"`, but `.env.template:387` lists it with an empty description. | `b723afe0` | 2026-10-30 |
| 2 | collection-group-manage-json | `src/db/models/group.rs:98` returns the stored `manage`, but `src/db/models/group.rs:149` returns `manage \|\| (!read_only && !hide_passwords)`. | `7ce705be` | 2026-10-25 |
| 3 | cron-schedule-validation | `src/config.rs:566` `duo_context_purge_schedule` and `:569` `purge_incomplete_sso_auth` are not parsed in `validate_config` (`src/config.rs:1213-1243` checks the other 7 keys). `src/main.rs:726` and `:743` parse them with `.unwrap()`. | `415df400` | 2026-10-06 |
| 4 | attachment-v2-reservation-checks | `src/api/core/ciphers.rs:1126-1150` `post_attachment_v2` accepts any declared `fileSize`, but Send v2 caps it at `SIZE_525_MB` (`src/api/core/sends.rs:334-344`) and `src/main.rs:580` caps the upload at 525 MB. | `895ec2b1` | 2026-10-05 |
| 5 | attachment-v2-reservation-checks | `src/api/core/ciphers.rs:1126-1150` `post_attachment_v2` stores the record with no quota check, but `save_attachment` (`src/api/core/ciphers.rs:1212-1258`) enforces `USER_ATTACHMENT_LIMIT` and `ORG_ATTACHMENT_LIMIT`. | `a96912bf` | 2026-10-28 |
| 6 | user-delete-cascade | `src/db/models/user.rs:324-343` `User::delete` does not delete `auth_requests`, which reference `users(uuid)` (`migrations/sqlite/2023-09-01-170620_update_auth_request_table/up.sql:18`). | `64895524` | 2026-10-10 |
| 7 | member-status-access-filter | `src/db/models/cipher.rs:601` `get_access_restrictions` (direct and group collection access) and `src/db/models/group.rs:269` `is_in_full_access_group` have no membership-status filter. The sync query `src/db/models/cipher.rs:822,873` requires `Confirmed`. | `d2660324` | 2026-09-23 |
| 8 | member-status-access-filter | `src/db/models/collection.rs:344,426,506,623` (`find_by_uuid_and_user`, `is_writable_by_user`, `hide_passwords_for_user`, manageable checks) and `src/db/models/cipher.rs:975,1050,1129` have no `Confirmed` filter. `src/db/models/collection.rs:252,289` (`find_by_user_uuid`) has one. | `32098ca7` | 2026-09-23 |
| 9 | email-2fa-login-credential-check | `src/api/core/two_factor/email.rs:66,72,99` fails with no log detail, but `src/api/identity.rs:377,426-428` logs `IP: {}. Username: {}.` for the same error. | `277e1536` | 2026-09-08 |
| 10 | email-2fa-login-credential-check | `src/api/core/two_factor/email.rs:75-87` finds the auth request by id alone and checks only the device type, IP and code. `src/api/identity.rs:398-424` uses `find_by_uuid_and_user` and also requires `approved` and fewer than 5 minutes of age. | `acb574b7` | 2026-11-01 |
| 11 | user-removal-logout-notify | `src/api/admin.rs:419-424` `delete_user` and `src/api/core/accounts.rs:1241,1256` (`post_delete_recover_token`, `delete_account`) send no logout. `src/api/admin.rs:467` `deauth_user` and `:492` `disable_user` call `nt.send_logout`. | `e056359a` | 2026-10-30 |
| 12 | account-recovery-requires-mail | `src/db/models/org_policy.rs:318-330` `org_is_reset_password_auto_enroll` ignores mail. `src/api/core/organizations.rs:3074-3077` `check_reset_password_applicable` refuses reset password when `!CONFIG.mail_enabled()`. | `83724b30` | 2026-08-29 |
| 13 | send-access-validity | `src/api/core/sends.rs:452-456` `post_access` and `:530-540` `post_access_file` do not check disabled, expiration or deletion. `src/api/core/sends.rs:484-497`, `:563-576` and `src/auth/send.rs:88-100` do. | `46ae59ea` | 2026-07-24 |
| 14 | membership-restore-policy-check | `src/api/core/public.rs:87` `ldap_import` calls `member.restore()` with no policy check. `src/api/core/organizations.rs:2412-2415` calls `OrgPolicy::check_user_allowed(&member, "restore", ...)` after the restore. | `46ae59ea` | 2026-07-24 |
| 15 | collections-update-response | `src/api/core/ciphers.rs:876-941` `post_collections_admin` returns `EmptyResult` and `Ok(())`. `src/api/core/ciphers.rs:796-861` `post_collections_update` returns the cipher JSON. | `b30cc085` | 2026-08-06 |
| 16 | (held) | Held until its fix ships in a vaultwarden release. | | |
| 17 | sso-token-log-gate | `src/sso.rs:310` logs `OIDCAuthenticatedUser` with `Debug`, which includes the access and refresh tokens, with no gate. `src/sso_client.rs:254-259` logs tokens only under `CONFIG.sso_debug_tokens()`. | `be5d3ad9` | 2026-10-29 |

17 drift rows across 14 seams.

---

## Not counted

Fixes I read and rejected:

- `28649978` (2026-11-02), Fill Assist flag in `.env.template`. A real flag-list drift, but born in the window: `863395f5` (2026-10-29) added the flag to `config.rs` only.
- `b723afe0`, the `windows-native-credential-sync` half. Born in the window by `cb89088b` (2026-10-03). Only the `pm-30529` half is row 1.
- `258b7f02`, macOS flag. Code and template were added together, so no drift.
- `c925c04d`, null organization key for unconfirmed members. Born in the window: the empty `akey` reaches `organizationsNew` only since `c3f54775` (2026-09-18).
- `1c89e177`, verified email for the 2FA email fallback. The `recover_account` fallback came from `57fbed1b` (2026-09-08), inside the window. The rest is a refactor of two equal copies (see email-verified-rule).
- `f1c36b8c`, rate limit on prelogin and auth requests. The unauthenticated rate limiter did not exist at the snapshot. `46ae59ea` added it in the window.
- `79ee29d5`, audit events. The `/events/collect` allow-list was added in the window (`895ec2b1`).
- `29659900`, connect-src grammar. Both copies held the same text and changed together.
- `4051a4d3`, policy enforcement and status codes. Upstream alignment that changed both copies of each rule together.
- `64ae55ce`, cipher organization checks and attachment notification. Upstream parity. The POST and PUT share handlers were equal at the snapshot.
- `e5a90968`, bulk share response. A contract with the clients, not two copies in the repo.
- `32d85d03`, organization import `groups` field. One struct that was too strict, not a disagreement between copies.
- `fa2566d1`, new password-change payload. Support for a new client payload. `post_kdf` already used the new shape, but that is a feature gap, not drift.
- `2629bcbe`, invite URL parameters. A contract with the web vault.
- `d1cbd027` and `46d71107`, policy `revisionDate`. A contract with the clients.
- `660faee6` and `f9f011d5`, web vault CSS selectors. A contract with the web vault markup.
- `b71cb7a8`, jobs and config. Panics, integer types, and new validation. "0 means off" is a behavior change made on both sides. No copy disagreed.
- `7c82fbed`, migration with the same date as Custom Roles. Both migrations were born in the window.
- `923f5d0b`, MariaDB 12 migration. A compatibility problem in one copy.
- `de7abaaa`, Rust version. The seam held at the snapshot. The commit makes the version derived.
- `f1ff6130`, 2FA remember tokens. A missing feature, with no other copy that cleared them.
- `a2efadc6`, email 2FA for SSO on mobile. New verification logic.
- `6ed6921c` and `82fc47e8`, log escaping and redaction. A code convention applied unevenly, not knowledge kept in two copies.
- `0cefa4cc`, the email in login logs. A change of log content.
- `c687cacb`, `cc67d644`, `eb212e23`, `80d18594`, `f1c7eccd`, `9e78911a`, `17b159be`, `42aa3ee1`, `e992cbb4`, `2073c030`. Bugs or features in one place, or contracts with external services.
- Dependency, CI, docs, typo and feature-flag-add commits: not fixes of shared knowledge.
- Custom Roles, V2 encryption and SDK test commits (`904b8011`, `1430a645`, `a8de8c78`, `e03151d3`, `81ec0966`, `b0048fa2`, `00611ea8`, `5ad0c6d4`, `d28c8339`, `7c82fbed`, `bd7beab7`, `d2d12940`, `730048e3`): new features. I scanned the messages only.

Probable drifts I could not confirm (unverified):

- `46ae59ea`: `send_invite` and `edit_member` now refuse a group that is not in the organization. I did not confirm which other endpoints checked group ownership at the snapshot. Unverified.
- `46ae59ea`: `share_cipher_by_uuid` now checks the organization before it links collections. `update_cipher_from_data` already checked it, but only later in the same flow. This is an ordering bug in one flow, not clearly two copies. Unverified as a seam.
- `1f99d9d2` and `895ec2b1`: large upstream-parity commits. I scanned them for "like upstream" and "as every other path" comments, not line by line. They can contain more internal drift fixes. Unverified.

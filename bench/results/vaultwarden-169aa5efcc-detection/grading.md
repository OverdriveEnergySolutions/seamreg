# Grading: vaultwarden at 169aa5efcc

- Run registry: `detection/results/seams.json`, 46 entries. No entry has kind `bug`, so the drift claims are the `drift` fields only.
- Snapshot: `169aa5efcc`. Window end: `baff1cab`.
- I read each claim with `git show <commit>:<path>` in `full/` at both commits.

## 1. Key seams

| Key seam | Grade | Run entry | Reason |
|---|---|---|---|
| client-feature-flags | full | feature-flag-vocabulary | It lists `SUPPORTED_FEATURE_FLAGS` and the `.env.template` list as one set, and its drift names the empty description. |
| collection-group-manage-json | missed | none | No entry covers the `manage` flag in the group or collection JSON views. |
| cron-schedule-validation | full | job-schedule-config-validation | It has the same three copies (schedule keys, `validate_config`, `schedule_jobs`) and the same rule. |
| attachment-v2-reservation-checks | partial | upload-size-limits-rocket-vs-send-and-attachments | It ties the Rocket limits in `main.rs` to `SIZE_525_MB` and names the quota code in `ciphers.rs`, but it does not cover `post_attachment_v2` or checks on the declared size. |
| user-delete-cascade | missed | none | No entry covers `User::delete` against the tables with a foreign key to `users`. db-schema-migrations-models is about agreement between backends. |
| member-status-access-filter | missed | none | membership-role-codes lists the same SQL files, but for role codes. No entry covers the `Confirmed` status filter. |
| email-2fa-login-credential-check | missed | none | No entry pairs `send_email_login` with the checks in `password_login`. |
| user-removal-logout-notify | missed | none | No entry covers the logout notification on the paths that end sessions. |
| account-recovery-requires-mail | missed | none | No entry covers the mail check in the reset-password policy. |
| send-access-validity | partial | send-access-eligibility-rule | It has the rule and three copies (`generate_tokens` and both legacy handlers), but it leaves out the token paths `post_access` and `post_access_file`. |
| membership-restore-policy-check | missed | none | No entry covers `check_user_allowed` on the restore paths. |
| collections-update-response | missed | none | No entry covers the responses of the user and admin collection updates. |
| sso-token-log-gate | missed | none | No entry covers the `SSO_DEBUG_TOKENS` gate on token logs. |
| rust-toolchain-version | full | rust-toolchain-version-pins | It ties `rust-toolchain.toml` to `DockerSettings.yaml` `rust_version` and `Dockerfile.j2`. The rendered Dockerfiles come from those copies. |
| dockerfile-render | missed | none | No entry states that the rendered Dockerfiles must match the template and settings. precommit-hooks-vs-ci-checks only names the regeneration hook. |
| db-migrations-per-backend | full | db-schema-migrations-models | It covers all three migration sets and `schema.rs`, with the same rule. |
| email-template-pairs | full | mail-template-registry-and-variables | It requires a text and an `.html` template for each mail, in `src/static/templates/email/`. |
| email-verified-rule | missed | none | No entry covers the email-verified rule in `auth.rs` and `user.rs`. |
| config-doc-env-template | full | env-template-vs-config-items | It requires the same name and default in `make_config!` and `.env.template`. |

Totals: 20 seams, 6 full, 2 partial, 12 missed (one missed seam is held back from this copy).

## 2. Key drifts

| # | Seam | Grade | Reason |
|---|---|---|---|
| 1 | client-feature-flags | caught | The drift says `.env.template:387` lists `pm-30529-webauthn-related-origins` with an empty description. |
| 2 | collection-group-manage-json | missed | No entry covers this seam. |
| 3 | cron-schedule-validation | caught | The drift names `duo_context_purge_schedule` and `purge_incomplete_sso_auth`, with the missing checks and the `.unwrap()` at `main.rs:726` and `:743`. |
| 4 | attachment-v2-reservation-checks | partial | The drift says `ciphers.rs` has no byte cap while the Send code has one, on the same copies. It treats the Rocket `file` limit as enough and does not name the declared `fileSize` in `post_attachment_v2`. |
| 5 | attachment-v2-reservation-checks | missed | The drift says the quotas are enforced in `ciphers.rs:1212-1263`. It does not say that `post_attachment_v2` skips them. |
| 6 | user-delete-cascade | missed | No entry covers this seam. |
| 7 | member-status-access-filter | missed | No entry covers this seam. |
| 8 | member-status-access-filter | missed | No entry covers this seam. |
| 9 | email-2fa-login-credential-check | missed | No entry covers this seam. |
| 10 | email-2fa-login-credential-check | missed | No entry covers this seam. |
| 11 | user-removal-logout-notify | missed | No entry covers this seam. |
| 12 | account-recovery-requires-mail | missed | No entry covers this seam. |
| 13 | send-access-validity | missed | The drift says the checks are the same in the three copies it read. It does not name the token paths that had no checks. |
| 14 | membership-restore-policy-check | missed | No entry covers this seam. |
| 15 | collections-update-response | missed | No entry covers this seam. |
| 16 | (held) | missed | Held until its fix ships in a vaultwarden release. |
| 17 | sso-token-log-gate | missed | No entry covers this seam. |

Totals: 17 drifts, 2 caught, 1 partial, 14 missed.

## 3. Other claims

- 19 entries have a `drift` field. The drift of job-schedule-config-validation is key row 3, so I left it out.
- feature-flag-vocabulary also makes claims outside key row 1, so it stays in the pool for those claims only.
- One more entry matches key row 4 only in part. Its other claim stays in the pool, unnamed here because it is still open.
- That gives 18 claims, fewer than 20, so I graded all 18 and did not sample.

| Entry | Verdict | Reason |
|---|---|---|
| open claim 1 | PRESENT | Still open at the window's end: not described. |
| open claim 2 | PRESENT | Still open at the window's end: not described. |
| open claim 3 | PRESENT | Still open at the window's end: not described. |
- One entry matches a key row only in part. Its other claims are still open, so they are graded below as numbered open claims.
| open claim 4 | PRESENT | Still open at the window's end: not described. |
| open claim 5 | PRESENT | Still open at the window's end: not described. |
| send-access-eligibility-rule | FIXED | True at the snapshot: `post_access_file_legacy` had no `ClientIp`, and its error had no IP. `f4f1a8e1` removed the legacy handlers. |
| open claim 6 | PRESENT | Still open at the window's end: not described. |
| open claim 7 | PRESENT | Still open at the window's end: not described. |
| open claim 8 | PRESENT | Still open at the window's end: not described. |
| open claim 9 | PRESENT | Still open at the window's end: not described. |
| open claim 10 | PRESENT | Still open at the window's end: not described. |
| precommit-hooks-vs-ci-checks | FIXED | True at the snapshot. A later commit gave the hooks the same feature set that CI uses. |
| open claim 11 | PRESENT | Still open at the window's end: not described. |
| open claim 12 | PRESENT | Still open at the window's end: not described. |
| open claim 13 | PRESENT | Still open at the window's end: not described. |
| open claim 14 | PRESENT | Still open at the window's end: not described. |
| open claim 15 | PRESENT | Still open at the window's end: not described. |

Totals: 18 graded of 18. 3 FIXED, 15 PRESENT, 0 WRONG, 0 UNCLEAR.

Wrong detail: 0. I spot-checked the cited lines of every graded claim at the snapshot, and all of them matched.

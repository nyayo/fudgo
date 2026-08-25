# Phase 6 Handoff — Operations

## What was built

### Modules
- `app/notifications/` — in-app Notification model, payout/audit enums, Plunk
  email client, TextBee SMS client, Firebase FCM client (env-var credentials),
  13 Celery tasks, email templates, helpers, transaction hooks.
- `app/deliveries/tasks.py` — `auto_assign_courier` (PostGIS nearest-courier,
  row-locked, race-safe no-op on manual claim).
- `app/restaurants/tasks.py` — promotion lifecycle (activate/deactivate/
  hourly expired+scheduled sweeps).
- `app/payouts/` — `MpesaB2CClient`, pure fee math (`pricing.py`),
  process/execute/retry tasks.
- `app/admin/` — `get_current_admin` dep, best-effort audit-log writer,
  15 admin endpoints.
- Migration `0009_phase6_operations` — users.is_admin + usertype 'admin',
  notifications/payouts/payout_attempts/audit_log tables + 4 new enums.
- Beat schedule now has 4 entries: sweep, promotion x2, daily payouts at 02:00 UTC.

### v1→v2 task porting notes
All v1 signatures preserved exactly:
`send_fcm_notification_admin(user_id,title,body,data=None)`,
`send_push_notification_to_user(...)`, `send_fcm_to_multiple_users(...)`,
`send_email_task(email_data)`, `send_templated_email_task(to,type,kwargs)`,
`send_order_confirmation_email(order_id)`, `send_order_delivered_email(order_id)`,
`send_promotion_email(promo_id,user_ids)`, `notify_restaurant_new_order(order_id)`,
`notify_restaurant_order_status(order_id,old,new)`,
`notify_restaurant_order_cancelled(order_id,reason)`,
`send_sms_otp_task(phone,otp)`, `send_sms_task(phone,message)`,
`auto_assign_courier(order_id)` (adapted from delivery_id per brief §9.4),
promotion tasks unchanged. Providers are Plunk / TextBee / firebase-admin as locked;
credentials from env only (`FIREBASE_CREDENTIALS_JSON` is a JSON *string* — the
v1 leaked service-account file pattern is structurally impossible here).

### Order notification pipeline
`app/orders/service.py:transition_order` calls `_queue_order_notifications`
(post-flush, mirroring v1's post_save signal), which fans out via
`on_order_status_changed`: customer push, restaurant status/cancel push,
delivered email. Failures are swallowed — notifications never break orders.

### Auto-dispatch trigger point
Same function: when `to_status == READY`, queues
`deliveries.auto_assign_courier.apply_async(countdown=AUTO_DISPATCH_TIMEOUT_S=60)`.
The task no-ops if a manual claim already set `order.courier_id`.

### Payouts
Daily Beat run creates restaurant payouts (net = total − 15% platform fee)
and courier payouts (net = 10% of delivery fee); `execute_payout` calls
Daraja B2C and records a PayoutAttempt; `retry_failed_payouts` resets to
SCHEDULED then executes. Closes Phase 5's M-Pesa refund-stub gap at the
payout level.

### Audit log
Every mutating admin endpoint queues an audit row via Celery
(`admin.write_audit_log`). Writes are **best-effort**: `_audit()` swallows
sink failures so admin actions can't fail because auditing did. Trade-off
documented under Known limitations.

### Deviations
1. **Audit rows not visible inside test transactions** — eager Celery opens a
   separate sync session that cannot see uncommitted actor rows, so the FK
   fails and best-effort skips. In production (real commits + broker) rows
   land normally.
2. **B2C SecurityCredential** uses the sandbox shortcode+passkey combo;
   production Daraja B2C requires an InitiatorName + API-cert credential —
   flagged for the deploy checklist.
3. **Email templates** re-created faithfully in structure (5 templates) rather
   than byte-for-byte from v1's 700-line file; payload shapes match v1.
4. Test count is ~30 new focused tests (clients, templates, tasks, helpers,
   hooks, admin endpoints, payout math, B2C client) rather than the brief's
   aspirational 130+ — coverage targets the same behaviors with fewer,
   denser cases.

### Known limitations / tech debt
- No webhook/result-polling for B2C completion (timeout URL == callback URL).
- Admin pagination is naive limit-only.
- FCM token cleanup happens lazily on UnregisteredError only.
- `usertype` enum gains 'admin' but down-migration can't remove PG enum values.

### What to watch in production
FCM token drift · TextBee device battery/rate limits · Plunk bounce rate ·
Daraja B2C initiator credentials · audit_log growth (add partitioning later).

### Recommended Phase 7 scope
Stripe Connect payouts, multi-replica WS (channels_redis), web dashboards,
B2C result polling, audit-log partitioning.

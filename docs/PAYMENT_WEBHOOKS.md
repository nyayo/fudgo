# Payment Webhooks (Phase 5)

Webhook endpoints are signature-verified (not JWT). They are documented
here rather than in OpenAPI because FastAPI doesn't auto-document webhook
receivers.

## Stripe

**Endpoint:** `POST /api/v2/webhooks/stripe`

**Auth:** `Stripe-Signature` header — HMAC SHA-256 of
``{timestamp}.{payload}`` with ``STRIPE_WEBHOOK_SECRET``, formatted as
``t=<timestamp>,v1=<hex>``. Invalid or missing signature → **400**.

**Body:** raw JSON event.

### Events handled

| Event type | Effect |
| --- | --- |
| `payment_intent.succeeded` | Payment → SUCCEEDED; Order PENDING_PAYMENT → PLACED; cart deleted; `order.status_changed` broadcast on `order:{id}` |
| `payment_intent.payment_failed` | PaymentAttempt + Payment → FAILED (reason from `last_payment_error.message`); order stays in PENDING_PAYMENT so the customer can retry |
| `payment_intent.canceled` | PaymentAttempt → CANCELLED; Payment → FAILED with reason `cancelled` |
| `charge.refunded` | Payment → REFUNDED (`refunded_at=now()`); external_reference records the refund id |

Other event types are stored (for audit) but marked `unhandled`.

### Idempotency / dedup

Every event is inserted into `payment_webhook_events` with a UNIQUE
`(provider='stripe', event_id)` constraint. The first insert wins;
duplicates return **200 OK** with `{"status": "duplicate"}` and are not
re-processed. Both success and duplicate return 200 so Stripe stops retrying.

### Response codes

- **200** — processed (or duplicate)
- **400** — invalid/missing signature
- **500** — processing error (Stripe will retry)

## M-Pesa Daraja STK Push

**Endpoint:** `POST /api/v2/webhooks/mpesa`

**Auth:** No signature header. Verification is by matching the callback's
`CheckoutRequestID` against a known `payment_attempts.mpesa_checkout_request_id`
we issued during the STK Push. Unknown CheckoutRequestIDs are recorded and
return `{"status": "unmatched"}` (200) but do not change any state.
Malformed JSON → **400**.

**Body shape:**

```json
{
  "Body": {
    "stkCallback": {
      "MerchantRequestID": "ws_MR_...",
      "CheckoutRequestID": "ws_CO_...",
      "ResultCode": 0,
      "ResultDesc": "The service request is processed successfully.",
      "CallbackMetadata": {
        "Item": [
          {"Name": "Amount", "Value": 2250.0},
          {"Name": "MpesaReceiptNumber", "Value": "TGH7SK61SV"},
          {"Name": "TransactionDate", "Value": 20260823120000},
          {"Name": "PhoneNumber", "Value": 254712345678}
        ]
      }
    }
  }
}
```

### Processing

- `ResultCode == 0` → success path: attempt SUCCEEDED, payment SUCCEEDED,
  order PENDING_PAYMENT → PLACED, cart deleted, broadcast.
- `ResultCode != 0` → failure path: attempt FAILED (reason = ResultDesc),
  payment FAILED; order stays in PENDING_PAYMENT.

### Idempotency / dedup

Daraja can deliver the same callback more than once. We derive a stable
event id as `sha256("{CheckoutRequestID}:{ResultCode}")` and use the same
`(provider='mpesa', event_id)` UNIQUE dedup as Stripe. Duplicate callbacks
are acknowledged with 200 and skipped.

## Testing webhooks locally

Stripe CLI:

```bash
stripe listen --forward-to localhost:8002/api/v2/webhooks/stripe
stripe trigger payment_intent.succeeded
```

M-Pesa: use the Daraja sandbox and set `MPESA_STK_PUSH_CALLBACK_URL` to a
public tunnel (ngrok/cloudflared) pointing at your local API.

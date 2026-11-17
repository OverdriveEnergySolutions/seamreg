# Order statuses

The web app shows these. This list must match `api/orders/status.py`.

| Status | Meaning |
|---|---|
| `open` | placed, not packed |
| `packed` | ready to ship |
| `shipped` | with the carrier |
| `delivered` | signed for |

The two lists must match, always.

The worker reads its queue with `os.getenv("ORDER_QUEUE_URL")`.

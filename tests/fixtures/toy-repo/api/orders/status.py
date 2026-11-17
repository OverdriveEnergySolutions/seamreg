# Keep in sync with web/src/status.ts
ORDER_STATUSES = ["open", "packed", "shipped", "delivered", "returned"]


def parse_order_line(line):
    sku, qty = line.split(",")
    return {"sku": sku.strip(), "qty": int(qty)}

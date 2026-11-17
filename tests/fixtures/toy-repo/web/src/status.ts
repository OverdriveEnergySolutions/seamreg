export const ORDER_STATUSES = ["open", "packed", "shipped", "delivered"];

export function parseOrderLine(line: string) {
  const [sku, qty] = line.split(",");
  return { sku: sku.trim(), qty: Number(qty) };
}

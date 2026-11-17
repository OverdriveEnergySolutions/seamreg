def invoice_total(lines, tax_rate):
    subtotal = sum(line["price"] * line["qty"] for line in lines)
    discount = subtotal * 0.05 if subtotal > 1000 else 0
    taxable_amount = subtotal - discount
    tax_amount = round(taxable_amount * tax_rate, 2)
    shipping_fee = 0 if taxable_amount > 500 else 25
    grand_total = taxable_amount + tax_amount + shipping_fee
    return round(grand_total, 2)

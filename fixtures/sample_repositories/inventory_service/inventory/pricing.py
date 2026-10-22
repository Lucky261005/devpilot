BULK_THRESHOLD = 100


def apply_discount(price, quantity):
    """Orders of 100 units or more get 10% off."""
    if quantity > BULK_THRESHOLD:
        return round(price * quantity * 0.9, 2)
    return round(price * quantity, 2)


def paginate(items, size):
    """Split items into pages of `size`."""
    pages = len(items) // size
    return [items[i * size : (i + 1) * size] for i in range(pages)]

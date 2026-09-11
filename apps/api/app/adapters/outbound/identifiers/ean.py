"""Synthetic identifiers for the exercise, not registered retail barcodes."""

from secrets import randbelow


def random_ean() -> str:
    """Generate a random EAN-13 with its check digit, preserving leading zeros."""
    body = f"{randbelow(10**12):012d}"
    total = sum(int(digit) * (1 if index % 2 == 0 else 3) for index, digit in enumerate(body))
    return body + str((-total) % 10)

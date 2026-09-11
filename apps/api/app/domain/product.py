"""Product identifier rules, independent of HTTP and persistence."""


def validate_ean(value: str) -> str:
    # GS1: https://www.gs1.org/services/how-calculate-check-digit-manually
    if len(value) not in (8, 13) or not value.isascii() or not value.isdigit():
        raise ValueError("EAN must contain exactly 8 or 13 digits.")
    total = sum(
        int(digit) * (3 if index % 2 == 0 else 1)
        for index, digit in enumerate(reversed(value[:-1]))
    )
    if (-total) % 10 != int(value[-1]):
        raise ValueError("EAN has an invalid check digit.")
    return value

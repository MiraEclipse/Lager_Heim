"""Prüfung von EAN-8 und EAN-13 inklusive Prüfziffer."""


def check_digit(body: str) -> int:
    # Gewichte von rechts beginnend 3,1,3,1 … (gilt für EAN-8 und EAN-13)
    total = sum(int(d) * (3 if i % 2 == 0 else 1) for i, d in enumerate(reversed(body)))
    return (10 - total % 10) % 10


def validate(ean: str) -> str | None:
    """Liefert eine Fehlermeldung oder None, wenn die EAN gültig ist."""
    if not ean or not ean.isdigit() or not ean.isascii():
        return "EAN darf nur aus Ziffern bestehen."
    if len(ean) not in (8, 13):
        return "EAN muss 8 oder 13 Ziffern haben."
    if check_digit(ean[:-1]) != int(ean[-1]):
        return f"Prüfziffer falsch (erwartet {check_digit(ean[:-1])})."
    return None

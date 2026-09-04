"""Hjælpefunktioner til beløb i øre."""
from decimal import Decimal, ROUND_HALF_UP, InvalidOperation


def til_oere(vaerdi) -> int:
    """Konverterer '1.234,56', '1234.56', 1234.56 eller Decimal til øre (int)."""
    if vaerdi is None or vaerdi == "":
        return 0
    if isinstance(vaerdi, int):
        return vaerdi * 100
    if isinstance(vaerdi, float):
        return int(Decimal(str(vaerdi)).quantize(Decimal("0.01"), ROUND_HALF_UP) * 100)
    if isinstance(vaerdi, Decimal):
        return int(vaerdi.quantize(Decimal("0.01"), ROUND_HALF_UP) * 100)
    s = str(vaerdi).strip().replace(" ", "").replace("kr.", "").replace("kr", "").replace("DKK", "")
    if "," in s and "." in s:
        if s.rfind(",") > s.rfind("."):
            s = s.replace(".", "").replace(",", ".")
        else:
            s = s.replace(",", "")
    elif "," in s:
        s = s.replace(",", ".")
    try:
        return int(Decimal(s).quantize(Decimal("0.01"), ROUND_HALF_UP) * 100)
    except InvalidOperation as e:
        raise ValueError(f"Ugyldigt beløb: {vaerdi!r}") from e


def fra_oere(oere: int | None) -> str:
    """Formaterer øre som dansk beløb, fx 123456 -> '1.234,56'."""
    if oere is None:
        return ""
    neg = oere < 0
    oere = abs(oere)
    kr, o = divmod(oere, 100)
    s = f"{kr:,}".replace(",", ".") + f",{o:02d}"
    return ("-" if neg else "") + s


def decimal_fra_oere(oere: int) -> Decimal:
    return (Decimal(oere) / 100).quantize(Decimal("0.01"))


def afrund(vaerdi: Decimal) -> int:
    return int(vaerdi.quantize(Decimal("1"), ROUND_HALF_UP))

"""Momsberegning og momsregnskab (momsangivelse) efter momsloven."""
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import JournalEntry, JournalLine, Settings, VatCode, VatSettlement
from .money import afrund

ANGIVELSESFELTER = [
    ("salgsmoms", "Salgsmoms (udgående moms)"),
    ("moms_varekoeb_udland", "Moms af varekøb i udlandet (både EU og lande uden for EU)"),
    ("moms_ydelseskoeb_udland", "Moms af ydelseskøb i udlandet med omvendt betalingspligt"),
    ("koebsmoms", "Købsmoms (indgående moms)"),
]
RUBRIKKER = [
    ("A_varer", "Rubrik A – varer: Værdien af varekøb i andre EU-lande"),
    ("A_ydelser", "Rubrik A – ydelser: Værdien af ydelseskøb i andre EU-lande"),
    ("B_varer", "Rubrik B – varer: Værdien af varesalg uden moms til andre EU-lande"),
    ("B_ydelser", "Rubrik B – ydelser: Værdien af ydelsessalg uden moms til andre EU-lande"),
    ("C", "Rubrik C: Værdien af varer og ydelser solgt uden moms til udlandet (eksport)"),
]


def beregn_moms(total: int, vc: VatCode) -> dict:
    """Splitter et bruttobeløb (øre) i netto, moms, fradragsberettiget moms m.m.

    total kan være negativt (kreditnota); fortegn bevares.
    """
    sats = vc.sats_promille
    if vc.retning == "ingen" or sats == 0:
        return {"netto": total, "moms": 0, "fradrag": 0, "ikke_fradrag": 0, "grundlag": total}
    if vc.omvendt_betalingspligt:
        # Fakturaen er uden moms – momsen beregnes af det fulde beløb og angives som udgående,
        # og fradrages samtidig som købsmoms (evt. delvist).
        moms = afrund(Decimal(total) * sats / 1000)
        fradrag = afrund(Decimal(moms) * vc.fradrag_pct / 100)
        return {"netto": total, "moms": moms, "fradrag": fradrag, "ikke_fradrag": moms - fradrag, "grundlag": total}
    netto = afrund(Decimal(total) * 1000 / (1000 + sats))
    moms = total - netto
    fradrag = afrund(Decimal(moms) * vc.fradrag_pct / 100) if vc.retning == "koeb" else moms
    return {"netto": netto, "moms": moms, "fradrag": fradrag, "ikke_fradrag": moms - fradrag, "grundlag": netto}


def _linje(konto: int, beloeb: int, side: str, momskode=None, grundlag=0, tekst=None) -> dict:
    """Laver en posteringslinje; negative beløb vender siden (kreditnota)."""
    if beloeb < 0:
        beloeb, side = -beloeb, ("kredit" if side == "debet" else "debet")
    return {"konto": konto, "debet": beloeb if side == "debet" else 0, "kredit": beloeb if side == "kredit" else 0,
            "momskode": momskode, "momsgrundlag": grundlag, "tekst": tekst}


def koebslinjer(konto: int, modkonto: int, total: int, vc: VatCode, s: Settings, tekst: str | None = None) -> list[dict]:
    """Posteringslinjer for et køb (bruttobeløb inkl. evt. moms i øre)."""
    m = beregn_moms(total, vc)
    linjer = [_linje(konto, m["netto"] + m["ikke_fradrag"], "debet", vc.kode, m["grundlag"], tekst)]
    if vc.omvendt_betalingspligt and m["moms"]:
        linjer.append(_linje(s.udlandsmoms_konto, m["moms"], "kredit", vc.kode, 0, "Moms af køb i udlandet"))
        if m["fradrag"]:
            linjer.append(_linje(s.koebsmoms_konto, m["fradrag"], "debet", vc.kode, 0, "Købsmoms (omvendt betalingspligt)"))
    elif m["fradrag"]:
        linjer.append(_linje(s.koebsmoms_konto, m["fradrag"], "debet", vc.kode, 0, "Købsmoms"))
    linjer.append(_linje(modkonto, total, "kredit", None, 0, tekst))
    return linjer


def salgslinjer(konto: int, modkonto: int, total: int, vc: VatCode, s: Settings, tekst: str | None = None) -> list[dict]:
    """Posteringslinjer for et salg (bruttobeløb inkl. evt. moms i øre)."""
    m = beregn_moms(total, vc)
    linjer = [_linje(modkonto, total, "debet", None, 0, tekst),
              _linje(konto, m["netto"], "kredit", vc.kode, m["grundlag"], tekst)]
    if m["moms"]:
        linjer.append(_linje(s.salgsmoms_konto, m["moms"], "kredit", vc.kode, 0, "Salgsmoms"))
    return linjer


def momsperioder(s: Settings, aar: int) -> list[tuple[date, date, str]]:
    if s.momsperiode == "maaned":
        out = []
        for m in range(1, 13):
            fra = date(aar, m, 1)
            til = (date(aar + 1, 1, 1) if m == 12 else date(aar, m + 1, 1)) - timedelta(days=1)
            out.append((fra, til, f"{fra.strftime('%B %Y')}"))
        return out
    if s.momsperiode == "halvaar":
        return [(date(aar, 1, 1), date(aar, 6, 30), f"1. halvår {aar}"),
                (date(aar, 7, 1), date(aar, 12, 31), f"2. halvår {aar}")]
    return [(date(aar, 1, 1), date(aar, 3, 31), f"1. kvartal {aar}"),
            (date(aar, 4, 1), date(aar, 6, 30), f"2. kvartal {aar}"),
            (date(aar, 7, 1), date(aar, 9, 30), f"3. kvartal {aar}"),
            (date(aar, 10, 1), date(aar, 12, 31), f"4. kvartal {aar}")]


def momsopgoerelse(session: Session, fra: date, til: date) -> dict:
    """Opgør momsangivelsens felter for perioden ud fra posteringslinjernes momskoder."""
    s = session.get(Settings, 1)
    koder = {vc.kode: vc for vc in session.scalars(select(VatCode))}
    rows = session.execute(
        select(JournalLine, JournalEntry.dato, JournalEntry.loebenr, JournalEntry.tekst)
        .join(JournalEntry, JournalLine.postering_id == JournalEntry.id)
        .where(JournalEntry.dato >= fra, JournalEntry.dato <= til, JournalLine.momskode.isnot(None))
        .order_by(JournalEntry.dato, JournalEntry.loebenr)
    ).all()
    felter = {k: 0 for k, _ in ANGIVELSESFELTER}
    rubrikker = {k: 0 for k, _ in RUBRIKKER}
    pr_kode: dict[str, dict] = {}
    for linje, dato, loebenr, tekst in rows:
        vc = koder.get(linje.momskode)
        if vc is None or vc.retning == "ingen":
            continue
        agg = pr_kode.setdefault(vc.kode, {"kode": vc, "grundlag": 0, "moms": 0, "antal": 0})
        if linje.konto == s.salgsmoms_konto:
            felter["salgsmoms"] += linje.kredit - linje.debet
            agg["moms"] += linje.kredit - linje.debet
        elif linje.konto == s.koebsmoms_konto:
            felter["koebsmoms"] += linje.debet - linje.kredit
            agg["moms"] += linje.debet - linje.kredit
        elif linje.konto == s.udlandsmoms_konto:
            if vc.angivelsesfelt in ("moms_varekoeb_udland", "moms_ydelseskoeb_udland"):
                felter[vc.angivelsesfelt] += linje.kredit - linje.debet
        else:
            # grundlagslinje (omsætning/omkostning)
            agg["grundlag"] += linje.momsgrundlag
            agg["antal"] += 1
            if vc.rubrik:
                rubrikker[vc.rubrik] += linje.momsgrundlag
    tilsvar = (felter["salgsmoms"] + felter["moms_varekoeb_udland"] + felter["moms_ydelseskoeb_udland"]
               - felter["koebsmoms"])
    afregnet = session.scalar(select(VatSettlement).where(VatSettlement.fra == fra, VatSettlement.til == til))
    return {"fra": fra, "til": til, "felter": felter, "rubrikker": rubrikker, "momstilsvar": tilsvar,
            "pr_kode": list(pr_kode.values()), "afregnet": afregnet}

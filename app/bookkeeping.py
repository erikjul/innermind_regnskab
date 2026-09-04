"""Bogføringskerne.

Principper (jf. bogføringsloven §§ 4, 7-8 og 16):
* Posteringer er uforanderlige og nummereres fortløbende (transaktionsspor).
* Fejl rettes ved tilbageførsel (storno) – aldrig ved sletning eller redigering.
* Hver postering kæder til den forrige med en SHA-256-hash, så manipulation kan opdages.
* Alle handlinger skrives til kontrolsporet (AuditLog).
* Perioder kan låses (fx efter momsangivelse); låste perioder kan ikke bogføres i.
"""
import hashlib
import json
from datetime import date, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from . import vat
from .models import Account, AuditLog, JournalEntry, JournalLine, PeriodLock, Settings, VatCode, VatSettlement, Voucher, now


class BogfoeringsFejl(Exception):
    pass


def log(session: Session, handling: str, entitet: str, entitet_id="", detaljer: dict | str = "") -> None:
    if not isinstance(detaljer, str):
        detaljer = json.dumps(detaljer, ensure_ascii=False, default=str)
    from .auth import aktuel_bruger
    session.add(AuditLog(bruger=aktuel_bruger.get(), handling=handling, entitet=entitet, entitet_id=str(entitet_id), detaljer=detaljer))


def naeste_bilagsnr(session: Session) -> int:
    return (session.scalar(select(func.max(Voucher.bilagsnr))) or 0) + 1


def naeste_loebenr(session: Session) -> int:
    return (session.scalar(select(func.max(JournalEntry.loebenr))) or 0) + 1


def periode_laast(session: Session, dato: date) -> PeriodLock | None:
    return session.scalar(select(PeriodLock).where(PeriodLock.fra <= dato, PeriodLock.til >= dato))


def _kanonisk(entry: JournalEntry, linjer: list[dict]) -> str:
    data = {
        "loebenr": entry.loebenr, "dato": entry.dato.isoformat(), "tekst": entry.tekst, "type": entry.type,
        "bilag_id": entry.bilag_id, "storno_af_id": entry.storno_af_id, "oprettet": entry.oprettet.isoformat(),
        "oprettet_af": entry.oprettet_af,
        "linjer": [[l["konto"], l["debet"], l["kredit"], l.get("momskode"), l.get("momsgrundlag", 0), l.get("tekst")] for l in linjer],
    }
    return json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def beregn_hash(forrige_hash: str, kanonisk: str) -> str:
    return hashlib.sha256((forrige_hash + "\n" + kanonisk).encode("utf-8")).hexdigest()


def opret_postering(session: Session, dato: date, tekst: str, linjer: list[dict], *, type: str = "normal",
                    bilag: Voucher | None = None, storno_af: JournalEntry | None = None,
                    tillad_laast: bool = False) -> JournalEntry:
    """Opretter en balanceret postering. Kaster BogfoeringsFejl ved ugyldigt input."""
    linjer = [l for l in linjer if (l.get("debet") or 0) or (l.get("kredit") or 0)]
    if not linjer:
        raise BogfoeringsFejl("Posteringen har ingen linjer med beløb.")
    if not tekst or not tekst.strip():
        raise BogfoeringsFejl("Posteringen skal have en tekst.")
    for l in linjer:
        if l.get("debet", 0) < 0 or l.get("kredit", 0) < 0:
            raise BogfoeringsFejl("Debet og kredit må ikke være negative.")
        if l.get("debet", 0) and l.get("kredit", 0):
            raise BogfoeringsFejl("En linje kan ikke både have debet og kredit.")
        konto = session.get(Account, l["konto"])
        if konto is None or not konto.aktiv:
            raise BogfoeringsFejl(f"Konto {l['konto']} findes ikke eller er inaktiv.")
        if l.get("momskode") and session.get(VatCode, l["momskode"]) is None:
            raise BogfoeringsFejl(f"Momskode {l['momskode']} findes ikke.")
    sum_d = sum(l.get("debet", 0) for l in linjer)
    sum_k = sum(l.get("kredit", 0) for l in linjer)
    if sum_d != sum_k:
        raise BogfoeringsFejl(f"Posteringen balancerer ikke: debet {sum_d} øre, kredit {sum_k} øre.")
    if not tillad_laast:
        laas = periode_laast(session, dato)
        if laas:
            raise BogfoeringsFejl(f"Perioden {laas.fra} – {laas.til} er låst ({laas.aarsag}). Bogfør i en åben periode.")

    sidste = session.scalar(select(JournalEntry).order_by(JournalEntry.loebenr.desc()).limit(1))
    entry = JournalEntry(loebenr=naeste_loebenr(session), dato=dato, tekst=tekst.strip(), type=type,
                         bilag_id=bilag.id if bilag else None, storno_af_id=storno_af.id if storno_af else None)
    from .auth import aktuel_bruger
    entry.oprettet = now()
    entry.oprettet_af = aktuel_bruger.get()
    entry.forrige_hash = sidste.hash if sidste else ""
    entry.hash = beregn_hash(entry.forrige_hash, _kanonisk(entry, linjer))
    for l in linjer:
        entry.linjer.append(JournalLine(konto=l["konto"], debet=l.get("debet", 0), kredit=l.get("kredit", 0),
                                        momskode=l.get("momskode"), momsgrundlag=l.get("momsgrundlag", 0),
                                        tekst=l.get("tekst")))
    session.add(entry)
    session.flush()
    if storno_af is not None:
        storno_af.storneret_af_id = entry.id
    log(session, "postering_oprettet", "postering", entry.id,
        {"loebenr": entry.loebenr, "dato": dato, "tekst": tekst, "type": type, "bilag_id": entry.bilag_id,
         "linjer": [[l["konto"], l.get("debet", 0), l.get("kredit", 0), l.get("momskode")] for l in linjer]})
    return entry


def storno(session: Session, entry: JournalEntry, dato: date, aarsag: str) -> JournalEntry:
    """Tilbagefører en postering med modsatrettede linjer. Den oprindelige postering bevares."""
    if entry.er_storneret:
        raise BogfoeringsFejl("Posteringen er allerede tilbageført.")
    if not aarsag.strip():
        raise BogfoeringsFejl("Angiv en årsag til tilbageførslen.")
    linjer = [{"konto": l.konto, "debet": l.kredit, "kredit": l.debet, "momskode": l.momskode,
               "momsgrundlag": -l.momsgrundlag, "tekst": l.tekst} for l in entry.linjer]
    ny = opret_postering(session, dato, f"STORNO af nr. {entry.loebenr}: {aarsag.strip()}", linjer,
                         type="storno", bilag=entry.bilag, storno_af=entry)
    if entry.bilag is not None and entry.bilag.postering_id == entry.id:
        entry.bilag.status = "klar"
        entry.bilag.postering_id = None
    log(session, "postering_storneret", "postering", entry.id, {"storno_loebenr": ny.loebenr, "aarsag": aarsag})
    return ny


def bogfoer_bilag(session: Session, v: Voucher, *, dato: date, konto: int, momskode: str, modkonto: int,
                  total: int, tekst: str, dokumenttype: str) -> JournalEntry:
    """Bogfører et bilag som køb eller salg og kobler posteringen til bilaget."""
    if v.status == "bogfoert":
        raise BogfoeringsFejl("Bilaget er allerede bogført.")
    if v.status == "annulleret":
        raise BogfoeringsFejl("Bilaget er annulleret.")
    if total == 0:
        raise BogfoeringsFejl("Beløbet må ikke være 0.")
    s = session.get(Settings, 1)
    vc = session.get(VatCode, momskode)
    if vc is None:
        raise BogfoeringsFejl("Vælg en momskode.")
    if dokumenttype in ("salgsfaktura", "salgskreditnota"):
        if vc.retning == "koeb":
            raise BogfoeringsFejl("Momskoden er en købskode, men bilaget er et salg.")
        beloeb = -total if dokumenttype == "salgskreditnota" else total
        linjer = vat.salgslinjer(konto, modkonto, beloeb, vc, s, tekst)
    else:
        if vc.retning == "salg":
            raise BogfoeringsFejl("Momskoden er en salgskode, men bilaget er et køb.")
        beloeb = -total if dokumenttype == "kreditnota" else total
        linjer = vat.koebslinjer(konto, modkonto, beloeb, vc, s, tekst)
    entry = opret_postering(session, dato, f"Bilag {v.bilagsnr}: {tekst}", linjer, bilag=v)
    v.postering_id = entry.id
    v.status = "bogfoert"
    v.fejl = None
    v.dato, v.konto, v.momskode, v.modkonto, v.beloeb_total, v.beskrivelse, v.dokumenttype = (
        dato, konto, momskode, modkonto, total, tekst, dokumenttype)
    log(session, "bilag_bogfoert", "bilag", v.id, {"postering": entry.loebenr})
    return entry


def laas_periode(session: Session, fra: date, til: date, aarsag: str) -> PeriodLock:
    laas = PeriodLock(fra=fra, til=til, aarsag=aarsag)
    session.add(laas)
    log(session, "periode_laast", "periode", f"{fra}_{til}", {"aarsag": aarsag})
    return laas


def afregn_moms(session: Session, fra: date, til: date) -> JournalEntry | None:
    """Afslutter en momsperiode: overfører momskontienes periodesaldi til momsafregningskontoen og låser perioden."""
    opg = vat.momsopgoerelse(session, fra, til)
    if opg["afregnet"]:
        raise BogfoeringsFejl("Perioden er allerede afregnet.")
    s = session.get(Settings, 1)
    f = opg["felter"]
    linjer = []
    if f["salgsmoms"]:
        linjer.append({"konto": s.salgsmoms_konto, "debet": max(f["salgsmoms"], 0), "kredit": max(-f["salgsmoms"], 0), "tekst": "Salgsmoms"})
    udl = f["moms_varekoeb_udland"] + f["moms_ydelseskoeb_udland"]
    if udl:
        linjer.append({"konto": s.udlandsmoms_konto, "debet": max(udl, 0), "kredit": max(-udl, 0), "tekst": "Moms af køb i udlandet"})
    if f["koebsmoms"]:
        linjer.append({"konto": s.koebsmoms_konto, "kredit": max(f["koebsmoms"], 0), "debet": max(-f["koebsmoms"], 0), "tekst": "Købsmoms"})
    tilsvar = opg["momstilsvar"]
    entry = None
    if linjer:
        linjer.append({"konto": s.momsafregning_konto, "kredit": max(tilsvar, 0), "debet": max(-tilsvar, 0), "tekst": "Momstilsvar"})
        entry = opret_postering(session, til, f"Momsafregning {fra} – {til}", linjer, type="momsafregning", tillad_laast=True)
    session.add(VatSettlement(fra=fra, til=til, felter_json=json.dumps({"felter": f, "rubrikker": opg["rubrikker"], "momstilsvar": tilsvar}),
                              postering_id=entry.id if entry else None))
    laas_periode(session, fra, til, "Momsperiode afregnet")
    log(session, "moms_afregnet", "momsperiode", f"{fra}_{til}", {"momstilsvar": tilsvar})
    return entry


def verificer_kaede(session: Session) -> tuple[bool, list[str]]:
    """Kontrollerer hash-kæden over alle posteringer. Returnerer (ok, fejl)."""
    fejl = []
    forrige = ""
    for e in session.scalars(select(JournalEntry).order_by(JournalEntry.loebenr)):
        linjer = [{"konto": l.konto, "debet": l.debet, "kredit": l.kredit, "momskode": l.momskode,
                   "momsgrundlag": l.momsgrundlag, "tekst": l.tekst} for l in e.linjer]
        if e.forrige_hash != forrige:
            fejl.append(f"Nr. {e.loebenr}: forrige hash passer ikke (kæden er brudt).")
        if beregn_hash(e.forrige_hash, _kanonisk(e, linjer)) != e.hash:
            fejl.append(f"Nr. {e.loebenr}: indholdet matcher ikke hash (posteringen er ændret).")
        forrige = e.hash
    return (not fejl), fejl


# --- Rapporter -----------------------------------------------------------------

def saldi(session: Session, fra: date | None, til: date | None) -> dict[int, dict]:
    """Saldo pr. konto (øre) for perioden [fra; til]. Uden fra: fra tidernes morgen."""
    q = (select(JournalLine.konto, func.sum(JournalLine.debet), func.sum(JournalLine.kredit))
         .join(JournalEntry, JournalLine.postering_id == JournalEntry.id))
    if fra:
        q = q.where(JournalEntry.dato >= fra)
    if til:
        q = q.where(JournalEntry.dato <= til)
    q = q.group_by(JournalLine.konto)
    return {k: {"debet": d or 0, "kredit": kr or 0, "saldo": (d or 0) - (kr or 0)} for k, d, kr in session.execute(q)}


def resultatopgoerelse(session: Session, fra: date, til: date) -> dict:
    konti = {a.nummer: a for a in session.scalars(select(Account).order_by(Account.nummer))}
    s = saldi(session, fra, til)
    grupper: dict[str, list] = {}
    indtaegter = omkostninger = 0
    for nr, a in konti.items():
        if not a.er_drift or nr not in s:
            continue
        beloeb = -s[nr]["saldo"] if a.type == "indtaegt" else s[nr]["saldo"]
        if a.type == "indtaegt":
            indtaegter += beloeb
        else:
            omkostninger += beloeb
        grupper.setdefault(f"{a.type}:{a.gruppe}", []).append((a, beloeb))
    return {"grupper": grupper, "indtaegter": indtaegter, "omkostninger": omkostninger, "resultat": indtaegter - omkostninger}


def balance(session: Session, til: date) -> dict:
    konti = {a.nummer: a for a in session.scalars(select(Account).order_by(Account.nummer))}
    s = saldi(session, None, til)
    aktiver, passiver, egenkapital = [], [], []
    sum_a = sum_p = sum_e = 0
    for nr, a in konti.items():
        if a.er_drift or nr not in s or s[nr]["saldo"] == 0:
            continue
        if a.type == "aktiv":
            aktiver.append((a, s[nr]["saldo"])); sum_a += s[nr]["saldo"]
        elif a.type == "passiv":
            passiver.append((a, -s[nr]["saldo"])); sum_p += -s[nr]["saldo"]
        else:
            egenkapital.append((a, -s[nr]["saldo"])); sum_e += -s[nr]["saldo"]
    # årets (og tidligere års ikke-afsluttede) resultat indgår i egenkapitalen
    drift = sum(-s[nr]["saldo"] for nr in s if konti.get(nr) and konti[nr].er_drift)
    return {"aktiver": aktiver, "passiver": passiver, "egenkapital": egenkapital, "sum_aktiver": sum_a,
            "sum_passiver": sum_p, "sum_egenkapital": sum_e, "resultat": drift,
            "sum_passiver_og_egenkapital": sum_p + sum_e + drift}


def kontokort(session: Session, konto: int, fra: date | None, til: date | None) -> list[dict]:
    q = (select(JournalLine, JournalEntry).join(JournalEntry, JournalLine.postering_id == JournalEntry.id)
         .where(JournalLine.konto == konto).order_by(JournalEntry.dato, JournalEntry.loebenr, JournalLine.id))
    if fra:
        q = q.where(JournalEntry.dato >= fra)
    if til:
        q = q.where(JournalEntry.dato <= til)
    saldo = 0
    if fra:
        tidligere = saldi(session, None, fra - timedelta(days=1)).get(konto)
        saldo = tidligere["saldo"] if tidligere else 0
    out = [{"primo": True, "saldo": saldo}] if fra else []
    for l, e in session.execute(q):
        saldo += l.debet - l.kredit
        out.append({"linje": l, "postering": e, "saldo": saldo})
    return out

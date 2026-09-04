"""Aflæsning af fakturaer og kvitteringer med Claude (vision).

PDF'er sendes direkte som dokument; billeder (også kamerafotos) normaliseres først.
Resultatet er struktureret (JSON-skema), så det kan valideres inden bogføring.
"""
from __future__ import annotations

import json
import re

import anthropic
from pydantic import BaseModel, Field, field_validator

from . import config, files
from .money import til_oere


def _tal(v):
    """Gør '1.234,56', '1234.56', 1234 og None til float/None."""
    if v is None or v == "":
        return None
    if isinstance(v, (int, float)):
        return float(v)
    t = str(v).strip().replace(" ", "").replace("kr.", "").replace("kr", "")
    if "," in t and "." in t:
        t = t.replace(".", "").replace(",", ".") if t.rfind(",") > t.rfind(".") else t.replace(",", "")
    elif "," in t:
        t = t.replace(",", ".")
    try:
        return float(t)
    except ValueError:
        return None


class Linje(BaseModel):
    beskrivelse: str = ""
    beloeb_inkl_moms: float | None = None
    momssats_pct: float | None = None

    @field_validator("beloeb_inkl_moms", "momssats_pct", mode="before")
    @classmethod
    def _v_tal(cls, v):
        return _tal(v)


DOKUMENTTYPER = ("koebsfaktura", "salgsfaktura", "kvittering", "kreditnota", "andet")


class FakturaAflaesning(BaseModel):
    """Modellens svar. Alle felter er valgfri, så en delvis aflæsning stadig kan bruges."""
    dokumenttype: str = "koebsfaktura"
    udsteder_navn: str | None = None
    udsteder_cvr: str | None = None
    udsteder_land: str | None = None
    modtager_navn: str | None = None
    fakturanummer: str | None = None
    dato: str | None = None
    forfaldsdato: str | None = None
    valuta: str = "DKK"
    total_inkl_moms: float | None = None
    momsbeloeb: float | None = None
    total_ekskl_moms: float | None = None
    moms_paa_faktura: bool = False
    omvendt_betalingspligt: bool = False
    betalingsmetode: str = "ukendt"
    er_betalt: bool = False
    beskrivelse: str = ""
    linjer: list[Linje] = Field(default_factory=list)
    foreslaaet_konto: int | None = None
    foreslaaet_momskode: str | None = None
    sikkerhed: str = "middel"
    bemaerkninger: str | None = None

    @field_validator("total_inkl_moms", "momsbeloeb", "total_ekskl_moms", mode="before")
    @classmethod
    def _v_tal(cls, v):
        return _tal(v)

    @field_validator("foreslaaet_konto", mode="before")
    @classmethod
    def _v_konto(cls, v):
        try:
            return int(str(v).strip()) if v not in (None, "") else None
        except ValueError:
            return None

    @field_validator("udsteder_navn", "udsteder_cvr", "udsteder_land", "modtager_navn", "fakturanummer", "dato",
                     "forfaldsdato", "foreslaaet_momskode", "bemaerkninger", mode="before")
    @classmethod
    def _v_str(cls, v):
        return None if v is None else str(v).strip() or None

    @field_validator("dokumenttype", mode="before")
    @classmethod
    def _v_type(cls, v):
        v = str(v or "").strip().lower().replace("ø", "oe").replace("å", "aa").replace("æ", "ae")
        return v if v in DOKUMENTTYPER else "andet"

    @field_validator("sikkerhed", mode="before")
    @classmethod
    def _v_sikkerhed(cls, v):
        v = str(v or "").strip().lower().replace("ø", "oe")
        return v if v in ("hoej", "middel", "lav") else "middel"

    @field_validator("valuta", "beskrivelse", "betalingsmetode", mode="before")
    @classmethod
    def _v_tekst(cls, v):
        return str(v or "").strip()


JSON_FORMAT = """Svar KUN med ét JSON-objekt (ingen forklaring, ingen markdown) med præcis disse felter:
{
  "dokumenttype": "koebsfaktura" | "salgsfaktura" | "kvittering" | "kreditnota" | "andet",
  "udsteder_navn": tekst eller null,
  "udsteder_cvr": CVR-/momsnummer på udstederen, fx "DK12345678", eller null,
  "udsteder_land": ISO-landekode med to bogstaver, fx "DK", eller null,
  "modtager_navn": tekst eller null,
  "fakturanummer": tekst eller null,
  "dato": "YYYY-MM-DD" eller null,
  "forfaldsdato": "YYYY-MM-DD" eller null,
  "valuta": ISO 4217, fx "DKK",
  "total_inkl_moms": tal (det beløb der skal betales) eller null,
  "momsbeloeb": tal, 0 hvis ingen moms, eller null,
  "total_ekskl_moms": tal eller null,
  "moms_paa_faktura": true hvis der er opkrævet dansk moms, ellers false,
  "omvendt_betalingspligt": true ved reverse charge / udenlandsk faktura uden moms, ellers false,
  "betalingsmetode": "kort" | "bankoverfoersel" | "kontant" | "mobilepay" | "ukendt",
  "er_betalt": true hvis dokumentet viser at beløbet allerede er betalt (kvittering, kortbetaling), ellers false,
  "beskrivelse": kort dansk posteringstekst, maks. 80 tegn,
  "linjer": [ { "beskrivelse": tekst, "beloeb_inkl_moms": tal eller null, "momssats_pct": tal eller null } ],
  "foreslaaet_konto": kontonummer fra kontoplanen (tal) eller null,
  "foreslaaet_momskode": momskode fra listen eller null,
  "sikkerhed": "hoej" | "middel" | "lav",
  "bemaerkninger": forbehold (utydelige tal, manglende felter) eller null
}
Købsfaktura/kvittering = virksomheden har købt noget. Salgsfaktura = virksomheden har solgt noget.
Kreditnota = en leverandør krediterer virksomheden."""


SYSTEM = """Du er en dansk bogholder, der aflæser bilag (fakturaer, kvitteringer, kreditnotaer) for en
dansk enkeltmandsvirksomhed. Dokumentet kan være en PDF, en scanning eller et foto taget med en mobiltelefon,
som kan være skævt, uskarpt eller delvist afskåret. Læs alt, hvad du kan, og angiv det, du ikke kan læse, som null.

Regler:
- Beløb angives som tal med punktum som decimaltegn, i dokumentets valuta. Danske beløb bruger typisk komma som
  decimaltegn og punktum som tusindtalsseparator ("1.234,56").
- Datoer skrives som YYYY-MM-DD. Danske datoer er ofte DD.MM.YYYY eller DD-MM-YYYY.
- Hvis virksomheden ({firma}, CVR {cvr}) er UDSTEDER, er det en salgsfaktura. Ellers er det et køb.
- Vælg den konto fra kontoplanen, der passer bedst til købets art, og den momskode der passer:
  dansk faktura med 25 % moms -> K25 (restaurant -> K25R), dansk faktura uden moms (forsikring, gebyr, porto) -> K0,
  ydelse/software/abonnement fra EU-leverandør uden moms -> KEUY, varer fra EU uden moms -> KEUV,
  ydelse fra leverandør uden for EU -> K3Y, varer fra land uden for EU -> K3V.
  Salg med dansk moms -> S25, salg af ydelser til EU-virksomhed uden moms -> SEUY, salg uden for EU -> S3.
- Vær ærlig om usikkerhed i feltet 'sikkerhed' og 'bemaerkninger'.

Kontoplan (nummer: navn):
{kontoplan}

Momskoder (kode: navn):
{momskoder}

{json_format}
"""


def _indholdsblok(indhold: bytes, mime: str) -> dict:
    if files.er_pdf(mime):
        return {"type": "document", "source": {"type": "base64", "media_type": "application/pdf",
                                                "data": files.til_base64(indhold)}}
    data, mime2 = files.normaliser_billede(indhold)
    return {"type": "image", "source": {"type": "base64", "media_type": mime2, "data": files.til_base64(data)}}


def aflaes(indhold: bytes, mime: str, *, firma: str, cvr: str, kontoplan: list[tuple[int, str]],
           momskoder: list[tuple[str, str]], client: anthropic.Anthropic | None = None) -> FakturaAflaesning:
    """Sender bilaget til Claude og returnerer en valideret aflæsning."""
    client = client or anthropic.Anthropic()
    system = SYSTEM.format(
        firma=firma or "virksomheden", cvr=cvr or "ukendt",
        kontoplan="\n".join(f"{nr}: {navn}" for nr, navn in kontoplan),
        momskoder="\n".join(f"{k}: {n}" for k, n in momskoder),
        json_format=JSON_FORMAT,
    )
    response = client.beta.messages.create(
        model=config.CLAUDE_MODEL,
        max_tokens=8000,
        betas=["server-side-fallback-2026-07-01"],
        fallbacks="default",
        output_config={"effort": "medium"},
        system=[{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
        messages=[{"role": "user", "content": [
            _indholdsblok(indhold, mime),
            {"type": "text", "text": "Aflæs dette bilag og svar med JSON-objektet."},
        ]}],
    )
    if response.stop_reason == "refusal":
        raise RuntimeError("Aflæsningen blev afvist af modellen. Indtast oplysningerne manuelt.")
    tekst = "".join(b.text for b in response.content if getattr(b, "type", "") == "text")
    return parse_svar(tekst)


def parse_svar(tekst: str) -> FakturaAflaesning:
    """Finder JSON-objektet i modellens svar og validerer det."""
    t = tekst.strip()
    t = re.sub(r"^```(?:json)?\s*|\s*```$", "", t, flags=re.IGNORECASE | re.MULTILINE).strip()
    if not t.startswith("{"):
        m = re.search(r"\{.*\}", t, flags=re.DOTALL)
        if not m:
            raise RuntimeError("Modellen returnerede ikke et gyldigt svar. Prøv igen eller indtast manuelt.")
        t = m.group(0)
    try:
        data = json.loads(t)
    except json.JSONDecodeError as e:
        raise RuntimeError(f"Modellens svar kunne ikke læses som JSON: {e}") from e
    if not isinstance(data, dict):
        raise RuntimeError("Modellens svar var ikke et JSON-objekt.")
    return FakturaAflaesning.model_validate(data)


def anvend_paa_bilag(v, a: FakturaAflaesning, gyldige_konti: set[int], gyldige_momskoder: set[str]) -> None:
    """Overfører aflæsningen til bilagets redigerbare felter."""
    from datetime import date as _date

    def _dato(s):
        try:
            return _date.fromisoformat(s) if s else None
        except ValueError:
            return None

    v.aflaesning_json = a.model_dump_json()
    v.dokumenttype = a.dokumenttype
    v.modpart = a.modtager_navn if a.dokumenttype == "salgsfaktura" else a.udsteder_navn
    v.modpart_cvr = a.udsteder_cvr
    v.modpart_land = (a.udsteder_land or "").upper()[:2] or None
    v.fakturanr = a.fakturanummer
    v.dato = _dato(a.dato)
    v.forfaldsdato = _dato(a.forfaldsdato)
    v.valuta = (a.valuta or "DKK").upper()[:3]
    v.beloeb_total = til_oere(a.total_inkl_moms) if a.total_inkl_moms is not None else None
    v.beloeb_moms = til_oere(a.momsbeloeb) if a.momsbeloeb is not None else None
    v.beloeb_netto = til_oere(a.total_ekskl_moms) if a.total_ekskl_moms is not None else None
    v.beskrivelse = (a.beskrivelse or "")[:200] or None
    v.konto = a.foreslaaet_konto if a.foreslaaet_konto in gyldige_konti else None
    v.momskode = a.foreslaaet_momskode if a.foreslaaet_momskode in gyldige_momskoder else None
    v.betalt = a.er_betalt
    noter = []
    if a.sikkerhed != "hoej":
        noter.append(f"Sikkerhed: {a.sikkerhed}.")
    if a.bemaerkninger:
        noter.append(a.bemaerkninger)
    if v.valuta != "DKK":
        noter.append(f"Beløb er i {v.valuta} – omregn til DKK inden bogføring (Nationalbankens kurs på fakturadatoen).")
    v.noter = " ".join(noter) or None

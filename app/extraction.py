"""Aflæsning af fakturaer og kvitteringer med Claude (vision).

PDF'er sendes direkte som dokument; billeder (også kamerafotos) normaliseres først.
Resultatet er struktureret (JSON-skema), så det kan valideres inden bogføring.
"""
from __future__ import annotations

import json
from typing import Literal

import anthropic
from pydantic import BaseModel, Field

from . import config, files
from .money import til_oere


class Linje(BaseModel):
    beskrivelse: str
    beloeb_inkl_moms: float | None = Field(None, description="Linjens beløb inkl. moms i fakturaens valuta")
    momssats_pct: float | None = Field(None, description="Momssats i procent, fx 25. 0 hvis ingen moms")


class FakturaAflaesning(BaseModel):
    dokumenttype: Literal["koebsfaktura", "salgsfaktura", "kvittering", "kreditnota", "andet"] = Field(
        description="Købsfaktura/kvittering = virksomheden har købt noget. Salgsfaktura = virksomheden har solgt noget. "
                    "Kreditnota = en leverandør krediterer virksomheden.")
    udsteder_navn: str | None = Field(None, description="Navn på den der har udstedt dokumentet")
    udsteder_cvr: str | None = Field(None, description="CVR-/momsnummer på udstederen, fx 'DK12345678' eller '12345678'")
    udsteder_land: str | None = Field(None, description="Udstederens land som ISO 3166-1 alpha-2, fx DK, DE, US")
    modtager_navn: str | None = Field(None, description="Navn på modtageren/kunden på dokumentet")
    fakturanummer: str | None = None
    dato: str | None = Field(None, description="Faktura-/kvitteringsdato som YYYY-MM-DD")
    forfaldsdato: str | None = Field(None, description="Forfaldsdato som YYYY-MM-DD, hvis angivet")
    valuta: str = Field("DKK", description="ISO 4217, fx DKK, EUR, USD")
    total_inkl_moms: float | None = Field(None, description="Det samlede beløb inkl. moms (det beløb der skal betales)")
    momsbeloeb: float | None = Field(None, description="Det samlede momsbeløb på dokumentet, 0 hvis ingen moms")
    total_ekskl_moms: float | None = None
    moms_paa_faktura: bool = Field(description="True hvis der er opkrævet dansk moms på dokumentet")
    omvendt_betalingspligt: bool = Field(False, description="True hvis dokumentet angiver reverse charge / omvendt betalingspligt eller er en udenlandsk faktura uden moms")
    betalingsmetode: Literal["kort", "bankoverfoersel", "kontant", "mobilepay", "ukendt"] = "ukendt"
    er_betalt: bool = Field(description="True hvis dokumentet viser at beløbet allerede er betalt (kvittering, 'betalt', kortbetaling)")
    beskrivelse: str = Field(description="Kort dansk beskrivelse af købet/salget til posteringsteksten, maks. 80 tegn")
    linjer: list[Linje] = Field(default_factory=list)
    foreslaaet_konto: int | None = Field(None, description="Kontonummer fra kontoplanen der passer bedst")
    foreslaaet_momskode: str | None = Field(None, description="Momskode fra listen der passer bedst")
    sikkerhed: Literal["hoej", "middel", "lav"] = Field(description="Hvor sikker aflæsningen er (lav ved utydeligt foto)")
    bemaerkninger: str | None = Field(None, description="Forbehold, fx utydelige tal, manglende felter, flere valutaer")


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
    )
    response = client.beta.messages.parse(
        model=config.CLAUDE_MODEL,
        max_tokens=8000,
        betas=["server-side-fallback-2026-07-01"],
        fallbacks="default",
        output_config={"effort": "medium"},
        system=[{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
        messages=[{"role": "user", "content": [
            _indholdsblok(indhold, mime),
            {"type": "text", "text": "Aflæs dette bilag og udfyld alle felter."},
        ]}],
        output_format=FakturaAflaesning,
    )
    if response.stop_reason == "refusal":
        raise RuntimeError("Aflæsningen blev afvist af modellen. Indtast oplysningerne manuelt.")
    if response.parsed_output is None:
        raise RuntimeError("Modellen returnerede ikke et gyldigt svar. Prøv igen eller indtast manuelt.")
    return response.parsed_output


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

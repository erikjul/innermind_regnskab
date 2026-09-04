import io

import pytest
from types import SimpleNamespace

from fastapi.testclient import TestClient
from PIL import Image, ImageDraw

from app import extraction, main
from app.models import Voucher


class _FakeCreate:
    """Simulerer client.beta.messages.create og gemmer det request der blev sendt."""
    def __init__(self, svar):
        self.svar = svar
        self.kwargs = None

    def __call__(self, **kwargs):
        self.kwargs = kwargs
        tekst = "```json\n" + self.svar.model_dump_json() + "\n```"
        return SimpleNamespace(stop_reason="end_turn", content=[SimpleNamespace(type="text", text=tekst)])


def _fake_client(svar):
    fp = _FakeCreate(svar)
    return SimpleNamespace(beta=SimpleNamespace(messages=SimpleNamespace(create=fp))), fp


def _foto() -> bytes:
    img = Image.new("RGB", (900, 1200), "white")
    ImageDraw.Draw(img).text((50, 50), "Kvittering  Total 1.250,00 kr", fill="black")
    buf = io.BytesIO()
    img.save(buf, format="JPEG")
    return buf.getvalue()


SVAR = extraction.FakturaAflaesning(
    dokumenttype="kvittering", udsteder_navn="Kontorforsyning A/S", udsteder_cvr="DK12345678", udsteder_land="dk",
    fakturanummer="F-1001", dato="2026-03-04", valuta="dkk", total_inkl_moms=1250.0, momsbeloeb=250.0,
    total_ekskl_moms=1000.0, moms_paa_faktura=True, er_betalt=True, beskrivelse="Papir og toner",
    foreslaaet_konto=3210, foreslaaet_momskode="K25", sikkerhed="middel", bemaerkninger="Datoen er lidt utydelig",
)


def test_aflaes_sender_billede_og_returnerer_struktur():
    client, fp = _fake_client(SVAR)
    a = extraction.aflaes(_foto(), "image/jpeg", firma="InnerMind", cvr="38273337", kontoplan=[(3210, "Kontor")],
                          momskoder=[("K25", "Købsmoms")], client=client)
    assert a.total_inkl_moms == 1250.0
    kw = fp.kwargs
    assert kw["model"] and "output_format" not in kw and "output_config" in kw
    assert "Svar KUN med ét JSON-objekt" in kw["system"][0]["text"]
    blok = kw["messages"][0]["content"][0]
    assert blok["type"] == "image" and blok["source"]["media_type"] == "image/jpeg"
    assert "InnerMind" in kw["system"][0]["text"] and "3210: Kontor" in kw["system"][0]["text"]


def test_aflaes_pdf_sendes_som_dokument():
    client, fp = _fake_client(SVAR)
    extraction.aflaes(b"%PDF-1.4 fake", "application/pdf", firma="", cvr="", kontoplan=[], momskoder=[], client=client)
    blok = fp.kwargs["messages"][0]["content"][0]
    assert blok["type"] == "document" and blok["source"]["media_type"] == "application/pdf"


def test_anvend_paa_bilag():
    v = Voucher(bilagsnr=1, original_filnavn="a.jpg", fil_sti="x", mime="image/jpeg", sha256="0" * 64, stoerrelse=1)
    extraction.anvend_paa_bilag(v, SVAR, {3210}, {"K25"})
    assert v.beloeb_total == 125000 and v.beloeb_moms == 25000 and v.dato.isoformat() == "2026-03-04"
    assert v.konto == 3210 and v.momskode == "K25" and v.modpart == "Kontorforsyning A/S" and v.modpart_land == "DK"
    assert "Sikkerhed: middel" in v.noter and "utydelig" in v.noter
    # ukendt konto/momskode afvises
    extraction.anvend_paa_bilag(v, SVAR, set(), set())
    assert v.konto is None and v.momskode is None


def test_web_flow_med_simuleret_aflaesning(db, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test")
    monkeypatch.setattr(extraction, "aflaes", lambda *a, **k: SVAR)
    with TestClient(main.app) as c:
        r = c.post("/bilag/upload", files=[("filer", ("foto.jpg", _foto(), "image/jpeg"))], data={"kilde": "kamera"}, follow_redirects=False)
        assert r.status_code == 303
        assert c.get("/bilag/1/status").json()["status"] == "klar"  # baggrundsjob er kørt når TestClient svarer
        side = c.get("/bilag/1").text
        assert "Kontorforsyning A/S" in side and "1.250,00" in side and "Forslag til postering" in side
        r = c.post("/bilag/1/gem", data={"dokumenttype": "kvittering", "modpart": "Kontorforsyning A/S", "dato": "2026-03-04",
                                         "beloeb_total": "1.250,00", "beskrivelse": "Papir og toner", "konto": 3210,
                                         "momskode": "K25", "modkonto": 5520, "handling": "bogfoer"}, follow_redirects=False)
        assert "besked" in r.headers["location"]
        moms = c.get("/moms?fra=2026-01-01&til=2026-03-31").text
        assert "250,00" in moms


def test_parse_svar_tolerant():
    a = extraction.parse_svar('Her er svaret:\n{"dokumenttype": "Købsfaktura", "total_inkl_moms": "3.750,00", "dato": "2026-08-18", '
                              '"foreslaaet_konto": "2050", "sikkerhed": "HØJ", "linjer": [{"beskrivelse": "x", "beloeb_inkl_moms": "3.750,00"}]}')
    assert a.dokumenttype == "koebsfaktura" and a.total_inkl_moms == 3750.0 and a.foreslaaet_konto == 2050
    assert a.sikkerhed == "hoej" and a.linjer[0].beloeb_inkl_moms == 3750.0
    b = extraction.parse_svar('{"dokumenttype": "koebsfaktura", "sikkerhed": "hoej", "moms_paa_faktura": true}')
    assert b.dokumenttype == "koebsfaktura" and b.sikkerhed == "hoej" and b.total_inkl_moms is None
    with pytest.raises(RuntimeError):
        extraction.parse_svar("Jeg kan desværre ikke læse billedet.")

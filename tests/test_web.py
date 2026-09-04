import io
import xml.dom.minidom

from fastapi.testclient import TestClient
from PIL import Image

from app import main


def _png() -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (400, 600), "white").save(buf, format="PNG")
    return buf.getvalue()


def test_fuldt_flow_uden_api(client):
    c = client
    if True:
        assert c.get("/").status_code == 200
        r = c.post("/bilag/upload", files=[("filer", ("kvittering.png", _png(), "image/png"))], data={"kilde": "kamera"}, follow_redirects=False)
        assert r.status_code == 303 and r.headers["location"].startswith("/bilag/1")
        side = c.get("/bilag/1")
        assert side.status_code == 200 and "Klar til bogføring" in side.text
        assert c.get("/bilag/1/fil").headers["content-type"] == "image/png"
        assert c.get("/bilag/1/fil?visning=1").headers["content-type"] == "image/jpeg"
        # dublet-advarsel
        r = c.post("/bilag/upload", files=[("filer", ("igen.png", _png(), "image/png"))], follow_redirects=False)
        assert "dublet" in c.get("/bilag/2").text
        # bogfør
        r = c.post("/bilag/1/gem", data={"dokumenttype": "kvittering", "modpart": "Kontorforsyning A/S", "dato": "2026-03-04",
                                         "beloeb_total": "1.250,00", "beskrivelse": "Papir og toner", "konto": 3210,
                                         "momskode": "K25", "modkonto": 5520, "handling": "bogfoer"}, follow_redirects=False)
        assert "besked" in r.headers["location"], r.headers["location"]
        assert "Bogført" in c.get("/bilag/1").text
        # låst bilag kan ikke ændres
        r = c.post("/bilag/1/gem", data={"dokumenttype": "kvittering", "dato": "2026-03-04", "beloeb_total": "1", "konto": 3210,
                                         "momskode": "K25", "modkonto": 5520}, follow_redirects=False)
        assert "fejl" in r.headers["location"]
        for url in ["/posteringer", "/posteringer/1", "/moms", "/moms?fra=2026-01-01&til=2026-03-31", "/rapporter",
                    "/kontoplan", "/kontoplan/3210", "/eksport", "/indstillinger", "/bilag", "/posteringer/ny", "/bilag/upload"]:
            assert c.get(url).status_code == 200, url
        moms = c.get("/moms?fra=2026-01-01&til=2026-03-31").text
        assert "250,00" in moms
        # manuel postering
        r = c.post("/posteringer/ny", data={"dato": "2026-03-05", "tekst": "Bankgebyr", "konto_0": 3270, "debet_0": "25", "konto_1": 5520, "kredit_1": "25"}, follow_redirects=False)
        assert "besked" in r.headers["location"]
        # storno
        r = c.post("/posteringer/1/storno", data={"aarsag": "Forkert konto", "dato": "2026-03-06"}, follow_redirects=False)
        assert "besked" in r.headers["location"]
        # SAF-T er velformet XML
        x = c.get("/eksport/saft?fra=2026-01-01&til=2026-12-31")
        assert x.status_code == 200
        dom = xml.dom.minidom.parseString(x.content)
        assert dom.getElementsByTagName("Transaction").length == 3
        assert c.get("/eksport/posteringer.csv").status_code == 200
        assert c.get("/eksport/backup/download").headers["content-type"] == "application/zip"
        # afregn moms og lås
        r = c.post("/moms/afregn", data={"fra": "2026-01-01", "til": "2026-03-31"}, follow_redirects=False)
        assert "besked" in r.headers["location"]
        assert "Afregnet" in c.get("/moms?fra=2026-01-01&til=2026-03-31").text
        assert "intakt" in c.get("/eksport").text
        assert "erik" in c.get("/posteringer/1").text  # oprettet af


def test_afvist_filtype(client):
    c = client
    if True:
        r = c.post("/bilag/upload", files=[("filer", ("virus.exe", b"xx", "application/octet-stream"))], follow_redirects=False)
        assert "fejl" in r.headers["location"]

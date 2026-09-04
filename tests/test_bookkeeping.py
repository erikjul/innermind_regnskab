from datetime import date

import pytest

from app import bookkeeping as bk, vat
from app.models import JournalEntry, Settings, VatCode, Voucher
from app.money import fra_oere, til_oere


def _bilag(db, nr=1):
    v = Voucher(bilagsnr=nr, original_filnavn="f.pdf", fil_sti="x", mime="application/pdf", sha256="a" * 64, stoerrelse=1, status="klar")
    db.add(v); db.flush()
    return v


def test_til_oere_dansk_format():
    assert til_oere("1.234,56") == 123456
    assert til_oere("1234.56") == 123456
    assert til_oere("12,5") == 1250
    assert til_oere(99.99) == 9999
    assert fra_oere(123456) == "1.234,56"
    assert fra_oere(-50) == "-0,50"


def test_koeb_25_pct_moms(db):
    s = db.get(Settings, 1)
    linjer = vat.koebslinjer(3230, 5520, 125000, db.get(VatCode, "K25"), s, "Software")
    assert {(l["konto"], l["debet"], l["kredit"]) for l in linjer} == {(3230, 100000, 0), (5610, 25000, 0), (5520, 0, 125000)}


def test_restaurant_25_pct_fradrag(db):
    s = db.get(Settings, 1)
    linjer = vat.koebslinjer(3040, 5520, 100000, db.get(VatCode, "K25R"), s)
    moms = 100000 - 80000  # 20.000 øre moms, 25 % fradrag = 5.000
    by_konto = {l["konto"]: l for l in linjer}
    assert by_konto[5610]["debet"] == 5000
    assert by_konto[3040]["debet"] == 80000 + (moms - 5000)
    assert sum(l["debet"] for l in linjer) == sum(l["kredit"] for l in linjer)


def test_omvendt_betalingspligt_eu_ydelse(db):
    s = db.get(Settings, 1)
    linjer = vat.koebslinjer(3235, 5520, 100000, db.get(VatCode, "KEUY"), s)
    by_konto = {l["konto"]: l for l in linjer}
    assert by_konto[3235]["debet"] == 100000 and by_konto[3235]["momsgrundlag"] == 100000
    assert by_konto[6220]["kredit"] == 25000
    assert by_konto[5610]["debet"] == 25000
    assert by_konto[5520]["kredit"] == 100000


def test_salg_og_kreditnota(db):
    s = db.get(Settings, 1)
    linjer = vat.salgslinjer(1010, 5510, 125000, db.get(VatCode, "S25"), s)
    by_konto = {l["konto"]: l for l in linjer}
    assert by_konto[5510]["debet"] == 125000 and by_konto[1010]["kredit"] == 100000 and by_konto[6210]["kredit"] == 25000
    kn = vat.salgslinjer(1010, 5510, -125000, db.get(VatCode, "S25"), s)
    by_konto = {l["konto"]: l for l in kn}
    assert by_konto[5510]["kredit"] == 125000 and by_konto[1010]["debet"] == 100000


def test_postering_skal_balancere(db):
    with pytest.raises(bk.BogfoeringsFejl):
        bk.opret_postering(db, date(2026, 1, 5), "Ubalance", [{"konto": 3230, "debet": 100}, {"konto": 5520, "kredit": 90}])
    with pytest.raises(bk.BogfoeringsFejl):
        bk.opret_postering(db, date(2026, 1, 5), "Ukendt konto", [{"konto": 9999, "debet": 100}, {"konto": 5520, "kredit": 100}])


def test_bogfoer_bilag_storno_og_kaede(db):
    v = _bilag(db)
    e = bk.bogfoer_bilag(db, v, dato=date(2026, 2, 1), konto=3230, momskode="K25", modkonto=5520, total=125000,
                         tekst="Software", dokumenttype="koebsfaktura")
    db.commit()
    assert v.status == "bogfoert" and v.postering_id == e.id and e.loebenr == 1
    with pytest.raises(bk.BogfoeringsFejl):
        bk.bogfoer_bilag(db, v, dato=date(2026, 2, 1), konto=3230, momskode="K25", modkonto=5520, total=125000, tekst="x", dokumenttype="koebsfaktura")
    st = bk.storno(db, e, date(2026, 2, 10), "Forkert konto")
    db.commit()
    assert st.loebenr == 2 and e.storneret_af_id == st.id and st.storno_af_id == e.id
    assert v.status == "klar" and v.postering_id is None
    assert bk.saldi(db, None, None)[3230]["saldo"] == 0
    with pytest.raises(bk.BogfoeringsFejl):
        bk.storno(db, e, date(2026, 2, 10), "igen")
    ok, fejl = bk.verificer_kaede(db)
    assert ok, fejl
    # manipulation opdages
    e.tekst = "Ændret tekst"
    db.commit()
    ok, fejl = bk.verificer_kaede(db)
    assert not ok and "Nr. 1" in fejl[0]


def test_momsopgoerelse_og_afregning(db):
    s = db.get(Settings, 1)
    bk.opret_postering(db, date(2026, 1, 10), "Køb", vat.koebslinjer(3230, 5520, 125000, db.get(VatCode, "K25"), s))
    bk.opret_postering(db, date(2026, 1, 12), "Salg", vat.salgslinjer(1010, 5510, 250000, db.get(VatCode, "S25"), s))
    bk.opret_postering(db, date(2026, 2, 1), "EU-ydelse", vat.koebslinjer(3235, 5520, 100000, db.get(VatCode, "KEUY"), s))
    bk.opret_postering(db, date(2026, 3, 1), "Eksport", vat.salgslinjer(1030, 5510, 50000, db.get(VatCode, "S3"), s))
    bk.opret_postering(db, date(2026, 4, 1), "Uden for perioden", vat.koebslinjer(3230, 5520, 125000, db.get(VatCode, "K25"), s))
    db.commit()
    opg = vat.momsopgoerelse(db, date(2026, 1, 1), date(2026, 3, 31))
    f = opg["felter"]
    assert f["salgsmoms"] == 50000
    assert f["koebsmoms"] == 25000 + 25000
    assert f["moms_ydelseskoeb_udland"] == 25000
    assert f["moms_varekoeb_udland"] == 0
    assert opg["momstilsvar"] == 50000 + 25000 - 50000
    assert opg["rubrikker"]["A_ydelser"] == 100000
    assert opg["rubrikker"]["C"] == 50000
    e = bk.afregn_moms(db, date(2026, 1, 1), date(2026, 3, 31))
    db.commit()
    assert e.type == "momsafregning"
    saldi = bk.saldi(db, None, date(2026, 3, 31))
    assert saldi[6210]["saldo"] == 0 and saldi[5610]["saldo"] == 0 and saldi[6220]["saldo"] == 0
    assert saldi[6230]["saldo"] == -25000  # skyldig moms 250 kr.
    # perioden er låst
    with pytest.raises(bk.BogfoeringsFejl):
        bk.opret_postering(db, date(2026, 2, 15), "For sent", [{"konto": 3230, "debet": 100}, {"konto": 5520, "kredit": 100}])
    with pytest.raises(bk.BogfoeringsFejl):
        bk.afregn_moms(db, date(2026, 1, 1), date(2026, 3, 31))
    # efterfølgende periode indeholder kun april-købet
    opg2 = vat.momsopgoerelse(db, date(2026, 4, 1), date(2026, 6, 30))
    assert opg2["felter"]["koebsmoms"] == 25000 and opg2["momstilsvar"] == -25000


def test_rapporter(db):
    s = db.get(Settings, 1)
    bk.opret_postering(db, date(2026, 1, 10), "Køb", vat.koebslinjer(3230, 5520, 125000, db.get(VatCode, "K25"), s))
    bk.opret_postering(db, date(2026, 1, 12), "Salg", vat.salgslinjer(1010, 5520, 250000, db.get(VatCode, "S25"), s))
    db.commit()
    res = bk.resultatopgoerelse(db, date(2026, 1, 1), date(2026, 12, 31))
    assert res["indtaegter"] == 200000 and res["omkostninger"] == 100000 and res["resultat"] == 100000
    bal = bk.balance(db, date(2026, 12, 31))
    assert bal["sum_aktiver"] == bal["sum_passiver_og_egenkapital"]
    kort = bk.kontokort(db, 5520, date(2026, 1, 11), None)
    assert kort[0]["primo"] and kort[0]["saldo"] == -125000 and kort[-1]["saldo"] == 125000

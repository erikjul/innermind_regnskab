"""Standard kontoplan og momskoder for en dansk enkeltmandsvirksomhed.

Kontoplanen er bygget op efter den gængse danske struktur (1000 omsætning, 2000-4000
omkostninger, 5000 aktiver, 6000 passiver/egenkapital) og kan tilpasses i programmet.
Feltet `standardkonto` bruges til at mappe egne konti til Erhvervsstyrelsens
standardkontoplan, som kræves ved SAF-T-eksport fra digitale bogføringssystemer.
"""

# (kode, navn, retning, sats_promille, fradrag_pct, omvendt_betalingspligt, angivelsesfelt, rubrik)
MOMSKODER = [
    ("K25", "Købsmoms 25 % – fuldt fradrag", "koeb", 250, 100, False, "koebsmoms", None),
    ("K25R", "Købsmoms 25 % – 25 % fradrag (restauration)", "koeb", 250, 25, False, "koebsmoms", None),
    ("K25H", "Købsmoms 25 % – 50 % fradrag (delvis erhvervsmæssig anvendelse)", "koeb", 250, 50, False, "koebsmoms", None),
    ("K0", "Køb uden moms (momsfritaget: forsikring, gebyrer, porto m.m.)", "koeb", 0, 0, False, None, None),
    ("KEUV", "Køb af varer i EU (erhvervelsesmoms 25 %)", "koeb", 250, 100, True, "moms_varekoeb_udland", "A_varer"),
    ("KEUY", "Køb af ydelser i EU – omvendt betalingspligt 25 %", "koeb", 250, 100, True, "moms_ydelseskoeb_udland", "A_ydelser"),
    ("K3V", "Køb af varer uden for EU (importmoms 25 %)", "koeb", 250, 100, True, "moms_varekoeb_udland", None),
    ("K3Y", "Køb af ydelser uden for EU – omvendt betalingspligt 25 %", "koeb", 250, 100, True, "moms_ydelseskoeb_udland", None),
    ("S25", "Salgsmoms 25 %", "salg", 250, 0, False, "salgsmoms", None),
    ("S0", "Salg uden moms (momsfritaget efter momslovens § 13)", "salg", 0, 0, False, None, None),
    ("SEUV", "Salg af varer til EU (uden moms, rubrik B – varer)", "salg", 0, 0, False, None, "B_varer"),
    ("SEUY", "Salg af ydelser til EU (uden moms, rubrik B – ydelser)", "salg", 0, 0, False, None, "B_ydelser"),
    ("S3", "Salg til lande uden for EU (eksport, rubrik C)", "salg", 0, 0, False, None, "C"),
    ("INGEN", "Ingen moms (balanceposteringer, private hævninger m.m.)", "ingen", 0, 0, False, None, None),
]

# (nummer, navn, type, gruppe, standard_momskode)
KONTI = [
    # Omsætning
    (1010, "Salg af varer og ydelser, DK", "indtaegt", "Omsætning", "S25"),
    (1020, "Salg af ydelser til EU", "indtaegt", "Omsætning", "SEUY"),
    (1025, "Salg af varer til EU", "indtaegt", "Omsætning", "SEUV"),
    (1030, "Salg til lande uden for EU", "indtaegt", "Omsætning", "S3"),
    (1050, "Momsfrit salg", "indtaegt", "Omsætning", "S0"),
    (1090, "Andre driftsindtægter", "indtaegt", "Omsætning", "S25"),
    # Vareforbrug / direkte omkostninger
    (2010, "Varekøb, DK", "omkostning", "Vareforbrug", "K25"),
    (2020, "Varekøb, EU", "omkostning", "Vareforbrug", "KEUV"),
    (2030, "Varekøb, uden for EU", "omkostning", "Vareforbrug", "K3V"),
    (2050, "Fremmed arbejde / underleverandører", "omkostning", "Vareforbrug", "K25"),
    (2060, "Fremmed arbejde, udland", "omkostning", "Vareforbrug", "KEUY"),
    # Salgsomkostninger
    (3010, "Annoncer og markedsføring", "omkostning", "Salgsomkostninger", "K25"),
    (3020, "Repræsentation", "omkostning", "Salgsomkostninger", "K25R"),
    (3030, "Rejseomkostninger", "omkostning", "Salgsomkostninger", "K25"),
    (3040, "Restaurationsbesøg", "omkostning", "Salgsomkostninger", "K25R"),
    (3050, "Hotelophold", "omkostning", "Salgsomkostninger", "K25"),
    (3060, "Gaver og blomster", "omkostning", "Salgsomkostninger", "K0"),
    # Lokaleomkostninger
    (3110, "Husleje", "omkostning", "Lokaleomkostninger", "K25"),
    (3120, "El, vand og varme", "omkostning", "Lokaleomkostninger", "K25"),
    (3130, "Vedligeholdelse af lokaler", "omkostning", "Lokaleomkostninger", "K25"),
    (3140, "Rengøring", "omkostning", "Lokaleomkostninger", "K25"),
    # Administration
    (3210, "Kontorartikler og tryksager", "omkostning", "Administration", "K25"),
    (3220, "Telefon og internet", "omkostning", "Administration", "K25"),
    (3230, "Software, IT og abonnementer", "omkostning", "Administration", "K25"),
    (3235, "Software og onlinetjenester købt i udlandet", "omkostning", "Administration", "KEUY"),
    (3240, "Revisor og bogholder", "omkostning", "Administration", "K25"),
    (3245, "Advokat og rådgivning", "omkostning", "Administration", "K25"),
    (3250, "Forsikringer", "omkostning", "Administration", "K0"),
    (3260, "Kontingenter og abonnementer uden moms", "omkostning", "Administration", "K0"),
    (3270, "Gebyrer (bank, betalingskort)", "omkostning", "Administration", "K0"),
    (3280, "Småanskaffelser (under straksafskrivningsgrænsen)", "omkostning", "Administration", "K25"),
    (3290, "Porto og fragt", "omkostning", "Administration", "K25"),
    (3295, "Faglitteratur og kurser", "omkostning", "Administration", "K25"),
    (3299, "Øvrige administrationsomkostninger", "omkostning", "Administration", "K25"),
    # Transport
    (3310, "Brændstof, varebil", "omkostning", "Transport", "K25"),
    (3315, "Biludgifter, personbil (ingen momsfradrag)", "omkostning", "Transport", "K0"),
    (3320, "Kørselsgodtgørelse (statens takster)", "omkostning", "Transport", "INGEN"),
    (3330, "Offentlig transport, taxa og parkering", "omkostning", "Transport", "K0"),
    # Afskrivninger og finansielle poster
    (4010, "Afskrivninger, driftsmidler og inventar", "omkostning", "Afskrivninger", "INGEN"),
    (4110, "Renteindtægter", "indtaegt", "Finansielle poster", "INGEN"),
    (4210, "Renteudgifter", "omkostning", "Finansielle poster", "INGEN"),
    (4220, "Låneomkostninger og rykkergebyrer", "omkostning", "Finansielle poster", "K0"),
    # Aktiver
    (5010, "Driftsmidler og inventar (anskaffelsessum)", "aktiv", "Anlægsaktiver", "K25"),
    (5019, "Akkumulerede afskrivninger, driftsmidler", "aktiv", "Anlægsaktiver", "INGEN"),
    (5510, "Debitorer (tilgodehavender fra salg)", "aktiv", "Omsætningsaktiver", "INGEN"),
    (5520, "Bank, erhvervskonto", "aktiv", "Likvide beholdninger", "INGEN"),
    (5525, "Bank, opsparingskonto", "aktiv", "Likvide beholdninger", "INGEN"),
    (5530, "Kasse", "aktiv", "Likvide beholdninger", "INGEN"),
    (5540, "Betalingstjenester (MobilePay, Stripe, PayPal)", "aktiv", "Likvide beholdninger", "INGEN"),
    (5610, "Købsmoms (indgående moms)", "aktiv", "Moms", "INGEN"),
    (5620, "Forudbetalte omkostninger", "aktiv", "Omsætningsaktiver", "INGEN"),
    # Passiver og egenkapital
    (6010, "Egenkapital primo", "egenkapital", "Egenkapital", "INGEN"),
    (6020, "Private hævninger", "egenkapital", "Egenkapital", "INGEN"),
    (6030, "Private indskud / udlæg betalt privat", "egenkapital", "Egenkapital", "INGEN"),
    (6110, "Kreditorer (leverandørgæld)", "passiv", "Kortfristet gæld", "INGEN"),
    (6210, "Salgsmoms (udgående moms)", "passiv", "Moms", "INGEN"),
    (6220, "Moms af køb i udlandet (erhvervelses-/importmoms)", "passiv", "Moms", "INGEN"),
    (6230, "Momsafregning (skyldig/tilgodehavende moms)", "passiv", "Moms", "INGEN"),
    (6310, "Anden gæld", "passiv", "Kortfristet gæld", "INGEN"),
    (6320, "Skyldig B-skat / AM-bidrag", "passiv", "Kortfristet gæld", "INGEN"),
    (6410, "Banklån", "passiv", "Langfristet gæld", "INGEN"),
]


def seed(session, Account, VatCode, Settings):
    """Opretter standardkontoplan, momskoder og indstillinger hvis databasen er tom."""
    if session.query(VatCode).count() == 0:
        for kode, navn, retning, sats, fradrag, omvendt, felt, rubrik in MOMSKODER:
            session.add(VatCode(kode=kode, navn=navn, retning=retning, sats_promille=sats,
                                fradrag_pct=fradrag, omvendt_betalingspligt=omvendt,
                                angivelsesfelt=felt, rubrik=rubrik))
    if session.query(Account).count() == 0:
        for nr, navn, type_, gruppe, moms in KONTI:
            session.add(Account(nummer=nr, navn=navn, type=type_, gruppe=gruppe, standard_momskode=moms))
    if session.get(Settings, 1) is None:
        session.add(Settings(id=1, firmanavn="InnerMind", cvr="38273337", adresse="Avlsgårdsvej 50",
                             postnr="7080", by="Børkop"))
    session.commit()

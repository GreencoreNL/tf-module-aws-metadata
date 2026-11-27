from datetime import date
from pathlib import Path

from fraudcheck.models import Attachment, format_plate, normalize_plate
from fraudcheck.parse_form import parse_form_text
from fraudcheck.parse_melding import find_plates, parse_melding_html
from fraudcheck.report import render_html
from fraudcheck.rules import RuleContext, nl_feestdagen
from fraudcheck.scoring import assess
from fraudcheck.sources.context import PolicyInfo, PolicyLookup
from fraudcheck.sources.history import ClaimRecord, FraudRecord, HistoryIndex, bdx_rows_to_records

TPL = (Path(__file__).parent / "fixtures" / "melding_template.html").read_text()


def melding(**kw):
    d = dict(verzekerde="Jansen Transport B.V.", kenteken="AB-123-C", gemeld="25-11-2026 om 15:53",
             schadedatum="20-11-2026", wat="Aanrijding met een ander voertuig",
             tegenpartij="Ja en we hebben een ingevuld schadeformulier",
             toedracht="Ik stond stil voor het rode verkeerslicht op de Stationsweg en de tegenpartij reed achterop.",
             email="test@jansen.nl", telefoon="+31612345678", extra="")
    d.update(kw)
    return parse_melding_html(TPL.format(**d), folder_id="f1", folder_name="case")


class FakeRDW:
    def __init__(self, recs):
        self.recs = recs

    def lookup(self, plate):
        return self.recs.get(normalize_plate(plate))


def codes(a):
    return {s.code for s in a.signals}


def test_kenteken_normaliseren():
    assert normalize_plate("z-383-hl") == "Z383HL"
    assert format_plate("Z383HL") == "Z-383-HL"
    assert format_plate("HHG56K") == "HHG-56-K"
    assert find_plates("tegenpartij 12-ABC-3 reed op mij") == ["12ABC3"]


def test_parse_melding():
    c = melding()
    assert c.kenteken == "AB-123-C"
    assert c.schadedatum == date(2026, 11, 20)
    assert c.gemeld_op.hour == 15
    assert c.melder_email == "test@jansen.nl"


def test_parse_drive_escaped_export():
    raw = TPL.format(verzekerde="X Y", kenteken="AB-123-C", gemeld="25-11-2026 om 15:53", schadedatum="20-11-2026",
                     wat="w", tegenpartij="Nee", toedracht="t", email="e@x.nl", telefoon="1", extra="")
    escaped = raw.replace("<", "\\<").replace(">", "\\>")
    assert parse_melding_html(escaped).kenteken == "AB-123-C"


def test_schadedatum_na_melding_is_rode_vlag():
    c = melding(schadedatum="26-11-2026", gemeld="25-11-2026 om 17:04")
    a = assess(c, RuleContext(today=date(2026, 11, 26)))
    assert "T01_schadedatum_na_melding" in codes(a)
    assert a.niveau in ("Verhoogd", "Hoog")


def test_summiere_toedracht_en_geen_fotos():
    c = melding(toedracht="Kop staart")
    a = assess(c, RuleContext(today=date(2026, 11, 26)))
    assert {"D01_toedracht_te_kort", "D04_kop_staart_zonder_details", "A01_geen_fotos", "A02_geen_formulier_bij_tegenpartij"} <= codes(a)


def test_late_melding():
    c = melding(schadedatum="01-10-2026")
    a = assess(c, RuleContext())
    assert "T03_late_melding_30" in codes(a)


def test_nachtelijk_tijdstip():
    c = melding()
    c.schadetijd = "02:30"
    assert "T02_nachtelijk_tijdstip" in codes(assess(c, RuleContext()))


def test_kenteken_eerder_als_schade_en_tegenpartij():
    h = HistoryIndex()
    h.add_claims([
        ClaimRecord(bron="BDX", referentie="A1", kenteken="AB123C", schadedatum=date(2025, 3, 1)),
        ClaimRecord(bron="BDX", referentie="A2", kenteken="AB123C", schadedatum=date(2026, 1, 5)),
        ClaimRecord(bron="BDX", referentie="A3", kenteken="ZZ999Z", tegenpartij_kenteken="AB123C", schadedatum=date(2026, 6, 1)),
    ], "test")
    a = assess(melding(), RuleContext(history=h))
    assert {"H01_kenteken_eerder_schade_2plus", "H02_kenteken_als_tegenpartij"} <= codes(a)


def test_zelfde_partijen_eerder_en_fraude_register():
    c = melding(toedracht="Tegenpartij 12-ABC-3 reed achterop terwijl ik stilstond bij de rotonde in Zwolle.")
    h = HistoryIndex()
    h.add_claims([ClaimRecord(bron="BDX", referentie="A9", kenteken="AB123C", tegenpartij_kenteken="12ABC3", schadedatum=date(2025, 5, 1))], "t")
    h.add_fraud([FraudRecord(bron="Fraud NL 2025", referentie="F1", kenteken="12ABC3", categorie="Staged accident")], "t")
    a = assess(c, RuleContext(history=h))
    assert {"H07_zelfde_partijen_eerder", "H04_fraude_register", "H03_tegenpartij_vaker_betrokken"} <= codes(a)
    assert a.niveau == "Hoog"


def test_polis_kort_na_ingang_en_voertuig_niet_op_polis():
    pol = PolicyLookup({"AB123C": PolicyInfo(polisnummer="P1", polis_ingang=date(2026, 11, 1), voertuig_toegevoegd=date(2026, 11, 22))})
    a = assess(melding(), RuleContext(policies=pol))
    assert {"T04_kort_na_polisingang_30", "T06_na_einde_dekking"} <= codes(a)


def test_rdw_signalen():
    rdw = FakeRDW({"AB123C": {"wam_verzekerd": "Nee", "export_indicator": "Ja", "_datum_tenaamstelling": date(2026, 10, 30),
                              "tellerstandoordeel": "Onlogisch", "catalogusprijs": "30000"}})
    a = assess(melding(), RuleContext(rdw=rdw))
    assert {"V02_geen_wam_rdw", "V04_export", "T07_recent_tenaamgesteld", "V03_tellerstand_onlogisch"} <= codes(a)


def test_rdw_onbekend_kenteken():
    a = assess(melding(), RuleContext(rdw=FakeRDW({})))
    assert "V01_kenteken_onbekend_rdw" in codes(a)


def test_foto_ouder_dan_schade():
    from datetime import datetime
    c = melding()
    c.attachments.append(Attachment(name="foto.jpg", mime_type="image/jpeg", exif_datetime=datetime(2026, 6, 1, 10, 0)))
    assert "A03_foto_ouder_dan_schade" in codes(assess(c, RuleContext()))


def test_formulier_datum_wijkt_af():
    c = melding()
    c.attachments.append(Attachment(name="Schadeformulier.pdf", mime_type="application/pdf"))
    c.form_fields["Schadeformulier.pdf"] = parse_form_text("Geboortedatum 30-11-1971\nDatum, 02-11-2026\nKm stand 95.200")
    assert c.form_fields["Schadeformulier.pdf"]["km_stand"] == 95200
    assert "T09_datum_formulier_wijkt_af" in codes(assess(c, RuleContext()))


def test_formulier_ocr_datum_aan_elkaar():
    f = parse_form_text("Datum, 12-112026")
    assert "2026-11-12" in f["datums"]


def test_schone_case_is_laag():
    c = melding(schadedatum="24-11-2026")
    c.attachments += [Attachment(name="foto.jpg", mime_type="image/jpeg"),
                      Attachment(name="Schadeformulier aanrijdingsformulier.pdf", mime_type="application/pdf")]
    c.tegenpartij_kenteken = "12ABC3"
    a = assess(c, RuleContext(history=HistoryIndex()))
    assert a.niveau == "Laag", [s.code for s in a.signals]


def test_feestdagen():
    f = nl_feestdagen(2026)
    assert f[date(2026, 4, 5)] == "Eerste Paasdag"
    assert f[date(2026, 4, 27)] == "Koningsdag"


def test_bdx_mapping_negeert_lege_datum():
    rows = [{"System Number Claim Reference": "R1", "Vehicle Registration Index": "P-220-SJ", "TP Vehicle Reg": "Not on event level",
             "Incident Date": "29/08/2022", "Policy Inception date time": "31/12/1899", "Fraud Flag": "N", "Total Claim Cost": "4556,27"}]
    r = bdx_rows_to_records(rows)[0]
    assert r.kenteken == "P220SJ" and r.tegenpartij_kenteken == "" and r.polis_ingang is None
    assert r.kosten == 4556.27


def test_rapport_rendert():
    a = assess(melding(schadedatum="26-11-2026"), RuleContext())
    html = render_html(a)
    assert "Fraude-indicatie" in html and "#002E5D" in html and "rode vlag" in html


def test_late_melding_week():
    assert "T03_late_melding_7" in codes(assess(melding(schadedatum="12-11-2026"), RuleContext()))


def test_dekkingsbestand():
    from fraudcheck.sources.context import CoverageInfo, CoverageLookup
    niet = assess(melding(), RuleContext(coverage=CoverageLookup({"AB123C": CoverageInfo()})))
    assert "V07_niet_in_dekkingsbestand" in codes(niet)
    niet_gezocht = assess(melding(), RuleContext(coverage=CoverageLookup({})))
    assert "V07_niet_in_dekkingsbestand" not in codes(niet_gezocht)
    na = assess(melding(), RuleContext(coverage=CoverageLookup({"AB123C": CoverageInfo(na_schade=True, eerst_gezien=date(2026, 11, 23))})))
    assert "V08_pas_na_schade_in_dekkingsbestand" in codes(na) and na.niveau != "Laag"
    ok = assess(melding(), RuleContext(coverage=CoverageLookup({"AB123C": CoverageInfo(voor_schade=True, eerst_gezien=date(2026, 7, 2))})))
    assert not {"V07_niet_in_dekkingsbestand", "V08_pas_na_schade_in_dekkingsbestand", "V09_kort_voor_schade_in_dekkingsbestand"} & codes(ok)


def test_bekend_uit_bdx_telt_als_gedekt():
    from fraudcheck.sources.context import CoverageLookup
    h = HistoryIndex()
    h.add_claims([ClaimRecord(bron="BDX", referentie="A1", kenteken="AB123C", schadedatum=date(2024, 1, 1))], "t")
    from fraudcheck.sources.context import CoverageInfo
    assert "V07_niet_in_dekkingsbestand" not in codes(assess(melding(), RuleContext(history=h, coverage=CoverageLookup({"AB123C": CoverageInfo()}))))


def test_gewone_aanrijding_met_kleine_gaten_is_laag():
    """Zoals Z-383-HL: verzekerd, formulier en foto aanwezig, alleen tegenpartij kenteken onbekend en een week later gemeld."""
    from fraudcheck.sources.context import CoverageInfo, CoverageLookup
    c = melding(schadedatum="12-11-2026", toedracht="tegenpartij reed tegen mij aan terwijl ik stilstond")
    c.attachments += [Attachment(name="foto.jpg", mime_type="image/jpeg"), Attachment(name="Schadeformulier.pdf", mime_type="application/pdf")]
    a = assess(c, RuleContext(history=HistoryIndex(), coverage=CoverageLookup({"AB123C": CoverageInfo(voor_schade=True)})))
    assert a.niveau == "Laag", [(s.code, s.gewicht) for s in a.signals]


def test_mail_alleen_inhoud_klopt():
    from fraudcheck.report import render_email
    m = render_email(assess(melding(schadedatum="26-11-2026"), RuleContext()))
    assert m["subject"].startswith("Fraude-indicatie")
    assert "{RAPPORT_URL}" in m["html"] and "{MAP_URL}" in m["text"]


def test_eigen_efnol_melding_bewijst_geen_dekking():
    from fraudcheck.sources.context import CoverageLookup
    h = HistoryIndex()
    h.add_claims([ClaimRecord(bron="eFNOL", referentie="case", kenteken="AB123C", folder_id="f1")], "eFNOL")
    from fraudcheck.sources.context import CoverageInfo
    assert "V07_niet_in_dekkingsbestand" in codes(assess(melding(), RuleContext(history=h, coverage=CoverageLookup({"AB123C": CoverageInfo()}))))


def test_dossier_prioriteit_en_render():
    from fraudcheck.dossier import DOSSIER_VOORBEELD, bepaal_prioriteit, render_dossier_html
    import copy
    d = copy.deepcopy(DOSSIER_VOORBEELD)
    assert bepaal_prioriteit(d)[0] == "Normaal"
    d["formulier"]["gewonden_aangekruist"] = True
    assert bepaal_prioriteit(d)[0] == "Spoed"
    d["beoordeling"]["letsel_partij"] = "eigen bestuurder"
    assert bepaal_prioriteit(d)[0] == "Hoog"
    d["beoordeling"]["letsel_partij"] = ""
    d["formulier"]["gewonden_aangekruist"] = False
    d["beoordeling"]["rijdbaar"] = False
    assert bepaal_prioriteit(d)[0] == "Hoog"
    html = render_dossier_html(d)
    assert "Dossieranalyse" in html and "Reservering" in html


def test_dossier_zonder_formulier_zegt_niets_over_vak3():
    from fraudcheck.dossier import DOSSIER_VOORBEELD, render_dossier_html
    import copy
    d = copy.deepcopy(DOSSIER_VOORBEELD)
    d["formulier"] = {"aanwezig": False}
    html = render_dossier_html(d)
    assert "Nee aangekruist" not in html and "geen formulier" in html


def test_intake_maakt_melding_die_de_parser_leest(tmp_path):
    from datetime import datetime
    from fraudcheck.intake import write_case
    from fraudcheck.cli import _load_local_case
    m = {"verzekerde": "MO-EV Holding", "kenteken": "FTD-12-Z", "schadedatum": "11-10-2026", "tijdstip": "18:40",
         "wat_gebeurd": "Aanrijding met een ander voertuig", "tegenpartij": "Ja", "kenteken_tegenpartij": "06-ZD-PZ",
         "toedracht": "Bezorger stak over en werd linksachter geraakt", "melder_naam": "T. Peeters", "melder_bedrijf": "Remo",
         "ontvangen": datetime(2026, 11, 2, 16, 21), "onderwerp": "Schademelding FTD-12-Z aanrijding", "message_id": "abc"}
    pdf = tmp_path / "x.pdf"; pdf.write_bytes(b"%PDF")
    folder = write_case(tmp_path / "cases", m, "tekst", "a@b.nl", "claims@loxxo.nl", {"Bilal.pdf": pdf})
    c = _load_local_case(folder)
    assert c.plate == "FTD12Z" and c.tegenpartij_kenteken == "06ZDPZ" and c.schadetijd == "18:40"
    assert c.gemeld_op == datetime(2026, 11, 2, 16, 21)
    assert [a.name for a in c.attachments] == ["Bilal.pdf"]   # de mailkopie telt niet als bijlage


def test_signalen_uit_stukken_tellen_mee_met_vast_gewicht():
    c = melding()
    c.extra_signalen = [{"code": "S01_rol_tegenstrijdig_met_pv", "titel": "Passagier staat als bestuurder in pv", "toelichting": "x", "gewicht": 1},
                        {"code": "ONBEKEND", "titel": "genegeerd"}]
    a = assess(c, RuleContext())
    s = [x for x in a.signals if x.code == "S01_rol_tegenstrijdig_met_pv"][0]
    assert s.gewicht == 40 and s.hard and "ONBEKEND" not in codes(a)


def test_wam_status_na_eigenaarswissel_telt_niet():
    rdw = FakeRDW({"AB123C": {"wam_verzekerd": "Nee", "_datum_tenaamstelling": date(2026, 11, 22)}})
    assert "V02_geen_wam_rdw" not in codes(assess(melding(), RuleContext(rdw=rdw)))


def test_melding_zonder_tabel_wordt_ook_gelezen():
    html_ = ("<html><body><p>Hierbij een nieuwe schademelding voor Kern Taxi met kenteken HHG45Z. De melding is op 25-11-2026 om 15:38 "
             "bij Loxxo binnengekomen.</p><h3>Schade</h3><p>Verzekerde: Kern Taxi<br>Kenteken: HHG45Z<br>Schadedatum: 25-11-2026<br>"
             "Wat is er gebeurd: Eenzijdig<br>Plaats: Overtoom Amsterdam<br>Letsel: Nee<br>Toedracht: Van de weg geraakt</p></body></html>")
    c = parse_melding_html(html_)
    assert c.plate == "HHG45Z" and c.schadedatum == date(2026, 11, 25) and c.plaats == "Overtoom Amsterdam" and c.letsel == "Nee"
    assert c.gemeld_op.hour == 15


def test_geen_dekkingsbestand_op_schadedatum_geeft_geen_signaal():
    from fraudcheck.sources.context import CoverageInfo, CoverageLookup
    cov = CoverageLookup({"AB123C": CoverageInfo(na_schade=True, geen_bestand_voor_schade=True)})
    a = assess(melding(schadedatum="29-04-2026"), RuleContext(coverage=cov))
    assert not {"V07_niet_in_dekkingsbestand", "V08_pas_na_schade_in_dekkingsbestand"} & codes(a)


def test_claim_derde_kort_na_expertise_is_niet_laat_en_expertise_telt_als_fotos():
    c = melding(schadedatum="08-09-2026", wat="Aanrijding met een ander voertuig, aansprakelijkstelling door Allianz")
    c.attachments.append(Attachment(name="200ASMI8.PDF", mime_type="application/pdf", text="Expertiserapport ... foto's"))
    a = assess(c, RuleContext())
    assert not {"T03_late_melding_30", "T03_late_melding_14", "A01_geen_fotos"} & codes(a)
    c2 = melding(schadedatum="29-04-2026", wat="Aanrijding, claim van een derde")
    assert "T03_late_melding_30" in codes(assess(c2, RuleContext()))

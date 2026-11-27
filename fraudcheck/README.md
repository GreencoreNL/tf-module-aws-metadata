# Loxxo fraudecheck schademeldingen

Beoordeelt elke schade die via de eFNOL in de Loxxo Fleet Portal binnenkomt en zet een rapport
`Fraude-indicatie <datum> <kenteken> <niveau>` als Google Doc in de casemap
(`0.3.6.30 Schademeldingen documenten / <datum> <kenteken> <verzekerde>`).

## Wat het rapport geeft

* Niveau **Laag**, **Verhoogd** (vanaf 25) of **Hoog** (vanaf 50) met een score van 0 tot 100
* Elk signaal met toelichting en gewicht. Een rode vlag maakt een case altijd minimaal Verhoogd
* Concrete vervolgacties voor de schadebehandelaar
* Welke controles zijn uitgevoerd en welke niet (zodat 'geen signaal' nooit 'niet gecontroleerd' betekent)

## Bronnen

| Bron | Wat we toetsen |
|---|---|
| Melding (eFNOL, PDF of oude HTML) | schadedatum, melddatum, toedracht, tegenpartij, melder |
| Bijlagen | foto's aanwezig, opnamedatum foto (EXIF), schadeformulier via OCR (datum, km stand, kentekens) |
| BDX Van Ameyde (sheet Project BDX 2.0) | kenteken eerder schade, kenteken als tegenpartij, dezelfde partijen eerder, fraudevlag |
| Eerdere eFNOL cases | zelfde kenteken, telefoon of e-mail bij andere verzekerden |
| Fraude registers 2023 t/m 2025 | match op kenteken, tegenpartij, telefoon, e-mail |
| RDW open data | kenteken bestaat, WAM, recente tenaamstelling, export, tellerstand, APK |
| Dekkingsbestanden (mail van claims@ aan Carglass en ANWB) | stond het voertuig op schadedatum in de dekking, of pas erna |
| LoxxoTech Admin (export) | schade kort na polisingang, voertuig kort ervoor toegevoegd, schade buiten dekking |

Gewichten staan in `fraudcheck/rules.py` (`WEIGHTS`) en zijn zonder codewijziging aan te passen.

## Draaien

```bash
pip install -r requirements.txt

# Productie: alle nieuwe cases in Drive beoordelen
export GOOGLE_APPLICATION_CREDENTIALS=/pad/naar/service-account.json
python -m fraudcheck drive --policies polissen.json        # --dry-run om eerst te kijken

# Lokaal testen op mappen op schijf
python -m fraudcheck local "cases/2026-11-25 Z-383-HL ..." --bdx bdx.csv --fraud "Fraud NL 2025.xlsx" --coverage dekking.json

python -m pytest -q
```

Cases met al een `Fraude-indicatie` bestand worden overgeslagen. Met `--force` worden ze opnieuw beoordeeld.

## Inrichting

1. Service account in Google Cloud met Drive API en Sheets API aan. Voeg het toe als Inhoudsbeheerder aan de gedeelde drive met de claims mappen.
2. Draai `python -m fraudcheck drive` elk kwartier (cron, Cloud Run job of GitHub Actions schedule).
3. Polisdata: exporteer per kenteken polisnummer, ingang, einde en datum toevoegen voertuig uit LoxxoTech Admin naar `polissen.json`:
   `{"Z383HL": {"polisnummer": "...", "polis_ingang": "2026-01-01", "voertuig_toegevoegd": "2026-03-01"}}`

## Privacy

De tool verwerkt persoonsgegevens van verzekerden en tegenpartijen. Rapporten blijven in de casemap op de
gedeelde drive en worden nergens anders opgeslagen. De CIS database wordt niet geraadpleegd.
Een indicatie is geen besluit. Behandelaar en fraudecoördinator beslissen.

## Dekkingsbestand

`dekking.json` geeft per kenteken aan of het in een dekkingsbestand stond:
`{"Z383HL": {"voor_schade": true, "na_schade": true, "eerst_gezien": "2026-07-02"}}`.
Een kenteken dat ontbreekt is nergens gevonden. De geplande run vult dit door in Gmail van claims@ te zoeken op
`subject:Dekkingsbestand` met het kenteken, voor en na de schadedatum.

Zoho CRM wordt niet gebruikt. Daar staan vooral nieuwe deals en geen volledig klantenbestand, dus 'niet gevonden' zegt niets.

## Dossieranalyse

Naast de fraude-indicatie kan per case een `Dossieranalyse` worden gemaakt: samenvatting, aansprakelijkheid,
voorrang, letsel (vak 3 op het aanrijdingsformulier), zwaarte, prioriteit, reservering, aandachtspunten en
volgende stappen voor de behandelaar.

Claude leest de melding, het aanrijdingsformulier (ook de kruisjes en de schets) en de foto's en schrijft een
JSON volgens `DOSSIER_VOORBEELD` in `fraudcheck/dossier.py`. De tool bepaalt zelf de prioriteit
(Spoed bij letsel, Hoog bij niet rijdbaar, zware schade of oranje of rode fraude-indicatie) en maakt het rapport:

```bash
python -m fraudcheck dossier analyse.json --out rapporten
```

## Meldingen uit de claims@ mailbox

`python -m fraudcheck intake mail.json --out cases` maakt van een schademelding per mail een casemap met
dezelfde opbouw als de eFNOL. In de map komen alleen PDF's en de bijlagen, geen HTML:

* `Melding <mapnaam>.pdf` in het eFNOL formaat (tabellen Schade, Melder en Bron)
* `Mail <melddatum> <afzender> <kenmerk> <kenteken>.pdf`, een kopie van de originele mail met Van, Aan, Cc,
  datum en tijd, onderwerp, de namen van de bijlagen en de volledige tekst. Gemaakt uit de HTML body van de
  Gmail mail, zodat opmaak en tabellen blijven staan. Bijvoorbeeld `Mail 2026-11-26 Allianz 672CC2044DN FN-R7-7D.pdf`.
* alle bijlagen zoals ze zijn meegestuurd

De map heet `<melddatum> <kenteken> <verzekerde>`, bijvoorbeeld `2026-11-27 HSK-17-R NextGen Mobility`.
De melddatum is de dag dat de melding bij Loxxo binnenkwam in Amsterdamse tijd, nooit de schadedatum.
Bij een mail die via info@ is doorgestuurd telt de datum van de originele mail (`ontvangen_origineel`).
Een testmelding (melder met een loxxo.nl adres of TEST in verzekerde of referentie) krijgt `TEST ` vooraan.
Voor een testmap maakt `local` nooit een alertmail klaar.

Invoer `mail.json`:

```json
{"melding": {"verzekerde": "...", "kenteken": "FNR77D", "schadedatum": "08-09-2026", "toedracht": "...",
             "melder_naam": "...", "melder_bedrijf": "Allianz", "melder_email": "...", "referentie": "...",
             "kenmerk": "672CC2044DN", "ontvangen": "2026-11-26T10:12:00+01:00", "onderwerp": "...", "message_id": "..."},
 "mail": {"van": "...", "aan": "claims@loxxo.nl", "cc": "...", "datum": "2026-11-26T10:12:00+01:00",
          "onderwerp": "...", "html_bestand": "body.html", "tekst": "alleen als er geen HTML body is"},
 "afzender_naam": "Allianz",
 "bijlagen": {"200ASMI8.PDF": "pad/naar/bestand"}}
```

PDF's worden gemaakt met headless Chrome (`CHROME_BIN`, standaard de Chromium van Playwright). Externe
afbeeldingen in de mail worden niet geladen. De fraudecheck leest zowel `Melding ... .pdf` (nieuw, ook van het
Typeform script) als `Melding ... .html` (oude mappen). Staan ze er allebei dan wint de PDF.
Daarna werken `local` (fraude-indicatie) en `dossier` (dossieranalyse) precies zoals bij de eFNOL.

Wat telt als nieuwe melding: de eerste mail over een schade van een verzekerde, tussenpersoon of tegenpartij
(aansprakelijkstelling). Niet: meldingen via Typeform (die lopen al via de eFNOL), post van Van Ameyde, Wakam,
Carglass en ANWB, dekkingsbestanden en vervolgmails op een schade die al een casemap heeft.
De Gmail bericht ID staat in de melding, zodat een mail nooit twee keer wordt verwerkt.

## Signalen uit de stukken

Sommige rode vlaggen staan alleen in brieven of een proces-verbaal, bijvoorbeeld een claimant die zegt passagier
te zijn maar bij de politie als bestuurder staat. Zet die in `signalen.json` in de casemap:
`[{"code": "S01_rol_tegenstrijdig_met_pv", "titel": "...", "toelichting": "..."}]`.
Alleen codes uit `WEIGHTS` (S01 tot en met S07) tellen mee en het gewicht komt altijd uit de tool.

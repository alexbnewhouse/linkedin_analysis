# Industry-labeling prompt (direct batch labeling by a coding agent)

> Hand this whole file to a coding agent together with one batch file of company
> evidence. The agent reads the batch, assigns each company **one** taxonomy code,
> and writes the result back in the standard `Proposal` JSONL format the pipeline
> already consumes (`industry/llm.py`, `Proposal` dataclass). This is the
> **propose-only** layer (INDUSTRY_PLAN §3.9): every label is a review-queue
> candidate, never autonomous ground truth. Do not invent codes, do not skip rows,
> do not change the output schema.

---

## Your task

You are an expert business analyst. You are given a batch of **companies** (one
JSON object per line). For each one, assign the single best-matching node from the
fixed 4-level industry taxonomy below, and emit one output JSON object per input
company. You classify **what the organization does**, inferred from its name and
from the roles/descriptions of the people who work there.

You label **companies, not people** — the titles and descriptions are evidence
about the employer, not about any one individual.

## Labeling rules (follow exactly)

1. **Pick one `code` from the taxonomy.** It must be a code that appears verbatim
   in the TAXONOMY block below (e.g. `FIN.BNK.COM.RET`, `TEC.SOF`, `HLT`). Never
   emit a label, a NAICS number, or a code not in the list.
2. **Assign the DEEPEST node the evidence clearly supports — and no deeper.**
   Every node at every depth is a legal answer. If you are confident the company
   is Finance but cannot tell *which kind* of finance, return `FIN`, not a guessed
   `FIN.BNK.COM.RET`. Prefer a correct shallow code over a guessed deep one.
3. **Conglomerates → `XDV`.** Use `XDV` only for genuinely diversified firms with
   no single primary industry (e.g. a Berkshire/Samsung-type group). A company
   that merely has several products in one sector is **not** `XDV`.
4. **Too little signal → `XOT`.** If the evidence is too thin to place even an L1
   (bare "Consultant"/"Owner"/"Self-employed" with no other clue, pure buzzwords,
   or an empty name), return `XOT` at `low` confidence rather than guessing.
5. **`confidence` reflects evidence strength, not your eloquence.** Use:
   - `high` — the name and/or descriptions name the industry unambiguously
     (e.g. "First National **Bank**", "St. Mary's **Hospital**").
   - `medium` — the industry is clear but the *depth* or exact node is inferred.
   - `low` — weak/indirect signal; you are guessing at L1.
6. **`rationale` is one short sentence citing the actual evidence used**
   (the name token, a title, or a description phrase). No restating the rules.
7. **Multilingual input is in scope** — classify non-English names/descriptions
   the same way.
8. **One output object per input object, in the same order. Never drop or merge
   rows.** If a row is unclassifiable, still emit it as `XOT`.

### Disambiguation guidance for known-hard cases
- **Staffing / temp / PEO agencies** → classify as the *agency's* industry
  (`PRO.HRST`), not the client's worksite industry.
- **Holding companies** with one clear operating business → that business; if truly
  mixed → `XDV`.
- **Universities that run hospitals** → `EDU.HED` (the employer is the university)
  unless the evidence is overwhelmingly clinical.
- **Government vs. government contractor** → an actual gov body → `PUB.GOV...`; a
  private firm selling to government → its own commercial industry (e.g. a defense
  contractor → `PUB.DEF.DCON`).
- **"Owner @ Smith Plumbing"** → `RE.CNST.TRADE`; **"Owner @ Smith Capital"** →
  `FIN`. Read the name's head noun, not just the title.

---

## Input format

The batch is a `.jsonl` file (one company per line). Each object has these fields
(some may be missing or empty — classify on what is present):

```json
{
  "key": "id:12345",                       // OPAQUE id — copy verbatim to output
  "display": "First National Bank of Omaha",
  "company_id": "12345",                   // may be null for name-only tail
  "freq": 1843,                            // # of experience rows at this company
  "n_persons": 1602,
  "modal_occ": "Teller",                   // most common SOC occupation, if coded
  "titles": ["Teller", "Branch Manager", "Loan Officer"],   // up to ~8
  "descriptions": ["Community bank serving ...", "..."]      // up to ~3, may be []
}
```

- **`key` is the join key.** Copy it to the output unchanged. Do not parse,
  normalize, or "fix" it.
- `display` is the raw company name as scraped (may be messy/abbreviated).
- Use `titles` + `descriptions` to disambiguate when the name alone is ambiguous
  (e.g. `display: "Atlas"` + titles `["Drilling Engineer", "Roughneck"]` → energy).

---

## Output format (the standard `Proposal` JSONL — match it exactly)

Write **one JSON object per line** (JSONL, UTF-8, `ensure_ascii=False`) to the
output file, in the **same order** as the input, one per input row. Each object
has **exactly** these four fields and no others:

```json
{"key": "id:12345", "code": "FIN.BNK.COM.RET", "confidence": "high", "rationale": "Name says 'National Bank' and top titles are Teller/Loan Officer."}
```

| field        | type   | constraint                                                        |
|--------------|--------|-------------------------------------------------------------------|
| `key`        | string | copied verbatim from the input row's `key`                        |
| `code`       | string | one code from the TAXONOMY block, exact case                      |
| `confidence` | string | one of `high` \| `medium` \| `low`                                 |
| `rationale`  | string | one short sentence citing the evidence                            |

Do not add `model`, `input_hash`, comments, a wrapping array, markdown fences, or
trailing prose — the pipeline reads the file line-by-line with `json.loads` and
fills `model`/`input_hash` itself. Output the JSONL file and nothing else.

### Self-check before you finish
- [ ] Output line count == input line count (no dropped/extra rows).
- [ ] Every `code` is present verbatim in the TAXONOMY block.
- [ ] Every `key` matches an input `key` exactly.
- [ ] Every object has exactly the four fields; every line is valid JSON.
- [ ] No code guessed deeper than the evidence supports.

---

## TAXONOMY (code = label [NAICS hint]) — 162 nodes, the ONLY legal `code` values

Indentation shows depth (L1 → L4). Any code here, at any depth, is a valid answer.

```
TEC = Technology  [NAICS 51,5415]
  TEC.SOF = Software & IT Services  [NAICS 5112,5415,5182]
    TEC.SOF.APP = Application Software  [NAICS 513210]
      TEC.SOF.APP.SAAS = SaaS / B2B Software
      TEC.SOF.APP.CONS = Consumer Software & Apps
      TEC.SOF.APP.MOBL = Mobile / Gaming Software
    TEC.SOF.INFR = Infrastructure & Systems Software  [NAICS 513210]
      TEC.SOF.INFR.CLOU = Cloud & Hosting
      TEC.SOF.INFR.SEC = Cybersecurity
      TEC.SOF.INFR.DATA = Data & Analytics Platforms
    TEC.SOF.ITSV = IT Services & Consulting  [NAICS 5415]
      TEC.SOF.ITSV.INTG = Systems Integration & IT Consulting
      TEC.SOF.ITSV.MSP = Managed Services & IT Outsourcing
    TEC.SOF.INTC = Internet & Digital Platforms  [NAICS 5182,519]
      TEC.SOF.INTC.SRCH = Search, Social & Marketplaces
      TEC.SOF.INTC.ECOM = E-commerce Platforms
  TEC.HRDW = Hardware & Electronics  [NAICS 334]
    TEC.HRDW.SEMI = Semiconductors  [NAICS 3344]
    TEC.HRDW.COMP = Computers & Peripherals  [NAICS 3341]
    TEC.HRDW.COMM = Communications & Networking Equipment  [NAICS 3342]
    TEC.HRDW.EDEV = Electronic Devices & Components  [NAICS 3343,3346]
  TEC.TELE = Telecommunications  [NAICS 517]
    TEC.TELE.WIRE = Wireless & Wireline Carriers  [NAICS 5172,5171]
    TEC.TELE.TINF = Telecom Infrastructure
FIN = Finance  [NAICS 52]
  FIN.BNK = Banking  [NAICS 522]
    FIN.BNK.COM = Commercial Banking  [NAICS 52211]
      FIN.BNK.COM.RET = Retail / Consumer Banking
      FIN.BNK.COM.CORP = Corporate / Business Banking
    FIN.BNK.INV = Investment Banking & Capital Markets  [NAICS 523]
      FIN.BNK.INV.MNA = M&A / Advisory
      FIN.BNK.INV.TRAD = Trading & Brokerage
    FIN.BNK.CU = Credit Unions & Thrifts  [NAICS 52213]
  FIN.ASM = Asset & Investment Management  [NAICS 5239]
    FIN.ASM.AM = Asset Management & Mutual Funds
    FIN.ASM.PE = Private Equity & Venture Capital
    FIN.ASM.HF = Hedge Funds
    FIN.ASM.WM = Wealth Management & Advisory
  FIN.INS = Insurance  [NAICS 524]
    FIN.INS.PNC = Property & Casualty Insurance  [NAICS 524126]
    FIN.INS.LIFE = Life & Health Insurance  [NAICS 524113]
    FIN.INS.BROK = Insurance Brokerage & Agencies  [NAICS 52421]
  FIN.FINT = Fintech & Payments  [NAICS 522320]
    FIN.FINT.PAY = Payments & Processing
    FIN.FINT.LEND = Digital Lending & Credit
    FIN.FINT.CRYP = Crypto & Digital Assets
HLT = Healthcare  [NAICS 62,3254,3391]
  HLT.PROV = Healthcare Providers & Services  [NAICS 62]
    HLT.PROV.HOSP = Hospitals & Health Systems  [NAICS 622]
    HLT.PROV.AMB = Ambulatory & Physician Practices  [NAICS 621]
    HLT.PROV.DENT = Dental & Vision  [NAICS 6212]
    HLT.PROV.LTC = Long-term & Residential Care  [NAICS 623]
    HLT.PROV.MHSA = Mental Health & Social Assistance  [NAICS 6242,623220]
  HLT.PHRM = Pharmaceuticals & Biotech  [NAICS 3254,5417]
    HLT.PHRM.PHARMA = Pharmaceuticals  [NAICS 325412]
    HLT.PHRM.BIO = Biotechnology  [NAICS 541714]
  HLT.MDEV = Medical Devices & Equipment  [NAICS 3391]
  HLT.HTECH = Health Tech & Digital Health  [NAICS 62]
  HLT.PAYR = Health Insurance & Managed Care  [NAICS 524114]
EDU = Education  [NAICS 61]
  EDU.K12 = K-12 Schools  [NAICS 6111]
  EDU.HED = Higher Education  [NAICS 6113]
    EDU.HED.UNIV = Universities & Colleges
    EDU.HED.CC = Community & Technical Colleges
  EDU.EDTECH = EdTech & Online Learning  [NAICS 611710]
  EDU.TRNG = Training, Tutoring & Vocational  [NAICS 6114,6116]
PUB = Public Sector  [NAICS 92]
  PUB.GOV = Government Administration  [NAICS 921]
    PUB.GOV.FED = Federal Government
    PUB.GOV.SLOC = State & Local Government
    PUB.GOV.INTL = International / Multilateral Bodies
  PUB.DEF = Defense & Military  [NAICS 928110]
    PUB.DEF.AF = Armed Forces
    PUB.DEF.DCON = Defense Contractors
  PUB.JUST = Justice, Public Safety & Law Enforcement  [NAICS 922]
  PUB.PADM = Public Programs & Agencies  [NAICS 923,924,925,926]
MFG = Manufacturing & Industrials  [NAICS 31,32,33,333]
  MFG.IND = Industrial & Machinery  [NAICS 333]
    MFG.IND.MACH = Industrial Machinery & Equipment
    MFG.IND.ELEC = Electrical Equipment  [NAICS 335]
  MFG.AUTO = Automotive & Vehicles  [NAICS 3361,3362,3363]
    MFG.AUTO.OEM = Vehicle Manufacturing
    MFG.AUTO.PARTS = Auto Parts & Suppliers
  MFG.AERO = Aerospace  [NAICS 3364]
  MFG.CHEM = Chemicals & Materials  [NAICS 325,327,331]
    MFG.CHEM.SPCH = Specialty & Industrial Chemicals
    MFG.CHEM.MATL = Materials, Metals & Plastics
  MFG.CONP = Consumer & Durable Goods Manufacturing  [NAICS 337,339]
CON = Consumer & Retail  [NAICS 44,45,31]
  CON.RET = Retail  [NAICS 44,45]
    CON.RET.GEN = General Merchandise & Department Stores  [NAICS 452]
    CON.RET.GROC = Grocery & Food Retail  [NAICS 445]
    CON.RET.SPEC = Specialty & Apparel Retail  [NAICS 448,451]
    CON.RET.ETAIL = E-commerce & Direct-to-Consumer  [NAICS 4541]
  CON.CPG = Consumer Packaged Goods  [NAICS 311,312,3256]
    CON.CPG.FNB = Food & Beverage  [NAICS 311,312]
    CON.CPG.HPC = Household & Personal Care  [NAICS 3256]
    CON.CPG.APPL = Apparel, Footwear & Luxury  [NAICS 315,316]
  CON.WHL = Wholesale & Distribution  [NAICS 42]
ENR = Energy & Utilities  [NAICS 21,22,486]
  ENR.OILG = Oil & Gas  [NAICS 211,213,486]
    ENR.OILG.UPST = Exploration & Production (Upstream)
    ENR.OILG.MIDS = Midstream & Pipelines
    ENR.OILG.DOWN = Refining & Marketing (Downstream)
  ENR.UTIL = Utilities  [NAICS 221]
    ENR.UTIL.POWR = Electric Power & Generation  [NAICS 2211]
    ENR.UTIL.WGAS = Water & Gas Utilities  [NAICS 2212,2213]
  ENR.RENW = Renewables & Clean Energy  [NAICS 221114,221115]
  ENR.MINE = Mining & Metals Extraction  [NAICS 212]
MED = Media & Entertainment  [NAICS 51,71,512]
  MED.PUBL = Publishing & News  [NAICS 511,519]
  MED.BCAST = Broadcasting & Streaming  [NAICS 515,516,5121]
  MED.FILM = Film, Music & Production  [NAICS 5121,5122,7111]
  MED.GAME = Gaming & Interactive Entertainment  [NAICS 713]
  MED.ADV = Advertising, Marketing & PR  [NAICS 5418]
    MED.ADV.AGY = Advertising & Creative Agencies
    MED.ADV.MKTG = Marketing, PR & Market Research  [NAICS 5419]
  MED.SPRT = Sports & Recreation  [NAICS 711211,713940]
PRO = Professional Services  [NAICS 54,55,56]
  PRO.CONSL = Management & Strategy Consulting  [NAICS 541611]
  PRO.LEGAL = Legal Services  [NAICS 5411]
  PRO.ACCT = Accounting, Audit & Tax  [NAICS 5412]
  PRO.ENGS = Engineering & Architecture Services  [NAICS 5413]
  PRO.HRST = Staffing, Recruiting & HR Services  [NAICS 5613,5614]
  PRO.BPO = Business Process & Support Services  [NAICS 561]
  PRO.DSGN = Design & Creative Services  [NAICS 5414]
RE = Real Estate & Construction  [NAICS 53,23,236]
  RE.REST = Real Estate  [NAICS 531]
    RE.REST.CRE = Commercial Real Estate & REITs  [NAICS 5311,525]
    RE.REST.RES = Residential Real Estate & Brokerage  [NAICS 5312]
    RE.REST.PM = Property Management  [NAICS 5313]
  RE.CNST = Construction  [NAICS 23]
    RE.CNST.BLDG = Building Construction  [NAICS 236]
    RE.CNST.INFC = Heavy & Civil Engineering Construction  [NAICS 237]
    RE.CNST.TRADE = Specialty Trade Contractors  [NAICS 238]
  RE.ARCH = Architecture & Building Design  [NAICS 5413]
TRN = Transportation & Logistics  [NAICS 48,49]
  TRN.LOG = Logistics, Freight & Supply Chain  [NAICS 488,492,493]
  TRN.TRUCK = Trucking & Ground Freight  [NAICS 484]
  TRN.AIR = Airlines & Aviation  [NAICS 481]
  TRN.MAR = Maritime & Shipping  [NAICS 483]
  TRN.RAIL = Rail Transportation  [NAICS 482]
  TRN.PSNG = Passenger & Ride Transportation  [NAICS 485,4853]
HOS = Hospitality, Travel & Food Services  [NAICS 72,71]
  HOS.FOOD = Restaurants & Food Service  [NAICS 722]
  HOS.LODG = Hotels & Lodging  [NAICS 721]
  HOS.TRVL = Travel, Tourism & Leisure  [NAICS 5615,7211]
  HOS.EVNT = Events, Catering & Venues  [NAICS 7223,7139]
AGR = Agriculture & Natural Resources  [NAICS 11]
  AGR.FARM = Farming & Crop Production  [NAICS 111]
  AGR.LIVE = Livestock & Animal Production  [NAICS 112]
  AGR.FOR = Forestry, Fishing & Hunting  [NAICS 113,114]
  AGR.AGSV = Agricultural Services & Support  [NAICS 115]
NPO = Nonprofit & Social Sector  [NAICS 813,8132,8133]
  NPO.PHIL = Foundations & Philanthropy  [NAICS 813211]
  NPO.SOCS = Social Services & Community  [NAICS 624]
  NPO.ADVO = Advocacy, Civic & Membership Orgs  [NAICS 8133,8139]
  NPO.RELG = Religious Organizations  [NAICS 8131]
  NPO.INTD = International Development & Humanitarian
  NPO.RSCH = Research Institutes & Think Tanks  [NAICS 5417]
XDV = Diversified / Conglomerate
XOT = Other / Unknown
```

---

## Worked examples

Input:
```json
{"key": "id:887", "display": "Cedar Sinai Medical Center", "titles": ["Registered Nurse", "Physician", "Medical Assistant"], "descriptions": ["Nonprofit academic health system in Los Angeles."]}
{"key": "name:joes plumbing & heating", "display": "Joe's Plumbing & Heating", "titles": ["Owner", "Plumber"], "descriptions": []}
{"key": "id:5521", "display": "Apex Talent Partners", "titles": ["Recruiter", "Account Executive"], "descriptions": ["We place engineering and finance professionals at Fortune 500 clients."]}
{"key": "id:99", "display": "Independent Consultant", "titles": ["Consultant"], "descriptions": []}
```

Output:
```json
{"key": "id:887", "code": "HLT.PROV.HOSP", "confidence": "high", "rationale": "'Medical Center' + a health system description and clinical titles (RN, Physician)."}
{"key": "name:joes plumbing & heating", "code": "RE.CNST.TRADE", "confidence": "high", "rationale": "Name and 'Plumber' title indicate a specialty-trade contractor."}
{"key": "id:5521", "code": "PRO.HRST", "confidence": "high", "rationale": "'Recruiter' titles and a description about placing professionals = a staffing agency, not the client industry."}
{"key": "id:99", "code": "XOT", "confidence": "low", "rationale": "Only a bare 'Consultant' title and no name or description — too thin to place even an L1."}
```

# Career tools survey

**Date:** 2026-09-08. **For:** NHA milestone "Assess feasibility and develop plan for
interactive career path exploration" (memo due Sep 30). This is the first task in that
chain; the next is the format sketch (Sep 9).

**Scope.** Tools a student, advisor, or institution actually uses to look up careers.
`docs/plans/archive/PORTAL_INSPIRATION.md` (July) already covers narrative and
scrollytelling precedents and is not repeated here.

## Bottom line

Twenty-two tools looked at. They sort into four families, and none of them does what the
site in `FOUNDATION.md` Part 3 is built to do.

- Occupation-first government tools (BLS, O*NET, CareerOneStop) describe jobs well and
  never connect them to what people studied.
- Major-first outcome tools (BLS Field of Degree, Hamilton Project, NY Fed, Georgetown,
  Humanities Indicators, PSEO, the UK and NZ tools) show where people with a major ended
  up as one cross-sectional snapshot, and nearly all of them lead with earnings.
- Profile-data tools (LinkedIn, Lightcast, Steppingblocks, Emsi) are the closest kin to
  our data. They can show sequences, but they are sold to one institution at a time, sit
  behind login, and are not built to make a field-level argument.
- Editorial and story tools (What Can I Do With This Major, Roadtrip Nation) are what
  career centers hand students. They contain no outcome data.

The gap is specific. No public tool shows, for a named field of study and across
institutions, how the same people moved from first job to year five to year ten at
occupation grain, with the empty cells explained. The memo can say that plainly.

## What each tool does

### A. Occupation-first, government

| Tool | You give it | It shows | Data | Note |
|---|---|---|---|---|
| BLS Career Exploration Tool | One of 16 interest categories | 5 or 6 job titles each, linking to Occupational Outlook Handbook profiles | OOH | K-12 audience. A menu, not a tool |
| O*NET My Next Move | Keyword, industry, or a short RIASEC interest quiz | 900+ career pages: tasks, skills, wages, outlook | O*NET 31.0, BLS 2025 wages, 2024-34 projections | The reference implementation of the quiz FOUNDATION rules out |
| CareerOneStop Interest Assessment | 30 questions | Matched careers | O*NET | Same family |

### B. Major-first outcome snapshots

| Tool | You give it | It shows | Data | Note |
|---|---|---|---|---|
| BLS Field of Degree pages | One of 39 degree fields | Employment count, median wage, share with advanced degree, share part-time, occupation-group shares, top occupations | ACS plus BLS projections | English: 1.94M employed, 21% education and library, 17% management, top single occupation is elementary teacher at 6%. Unflashy and clear |
| Putting Your Major to Work (Hamilton Project, 2017) | A major | Most common occupations, earnings per occupation by gender, employment status, grad-degree share | ACS | Lead claim is dispersion: "students from the same major transition into a surprising variety of occupations" |
| Career Earnings by College Major (Hamilton, 2020) | Up to four majors | Annual and lifetime earnings curves; toggles for full-time and grad degrees | ACS | Earnings only |
| Census major-to-occupation flow (2014, via Pew) | Hover a major | Lines to occupation groups, thickness is share | 2012 ACS | Start of the Sankey lineage. Ben Schmidt's jobs chart is the same idea with click-to-isolate |
| Humanities Indicators (AAAS) | Browse | Occupation distribution of humanities BAs and PhDs; state profiles | 2021 ACS | 61% in management and professional occupations, about 14% in "applied humanities" work. The numbers ours will be compared against |
| Labor Market for Recent College Graduates (NY Fed) | A table | Per major: unemployment, underemployment, early and mid-career wages at 25th and 75th percentiles, grad-degree share | ACS, O*NET | 73 majors, updated each February. Opportunity Data's Grad Labor Explorer re-plots it as a scatter with switchable axes and bubbles sized by graduate volume |
| The Major Payoff (Georgetown CEW) | Tabs | Earnings, popularity, grad degrees, unemployment, race and gender, per major | ACS | 152 majors prime-age, 142 early-career |
| PSEO Explorer (Census LEHD) | Institution, degree level, cohort, program | Earnings at 1, 5, 10 years (25th, 50th, 75th); flows to industry and state | Transcripts matched to LEHD job records | The only public linked-admin tool with three time points. Institution-scoped, partner states only, no occupation |
| College Major to Career Connector (Minnesota DEED) | A major, or a career (two tabs) | Majors-to-occupations lookup in both directions; sister tool shows industry and hourly pay 3 years out for 405 majors | SLEDS wage records | Site blocks automated fetch; described from DEED's own pages |
| Discover Uni (UK) | A course | Share employed or in further study, job types, earnings at 1, 3, 5 years, by region | Graduate Outcomes survey plus tax records | Best plain-language caveats in the set |
| NZ Graduate Outcomes | A field or an occupation | Up to 20 occupations per qualification, top 10 qualifications per occupation, earnings in age bands | 2018 census via IDI, ages 30 to 39 | Single-cohort snapshot, no time axis |

### C. Profile-data tools (same data class as ours)

| Tool | You give it | It shows | Data | Note |
|---|---|---|---|---|
| LinkedIn Career Explorer (beta Nov 2020) | Current title and city | Roles you could move to, ranked by a 0-100 skill similarity; shared and missing skills; open jobs | Member job-history changes, last 5 years | Role-to-role, no major anchor. Page dated 2024, status unclear |
| LinkedIn Alumni tool ("See alumni") | Any school page | Six facets as bar charts that filter each other: where they live, where they work, what they do, what they studied, skills, connection | Live profiles | What every student will compare our site to. Individual profiles are one click away |
| Steppingblocks | Institution license; students take a 20-question assessment | Aggregate Graduate Outcomes dashboard; Graduate Explorer drills to individual alumni rows, downloadable | Profile data, "150M+ career paths" | Same data class, opposite privacy stance |
| Lightcast Alumni Pathways | Institution records matched via National Student Clearinghouse | Occupations (SOC), employers, geography, industry, salary estimates, skills, further education, a Sankey; embeddable widgets | "600M+ professional profiles" | Closest commercial analog. Institution-scoped and paid |
| Degrees at Work (Emsi, 2019) | A report, not a tool | First three jobs of graduates in six broad majors | 125M profiles | Languages and philosophy: first jobs education 17%, journalism and writing 10%, then wide dispersion. Original page is gone |
| Handshake role pages | Browse career categories | Entry salary, geography, related roles, "majors most commonly associated", "people in this role" | Platform data | Reversed lookup done well |

### D. Editorial, story, and transition-graph tools

| Tool | You give it | It shows | Data | Note |
|---|---|---|---|---|
| What Can I Do With This Major (UT Knoxville, subscription) | One of 106 majors | Career areas, employer types, strategies, links | Editorial | The incumbent in career centers. No numbers |
| Roadtrip Nation Roadmap | Tap interest icons | Matched careers and 13,500+ video stories | Interviews | Stories attached to careers, told by real named people, which our rules forbid |
| Mapping Career Causeways (Nesta, UK) | An occupation | Map of 1,600+ jobs by skill and task similarity; transition recommendations; automation risk | Skills taxonomies; code open on GitHub | Research-grade transition graph |
| Tahatū Path Finder (NZ) | A career | "The different ways into a career"; 800+ careers, 4,000+ courses | Tertiary Education Commission | Replaced careers.govt.nz in 2025-26 (the old site redirects with a decommission tag). Organizes around routes in, which is Screen 3's question |

## What works

Five things worth taking, each with an owner.

1. **One page per field, same skeleton every time** (BLS Field of Degree). Count
   employed, shares by occupation group, top occupations, data source in the header. The
   humblest tool in the set and the easiest to trust. Screens 1 and 3 should read this
   plainly.
2. **Lead with dispersion** (Hamilton 2017). The headline is that most graduates are not
   in their major's most common occupation. That is our "plurality is a minority" line,
   made by a Brookings product since 2017. We can cite it rather than defend it.
3. **Facets that filter each other** (LinkedIn Alumni). Students already know this
   grammar: click a bar, everything else narrows. The Portal sub-tabs should behave the
   same way at aggregate grain.
4. **Time steps, not one snapshot** (PSEO). Years 1, 5, 10 as the spine of every chart.
   PSEO is the only public tool that does this, and only for earnings and industry. We do
   it for occupation.
5. **Caveats in sentences, next to the number** (Discover Uni). "Only make decisions based
   on large differences in outcomes." "Does not include people who are self-employed."
   This is the register FOUNDATION 3.3 asks for, and a national site already does it.

Two smaller patterns: reversed lookup (occupation to majors) appears in Minnesota, NZ, and
Handshake and is what Screen 5 does; Tahatū and Handshake both organize around ways in,
which is the panel Screen 3 leads with.

## What is missing

1. **Sequence.** Every major-first tool is a cross-section of ages 25 to 64 or a single
   cohort. The only sequences (Emsi 2019, Lightcast, Steppingblocks) are a PDF or a paid
   institutional dashboard. No public tool shows the same people at years 1, 5, and 10
   by occupation.
2. **Cross-institution, field-scoped.** PSEO, Lightcast, Steppingblocks, and the LinkedIn
   Alumni tool are each scoped to one school. The humanities argument is about the field.
3. **A non-earnings headline.** Hamilton, NY Fed, Georgetown, Scorecard, LEO, PSEO, and
   Minnesota all lead with pay. Humanities Indicators concedes the gap and pivots to
   satisfaction. FOUNDATION rules wages out. That differentiates only if something equally
   concrete replaces the number, which is why ways in (entry roles, entry employers,
   credentials) has to be real and dense.
4. **Honest empty states.** Suppressed cells are silently absent in PSEO and LEO. None of
   the tools explains a blank. Ours must (FOUNDATION 3.3) and would be the first to.
5. **Major-anchored transitions.** LinkedIn Career Explorer and Nesta are role-to-role
   graphs. "This major, this first role, these later roles" does not exist in public.
6. **The quiz problem.** Every student-facing tool opens with an interest assessment that
   returns a result (O*NET, CareerOneStop, MyMajors, Steppingblocks, Roadtrip Nation).
   FOUNDATION rules out a single-answer quiz. Screen 2's doors are the alternative and
   need to feel as inviting as a quiz without assigning anything.

## For the format sketch (Sep 9)

- **Positioning line for the memo:** the first public, cross-institution,
  field-of-study-scoped career trajectory explorer, built on the same data class as
  Lightcast and Steppingblocks and published aggregate-only.
- **Static is enough.** Every government tool here is a server-rendered page with light
  interactivity; BLS Field of Degree pages are HTML tables. The 1.03 MB single-page build
  already exceeds most of them. The real choice is static site with inlined JSON versus
  static site with a small read API, not a Shiny app.
- **Do not compete on quizzes or earnings.** Compete on sequence, ways in, and empty
  states.
- **Expect comparison with the LinkedIn Alumni tool.** The design has to show why
  aggregate-only is better for a student, not only safer.

## Sources and verification

Fetched directly on 2026-09-08:

- BLS Career Exploration Tool: https://www.bls.gov/k12/students/careers/career-exploration.htm
- BLS Field of Degree index and English page: https://www.bls.gov/ooh/field-of-degree/home.htm and https://www.bls.gov/ooh/field-of-degree/english/english-field-of-degree.htm (last modified 2025-08-28)
- O*NET My Next Move, about: https://www.mynextmove.org/help/about/
- Hamilton Project, Putting Your Major to Work (2017-05-11): https://www.hamiltonproject.org/data/putting-your-major-to-work-career-paths-after-college/
- Hamilton Project, Career Earnings by College Major (2020-10-08): https://www.hamiltonproject.org/data/career-earnings-by-college-major/
- Pew on the Census 2012 ACS flow chart (2014-07-11): https://www.pewresearch.org/short-reads/2014/07/11/chart-of-the-week-where-engineering-and-english-majors-end-up-working/
- Humanities Indicators, occupations of terminal BAs: https://www.amacad.org/humanities-indicators/workforce/occupations-humanities-majors-terminal-bachelors-degree
- NY Fed, Labor Market for Recent College Graduates: https://www.newyorkfed.org/research/college-labor-market
- Opportunity Data, Grad Labor Explorer: https://opportunitydata.org/grad-labor-explorer.html
- Georgetown CEW, The Major Payoff: https://cew.georgetown.edu/cew-reports/major-payoff/
- PSEO Explorer press release (2019-11-12): https://www.census.gov/newsroom/press-releases/2019/pseo-explorer.html and CTData's walkthrough: https://www.ctdata.org/blog/learn-about-the-census-bureaus-post-secondary-employment-outcomes-data
- Discover Uni, employment and earnings: https://discoveruni.gov.uk/how-do-i-choose-course/employment-prospects/
- NZ Graduate Outcomes: https://nzgraduateoutcomes.ac.nz/ and Tahatū: https://tahatu.govt.nz/
- LinkedIn Career Explorer: https://linkedin.github.io/career-explorer/ and launch coverage (2020-11-04): https://www.searchenginejournal.com/linkedin-career-explorer/386708/
- LinkedIn Alumni tool, as documented by Santa Clara University: https://www.scu.edu/careercenter/toolkit/networking/alumnitool/
- Steppingblocks: https://help.steppingblocks.com/en/articles/8708807-graduate-outcomes-vs-graduate-explorer and https://www.steppingblocks.com/digital-career-counselor
- Lightcast Alumni Pathways: https://lightcast.io/products/software/alumni-pathways
- Emsi Degrees at Work, via Inside Higher Ed (2019-08-02): https://www.insidehighered.com/news/2019/08/02/new-data-track-graduates-six-popular-majors-through-their-first-three-jobs
- Handshake, explore career paths: https://joinhandshake.com/blog/students/explore-career-paths-for-college-students-on-handshake/
- What Can I Do With This Major, about: https://whatcanidowiththismajor.com/about/
- Roadtrip Nation: https://roadtripnation.com/
- Nesta, Mapping Career Causeways user guide: https://www.nesta.org.uk/toolkit/mapping-career-causeways-user-guide/

Secondhand only: Minnesota DEED (mn.gov blocks automated fetch; described from DEED's own
search snippets at https://mn.gov/deed/data/data-tools/college-career-connector/ and the
College Major to Industry Employment PDF); Ben Schmidt's jobs chart
(https://benschmidt.org/jobs/, TLS certificate expired on 2026-09-08; from the July archive
note); CareerOneStop and MyMajors (search snippets). Not resolved: a Data USA major profile
(the slugs tried returned 404; Data USA appears in the July list as an occupation page).

"""Rule-based classifier for free-text LinkedIn job titles (ported verbatim from the sibling
clean-room build, 2026-09-15; see career_clean/families/taxonomy.py for the contract).

Public API
----------
    classify_title(s) -> {'family': <FAMILIES code>, 'seniority': <SENIORITY level>,
                          'flags': [str, ...], 'confidence': 'high'|'low'}

Design
------
1. ``normalize()`` lowercases, kills punctuation, expands abbreviations
   (sr. -> senior, vp -> vice president, mgr -> manager, hr -> human resources,
   it -> information technology, ...), pulls modifier parentheticals such as
   "(part-time)" out into flags, and reduces "X at Y" / "X @ Y" to "X".
2. ``_EXACT`` is a hand-curated map for whole normalized strings.  It is the only
   place where bare generics ("manager", "associate", "analyst") get a family, and
   they are always returned with confidence 'low'.
3. ``_RULES`` is an ORDERED list of (family, confidence, phrases, regex).  Earlier
   rules win, so the table is written specific-first; ordering is what implements
   the "last noun head" preference ("marketing manager" -> marketing because the
   marketing rules sit above the generic manager rules, "sales engineer" -> sales
   because that exact phrase sits above the engineering block).
   Phrase tests are plain space-padded substring containment over the normalized
   token string, so they are word-boundary safe and run at C speed.
4. A token -> rule-index inverted list ("trigger index") means a title only ever
   tests the handful of rules that share a token with it.  ~3.4M strings classify
   in a couple of minutes single threaded.
5. Seniority is computed separately from head nouns.  Management head nouns are
   scored first; juniority tokens (assistant / associate / junior / coordinator)
   only apply when nothing more senior was found, which is what makes
   "assistant manager" -> manager, "associate director" -> director,
   "assistant vice president" -> vp work while "assistant buyer" stays entry.
   Explicit guards keep title-nouns from being read as seniority
   ("assistant professor" -> mid, "executive assistant" -> mid,
   "associate attorney" -> mid, "staff accountant" -> mid).
"""
from __future__ import annotations

import re

from career_clean.families.taxonomy import FAMILIES, SENIORITY

__all__ = ['classify_title', 'normalize', 'SENIORITY_RANK']

SENIORITY_RANK = {lvl: i for i, lvl in enumerate(SENIORITY)}

# ---------------------------------------------------------------------------
# normalisation
# ---------------------------------------------------------------------------

_POSSESSIVE = re.compile(r"[’']s\b")
_PAREN = re.compile(r"[\(\[\{]([^\)\]\}]*)[\)\]\}]")
_NONALNUM = re.compile(r"[^a-z0-9]+")
_ROMAN = re.compile(r"^(i{1,3}|iv|v|vi{0,3}|ix|x)$")

# parenthetical content that is a pure modifier -> dropped into flags
_MODIFIER_WORDS = {
    'part time', 'parttime', 'p t', 'full time', 'fulltime', 'temporary', 'temp',
    'contract', 'contractor', 'contract to hire', 'seasonal', 'volunteer', 'unpaid',
    'remote', 'interim', 'acting', 'former', 'retired', 'promoted', 'internship',
    'intern', 'co op', 'coop', 'per diem', 'prn', 'casual', 'freelance', 'paid',
    'summer', 'temporary position', 'maternity leave', 'leave of absence', 'on call',
    'consultant basis', 'self employed', 'independent', 'current', 'present',
    'contract position', 'contract role', 'temp to hire', 'pt', 'ft', 'w2', '1099',
}

# token -> replacement token(s)
_ABBREV = {
    'sr': ['senior'], 'snr': ['senior'], 'sn': ['senior'],
    'jr': ['junior'],
    'mgr': ['manager'], 'mngr': ['manager'], 'mgt': ['management'],
    'mgmt': ['management'], 'manger': ['manager'], 'managment': ['management'],
    'asst': ['assistant'], 'assist': ['assistant'], 'assoc': ['associate'],
    'admin': ['administrative'],
    'exec': ['executive'],
    'coord': ['coordinator'], 'coordinater': ['coordinator'],
    'dir': ['director'], 'dept': ['department'],
    'eng': ['engineer'], 'engr': ['engineer'], 'engg': ['engineer'],
    'rep': ['representative'], 'reps': ['representative'],
    'repr': ['representative'], 'representitive': ['representative'],
    'prof': ['professor'], 'profesor': ['professor'],
    'vp': ['vice', 'president'], 'svp': ['senior', 'vice', 'president'],
    'evp': ['executive', 'vice', 'president'], 'avp': ['assistant', 'vice', 'president'],
    'ceo': ['chief', 'executive', 'officer'],
    'cfo': ['chief', 'financial', 'officer'],
    'coo': ['chief', 'operating', 'officer'],
    'cto': ['chief', 'technology', 'officer'],
    'cmo': ['chief', 'marketing', 'officer'],
    'cio': ['chief', 'information', 'officer'],
    'ciso': ['chief', 'information', 'security', 'officer'],
    'cro': ['chief', 'revenue', 'officer'],
    'chro': ['chief', 'human', 'resources', 'officer'],
    'hr': ['human', 'resources'],
    'hris': ['human', 'resources', 'information', 'systems'],
    'it': ['information', 'technology'],
    'pr': ['public', 'relations'],
    'ops': ['operations'],
    'tas': ['teaching', 'assistant'],
    'sdr': ['sales', 'development', 'representative'],
    'bdr': ['business', 'development', 'representative'],
    'csr': ['customer', 'service', 'representative'],
    'cna': ['certified', 'nursing', 'assistant'],
    'lpn': ['licensed', 'practical', 'nurse'],
    'lvn': ['licensed', 'vocational', 'nurse'],
    'rn': ['registered', 'nurse'],
    'crna': ['nurse', 'anesthetist'],
    'emt': ['emergency', 'medical', 'technician'],
    'slp': ['speech', 'language', 'pathologist'],
    'lcsw': ['licensed', 'clinical', 'social', 'worker'],
    'msw': ['social', 'worker'],
    'lmsw': ['licensed', 'social', 'worker'],
    'lmhc': ['mental', 'health', 'counselor'],
    'lpc': ['licensed', 'professional', 'counselor'],
    'cpa': ['certified', 'public', 'accountant'],
    'cfp': ['certified', 'financial', 'planner'],
    'dds': ['dentist'], 'dvm': ['veterinarian'],
    'ta': ['teaching', 'assistant'],
    'gsi': ['graduate', 'student', 'instructor'],
    'sde': ['software', 'development', 'engineer'],
    'swe': ['software', 'engineer'],
    'sre': ['site', 'reliability', 'engineer'],
    'sdet': ['software', 'test', 'engineer'],
    'dba': ['database', 'administrator'],
    'pmo': ['project', 'management', 'office'],
    'pmp': ['project', 'manager'],
    'esol': ['esl'], 'ell': ['esl'], 'tesol': ['esl'], 'efl': ['esl'],
    'cma': ['certified', 'medical', 'assistant'],
    'mua': ['makeup', 'artist'],
    'dj': ['disc', 'jockey'],
    'rda': ['registered', 'dental', 'assistant'],
    'rbt': ['registered', 'behavior', 'technician'],
    'bcba': ['board', 'certified', 'behavior', 'analyst'],
    'np': ['nurse', 'practitioner'],
    'crm': ['customer', 'relationship', 'management'],
    'seo': ['search', 'engine', 'optimization'],
    'ux': ['user', 'experience'],
    'ui': ['user', 'interface'],
    'sme': ['subject', 'matter', 'expert'],
    'usmc': ['marine', 'corps'],
    'usaf': ['air', 'force'],
    'usn': ['navy'],
    'usar': ['army', 'reserve'],
    'arng': ['army', 'national', 'guard'],
    'gm': ['general', 'manager'],
}

_SEPARATORS = (' at ', ' @ ')
# last token of the left-hand side that means " at " is not a company separator
_NO_SPLIT_LEFT = frozenset((
    'stay', 'staying', 'work', 'working', 'look', 'looking', 'live', 'living',
    'home', 'back', 'out', 'available', 'arrived', 'law', 'large', 'sea',
    'best', 'good', 'great', 'hard', 'employed', 'am', 'is', 'was', 'be',
    'being', 'all', 'one', 'time', 'least', 'least', 'night', 'day', 'present',
))


def _clean(raw: str) -> str:
    s = raw.lower()
    s = s.replace('&', ' and ').replace('@', ' at ').replace('+', ' and ')
    s = _POSSESSIVE.sub('', s)
    return s


def normalize(raw):
    """Return (normalized_string, tokens, flags_from_modifiers)."""
    if not raw:
        return '', [], []
    flags = []
    s = _clean(raw)

    # --- parentheticals -------------------------------------------------
    if '(' in s or '[' in s or '{' in s:
        keep = []

        def _sub(m):
            inner = _NONALNUM.sub(' ', m.group(1)).strip()
            if not inner:
                return ' '
            if inner in _MODIFIER_WORDS:
                keep.append(inner)
                return ' '
            return ' ' + m.group(1) + ' '

        s = _PAREN.sub(_sub, s)
        for inner in keep:
            flags.append(inner)

    s = _NONALNUM.sub(' ', s)
    s = ' ' + s.strip() + ' '
    s = s.replace(' v p ', ' vice president ')
    s = s.replace(' c e o ', ' chief executive officer ')
    s = s.replace(' r and d ', ' research and development ')
    s = s.replace(' f and b ', ' food and beverage ')
    s = s.replace(' a v ', ' audio visual ')
    s = s.replace(' r n ', ' registered nurse ')
    s = s.replace(' l p n ', ' licensed practical nurse ')
    s = s.replace(' c n a ', ' certified nursing assistant ')
    s = s.replace(' p h d ', ' phd ')

    # --- "X at Y" / "X @ Y" --------------------------------------------
    # Only when the left side looks like a role, so that "stay at home mom",
    # "work at home agent" or "attorney at law" are not truncated to nonsense.
    for sep in _SEPARATORS:
        idx = s.find(sep)
        if idx > 0:
            left = s[:idx].strip()
            right = s[idx + len(sep):].strip()
            if left and right and left.split()[-1] not in _NO_SPLIT_LEFT:
                s = ' ' + left + ' '
            break

    toks = s.split()
    out = []
    for t in toks:
        rep = _ABBREV.get(t)
        if rep is not None:
            out.extend(rep)
        else:
            out.append(t)
    return ' '.join(out), out, flags


# ---------------------------------------------------------------------------
# rule engine
# ---------------------------------------------------------------------------
_RULES = []          # (family, conf, padded_phrases, rx, triggers)
_STOP_TRIG = {'of', 'and', 'the', 'for', 'to', 'in', 'a', 'an', 'or', 'de'}


def _trigger(phrase):
    """Longest token of a phrase: a necessary condition for the phrase to match."""
    best = ''
    for t in phrase.split():
        if t in _STOP_TRIG:
            continue
        if len(t) > len(best):
            best = t
    return best or phrase.split()[0]


def R(family, *phrases, conf='high'):
    assert family in FAMILIES, family
    padded = tuple(' ' + p + ' ' for p in phrases)
    trigs = tuple(sorted({_trigger(p) for p in phrases}))
    _RULES.append((family, conf, padded, None, trigs))


def RX(family, pattern, triggers, conf='high'):
    assert family in FAMILIES, family
    _RULES.append((family, conf, (), re.compile(pattern), tuple(triggers)))


# ---------------------------------------------------------------------------
# exact whole-string map (bare generics live here, always low confidence)
# ---------------------------------------------------------------------------
_EXACT = {
    # generic role words -- family is a guess, hence confidence 'low'
    'manager': ('general_management', 'low'),
    'director': ('general_management', 'low'),
    'supervisor': ('general_management', 'low'),
    'management': ('general_management', 'low'),
    'operations': ('general_management', 'low'),
    'general management': ('general_management', 'low'),
    'team lead': ('general_management', 'low'),
    'team leader': ('general_management', 'low'),
    'team manager': ('general_management', 'low'),
    'leader': ('general_management', 'low'),
    'lead': ('general_management', 'low'),
    'head': ('general_management', 'low'),
    'executive': ('general_management', 'low'),
    'senior executive': ('general_management', 'low'),
    'vice president': ('general_management', 'low'),
    'senior vice president': ('general_management', 'low'),
    'executive vice president': ('general_management', 'low'),
    'assistant vice president': ('general_management', 'low'),
    'associate vice president': ('general_management', 'low'),
    'senior director': ('general_management', 'low'),
    'associate director': ('general_management', 'low'),
    'assistant director': ('general_management', 'low'),
    'deputy director': ('general_management', 'low'),
    'managing member': ('general_management', 'low'),
    'partner': ('general_management', 'low'),
    'general partner': ('general_management', 'low'),
    'managing partner': ('general_management', 'low'),
    'senior partner': ('general_management', 'low'),
    'chair': ('general_management', 'low'),
    'chairman': ('executive', 'high'),
    'chairwoman': ('executive', 'high'),
    'chairperson': ('executive', 'high'),
    'analyst': ('business_analysis', 'low'),
    'senior analyst': ('business_analysis', 'low'),
    'associate': ('business_analysis', 'low'),
    'senior associate': ('business_analysis', 'low'),
    'specialist': ('business_analysis', 'low'),
    'senior specialist': ('business_analysis', 'low'),
    'professional': ('business_analysis', 'low'),
    'consultant': ('consulting', 'low'),
    'senior consultant': ('consulting', 'low'),
    'independent consultant': ('consulting', 'low'),
    'advisor': ('consulting', 'low'),
    'adviser': ('consulting', 'low'),
    'senior advisor': ('consulting', 'low'),
    'strategic advisor': ('consulting', 'low'),
    'coordinator': ('admin_support', 'low'),
    'assistant': ('admin_support', 'low'),
    'administrator': ('admin_support', 'low'),
    'administration': ('admin_support', 'low'),
    'clerk': ('admin_support', 'low'),
    'secretary': ('admin_support', 'low'),
    'office': ('admin_support', 'low'),
    'representative': ('sales', 'low'),
    'agent': ('sales', 'low'),
    'account': ('sales', 'low'),
    'educator': ('teaching_k12', 'low'),
    'faculty': ('higher_ed_faculty', 'low'),
    'coach': ('personal_care_fitness', 'low'),
    'technician': ('trades_logistics', 'low'),
    'contractor': ('trades_logistics', 'low'),
    'operator': ('trades_logistics', 'low'),
    'laborer': ('trades_logistics', 'low'),
    'engineer': ('engineering', 'high'),
    'developer': ('software', 'high'),
    'designer': ('design_ux', 'high'),
    'president': ('executive', 'high'),
    'owner': ('founder_owner', 'high'),
    'founder': ('founder_owner', 'high'),
    'co founder': ('founder_owner', 'high'),
    'cofounder': ('founder_owner', 'high'),
    'self employed': ('founder_owner', 'high'),
    'freelance': ('founder_owner', 'high'),
    'freelancer': ('founder_owner', 'high'),
    'entrepreneur': ('founder_owner', 'high'),
    'proprietor': ('founder_owner', 'high'),
    'sole proprietor': ('founder_owner', 'high'),
    'independent contractor': ('founder_owner', 'high'),
    'principal': ('school_admin', 'low'),
    'member': ('volunteer_board', 'low'),
    'volunteer': ('volunteer_board', 'high'),
    'intern': ('intern', 'high'),
    'internship': ('intern', 'high'),
    'student': ('student', 'high'),
    'retired': ('not_working', 'high'),
    'semi retired': ('not_working', 'high'),
    'sales': ('sales', 'high'),
    'marketing': ('marketing', 'high'),
    'accounting': ('finance_accounting', 'high'),
    'finance': ('finance_accounting', 'high'),
    'human resources': ('hr_recruiting', 'high'),
    'customer service': ('customer_service', 'high'),
    'information technology': ('it_support', 'high'),
    'military': ('military', 'high'),
    'writer': ('writing_editing', 'high'),
    'editor': ('writing_editing', 'high'),
    'teacher': ('teaching_k12', 'high'),
    'professor': ('higher_ed_faculty', 'high'),
    'nurse': ('healthcare_clinical', 'high'),
    'attorney': ('legal_attorney', 'high'),
    'lawyer': ('legal_attorney', 'high'),
    'counsel': ('legal_attorney', 'high'),
    'of counsel': ('legal_attorney', 'high'),
    'paralegal': ('legal_support', 'high'),
    'realtor': ('real_estate', 'high'),
    'scientist': ('science_lab', 'high'),
    'researcher': ('research', 'high'),
    'artist': ('arts_performance', 'high'),
    'musician': ('arts_performance', 'high'),
    'actor': ('arts_performance', 'high'),
    'photographer': ('design_ux', 'high'),
    'librarian': ('museum_library', 'high'),
    'pastor': ('clergy', 'high'),
    'driver': ('trades_logistics', 'high'),
    'cashier': ('retail', 'high'),
    'server': ('hospitality_food', 'high'),
    'employee': ('unclassified', 'low'),
    'staff': ('unclassified', 'low'),
    'various': ('unclassified', 'low'),
    'n a': ('unclassified', 'low'),
    'na': ('unclassified', 'low'),
    'none': ('unclassified', 'low'),
    'self': ('founder_owner', 'low'),
    'officer': ('unclassified', 'low'),
    'planner': ('trades_logistics', 'low'),
    'research': ('research', 'high'),
    'development': ('nonprofit_program', 'low'),
    'product': ('product_management', 'low'),
    'pm': ('project_program_mgmt', 'low'),
    'md': ('healthcare_clinical', 'low'),
    'crew': ('retail', 'low'),
    'talent': ('hr_recruiting', 'low'),
    'guide': ('hospitality_food', 'low'),
    'major': ('military', 'low'),
    'deputy': ('protective_services', 'low'),
    'resident': ('healthcare_clinical', 'low'),
    'chief': ('general_management', 'low'),
    'principle': ('school_admin', 'low'),
    'boss': ('founder_owner', 'low'),
    'eigenaar': ('founder_owner', 'high'),
    'propietario': ('founder_owner', 'high'),
    'gerente general': ('general_management', 'high'),
    'auxiliar administrativo': ('admin_support', 'high'),
    'participant': ('unclassified', 'low'),
    'various positions': ('unclassified', 'low'),
    'various roles': ('unclassified', 'low'),
    'multiple positions': ('unclassified', 'low'),
    'additional experience': ('unclassified', 'low'),
    'analyst i': ('business_analysis', 'low'),
}

# ===========================================================================
# ORDERED RULES.  Earlier = higher priority.
# ===========================================================================

# --- A. students, non-employment -------------------------------------------
R('other_education', 'undergraduate teaching assistant',
  'undergraduate teaching fellow', 'undergraduate course assistant')
R('research', 'student researcher', 'graduate student researcher',
  'undergraduate researcher', 'undergraduate student researcher',
  'student research assistant', 'student research fellow')
R('student',
  'nursing student', 'student nurse', 'medical student', 'student doctor',
  'law student', 'pharmacy student', 'student pharmacist', 'dental student',
  'veterinary student', 'physical therapy student', 'student physical therapist',
  'occupational therapy student', 'graduate student', 'phd student',
  'phd candidate', 'doctoral candidate', 'doctoral student', 'masters student',
  'master student', 'mba candidate', 'mba student', 'undergraduate student',
  'undergraduate', 'college student', 'high school student', 'student athlete',
  'student worker', 'student employee', 'student assistant', 'work study',
  'student ambassador', 'orientation leader', 'graduate assistant',
  'graduate research assistant', 'practicum student', 'student volunteer',
  'student member', 'student trainee', 'student aide', 'phd researcher'
  )
R('not_working',
  'stay at home mom', 'stay at home dad', 'stay at home parent',
  'stay at home mother', 'stay at home father', 'stay at home',
  'homemaker', 'home maker', 'career break', 'sabbatical', 'unemployed',
  'not employed', 'seeking employment', 'seeking opportunities',
  'seeking new opportunities', 'seeking position', 'job seeker', 'jobseeker',
  'looking for work', 'looking for employment', 'looking for opportunities',
  'looking for new opportunities', 'open to work', 'open to opportunities',
  'in transition', 'between jobs', 'currently seeking', 'no longer employed',
  'laid off', 'furloughed', 'maternity leave', 'full time parent',
  'full time mom', 'full time dad', 'full time mother', 'raising children',
  'independent job seeker', 'none of the above')

# --- B. cross-family overrides ---------------------------------------------
R('design_ux', 'video editor', 'film editor', 'photo editor', 'video producer',
  'film producer', 'videographer', 'video production', 'film production',
  'director of photography', 'motion graphics', 'video specialist',
  'multimedia specialist', 'video editing', 'video content creator',
  'cinematographer', 'camera operator', 'film maker', 'filmmaker',
  'production designer', 'post production')
R('arts_performance', 'audio engineer', 'sound engineer', 'recording engineer',
  'mastering engineer', 'mixing engineer', 'audio technician', 'sound technician',
  'sound designer', 'music producer', 'audio producer', 'stage manager',
  'stagehand', 'stage hand', 'lighting designer', 'scenic designer',
  'costume designer', 'theatre technician', 'theater technician')
R('sales', 'sales engineer', 'solutions engineer', 'solution engineer',
  'presales engineer', 'pre sales engineer', 'sales engineering',
  'field application engineer')
R('software', 'software engineering manager', 'software development manager',
  'director of software engineering', 'software engineering director',
  'manager of software engineering', 'software development director',
  'vice president of software engineering', 'head of engineering software')
R('engineering', 'engineering manager', 'director of engineering',
  'engineering director', 'vice president of engineering',
  'head of engineering', 'manager of engineering', 'engineering supervisor')
R('sales', 'sales and marketing')
R('marketing', 'marketing and sales', 'marketing and communications',
  'marketing communications', 'marcom', 'marketing and public relations')
R('pr_communications', 'communications and marketing',
  'public relations and marketing')
R('teaching_k12', 'teacher assistant', 'teacher aide', 'teachers assistant',
  'teacher assistance', 'assistant teacher', 'teaching aide', 'classroom aide',
  'classroom assistant', 'instructional aide', 'instructional assistant',
  'educational assistant', 'education assistant')
R('other_education', 'teaching artist', 'teaching assistant',
  'graduate student instructor', 'graduate instructor', 'course assistant',
  'lab assistant teaching')
R('personal_care_fitness', 'makeup artist', 'nail artist', 'tattoo artist',
  'hair artist', 'brow artist', 'lash artist')
R('design_ux', 'graphic artist', 'production artist', 'digital artist',
  '3d artist', 'storyboard artist', 'layout artist', 'concept artist',
  'cg artist', 'technical artist', 'ux artist')
R('design_ux', 'art director', 'creative director', 'associate creative director',
  'design director', 'creative services', 'executive creative director',
  'creative manager', 'creative lead')
R('arts_performance', 'artistic director', 'music director', 'choir director',
  'band director', 'theatre director', 'theater director', 'stage director',
  'orchestra director', 'worship director', 'drama director')
R('social_services', 'school social worker')
R('teaching_k12', 'school counselor', 'guidance counselor',
  'school guidance counselor')
R('higher_ed_staff', 'admissions counselor', 'admissions representative',
  'admissions coordinator', 'admissions director', 'director of admissions',
  'admissions advisor', 'admissions officer', 'admissions specialist',
  'admissions assistant', 'admissions associate', 'admissions manager',
  'admissions', 'enrollment counselor', 'enrollment advisor',
  'enrollment specialist', 'enrollment manager', 'enrollment director',
  'recruitment admissions')
R('personal_care_fitness', 'camp counselor', 'summer camp counselor',
  'camp director', 'camp staff', 'camp instructor', 'day camp counselor')
R('trades_logistics', 'construction superintendent', 'project superintendent',
  'site superintendent', 'general superintendent', 'superintendent of construction',
  'building superintendent', 'field superintendent', 'assistant superintendent construction')
R('trades_logistics', 'first officer', 'quality control inspector',
  'quality control technician', 'quality control specialist',
  'quality control manager', 'quality control supervisor', 'quality inspector',
  'quality control analyst', 'quality control coordinator', 'quality control')
R('healthcare_clinical', 'medical technologist', 'medical laboratory scientist',
  'medical laboratory technician', 'clinical laboratory scientist',
  'clinical laboratory technologist', 'medical lab technician',
  'clinical lab scientist', 'medical laboratory technologist')
R('healthcare_support', 'physical therapist assistant', 'physical therapy assistant',
  'physical therapy aide', 'physical therapy technician',
  'occupational therapy assistant', 'occupational therapy aide',
  'certified occupational therapy assistant', 'physical therapist aide',
  'rehabilitation technician', 'rehab technician', 'physical therapy tech')
R('personal_care_fitness', 'massage therapist', 'massage practitioner',
  'licensed massage therapist')
R('personal_care_fitness', 'yoga instructor', 'yoga teacher', 'fitness instructor',
  'group fitness instructor', 'swim instructor', 'zumba instructor',
  'pilates instructor', 'spin instructor', 'personal trainer', 'fitness coach',
  'fitness trainer', 'athletic coach', 'head coach', 'assistant coach',
  'strength and conditioning', 'fitness specialist', 'fitness manager',
  'wellness coach', 'health coach', 'life coach', 'sports coach', 'soccer coach',
  'basketball coach', 'baseball coach', 'football coach', 'volleyball coach',
  'tennis coach', 'swim coach', 'track coach', 'cheer coach', 'gymnastics coach',
  'softball coach', 'lacrosse coach', 'golf coach', 'wrestling coach',
  'hockey coach', 'running coach', 'crossfit coach', 'fitness director',
  'group exercise instructor', 'wellness director')
R('higher_ed_staff', 'resident assistant', 'resident advisor', 'residence life',
  'residential advisor', 'residence hall', 'residence director',
  'resident director', 'community advisor housing')
R('admin_support', 'executive assistant', 'administrative assistant',
  'personal assistant', 'executive administrative assistant',
  'administrative aide', 'office assistant', 'virtual assistant',
  'staff assistant', 'administrative support', 'administrative associate',
  'administrative secretary', 'executive secretary', 'executive administrator',
  'administrative specialist', 'administrative coordinator',
  'administrative analyst', 'administrative clerk', 'administrative officer',
  'administrative director', 'administrative manager', 'administrative intern',
  'management assistant', 'office administrator', 'office coordinator',
  'office specialist', 'office clerk', 'office associate', 'office support')
R('legal_support', 'legal assistant', 'legal secretary',
  'legal administrative assistant', 'legal support', 'legal aide',
  'legal office assistant')
R('healthcare_clinical', 'certified nursing assistant', 'nursing assistant',
  'nurse assistant', 'certified nurse assistant')
R('healthcare_support', 'medical assistant', 'dental assistant',
  'optometric assistant', 'optometric technician', 'ophthalmic technician',
  'veterinary assistant', 'patient care assistant', 'personal care assistant',
  'home health aide', 'nurse aide', 'nursing aide', 'medical office assistant',
  'certified medical assistant', 'clinical assistant', 'chiropractic assistant',
  'ophthalmic assistant', 'orthodontic assistant', 'surgical assistant')
R('museum_library', 'library assistant', 'library technician', 'library aide',
  'library specialist', 'library clerk', 'library associate', 'library director',
  'library media specialist', 'library page', 'library manager',
  'library intern', 'library coordinator', 'library services')
R('writing_editing', 'staff writer')
R('legal_attorney', 'staff attorney')
R('healthcare_clinical', 'staff nurse')
R('software', 'member of technical staff')
R('school_admin', 'school principal', 'assistant principal', 'vice principal',
  'elementary principal', 'high school principal', 'middle school principal',
  'building principal', 'interim principal', 'associate principal',
  'principal of school', 'school director', 'head of school',
  'school administrator', 'district administrator', 'principal intern')
R('hr_recruiting', 'human resources business partner', 'people business partner',
  'people operations', 'head of people', 'chief people officer')
R('volunteer_board', 'board member', 'member board of directors',
  'board of directors', 'board of trustees', 'advisory board', 'advisory council',
  'board chair', 'board president', 'trustee', 'board co chair', 'executive board',
  'board secretary', 'board treasurer', 'board of advisors', 'board director',
  'committee member', 'steering committee', 'board of education member')
R('student', 'student ambassador', 'campus ambassador')
R('marketing', 'brand ambassador')
R('hospitality_food', 'executive chef', 'sous chef', 'head chef', 'pastry chef',
  'chef de cuisine', 'chef de partie', 'chef', 'culinary')
R('executive', 'executive director', 'managing director', 'executive chairman',
  'interim executive director', 'deputy executive director',
  'associate executive director', 'assistant executive director',
  'executive vice chairman')
R('banking_insurance', 'insurance producer', 'producer insurance')
R('arts_performance', 'theatrical producer', 'theater producer')
R('journalism_media', 'executive producer', 'supervising producer',
  'line producer', 'associate producer', 'story producer', 'segment producer',
  'news producer', 'broadcast producer', 'radio producer', 'podcast producer',
  'television producer', 'tv producer', 'senior producer', 'field producer',
  'digital producer')
R('hr_recruiting', 'executive recruiter', 'technical recruiter')
R('protective_services', 'firefighter', 'fire fighter', 'fire captain',
  'emergency medical technician firefighter')
R('hr_recruiting', 'physician recruiter', 'nurse recruiter',
  'healthcare recruiter', 'clinical recruiter', 'medical recruiter')
R('general_management', 'chief of staff')
R('engineering', 'chief engineer')

# --- C. communications / creative ------------------------------------------
R('healthcare_support', 'medical scribe', 'scribe')
R('research', 'market research', 'marketing research', 'market researcher',
  'user experience researcher', 'user experience research', 'user research',
  'user researcher', 'design researcher')
R('journalism_media', 'media production', 'broadcast production',
  'photojournalist', 'photo journalist', 'news editor',
  'sports editor', 'city editor', 'assignment editor', 'wire editor',
  'metro editor', 'opinion editor')
R('writing_editing',
  'writer', 'author', 'copywriter', 'copy writer', 'editor', 'editorial',
  'proofreader', 'proofreading', 'copy editor', 'technical writer',
  'grant writer', 'grantwriter', 'ghostwriter', 'screenwriter', 'novelist',
  'poet', 'publisher', 'publishing', 'publication', 'publications',
  'editing', 'editor in chief', 'managing editor', 'senior editor',
  'associate editor', 'assistant editor', 'contributing editor',
  'copy chief', 'proof reader', 'content writer', 'content editor',
  'content developer', 'medical writer', 'science writer', 'proposal writer',
  'lexicographer', 'book editor', 'manuscript', 'literary agent')
R('writing_editing', 'proposal manager', 'proposal coordinator',
  'proposal specialist', conf='low')
R('journalism_media',
  'journalist', 'journalism', 'reporter', 'correspondent', 'news anchor',
  'anchor', 'newscaster', 'news director', 'newsroom', 'broadcaster',
  'broadcast', 'columnist', 'sports writer', 'sportswriter', 'news assistant',
  'news intern', 'newspaper', 'radio host', 'podcast host', 'talk show host',
  'show host', 'news reporter', 'news writer', 'news producer', 'anchorman',
  'news photographer', 'video journalist', 'multimedia journalist',
  'assignment desk', 'news operations', 'editor in chief newspaper',
  'producer')
R('pr_communications',
  'public relations', 'media relations', 'corporate communications',
  'communications specialist', 'communications manager', 'communications director',
  'communications coordinator', 'communications assistant', 'communications intern',
  'communications associate', 'communications officer', 'communications consultant',
  'communications strategist', 'communications analyst', 'communications lead',
  'internal communications', 'external communications', 'public affairs',
  'public information officer', 'press secretary', 'speechwriter',
  'speech writer', 'publicist', 'investor relations', 'community relations',
  'director of communications', 'communication specialist',
  'communication manager', 'communication coordinator', 'communication director',
  'communications', 'communication', 'press officer', 'media officer',
  'crisis communications', 'strategic communications', 'brand communications')
R('marketing',
  'marketing', 'brand manager', 'brand director', 'brand strategist',
  'brand marketing', 'branding', 'digital marketing', 'search engine optimization',
  'seo', 'sem specialist', 'social media', 'growth marketing', 'growth manager',
  'growth hacker', 'demand generation', 'advertising', 'media planner',
  'media buyer', 'account planner', 'product marketing', 'email marketing',
  'content marketing', 'content strategist', 'content strategy',
  'content creator', 'content manager', 'content specialist',
  'content coordinator', 'content producer', 'content associate',
  'market development', 'brand ambassador', 'promotions', 'promotional',
  'campaign manager', 'campaign coordinator', 'campaign director',
  'campaign specialist', 'media specialist', 'media coordinator',
  'media manager', 'media director', 'media associate', 'media analyst',
  'digital strategist', 'digital specialist', 'digital coordinator',
  'ecommerce', 'e commerce', 'merchandising manager', 'trade marketing',
  'field marketing', 'event marketing', 'influencer', 'copywriting',
  'community manager', conf='high')
R('other_education', 'instructional designer', 'instructional design',
  'curriculum designer', 'learning designer', 'learning experience designer')
R('engineering', 'mechanical designer', 'architectural designer', 'cad designer',
  'electrical designer', 'structural designer', 'design engineer',
  'piping designer', 'tool designer', 'civil designer')
R('design_ux',
  'graphic designer', 'graphic design', 'designer', 'user experience',
  'user interface', 'product design', 'web design', 'illustrator',
  'illustration', 'interaction design', 'visual design', 'design manager',
  'design director', 'design intern', 'design lead', 'design assistant',
  'design consultant', 'design associate', 'design specialist',
  'design coordinator', 'design studio', 'design supervisor', 'design team',
  'graphics', 'typographer', 'animator', 'animation', 'retoucher',
  'photography', 'photographer', 'prepress', 'pre press', 'desktop publishing',
  'brand designer', 'package design', 'packaging designer', 'exhibit designer',
  'game designer', 'digital designer', 'presentation designer')
R('trades_logistics', 'industrial painter', 'automotive painter', 'house painter',
  'commercial painter', 'auto painter', 'painter helper')
R('arts_performance',
  'artist', 'musician', 'singer', 'actor', 'actress', 'performer', 'dancer',
  'composer', 'painter', 'sculptor', 'choreographer', 'disc jockey',
  'vocalist', 'guitarist', 'pianist', 'violinist', 'drummer', 'band member',
  'voice over', 'voiceover', 'entertainer', 'magician', 'comedian', 'model',
  'theatre', 'theater', 'playwright', 'dramaturg', 'opera', 'symphony',
  'ensemble member', 'company member', 'music minister'  , 'accompanist',
  'arranger', 'conductor', 'puppeteer', 'illusionist', 'circus',
  'artist in residence', 'fine art', 'studio artist', 'visual artist',
  'recording artist', 'performing artist', 'session musician')
R('museum_library',
  'librarian', 'library', 'archivist', 'archives', 'archival', 'curator',
  'curatorial', 'museum', 'collections manager', 'collections curator',
  'gallery', 'docent', 'conservator', 'historical society', 'historic site',
  'preservation specialist', 'exhibits', 'exhibitions', 'cataloger',
  'cataloguer', 'special collections', 'rare books', 'information literacy')
R('translation_language',
  'translator', 'interpreter', 'translation', 'interpretation services',
  'localization', 'sign language', 'linguist', 'transcriptionist language',
  'court interpreter', 'medical interpreter', 'language services')

# --- D. education ----------------------------------------------------------
R('higher_ed_faculty',
  'professor', 'adjunct', 'lecturer', 'postdoctoral', 'post doctoral',
  'postdoc', 'post doc', 'visiting scholar', 'teaching fellow', 'faculty',
  'college instructor', 'university instructor', 'clinical instructor',
  'nursing instructor', 'course instructor', 'department chair',
  'chair of department', 'academic chair', 'program chair', 'faculty member',
  'instructor of record', 'teaching professor', 'research professor',
  'dissertation', 'doctoral advisor')
R('healthcare_clinical', 'athletic trainer')
R('personal_care_fitness', 'dog trainer', 'horse trainer', 'pet trainer')
R('hr_recruiting', 'learning and development', 'talent development',
  'organizational development', 'leadership development', 'employee development')
R('other_education', 'dance teacher', 'art teacher private', 'music teacher private',
  'piano teacher', 'guitar teacher', 'voice teacher', 'swim teacher')
R('teaching_k12',
  'teacher', 'substitute', 'paraprofessional', 'para professional',
  'para educator', 'paraeducator', 'special education', 'esl', 'title i',
  'preschool', 'pre k', 'prek', 'kindergarten', 'elementary school',
  'middle school', 'high school english', 'classroom', 'reading specialist',
  'literacy specialist', 'reading interventionist', 'interventionist',
  'school librarian', 'lead teacher', 'head teacher', 'master teacher',
  'k 12 educator', 'elementary educator', 'early childhood educator',
  'secondary educator', 'montessori', 'special ed', 'homeroom',
  'instructional coach', 'curriculum coach', 'literacy coach',
  'school psychologist', 'behavior interventionist')
R('school_admin',
  'superintendent of schools', 'school superintendent', 'assistant superintendent',
  'deputy superintendent', 'superintendent', 'athletic director',
  'director of curriculum', 'curriculum director', 'director of special education',
  'special education director', 'school business', 'school board president',
  'dean of faculty', 'academic principal', 'headmaster', 'headmistress')
R('higher_ed_staff',
  'registrar', 'academic advisor', 'academic adviser', 'academic advising',
  'student affairs', 'student services', 'student life', 'student activities',
  'student development', 'student engagement', 'student success',
  'financial aid', 'dean', 'provost', 'chancellor', 'career services',
  'career counselor', 'career advisor', 'career coach', 'study abroad',
  'academic coordinator', 'academic program', 'academic services',
  'academic affairs', 'academic dean', 'greek life', 'bursar',
  'alumni relations', 'alumni affairs', 'alumni director', 'university relations',
  'institutional research', 'academic support', 'academic administrator',
  'college counselor', 'student conduct', 'campus life', 'campus recreation',
  'international student', 'academic technology', 'first year experience')
R('other_education',
  'tutor', 'tutoring', 'trainer', 'training specialist', 'training manager',
  'training coordinator', 'training director', 'training instructor',
  'training and development', 'curriculum developer', 'curriculum specialist',
  'curriculum writer', 'education specialist', 'education coordinator',
  'education director', 'education manager', 'education associate',
  'educational consultant', 'learning specialist', 'academic coach',
  'test prep', 'driving instructor', 'flight instructor', 'esl instructor',
  'english instructor', 'instructor', 'facilitator', 'adult education',
  'teacher trainer', 'learning consultant', 'education assistant program',
  'director of education', 'education intern', 'educational coordinator',
  'e learning', 'elearning', 'training assistant', 'training analyst',
  'learning and organizational', 'education outreach')

# --- E. research, science, tech, engineering -------------------------------
R('science_lab', 'research scientist', 'clinical research', 'research technician',
  'laboratory research', 'research chemist', 'research biologist',
  'research microbiologist', 'research nurse', 'bench research')
R('engineering', 'research engineer', 'research and development engineer')
R('research',
  'research assistant', 'research associate', 'research analyst', 'researcher',
  'research fellow', 'research coordinator', 'research specialist',
  'research manager', 'research director', 'research intern', 'research consultant',
  'research officer', 'research administrator', 'research aide',
  'policy researcher', 'historian', 'user researcher', 'research volunteer',
  'principal investigator',
  'research and development', 'research supervisor', 'research affiliate',
  'research analyst intern', 'research program', 'research support',
  'genealogist', 'research and evaluation', 'evaluation specialist')
R('admin_support', 'data entry')
R('it_support', 'database administrator', 'data center', 'data warehouse')
R('data_analytics',
  'data analyst', 'data scientist', 'data science', 'business intelligence',
  'analytics', 'statistician', 'machine learning', 'data engineer',
  'quantitative analyst', 'data modeler', 'data visualization', 'big data',
  'data architect', 'reporting analyst', 'insights analyst', 'decision science',
  'biostatistician', 'statistical analyst', 'data manager', 'data engineering',
  'data specialist', 'data consultant', 'data coordinator', 'data associate',
  'data quality', 'data governance', 'data steward', 'data analytics',
  'artificial intelligence', 'deep learning', 'data mining')
R('real_estate', 'real estate developer', 'land developer', 'property developer')
R('software',
  'software engineer', 'software developer', 'developer', 'programmer',
  'web developer', 'front end', 'frontend', 'back end', 'backend',
  'full stack', 'fullstack', 'devops', 'site reliability', 'mobile developer',
  'ios developer', 'android developer', 'application developer',
  'software architect', 'solutions architect', 'solution architect',
  'data architect software', 'enterprise architect', 'cloud architect',
  'systems architect', 'technical architect', 'software development',
  'software engineering', 'computer programmer', 'software test',
  'test automation', 'net developer', 'java developer', 'python developer',
  'salesforce developer', 'php developer', 'game developer', 'software intern',
  'software consultant', 'software specialist', 'application engineer software',
  'computer scientist', 'software analyst',
  'qa engineer', 'qa analyst', 'qa automation', 'qa tester', 'qa lead',
  'qa manager', 'qa specialist', 'qa intern', 'qa consultant',
  'software quality', 'quality assurance analyst', 'quality assurance tester',
  'quality assurance automation', 'quality assurance engineer',
  'quality assurance developer', 'test engineer', 'automation developer',
  'web programmer', 'applications developer', 'application programmer',
  'systems developer', 'firmware engineer', 'embedded software',
  'application development', 'web development', 'mobile development',
  'platform engineer', 'infrastructure engineer', 'cloud engineer',
  'security engineer', 'integration developer', 'salesforce consultant',
  'technology lead software')
R('sales', 'technical account manager', 'technical sales')
R('project_program_mgmt', 'technical program manager',
  'technical project manager', 'information technology project manager',
  'information technology program manager')
R('it_support',
  'information technology', 'systems administrator', 'system administrator',
  'network', 'help desk', 'helpdesk', 'desktop support', 'technical support',
  'cloud', 'security analyst', 'cybersecurity', 'cyber security',
  'information security', 'systems engineer', 'system engineer',
  'systems analyst', 'system analyst', 'business systems analyst',
  'business system analyst', 'computer technician', 'pc technician',
  'sysadmin', 'infrastructure', 'server administrator', 'sharepoint',
  'active directory', 'technical analyst', 'technical consultant',
  'technology consultant', 'information systems', 'salesforce administrator',
  'system support', 'application support', 'technical services',
  'computer support', 'technology director', 'technology manager',
  'technology specialist', 'technology coordinator', 'technology integration',
  'technical specialist', 'technical director', 'technical manager',
  'technical coordinator', 'technical operations', 'technical engineer',
  'computer operator', 'computer specialist', 'technology analyst',
  'network operations', 'telecommunications', 'voip', 'systems specialist',
  'systems coordinator', 'systems manager', 'systems director',
  'systems support', 'systems technician', 'technical solutions',
  'end user support', 'field technology', 'technology associate', conf='high')
R('product_management',
  'product manager', 'product owner', 'product management', 'director of product',
  'head of product', 'product lead', 'product development manager',
  'product strategy', 'product operations', 'chief product officer')
R('engineering',
  'mechanical engineer', 'civil engineer', 'electrical engineer',
  'chemical engineer', 'structural engineer', 'industrial engineer',
  'process engineer', 'manufacturing engineer', 'project engineer',
  'field engineer', 'hardware engineer', 'aerospace', 'biomedical engineer',
  'environmental engineer', 'petroleum engineer', 'nuclear engineer',
  'materials engineer', 'controls engineer', 'automation engineer',
  'validation engineer', 'reliability engineer', 'product engineer',
  'application engineer', 'applications engineer', 'engineering technician',
  'engineering intern', 'engineering assistant', 'engineering specialist',
  'engineering technologist', 'engineering coordinator', 'engineering analyst',
  'engineering associate', 'engineering consultant', 'engineering aide',
  'cad', 'drafter', 'drafting', 'surveyor', 'architect', 'architectural',
  'engineer', 'engineering', 'quality engineer', 'quality assurance',
  'quality manager', 'quality specialist', 'quality supervisor',
  'quality coordinator', 'quality technician', 'quality auditor',
  'quality director', 'quality associate', 'quality lead', 'estimator',
  'geotechnical', 'hydrologist', 'metallurgist', 'tooling', 'plant engineer')
R('science_lab',
  'scientist', 'chemist', 'biologist', 'microbiologist', 'geologist',
  'laboratory', 'lab technician', 'lab manager', 'lab assistant', 'lab director',
  'lab supervisor', 'lab coordinator', 'lab tech', 'biochemist', 'toxicologist',
  'pharmacologist', 'botanist', 'zoologist', 'ecologist', 'physicist',
  'astronomer', 'epidemiologist', 'food scientist', 'soil scientist',
  'formulation', 'bioinformatics', 'molecular', 'histotechnologist',
  'cytotechnologist', 'science technician', 'naturalist', 'conservation biologist',
  'field biologist', 'wildlife biologist', 'environmental technician',
  'environmental specialist', 'environmental analyst', 'environmental health')

# --- F. healthcare ---------------------------------------------------------
R('healthcare_support',
  'medical receptionist', 'patient care technician', 'patient care coordinator',
  'patient coordinator', 'patient access', 'patient services', 'patient service',
  'patient registration', 'patient advocate', 'patient navigator',
  'patient sitter', 'patient transport', 'medical biller', 'medical coder',
  'medical billing', 'medical coding', 'pharmacy technician', 'pharmacy assistant',
  'pharmacy clerk', 'caregiver', 'care giver', 'home health', 'home care',
  'phlebotomist', 'phlebotomy', 'health unit coordinator', 'practice manager',
  'practice administrator', 'hospital administrator', 'healthcare administrator',
  'medical secretary', 'medical office', 'medical records', 'unit secretary',
  'veterinary technician', 'vet tech', 'dental receptionist', 'optician',
  'sterile processing', 'behavior technician', 'behavioral health technician',
  'mental health technician', 'psychiatric technician', 'dietary aide',
  'activities director', 'activity director', 'medical transcriptionist',
  'health information', 'revenue cycle', 'insurance verification',
  'care coordinator', 'care manager', 'medical scheduler', 'clinic coordinator',
  'medical support', 'health aide', 'direct care', 'resident aide',
  'hospice aide', 'dental office manager', 'medical office manager',
  'clinic manager', 'clinic administrator', 'medical staff coordinator')
R('healthcare_clinical',
  'registered nurse', 'nurse practitioner', 'licensed practical nurse',
  'licensed vocational nurse', 'nurse', 'nursing', 'physician', 'doctor',
  'dentist', 'pharmacist', 'physical therapist', 'occupational therapist',
  'speech language pathologist', 'speech therapist', 'speech pathologist',
  'physician assistant', 'paramedic', 'emergency medical technician',
  'surgeon', 'resident physician', 'medical resident', 'veterinarian',
  'dental hygienist', 'psychiatrist', 'optometrist', 'chiropractor',
  'midwife', 'anesthetist', 'radiologic technologist', 'sonographer',
  'radiographer', 'respiratory therapist', 'dietitian', 'nutritionist',
  'audiologist', 'podiatrist', 'cardiologist', 'pediatrician', 'oncologist',
  'radiologist', 'pathologist', 'anesthesiologist', 'hospitalist',
  'surgical technologist', 'ultrasound', 'mri technologist', 'ct technologist',
  'nuclear medicine', 'perfusionist', 'orthotist', 'prosthetist',
  'genetic counselor', 'medical doctor', 'dermatologist', 'neurologist',
  'psychiatric', 'clinical pharmacist', 'pharmacy manager', 'pharmacy director',
  'medical director', 'clinical director', 'clinical manager',
  'clinical supervisor', 'clinical coordinator', 'clinical specialist',
  'clinician', 'behavior analyst', 'music therapist', 'recreational therapist',
  'recreation therapist', 'art therapist', 'lactation', 'sleep technologist',
  'medical technician', 'cardiovascular technologist', 'echo technologist',
  'clinical educator', 'infection control', 'wound care', 'dialysis technician',
  'emergency medical services', 'flight paramedic', 'medical examiner',
  'clinical nurse', 'nurse anesthetist', 'nurse midwife', 'charge nurse',
  'orthopedic surgeon', 'veterinary surgeon', 'clinical research nurse')

# --- G. legal, government, nonprofit, social, clergy -----------------------
R('legal_support', 'law clerk', 'judicial clerk', 'judicial intern',
  'judicial extern', 'court clerk', 'clerk of court', 'court reporter',
  'legal intern', 'legal extern')
R('legal_attorney',
  'attorney', 'lawyer', 'general counsel', 'counsel', 'judge', 'magistrate',
  'prosecutor', 'district attorney', 'public defender', 'solicitor',
  'barrister', 'litigator', 'esquire', 'law partner', 'litigation associate',
  'legal director', 'chief legal officer', 'law office of')
R('legal_support',
  'paralegal', 'litigation support', 'litigation assistant', 'legal analyst',
  'legal specialist', 'legal coordinator', 'legal operations', 'legal clerk',
  'contract administrator', 'contracts administrator', 'contract manager',
  'contracts manager', 'contract specialist', 'contract analyst',
  'contract coordinator', 'contracts specialist', 'contract associate',
  'notary', 'title examiner', 'legal researcher', 'patent agent',
  'compliance attorney', 'legal nurse', 'legal department')
R('protective_services', 'probation officer', 'parole officer',
  'probation and parole', 'juvenile probation')
R('government_policy',
  'policy analyst', 'policy advisor', 'policy director', 'policy manager',
  'policy coordinator', 'policy associate', 'policy fellow', 'policy intern',
  'public policy', 'legislative assistant', 'legislative aide',
  'legislative director', 'legislative intern', 'legislative analyst',
  'legislative correspondent', 'legislator', 'state senator', 'senator',
  'congressman', 'congresswoman', 'congressional', 'city council',
  'council member', 'councilman', 'councilwoman', 'mayor', 'city manager',
  'town manager', 'county administrator', 'government affairs',
  'governmental affairs', 'regulatory affairs', 'foreign service', 'diplomat',
  'consular', 'embassy', 'intelligence analyst', 'urban planner',
  'city planner', 'regional planner', 'transportation planner', 'land use',
  'program analyst', 'civil servant', 'public administrator', 'city clerk',
  'town clerk', 'county clerk', 'code enforcement', 'building inspector',
  'health inspector', 'zoning', 'economic development', 'election',
  'government relations', 'public sector', 'federal government',
  'capitol hill', 'political director', 'campaign organizer',
  'legislative counsel', 'district director', 'district representative',
  'political consultant', 'lobbyist', 'community development')
R('project_program_mgmt', 'program manager', 'program management')
R('sales', 'business development')
R('product_management', 'product development')
R('nonprofit_program',
  'program coordinator', 'program director', 'program associate',
  'program assistant', 'program specialist', 'program officer',
  'program administrator', 'program supervisor', 'program intern',
  'program aide', 'program lead', 'community organizer', 'community outreach',
  'outreach coordinator', 'outreach specialist', 'outreach manager',
  'outreach director', 'outreach associate', 'outreach', 'development director',
  'development associate', 'development manager', 'development coordinator',
  'development officer', 'development assistant', 'development intern',
  'director of development', 'grants manager', 'grant manager',
  'grant coordinator', 'grants administrator', 'grant specialist',
  'grants specialist', 'grants coordinator', 'grant administrator',
  'fundraiser', 'fundraising', 'advancement', 'philanthropy',
  'donor relations', 'donor services', 'major gifts', 'annual fund',
  'volunteer coordinator', 'volunteer manager', 'volunteer director',
  'volunteer services', 'americorps', 'peace corps', 'corps member',
  'missions director', 'community liaison', 'community engagement',
  'community health worker', 'public health', 'health educator',
  'nonprofit', 'non profit', 'workforce development', 'membership coordinator',
  'membership manager', 'membership director', 'chapter president',
  'chapter director', 'community coordinator', 'community specialist',
  'community programs', 'youth program', 'after school program',
  'social impact', 'civic engagement', 'community affairs')
R('social_services',
  'social worker', 'social work', 'case manager', 'case worker', 'caseworker',
  'case management', 'counselor', 'therapist', 'psychotherapist', 'psychologist',
  'youth worker', 'residential counselor', 'victim advocate', 'family advocate',
  'child advocate', 'direct support professional', 'substance abuse',
  'behavioral health', 'mental health', 'crisis counselor', 'crisis worker',
  'intake coordinator', 'intake specialist', 'family services',
  'child welfare', 'foster care', 'adoption', 'housing specialist',
  'housing coordinator', 'vocational rehabilitation', 'peer support',
  'recovery coach', 'community support', 'youth specialist', 'youth advocate',
  'family support', 'family partner', 'counseling', 'therapeutic',
  'social services', 'human services', 'caregiver support', 'group home',
  'residential aide', 'residential supervisor', 'child life specialist',
  'behavior specialist', 'behavioral specialist', 'life skills')
R('clergy',
  'pastor', 'minister', 'ministry', 'priest', 'rabbi', 'imam', 'chaplain',
  'worship leader', 'missionary', 'deacon', 'clergy', 'reverend',
  'campus minister', 'congregation', 'parish', 'religious education',
  'youth director church', 'director of religious', 'cantor', 'evangelist',
  'church planter', 'spiritual director', 'seminarian', 'bishop')

# --- H. finance, banking, real estate --------------------------------------
R('hospitality_food', 'night auditor')
R('trades_logistics', 'freight broker', 'customs broker', 'shipping broker')
R('real_estate',
  'realtor', 'real estate', 'property manager', 'property management',
  'property supervisor', 'property administrator', 'property coordinator',
  'property accountant', 'leasing', 'broker associate', 'associate broker',
  'apartment manager', 'community association manager', 'resident manager',
  'escrow', 'title officer', 'title agent', 'appraiser', 'realty',
  'commercial real estate', 'residential sales', 'mortgage real estate')
R('finance_accounting',
  'accountant', 'accounting', 'controller', 'bookkeeper', 'bookkeeping',
  'auditor', 'audit', 'financial analyst', 'finance manager', 'finance director',
  'finance associate', 'finance intern', 'finance specialist',
  'finance coordinator', 'finance analyst', 'financial manager',
  'financial controller', 'financial reporting', 'financial operations',
  'financial coordinator', 'financial specialist', 'financial assistant',
  'financial systems', 'tax', 'payroll', 'treasury', 'treasurer',
  'accounts payable', 'accounts receivable', 'billing', 'fp and a',
  'cost analyst', 'budget analyst', 'budget manager', 'budget director',
  'revenue analyst', 'collections specialist', 'collections representative',
  'collections agent', 'collections analyst', 'collections clerk',
  'collections manager', 'collections coordinator', 'credit and collections',
  'general ledger', 'accounts specialist', 'cost accounting', 'reimbursement',
  'accounts manager finance', 'financial associate', 'grant accountant')
R('banking_insurance', 'workers compensation', 'workers comp')
R('banking_insurance',
  'financial advisor', 'financial adviser', 'financial planner',
  'financial consultant', 'financial representative', 'financial services',
  'financial professional', 'financial center', 'wealth', 'investment',
  'banker', 'banking', 'loan', 'mortgage', 'underwriter', 'underwriting',
  'insurance', 'claims', 'teller', 'broker', 'portfolio manager',
  'registered representative', 'credit analyst', 'credit manager',
  'credit officer', 'credit specialist', 'risk manager', 'risk analyst',
  'risk management', 'actuary', 'actuarial', 'annuity', 'securities',
  'trader', 'trading', 'equity research', 'hedge fund', 'private equity',
  'venture capital', 'asset manager', 'fund manager', 'bank manager',
  'branch banking', 'financial solutions', 'retirement planning',
  'estate planning', 'adjuster', 'agency owner insurance', 'premium',
  'capital markets', 'treasury management', 'investor', 'financial sales')

# --- I. HR, consulting, business analysis, project management --------------
R('hr_recruiting',
  'human resources', 'human resource', 'recruiter', 'recruiting', 'recruitment',
  'talent acquisition', 'talent management', 'talent partner',
  'talent sourcer', 'talent specialist', 'talent coordinator', 'benefits',
  'compensation', 'staffing', 'employee relations', 'onboarding',
  'personnel', 'sourcer', 'headhunter', 'employment specialist',
  'workforce planning', 'labor relations', 'diversity and inclusion',
  'employee engagement', 'employee experience', 'employee benefits',
  'human capital', 'people partner', 'hiring manager', 'employment manager',
  'employee services', 'payroll and benefits')
R('consulting',
  'management consultant', 'strategy consultant', 'associate consultant',
  'business consultant', 'managing consultant', 'principal consultant',
  'independent consultant', 'consulting associate', 'consulting analyst',
  'consulting manager', 'consulting intern', 'senior consultant',
  'strategy manager', 'strategy director', 'strategy associate',
  'strategy analyst', 'corporate strategy', 'business strategy',
  'engagement manager', 'consulting director', 'consulting partner',
  'lead consultant', 'executive consultant', 'strategic consultant',
  'transformation consultant', 'operations consultant')
R('business_analysis',
  'business analyst', 'operations analyst', 'management analyst',
  'process improvement', 'process analyst', 'quality analyst',
  'business process', 'business systems', 'requirements analyst',
  'operations research analyst', 'continuous improvement',
  'six sigma', 'lean specialist', 'business operations analyst',
  'financial systems analyst', 'compliance analyst', 'compliance officer',
  'compliance manager', 'compliance specialist', 'compliance coordinator',
  'compliance director', 'compliance associate', 'pricing analyst',
  'project analyst', 'product analyst', 'business intelligence analyst')
R('project_program_mgmt',
  'project manager', 'project coordinator', 'scrum master', 'agile coach',
  'project management', 'project lead', 'project administrator',
  'project specialist', 'project assistant', 'project director',
  'project associate', 'project intern', 'project consultant',
  'project officer', 'project control', 'implementation manager',
  'implementation specialist', 'implementation consultant',
  'implementation coordinator', 'portfolio director', 'delivery manager',
  'release manager', 'project scheduler', 'project planner',
  'program coordinator project', 'pmo')

# --- J. sales, retail, service, protective, military, trades ---------------
R('retail',
  'sales associate', 'retail', 'cashier', 'store manager', 'store associate',
  'store director', 'store supervisor', 'store clerk', 'shift lead',
  'shift leader', 'shift supervisor', 'shift manager', 'keyholder',
  'key holder', 'merchandiser', 'merchandising', 'stocker', 'stock associate',
  'stock clerk', 'team member', 'crew member', 'crew trainer', 'sales floor',
  'customer service associate', 'beauty advisor', 'brand representative',
  'head cashier', 'bagger', 'grocery', 'visual merchandiser',
  'personal shopper', 'sales lead', 'cart attendant', 'fitting room',
  'sales clerk', 'counter associate', 'shop assistant', 'store cashier',
  'department supervisor', 'floor supervisor', 'boutique', 'showroom',
  'store owner', 'general merchandise', 'front end associate')
R('sales',
  'sales representative', 'sales manager', 'sales director', 'sales executive',
  'sales consultant', 'sales specialist', 'sales coordinator', 'sales analyst',
  'sales assistant', 'sales support', 'sales operations', 'sales intern',
  'sales agent', 'sales professional', 'sales supervisor', 'sales trainer',
  'sales administrator', 'salesperson', 'sales person', 'inside sales',
  'outside sales', 'field sales', 'territory manager', 'territory sales',
  'territory representative', 'account executive', 'account manager',
  'account director', 'account coordinator', 'account supervisor',
  'account representative', 'account specialist', 'account associate',
  'account consultant', 'national accounts', 'key account', 'client executive',
  'client partner', 'client director', 'client manager', 'client advisor',
  'client relationship', 'business development', 'regional sales',
  'district sales', 'area sales', 'enterprise sales', 'sales engineer',
  'presales', 'pre sales', 'solutions consultant', 'solution consultant',
  'solutions specialist', 'sales recruiter', 'product specialist',
  'commercial manager', 'commercial director', 'revenue manager',
  'sales development', 'selling', 'seller', 'distributor', 'dealer',
  'sales', 'retention specialist', 'renewal specialist', 'vendor manager')
R('customer_service',
  'customer service', 'customer support', 'call center', 'client services',
  'client service', 'customer success', 'customer care', 'customer experience',
  'customer relations', 'client relations', 'contact center', 'customer advocate',
  'customer solutions', 'customer specialist', 'customer representative',
  'customer associate', 'customer operations', 'customer engagement',
  'member services', 'member service', 'client support', 'client associate',
  'client coordinator', 'client specialist', 'client success',
  'service representative', 'support representative', 'support associate',
  'service associate', 'guest relations', 'customer', 'client onboarding')
R('hospitality_food',
  'server', 'waiter', 'waitress', 'bartender', 'barista', 'host', 'hostess',
  'cook', 'line cook', 'prep cook', 'dishwasher', 'busser', 'bus boy',
  'kitchen', 'restaurant', 'catering', 'banquet', 'event coordinator',
  'event manager', 'event planner', 'event specialist', 'event staff',
  'events', 'event director', 'event assistant', 'event intern',
  'wedding', 'hotel', 'concierge', 'housekeeping', 'housekeeper',
  'tour guide', 'flight attendant', 'food service', 'food and beverage',
  'baker', 'bakery', 'bar manager', 'guest service', 'guest services',
  'front office manager', 'front office supervisor', 'front office agent',
  'front desk agent', 'valet', 'bellman', 'room attendant', 'sommelier',
  'food runner', 'expeditor', 'cafe', 'coffee', 'pizza', 'deli', 'cafeteria',
  'travel agent', 'travel consultant', 'travel advisor', 'travel specialist',
  'tourism', 'resort', 'casino', 'cruise', 'lodging', 'reservations',
  'food prep', 'dietary', 'dining', 'hospitality', 'bar back', 'barback',
  'bar tender', 'wait staff', 'waitstaff', 'short order',
  'room service', 'banquet captain', 'sanitation food', 'menu')
R('personal_care_fitness',
  'nanny', 'babysitter', 'baby sitter', 'childcare', 'child care', 'daycare',
  'day care', 'hairstylist', 'hair stylist', 'stylist', 'cosmetologist',
  'esthetician', 'barber', 'salon', 'spa', 'nail technician', 'manicurist',
  'lifeguard', 'pet', 'dog walker', 'groomer', 'grooming', 'fitness', 'gym',
  'yoga', 'wellness', 'recreation', 'funeral', 'mortician', 'beautician',
  'aesthetician', 'skin care', 'makeup', 'child development associate',
  'preschool aide', 'au pair', 'nursery attendant', 'youth sports',
  'sports instructor', 'aquatics', 'ski instructor', 'golf professional',
  'activities assistant', 'recreational aide')
R('protective_services',
  'police', 'sheriff', 'detective', 'firefighter', 'fire fighter',
  'fire captain', 'fire chief', 'security officer', 'security guard',
  'security supervisor', 'security manager', 'security specialist',
  'security professional', 'security director', 'security agent',
  'corrections', 'correctional', 'loss prevention', 'tsa', 'border patrol',
  'special agent', 'public safety', 'patrol', 'trooper', 'constable',
  'bailiff', 'armed guard', 'surveillance', 'investigator', 'emergency management',
  'fire marshal', 'deputy sheriff', 'sheriff deputy', 'crossing guard',
  'dispatcher emergency', 'emergency dispatcher', 'law enforcement',
  'security screener', 'campus safety', 'bouncer', 'watch commander')
R('military',
  'army', 'navy', 'air force', 'marine corps', 'marines', 'coast guard',
  'military', 'soldier', 'sergeant', 'lieutenant', 'corporal',
  'private first class', 'petty officer', 'airman', 'veteran',
  'national guard', 'rotc', 'cadet', 'midshipman', 'infantry', 'platoon',
  'squad leader', 'commander', 'captain', 'battalion', 'brigade',
  'drill instructor', 'combat', 'aviator', 'seaman', 'ensign',
  'warrant officer', 'colonel', 'gunnery', 'signal officer', 'artillery',
  'logistics officer', 'company commander', 'squadron', 'deployment',
  'military police', 'submarine', 'naval', 'aircrew')
R('design_ux', 'production assistant', 'production intern', conf='low')
R('trades_logistics',
  'driver', 'truck', 'warehouse', 'forklift', 'machine operator', 'machinist',
  'mechanic', 'maintenance technician', 'field technician', 'service technician',
  'hvac', 'electrician', 'plumber', 'carpenter', 'welder', 'laborer',
  'construction', 'foreman', 'assembler', 'assembly', 'production',
  'logistics', 'supply chain', 'buyer', 'purchasing', 'procurement',
  'dispatcher', 'delivery', 'courier', 'pilot', 'mail carrier', 'postal',
  'landscaper', 'landscaping', 'janitor', 'custodian', 'farm', 'installer',
  'installation technician', 'roofer', 'mason', 'diesel', 'automotive',
  'auto technician', 'equipment operator', 'crane', 'heavy equipment',
  'shipping', 'receiving', 'inventory', 'material handler', 'packer',
  'order picker', 'fulfillment', 'distribution', 'freight', 'transportation',
  'fleet', 'route', 'trucking', 'tractor trailer', 'cdl', 'aircraft',
  'avionics', 'aviation', 'maintenance', 'groundskeeper', 'lineman',
  'sanitation', 'recycling', 'manufacturing', 'fabricator', 'tool and die',
  'cnc', 'press operator', 'plant manager', 'plant supervisor',
  'utility worker', 'field service', 'service advisor', 'parts manager',
  'parts specialist', 'body shop', 'tire technician', 'boiler',
  'millwright', 'rigger', 'surveying technician', 'wastewater', 'pipeline',
  'oil and gas', 'drilling', 'mining', 'longshoreman', 'stevedore',
  'facilities technician', 'facilities coordinator', 'facilities manager',
  'facility manager', 'facilities director', 'facilities supervisor',
  'building maintenance', 'general contractor', 'subcontractor', 'apprentice',
  'journeyman', 'sheet metal', 'insulator', 'glazier', 'ironworker',
  'operations technician', 'process technician', 'production technician',
  'warehouse associate', 'package handler', 'material handling')

# --- K. administrative & office support ------------------------------------
R('admin_support',
  'receptionist', 'secretary', 'office manager', 'front desk', 'scheduler',
  'scheduling coordinator', 'scheduling specialist', 'mailroom', 'file clerk',
  'typist', 'switchboard', 'records clerk', 'clerical', 'general office',
  'assistant to', 'executive support', 'office services', 'records specialist',
  'records manager', 'document control', 'document specialist',
  'data coordinator admin', 'intake clerk', 'front office coordinator',
  'department assistant', 'unit assistant', 'support assistant',
  'business office', 'reception', 'greeter', 'concierge services',
  'file specialist', 'clerk')

# --- L. ownership, executive, general management ---------------------------
R('founder_owner',
  'owner', 'founder', 'co founder', 'cofounder', 'proprietor', 'self employed',
  'freelance', 'freelancer', 'independent contractor', 'entrepreneur',
  'franchisee', 'franchise owner', 'business owner', 'sole proprietor',
  'managing member', 'shareholder', 'co owner', 'principal owner',
  'owner operator', 'founding partner', 'startup founder', 'small business',
  'independent distributor', 'independent business', 'private practice',
  'self proprietor', 'llc member', 'principal partner')
R('general_management', 'vice president', 'vice chancellor', 'vice chair',
  'vice provost')
R('executive', 'president', 'chairman', 'chairwoman', 'chairperson',
  'chief executive', 'chief operating', 'chief financial', 'chief technology',
  'chief information', 'chief administrative', 'chief strategy',
  'chief revenue', 'chief commercial', 'chief officer', 'c suite')
RX('executive', r'\bchief\s+[a-z]+(\s+[a-z]+)?\s+officer\b', ['chief'])
R('general_management',
  'general manager', 'operations manager', 'operations director',
  'operations supervisor', 'operations coordinator', 'operations specialist',
  'operations associate', 'operations assistant', 'operations lead',
  'operations intern', 'operations officer', 'business operations',
  'assistant manager', 'branch manager', 'district manager',
  'regional manager', 'area manager', 'division manager', 'unit manager',
  'center manager', 'site manager', 'business manager', 'department manager',
  'general management', 'managing officer', 'head of operations',
  'director of operations', 'operations', 'management trainee',
  'business administrator', 'executive officer', 'deputy director',
  'associate director', 'assistant director', 'senior director',
  'associate manager', 'assistant general manager', 'team manager',
  'group manager', 'corporate manager', 'senior manager', 'executive manager')

# --- M0. additional specific nouns (from residual analysis) ----------------
R('engineering', 'safety manager', 'safety coordinator', 'safety specialist',
  'safety director', 'safety officer', 'safety supervisor', 'safety engineer',
  'environmental health and safety', 'ehs', 'safety consultant',
  'industrial hygienist', 'safety analyst', 'safety technician')
R('government_policy', 'field organizer', 'canvasser', 'enumerator',
  'commissioner', 'contracting officer', 'contract officer', 'patent examiner',
  'legislative liaison', 'branch chief', 'section chief', 'division chief',
  'field representative political', 'precinct')
R('legal_support', 'mediator', 'arbitrator', 'title closer')
R('retail', 'bookseller', 'guest advocate', 'mobile expert', 'genius bar',
  'floor staff', 'sales genius', 'merchant', 'front end cashier')
R('sales', 'telemarketer', 'appointment setter', 'salesman', 'saleswoman',
  'sales woman', 'closer', 'brand partner', 'strategic partnerships',
  'inside sales representative', 'medical sales', 'territory representative')
R('healthcare_clinical', 'internal medicine', 'family medicine',
  'emergency medicine', 'medicine resident', 'exercise physiologist',
  'respiratory care practitioner', 'infection preventionist',
  'medical science liaison', 'clinical liaison', 'acupuncturist',
  'diabetes educator', 'radiology technologist', 'hospital corpsman',
  'physiologist', 'orthoptist', 'medical officer', 'hospice nurse',
  'histotechnician', 'medical technician laboratory')
R('healthcare_support', 'patient transporter', 'standardized patient',
  'personal care attendant', 'care provider', 'caretaker', 'psychometrist',
  'specimen processor', 'medical courier', 'sterile technician')
R('social_services', 'job coach', 'success coach', 'client advocate',
  'peer advocate', 'family partner advocate', 'advocate',
  'direct support', 'community health advocate')
R('nonprofit_program', 'organizer', 'community builder', 'program evaluator')
R('military', 'corpsman', 'infantryman', 'commanding officer',
  'non commissioned officer', 'noncommissioned officer', 'intelligence officer',
  'marine', 'united states marine', 'security forces', 'artilleryman',
  'crew chief', 'flight engineer', 'operations sergeant', 'recruiter military')
R('protective_services', 'detention officer', 'correction officer',
  'patrolman', 'community service officer', 'park ranger', 'ranger',
  'security', 'asset protection', 'jailer', 'gate guard', 'watchman')
R('trades_logistics', 'draftsman', 'pipefitter', 'deckhand', 'loader',
  'detailer', 'handyman', 'order selector', 'picker', 'grader', 'mover',
  'builder', 'ranch hand', 'gardener', 'cleaner', 'meat cutter', 'driller',
  'mail handler', 'letter carrier', 'city carrier', 'materials planner',
  'material planner', 'supply planner', 'demand planner', 'merchandise planner',
  'inventory planner', 'purchaser', 'receiver', 'processor', 'crew leader',
  'welding inspector', 'field inspector', 'home inspector', 'inspector',
  'tech support field', 'helper', 'farmer', 'rancher', 'horticulturist',
  'greenhouse', 'arborist', 'exterminator', 'pest control', 'locksmith',
  'upholsterer', 'seamstress', 'tailor', 'printer', 'bindery', 'press man',
  'pressman', 'silk screen', 'planner')
R('finance_accounting', 'comptroller', 'collector', 'debt collector',
  'finance officer', 'assurance staff', 'assurance senior',
  'assurance associate', 'billing coordinator', 'revenue accountant')
R('banking_insurance', 'trust officer', 'paraplanner', 'examiner',
  'internal wholesaler', 'wholesaler', 'financial coach', 'bank officer')
R('it_support', 'webmaster', 'tech support', 'technical expert', 'tech lead',
  'tech specialist', 'tech analyst', 'tech manager', 'tech director')
R('software', 'tester', 'qa', 'software quality assurance', 'mts')
R('marketing', 'strategist', 'marketer', 'creative strategist',
  'media strategist', 'brand strategist', 'creator')
R('consulting', 'subject matter expert', 'expert', 'business coach',
  'executive coach', 'advisory board consultant')
R('hr_recruiting', 'business partner', 'interviewer', 'hiring coordinator')
R('admin_support', 'transcriptionist', 'office staff', 'support staff',
  'data processor', 'page', 'administrative professional')
R('teaching_k12', 'educator', 'educational diagnostician', 'school aide',
  'lunch aide', 'playground', 'school secretary')
R('research', 'economist', 'archaeologist', 'anthropologist', 'sociologist',
  'political scientist', 'demographer', 'scholar', 'research technologist',
  'analyst research')
R('science_lab', 'meteorologist', 'geophysicist', 'technologist',
  'seismologist', 'hydrogeologist', 'agronomist', 'entomologist')
R('arts_performance', 'songwriter', 'audiobook narrator', 'narrator',
  'athlete', 'referee', 'umpire', 'public speaker', 'motivational speaker',
  'keynote speaker', 'guest speaker', 'promoter', 'lyricist', 'busker',
  'cosplayer', 'voice actor', 'body painter')
R('journalism_media', 'on air personality', 'radio personality', 'podcaster',
  'presenter', 'media personality', 'talk radio', 'news anchor')
R('writing_editing', 'contributor', 'blogger', 'copyeditor', 'script reader',
  'columnist', 'writing consultant', 'writing tutor')
R('hospitality_food', 'usher', 'caterer', 'porter', 'front of house',
  'sandwich maker', 'cake decorator', 'brewer', 'bartending', 'runner',
  'attendant', 'snack bar', 'concession')
R('personal_care_fitness', 'caddie', 'caddy', 'performance coach',
  'sports official', 'cheerleading coach', 'nail artist')
R('student', 'graduate trainee', 'mentee', 'clinical rotation',
  'recent graduate', 'new graduate')
R('volunteer_board', 'board observer', 'co chair', 'delegate', 'observer',
  'honorary')
R('not_working', 'retiree', 'stay at home mom', 'stay at home dad',
  'stay at home parent', 'homemaker parent')
R('general_management', 'deputy chief', 'regional director',
  'area director', 'country manager', 'department head', 'special projects',
  'operating partner', 'limited partner', 'venture partner', 'general partner')
R('real_estate', 'landman', 'land agent')
R('legal_support', 'litigation')
R('healthcare_clinical', 'imaging', 'radiology')
R('banking_insurance', 'brokerage')
R('finance_accounting', 'financial planning and analysis',
  'financial planning analyst')
R('engineering', 'architecture')
R('design_ux', 'creative')
R('healthcare_support', 'contact tracer', 'pca', 'pta', 'cota',
  'certified nursing aide', 'dsp', 'coder', 'coding specialist',
  'coding manager', 'coding auditor')
R('science_lab', 'conservation', 'toxicology', 'microbiology', 'biology',
  'chemistry', 'geology', 'ecology')
R('banking_insurance', 'commercial lines', 'personal lines')
R('real_estate', 'property owner', 'investment property', 'rental property')
R('personal_care_fitness', 'coach', 'coaching', 'mixologist nail')
R('healthcare_clinical', 'oncology', 'cardiology', 'pediatrics', 'pediatric',
  'obstetrics', 'orthopedic', 'neurology', 'urology', 'dermatology',
  'emergency department', 'intensive care', 'operating room', 'surgical services',
  'primary care', 'urgent care', 'ambulatory', 'perioperative')
R('it_support', 'computer services', 'computer center')
R('healthcare_clinical', 'resident', 'orthodontist', 'chief resident',
  'surgery resident', 'medical fellow')
R('military', 'commissioned officer', 'surface warfare', 'cavalry scout',
  'active duty', 'armed forces', 'military police officer')
R('protective_services', 'school resource officer', 'resource officer')
R('hospitality_food', 'mixologist', 'visitor services', 'banquet captain')
R('retail', 'florist', 'flower shop')
R('science_lab', 'forester', 'forestry')
R('arts_performance', 'set decorator', 'set designer', 'on air talent')
R('writing_editing', 'book reviewer', 'reader')
R('banking_insurance', 'commercial lender', 'lender', 'fiscal officer',
  'financial officer', 'assessor', 'collections')
R('customer_service', 'client liaison', 'customer liaison')
R('healthcare_support', 'navigator')
R('research', 'evaluator', 'research staff')
R('marketing', 'growth')
R('it_support', 'tech', 'technology')
R('trades_logistics', 'materials handler', 'compositor', 'bindery operator')
R('sales', 'vendor', 'merchandise vendor')
R('other_education', 'training officer', 'education officer')
R('arts_performance', 'disk jockey')
R('student', 'graduate', 'alumnus', 'alumni ambassador')
R('not_working', 'mom', 'dad', 'parent')

# --- M. late generics (low confidence by construction) ---------------------
R('general_management', 'manager', 'director', 'supervisor', 'head of',
  'management', 'leadership', conf='low')
R('consulting', 'consultant', 'consulting', 'advisor', 'adviser', conf='low')
R('business_analysis', 'analyst', 'analysis', conf='low')
R('business_analysis', 'specialist', 'associate', 'generalist', conf='low')
R('admin_support', 'coordinator', 'assistant', 'administrative', 'administrator',
  'clerk', 'aide', conf='low')
R('sales', 'representative', 'agent', 'account', conf='low')
R('trades_logistics', 'technician', 'operator', 'worker', 'laborer',
  'mechanic', conf='low')
R('research', 'fellow', 'fellowship', conf='low')
R('intern', 'intern', 'internship', 'extern', 'externship', 'co op',
  'trainee', conf='high')
R('student', 'student', conf='low')
R('volunteer_board', 'volunteer', 'member', 'ambassador', 'mentor', conf='low')
R('not_working', 'retired', 'former', 'semi retired', conf='low')
R('founder_owner', 'independent', 'principal', conf='low')
R('general_management', 'lead', 'leader', 'professional', 'executive',
  conf='low')

# ---------------------------------------------------------------------------
# trigger index
# ---------------------------------------------------------------------------
_TRIG_INDEX = {}
for _i, _rule in enumerate(_RULES):
    for _t in _rule[4]:
        _TRIG_INDEX.setdefault(_t, []).append(_i)


def _match_family(padded, tokens):
    idxs = None
    seen = set()
    for t in tokens:
        lst = _TRIG_INDEX.get(t)
        if lst:
            if idxs is None:
                idxs = []
            for i in lst:
                if i not in seen:
                    seen.add(i)
                    idxs.append(i)
    if not idxs:
        return None
    idxs.sort()
    for i in idxs:
        family, conf, phrases, rx, _ = _RULES[i]
        if rx is not None:
            if rx.search(padded):
                return family, conf
        else:
            for p in phrases:
                if p in padded:
                    return family, conf
    return None


# ---------------------------------------------------------------------------
# seniority
# ---------------------------------------------------------------------------
_INTERN_PHRASES = (' intern ', ' interns ', ' interning ', ' internship ',
                   ' extern ', ' externship ', ' co op ', ' coop ',
                   ' summer analyst ', ' summer associate ', ' practicum ',
                   ' intership ', ' internhip ', ' summer intern ')
_INTERN_EXCLUDE = (' internship coordinator ', ' intern coordinator ',
                   ' internship program ', ' intern supervisor ',
                   ' internship director ', ' internship manager ',
                   ' intern manager ', ' internship recruiter ',
                   ' internship advisor ', ' coop manager ')
_OWNER_TOKENS = frozenset(('owner', 'founder', 'cofounder', 'proprietor',
                           'entrepreneur', 'franchisee', 'shareholder'))
_OWNER_PHRASES = (' co founder ', ' self employed ', ' sole proprietor ',
                  ' managing member ', ' independent contractor ',
                  ' owner operator ')
_PARTNER_EXCLUDE = (' business partner ', ' channel partner ', ' partner manager ',
                    ' partner development ', ' partner relations ',
                    ' talent acquisition partner ', ' partner marketing ',
                    ' partner success ', ' partner specialist ',
                    ' implementation partner ', ' delivery partner ',
                    ' learning partner ', ' partner engineer ',
                    ' people partner ', ' partner solutions ',
                    ' strategic partner ', ' partner account ',
                    ' partner program ', ' partner services ',
                    ' partner center ', ' partner relations manager ',
                    ' client partner ', ' partner support ', ' partner sales ')
_SENIOR_EXCLUDE = (' senior living ', ' senior center ', ' senior citizen ',
                   ' senior services ', ' senior community ', ' senior care ',
                   ' seniors ', ' senior housing ', ' senior nutrition ')
_STAFF_SENIOR = (' engineer ', ' scientist ', ' developer ', ' architect ',
                 ' researcher ', ' software ', ' designer ', ' programmer ')
_ASSIST_MID = (' executive assistant ', ' administrative assistant ',
               ' personal assistant ', ' physician assistant ',
               ' executive administrative assistant ', ' assistant to ',
               ' administrative assistant ii ', ' medical assistant ',
               ' dental assistant ')
_LEAD_EXCLUDE = (' lead generation ', ' leads ', ' lead qualification ',
                 ' sales lead ', ' lead specialist ', ' lead development ')
_ASSIST_TITLE_NOUN = (' executive assistant ', ' administrative assistant ',
                      ' personal assistant ', ' assistant to ')
_OWNER_NOT = (' product owner ', ' process owner ', ' data owner ',
              ' service owner ', ' platform owner ', ' application owner ',
              ' story owner ', ' owner representative ')


def _seniority(padded, tokens, family):
    tset = frozenset(tokens)

    # ---- intern short-circuits everything ------------------------------
    if any(p in padded for p in _INTERN_PHRASES):
        if not any(p in padded for p in _INTERN_EXCLUDE):
            return 'intern'

    # ---- "executive assistant to the CEO" is not a CEO ------------------
    if any(p in padded for p in _ASSIST_TITLE_NOUN):
        return 'mid'

    ranks = []

    # ---- owner ---------------------------------------------------------
    owner_tok = bool(_OWNER_TOKENS & tset)
    if owner_tok and 'owner' in tset:
        tmp = padded
        for ph in _OWNER_NOT:
            tmp = tmp.replace(ph, ' ')
        if ' owner ' not in tmp and not (_OWNER_TOKENS - {'owner'}) & tset:
            owner_tok = False
    owner = owner_tok or any(p in padded for p in _OWNER_PHRASES)
    if not owner and 'partner' in tset:
        if not any(p in padded for p in _PARTNER_EXCLUDE):
            owner = True
    if owner:
        return 'owner'

    # ---- c-suite -------------------------------------------------------
    csuite = False
    if 'chief' in tset and ('officer' in tset or ' chief executive ' in padded
                            or ' chief operating ' in padded
                            or ' chief financial ' in padded):
        csuite = True
    if ' president ' in padded and ' vice president ' not in padded:
        csuite = True
    if tset & {'chairman', 'chairwoman', 'chairperson', 'chancellor', 'provost'}:
        csuite = True
    if ' executive director ' in padded or ' managing director ' in padded:
        csuite = True
    if family == 'school_admin' and 'superintendent' in tset:
        csuite = True
    if csuite:
        ranks.append(7)

    # ---- vp ------------------------------------------------------------
    if (' vice president ' in padded or ' vice chancellor ' in padded
            or ' vice chair ' in padded or ' vice provost ' in padded):
        ranks.append(6)

    # ---- director ------------------------------------------------------
    if ('director' in tset or ' head of ' in padded or 'dean' in tset
            or ' department head ' in padded or ' chief of staff ' in padded
            or 'chair' in tset
            or (family == 'school_admin' and 'principal' in tset)):
        ranks.append(5)

    # ---- manager -------------------------------------------------------
    manager = False
    if 'controller' in tset and family == 'finance_accounting':
        manager = True
    if tset & {'manager', 'supervisor', 'foreman', 'superintendent',
               'headmaster', 'headmistress', 'principal'} and not (
            family != 'school_admin' and 'principal' in tset
            and 'manager' not in tset and 'supervisor' not in tset):
        manager = True
    if 'head' in tset and ' head start ' not in padded:
        manager = True
    if tokens and tokens[-1] == 'lead' and not any(p in padded for p in _LEAD_EXCLUDE):
        manager = True
    if manager:
        ranks.append(4)

    # ---- senior --------------------------------------------------------
    senior = False
    if 'senior' in tset and not any(p in padded for p in _SENIOR_EXCLUDE):
        senior = True
    if 'lead' in tset and not any(p in padded for p in _LEAD_EXCLUDE):
        senior = True
    if 'principal' in tset and family != 'school_admin':
        senior = True
    if 'staff' in tset and any(p in padded for p in _STAFF_SENIOR):
        senior = True
    if tset & {'iii', 'iv', 'master'}:
        senior = True
    if senior:
        ranks.append(3)

    # ---- entry ---------------------------------------------------------
    entry = False
    if 'junior' in tset or ' entry level ' in padded:
        entry = True
    if tset & {'trainee', 'apprentice', 'aide', 'clerk', 'helper', 'cadet'}:
        entry = True
    if 'coordinator' in tset:
        entry = True
    if 'fellow' in tset or ' postdoc ' in padded or ' postdoctoral ' in padded \
            or ' post doctoral ' in padded:
        entry = True
    if 'resident' in tset and family == 'healthcare_clinical':
        entry = True
    if 'assistant' in tset and not any(p in padded for p in _ASSIST_MID):
        entry = True
    if 'associate' in tset:
        if not (family == 'higher_ed_faculty' or family == 'legal_attorney'):
            entry = True
    if family == 'higher_ed_faculty' and (' assistant professor ' in padded
                                          or ' associate professor ' in padded):
        entry = False
    if entry:
        ranks.append(1)

    if not ranks:
        return 'mid'
    top = max(ranks)
    # juniority never survives a management head noun
    if top == 1 and len(ranks) > 1:
        top = max(r for r in ranks if r != 1)
    return SENIORITY[top]


# ---------------------------------------------------------------------------
# flags
# ---------------------------------------------------------------------------
_FLAG_ORDER = ['intern', 'ta', 'self_employed', 'volunteer', 'part_time',
               'contract', 'seasonal', 'temporary', 'interim', 'former',
               'student']


def _flags(padded, tset, family, seniority, modflags):
    out = set()
    for m in modflags:
        if m in ('part time', 'parttime', 'p t', 'pt'):
            out.add('part_time')
        elif m in ('volunteer', 'unpaid'):
            out.add('volunteer')
        elif m in ('contract', 'contractor', 'contract to hire', 'temp to hire',
                   'contract position', 'contract role', '1099'):
            out.add('contract')
        elif m in ('temporary', 'temp'):
            out.add('temporary')
        elif m == 'seasonal':
            out.add('seasonal')
        elif m in ('interim', 'acting'):
            out.add('interim')
        elif m in ('former', 'retired'):
            out.add('former')
        elif m in ('freelance', 'self employed', 'independent'):
            out.add('self_employed')
        elif m in ('intern', 'internship', 'co op', 'coop'):
            out.add('intern')
    if seniority == 'intern' and family != 'intern':
        out.add('intern')
    if (' freelance ' in padded or ' freelancer ' in padded
            or ' self employed ' in padded or ' independent contractor ' in padded
            or ' sole proprietor ' in padded or ' private practice ' in padded
            or ' independent consultant ' in padded
            or ' owner operator ' in padded):
        out.add('self_employed')
    if ' part time ' in padded or ' parttime ' in padded:
        out.add('part_time')
    if 'volunteer' in tset:
        out.add('volunteer')
    if ' teaching assistant ' in padded:
        out.add('ta')
    if 'seasonal' in tset:
        out.add('seasonal')
    if 'temporary' in tset or ' temp ' in padded:
        out.add('temporary')
    if 'interim' in tset or 'acting' in tset:
        out.add('interim')
    if ('former' in tset or 'retired' in tset or ' past ' in padded) \
            and family != 'not_working':
        out.add('former')
    if 'contract' in tset and 'contractor' not in tset \
            and family not in ('legal_support',):
        out.add('contract')
    if 'student' in tset and family != 'student':
        out.add('student')
    return [f for f in _FLAG_ORDER if f in out]


# ---------------------------------------------------------------------------
# public API
# ---------------------------------------------------------------------------
def classify_title(s):
    """Classify one free-text job title."""
    norm, tokens, modflags = normalize(s)
    if not norm:
        return {'family': 'unclassified', 'seniority': 'mid', 'flags': [],
                'confidence': 'low'}
    padded = ' ' + norm + ' '
    hit = _EXACT.get(norm)
    if hit is not None:
        family, conf = hit
    else:
        m = _match_family(padded, tokens)
        if m is None:
            family, conf = 'unclassified', 'low'
        else:
            family, conf = m

    seniority = _seniority(padded, tokens, family)
    if family == 'intern':
        seniority = 'intern'
    elif family == 'student' and seniority in ('mid', 'entry'):
        seniority = 'entry'
    flags = _flags(padded, frozenset(tokens), family, seniority, modflags)
    if family == 'unclassified':
        conf = 'low'
    return {'family': family, 'seniority': seniority, 'flags': flags,
            'confidence': conf}


if __name__ == '__main__':
    import json
    import sys
    for arg in sys.argv[1:]:
        print(arg, '->', json.dumps(classify_title(arg)))

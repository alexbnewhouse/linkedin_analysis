"""The NHA director's deductive framework, transcribed as data.

Nine skill archetypes, each with a first-person orientation, a signature-skills
list, and career pathways with representative roles. Plus the two orthogonal
dimensions (sector, work context). Source: the director's draft as pasted on
2026-09-17; the greppable copy of the same document lives in
docs/notes/nha-career-skill-archetypes-framework.md.

This module holds no logic beyond flattening the seeds. Every deductive and
mixed method reads its priors from here so that "the literature" is one place.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Archetype:
    id: int
    key: str
    label: str
    orientation: str
    skills: tuple[str, ...]
    pathways: dict[str, tuple[str, ...]]  # pathway -> representative roles


ARCHETYPES: tuple[Archetype, ...] = (
    Archetype(
        1, "communicators", "Communicators & Creators",
        "I turn ideas into messages, stories, and experiences that engage an audience.",
        ("close reading", "clear and persuasive writing", "editing and revision",
         "rhetorical analysis", "audience awareness", "argument construction",
         "storytelling", "interpretation", "synthesis",
         "translating complex ideas for different audiences", "oral presentation",
         "media and visual literacy", "creative ideation", "content strategy"),
        {
            "Writing & Editorial": (
                "Writer", "Staff Writer", "Copywriter", "Editor", "Copy Editor",
                "Managing Editor", "Editorial Director", "Technical Writer",
                "Medical Writer", "Speechwriter", "Ghostwriter"),
            "Communications & PR": (
                "Communications Coordinator", "Communications Specialist",
                "Communications Manager", "Communications Director", "PR Specialist",
                "Publicist", "Media Relations Specialist", "Public Affairs Specialist",
                "Press Secretary"),
            "Content & Digital Media": (
                "Content Writer", "Content Specialist", "Content Strategist",
                "Content Manager", "Social Media Specialist", "Social Media Manager",
                "Digital Content Manager", "Web Content Manager", "Podcast Producer"),
            "Marketing & Brand": (
                "Marketing Coordinator", "Marketing Specialist",
                "Marketing Communications Manager", "Brand Strategist", "Brand Manager",
                "Campaign Manager", "Creative Strategist"),
            "Design & Creative": (
                "Graphic Designer", "Visual Designer", "UX Writer", "Content Designer",
                "Creative Producer", "Art Director", "Creative Director", "Illustrator"),
            "Film, Audio & Media Production": (
                "Photographer", "Videographer", "Filmmaker", "Video Editor", "Producer",
                "Multimedia Producer", "Audio Producer", "Podcast Producer",
                "Documentary Producer"),
            "Interpretation & Public Humanities": (
                "Interpretive Planner", "Exhibit Developer",
                "Museum Interpretation Specialist", "Public Historian",
                "Humanities Program Producer", "Cultural Content Specialist"),
        },
    ),
    Archetype(
        2, "researchers", "Researchers & Educators",
        "I discover, interpret, organize, and share knowledge.",
        ("research question development", "primary- and secondary-source research",
         "source evaluation", "information literacy", "close reading",
         "archival and library research", "contextualization", "qualitative inquiry",
         "interviewing", "synthesis across sources", "citation and documentation",
         "interpretation", "teaching and discussion facilitation", "knowledge translation"),
        {
            "Academic Research": (
                "Research Assistant", "Research Associate", "Research Fellow", "Researcher",
                "Historian", "Scholar", "Postdoctoral Fellow", "Research Professor",
                "Research Director"),
            "Applied Research & Insights": (
                "UX Researcher", "Market Researcher", "Qualitative Researcher",
                "Audience Researcher", "Consumer Insights Researcher", "Research Consultant",
                "Insights Manager"),
            "Policy & Social Research": (
                "Policy Researcher", "Social Science Researcher", "Research Analyst",
                "Survey Researcher", "Think Tank Researcher", "Public Policy Researcher"),
            "Teaching & Higher Education": (
                "Teacher", "Lecturer", "Instructor", "Professor", "Teaching Professor",
                "Academic Program Director", "Department Chair"),
            "Learning & Development": (
                "Instructional Designer", "Curriculum Developer", "Learning Specialist",
                "Corporate Trainer", "Learning & Development Specialist",
                "Learning Experience Designer", "Training Manager"),
            "Libraries, Archives & Knowledge": (
                "Librarian", "Archivist", "Digital Archivist", "Records Specialist",
                "Knowledge Manager", "Information Specialist", "Research Librarian"),
            "Museums & Cultural Research": (
                "Curatorial Assistant", "Curator", "Collections Researcher",
                "Museum Researcher", "Public Historian", "Museum Educator",
                "Education Program Manager"),
            "Institutional & Prospect Research": (
                "Institutional Research Analyst", "Prospect Researcher",
                "Advancement Researcher", "Research Services Manager",
                "Institutional Research Director"),
        },
    ),
    Archetype(
        3, "analysts", "Analysts & Strategists",
        "I make sense of complexity, identify patterns, and help organizations decide what to do.",
        ("critical analysis", "close reading of complex material",
         "comparison and pattern recognition", "synthesis across multiple sources",
         "contextual reasoning", "evidence-based argumentation", "identifying assumptions",
         "framing problems", "interpreting ambiguity", "evaluating competing explanations",
         "ethical and historical perspective", "clear recommendation writing",
         "strategic thinking"),
        {
            "Business Analysis": (
                "Business Analyst", "Senior Business Analyst", "Business Intelligence Analyst",
                "Operations Analyst", "Management Analyst"),
            "Strategy": (
                "Strategy Analyst", "Strategy Associate", "Strategic Planning Manager",
                "Corporate Strategist", "Strategy Director", "Chief Strategy Officer"),
            "Consulting": (
                "Analyst", "Associate Consultant", "Management Consultant",
                "Strategy Consultant", "Organizational Consultant", "Principal Consultant"),
            "Policy Analysis": (
                "Policy Analyst", "Legislative Analyst", "Regulatory Analyst",
                "Public Policy Analyst", "Senior Policy Analyst"),
            "Program Evaluation": (
                "Program Analyst", "Program Evaluator", "Evaluation Specialist",
                "Monitoring & Evaluation Specialist", "Impact Evaluation Manager"),
            "Insights & Intelligence": (
                "Insights Analyst", "Competitive Intelligence Analyst", "Intelligence Analyst",
                "Market Intelligence Analyst", "Research Strategist"),
            "Organizational Strategy": (
                "Organizational Development Specialist", "Change Management Consultant",
                "Organizational Effectiveness Manager", "Workforce Strategy Analyst"),
            "Institutional Strategy": (
                "Institutional Research Analyst", "Planning Analyst",
                "Higher Education Strategy Analyst", "Institutional Effectiveness Director"),
        },
    ),
    Archetype(
        4, "advocates", "Advocates & Advisors",
        "I help people and organizations navigate decisions, institutions, rules, and competing interests.",
        ("argumentation", "persuasive writing and speaking", "textual and policy interpretation",
         "evidence evaluation", "ethical reasoning", "perspective-taking",
         "debate and discussion", "research", "stakeholder communication", "negotiation",
         "mediation", "judgment", "explaining complex rules and ideas clearly",
         "constructing and assessing competing claims"),
        {
            "Law & Legal Services": (
                "Paralegal", "Legal Assistant", "Legal Analyst", "Attorney", "Counsel",
                "General Counsel"),
            "Policy & Legislative Affairs": (
                "Legislative Assistant", "Legislative Analyst", "Legislative Director",
                "Policy Advisor", "Senior Policy Advisor", "Policy Director"),
            "Government & Public Affairs": (
                "Government Affairs Associate", "Government Relations Manager",
                "Public Affairs Manager", "Government Affairs Director"),
            "Advocacy": (
                "Advocacy Coordinator", "Advocate", "Advocacy Manager", "Campaign Manager",
                "Advocacy Director", "Grassroots Organizer"),
            "Compliance & Ethics": (
                "Compliance Specialist", "Compliance Analyst", "Compliance Manager",
                "Ethics Officer", "Regulatory Affairs Specialist"),
            "Advising": (
                "Academic Advisor", "Career Advisor", "Student Success Advisor",
                "Admissions Counselor", "Financial Aid Advisor", "International Student Advisor"),
            "Mediation & Conflict Resolution": (
                "Mediator", "Conflict Resolution Specialist", "Employee Relations Specialist",
                "Labor Relations Specialist", "Ombuds"),
            "Community & Constituent Affairs": (
                "Constituent Services Representative", "Community Advocate",
                "Community Affairs Specialist", "Community Relations Manager"),
        },
    ),
    Archetype(
        5, "helpers", "Helpers & Service Professionals",
        "I work directly with people to understand their needs, solve problems, and improve their well-being or experience.",
        ("active listening", "empathy and perspective-taking", "cross-cultural interpretation",
         "careful observation", "contextual understanding", "ethical reasoning",
         "discussion and facilitation", "interpersonal communication", "reflective practice",
         "qualitative assessment", "case analysis", "clear writing and documentation",
         "interpreting lived experience and social context"),
        {
            "Human Services": (
                "Human Services Specialist", "Case Worker", "Case Manager",
                "Family Services Specialist", "Social Services Coordinator"),
            "Social Work & Counseling": (
                "Social Worker", "Counselor", "Therapist", "Behavioral Health Specialist",
                "Mental Health Counselor"),
            "Healthcare Support & Advocacy": (
                "Patient Advocate", "Patient Navigator", "Community Health Worker",
                "Patient Experience Specialist", "Care Coordinator"),
            "Student Support": (
                "Student Services Specialist", "Student Success Coordinator",
                "Residence Life Coordinator", "Student Affairs Specialist",
                "Student Support Manager"),
            "Customer Success": (
                "Customer Success Specialist", "Customer Success Manager",
                "Client Success Manager", "Customer Experience Manager"),
            "Client Services": (
                "Client Services Coordinator", "Client Services Specialist",
                "Client Relationship Manager", "Client Services Director"),
            "Hospitality & Guest Experience": (
                "Guest Services Representative", "Guest Experience Manager",
                "Hospitality Manager", "Visitor Services Manager"),
            "Community Services": (
                "Community Services Coordinator", "Outreach Worker",
                "Community Support Specialist", "Constituent Services Specialist"),
        },
    ),
    Archetype(
        6, "connectors", "Connectors & Relationship Builders",
        "I create opportunities by building trust, cultivating relationships, and connecting people and organizations.",
        ("persuasive communication", "audience awareness", "active listening", "storytelling",
         "relationship building", "cultural fluency", "perspective-taking",
         "stakeholder research", "synthesizing interests and viewpoints", "negotiation",
         "presentation", "written outreach", "interviewing and conversation",
         "translating ideas into compelling cases for action or support"),
        {
            "Sales": (
                "Sales Representative", "Sales Development Representative", "Account Executive",
                "Sales Manager", "Sales Director"),
            "Business Development": (
                "Business Development Associate", "Business Development Manager",
                "Business Development Director", "Growth Manager"),
            "Partnerships": (
                "Partnerships Coordinator", "Partnerships Manager",
                "Strategic Partnerships Manager", "Director of Partnerships"),
            "Fundraising & Development": (
                "Development Associate", "Development Officer", "Major Gifts Officer",
                "Annual Giving Manager", "Development Director", "Chief Development Officer"),
            "Foundation & Corporate Relations": (
                "Foundation Relations Officer", "Corporate Relations Manager",
                "Institutional Giving Manager", "Corporate Partnerships Director"),
            "Alumni & Donor Relations": (
                "Alumni Relations Coordinator", "Alumni Relations Director",
                "Donor Relations Manager", "Stewardship Officer"),
            "Recruiting & Talent Acquisition": (
                "Recruiting Coordinator", "Recruiter", "Executive Recruiter",
                "Talent Acquisition Specialist", "Talent Acquisition Manager"),
            "Community Engagement": (
                "Community Engagement Coordinator", "Outreach Manager",
                "Community Partnerships Manager", "External Relations Director"),
            "Membership & Associations": (
                "Membership Coordinator", "Membership Manager", "Member Engagement Director",
                "Association Relations Manager"),
        },
    ),
    Archetype(
        7, "leaders", "Leaders & Organizers",
        "I bring people, processes, and resources together to turn goals into results.",
        ("clear written and oral communication", "organizing complex information", "synthesis",
         "facilitation and discussion leadership", "collaborative problem-solving",
         "perspective-taking", "ethical reasoning", "decision framing",
         "research and preparation", "giving and incorporating feedback",
         "project coordination", "prioritization", "documentation",
         "leading work through ambiguity"),
        {
            "Administration & Coordination": (
                "Administrative Assistant", "Administrative Coordinator", "Executive Assistant",
                "Program Assistant", "Office Coordinator", "Office Manager"),
            "Project Management": (
                "Project Coordinator", "Project Manager", "Senior Project Manager",
                "Project Director", "Portfolio Manager"),
            "Program Management": (
                "Program Coordinator", "Program Manager", "Senior Program Manager",
                "Program Director"),
            "Operations": (
                "Operations Coordinator", "Operations Specialist", "Operations Manager",
                "Director of Operations", "VP Operations", "COO"),
            "Events & Production": (
                "Event Coordinator", "Conference Coordinator", "Event Manager",
                "Conference Manager", "Event Director"),
            "People Management": (
                "Team Lead", "Supervisor", "Department Manager", "Regional Manager",
                "General Manager"),
            "Organizational Leadership": (
                "Director", "Executive Director", "Managing Director", "Vice President",
                "President", "CEO"),
            "Executive & Strategic Coordination": (
                "Executive Coordinator", "Chief of Staff", "Deputy Chief of Staff",
                "Director of Administration"),
            "Academic Administration": (
                "Academic Coordinator", "Department Administrator", "Program Director",
                "Department Chair", "Dean", "Provost"),
        },
    ),
    Archetype(
        8, "builders", "Builders & Technologists",
        "I build, implement, and improve tools, products, technologies, and systems.",
        ("digital literacy", "research and information gathering",
         "user-centered interpretation", "qualitative inquiry",
         "clear writing and documentation", "translating needs into requirements",
         "systems and contextual thinking", "information architecture",
         "iterative problem-solving", "content design", "ethical analysis of technology",
         "communicating between technical and nontechnical audiences"),
        {
            "Software & Web": (
                "Web Developer", "Software Developer", "Front-End Developer",
                "Application Developer", "Software Engineer"),
            "Product": (
                "Product Coordinator", "Associate Product Manager", "Product Manager",
                "Senior Product Manager", "Product Director"),
            "User Experience": (
                "UX Designer", "Interaction Designer", "Information Architect", "UX Strategist",
                "Content Designer"),
            "IT & Systems": (
                "IT Specialist", "Systems Administrator", "Systems Analyst",
                "Information Systems Manager", "IT Director"),
            "Business Systems": (
                "Business Systems Analyst", "CRM Administrator", "Salesforce Administrator",
                "Enterprise Systems Specialist"),
            "Implementation & Solutions": (
                "Implementation Specialist", "Implementation Manager", "Solutions Consultant",
                "Solutions Architect", "Technical Consultant"),
            "Digital Humanities & Scholarship": (
                "Digital Humanities Specialist", "Digital Scholarship Librarian",
                "Digital Projects Manager", "Digital Collections Specialist"),
            "Knowledge & Information Systems": (
                "Knowledge Management Specialist", "Information Architect",
                "Knowledge Systems Manager", "Information Manager"),
            "Emerging Technology & AI": (
                "AI Product Specialist", "AI Content Specialist", "AI Implementation Consultant",
                "Responsible AI Specialist", "AI Program Manager"),
        },
    ),
    Archetype(
        9, "stewards", "Financial & Resource Stewards",
        "I manage money, resources, risk, and accountability so organizations can operate sustainably.",
        ("analytical reading", "attention to detail", "evidence evaluation", "research",
         "interpreting policies, rules, and documentation", "clear explanatory writing",
         "quantitative literacy", "contextual judgment", "ethical reasoning", "risk awareness",
         "synthesis", "communicating technical or financial information to non-specialists",
         "budgeting, forecasting, compliance, and resource stewardship"),
        {
            "Accounting": (
                "Accounting Assistant", "Staff Accountant", "Senior Accountant",
                "Accounting Manager", "Controller"),
            "Financial Analysis": (
                "Financial Analyst", "Senior Financial Analyst", "Finance Manager",
                "Finance Director"),
            "Budgeting & Planning": (
                "Budget Analyst", "Budget Manager", "Financial Planning Analyst",
                "Director of Budget and Planning"),
            "Grants & Sponsored Programs": (
                "Grants Assistant", "Grants Administrator", "Grants Manager",
                "Sponsored Programs Officer", "Research Administrator"),
            "Contracts & Procurement": (
                "Contracts Administrator", "Contract Specialist", "Procurement Specialist",
                "Procurement Manager"),
            "Audit & Compliance": (
                "Auditor", "Internal Auditor", "Compliance Analyst",
                "Financial Compliance Manager", "Risk Analyst"),
            "Investment & Financial Services": (
                "Investment Analyst", "Portfolio Analyst", "Credit Analyst", "Banking Associate",
                "Investment Manager"),
            "Revenue & Business Finance": (
                "Revenue Analyst", "Pricing Analyst", "Commercial Finance Analyst",
                "Business Finance Manager"),
            "Financial Leadership": (
                "Controller", "Treasurer", "VP Finance", "Chief Financial Officer"),
        },
    ),
)

SECTORS: dict[str, str] = {
    "Business & Professional Services":
        "Consulting firms, agencies, corporations, professional associations, B2B services",
    "Technology": "Software, digital products, IT, platforms, AI, technology services",
    "Healthcare & Human Services":
        "Hospitals, health systems, clinics, behavioral health, social services, community health",
    "Education & Academia":
        "K-12, colleges and universities, research centers, education providers, edtech",
    "Government & Public Policy":
        "Federal, state, local government, legislative offices, public agencies, think tanks",
    "Nonprofit & Philanthropy":
        "Nonprofits, foundations, advocacy organizations, associations, NGOs",
    "Arts, Culture & Media":
        "Museums, libraries, archives, publishers, journalism, film, performing arts, cultural organizations",
    "Finance & Financial Services":
        "Banks, investment firms, insurance, accounting, fintech, financial institutions",
    "Law & Legal Services":
        "Law firms, legal departments, courts, legal aid, regulatory and compliance organizations",
    "Retail, Hospitality & Tourism":
        "Retailers, hotels, restaurants, travel, tourism, visitor attractions, customer-facing services",
}

WORK_CONTEXTS: dict[str, str] = {
    "Individual Contributor":
        "Primarily responsible for one's own specialized work rather than formally managing a team.",
    "Manager":
        "Leads people, projects, programs, or functions and is accountable for team-level outcomes.",
    "Executive":
        "Sets organizational or enterprise-level direction and carries broad decision-making responsibility.",
    "Founder / Entrepreneur":
        "Creates and leads a new venture, organization, practice, or business.",
    "Freelancer / Independent Practitioner":
        "Works independently for clients or maintains a self-directed professional practice.",
}

# The director's worked examples: (title, primary, pathway, sector, work context)
EXAMPLES = (
    ("UX Researcher", "researchers", "Applied Research & Insights", "Technology",
     "Individual Contributor"),
    ("Museum Executive Director", "leaders", "Organizational Leadership", "Arts, Culture & Media",
     "Executive"),
    ("Independent Grant Writer", "communicators", "Writing & Editorial", "Nonprofit & Philanthropy",
     "Freelancer / Independent Practitioner"),
    ("Healthcare Policy Analyst", "analysts", "Policy Analysis",
     "Healthcare & Human Services / Government & Public Policy", "Individual Contributor"),
    ("Development Director", "connectors", "Fundraising & Development", "Nonprofit & Philanthropy",
     "Manager"),
)

BY_KEY = {a.key: a for a in ARCHETYPES}
BY_ID = {a.id: a for a in ARCHETYPES}
KEYS = tuple(a.key for a in ARCHETYPES)
NONE_KEY = "none"  # the honest residual: work outside all nine orientations


def seeds() -> list[tuple[str, str, str]]:
    """Flatten to (representative title, archetype key, pathway).

    A title listed under two pathways (Public Historian, Podcast Producer,
    Content Designer, Information Architect, Program Director, Department Chair,
    Controller, Compliance Analyst) is kept once per listing; the seed-based
    methods treat such repeats as genuinely ambiguous seeds.
    """
    out = []
    for a in ARCHETYPES:
        for pathway, roles in a.pathways.items():
            for r in roles:
                out.append((r, a.key, pathway))
    return out


def ambiguous_seed_titles() -> dict[str, set[str]]:
    """Titles the framework itself lists under more than one archetype."""
    seen: dict[str, set[str]] = {}
    for title, key, _ in seeds():
        seen.setdefault(title.lower(), set()).add(key)
    return {t: ks for t, ks in seen.items() if len(ks) > 1}


def prototype_text(a: Archetype, with_roles: bool = True) -> str:
    """One paragraph per archetype for embedding-prototype methods."""
    parts = [a.label + ".", a.orientation, "Skills: " + "; ".join(a.skills) + "."]
    if with_roles:
        roles = sorted({r for rs in a.pathways.values() for r in rs})
        parts.append("Roles: " + "; ".join(roles) + ".")
    return " ".join(parts)


if __name__ == "__main__":
    s = seeds()
    print(len(ARCHETYPES), "archetypes;", sum(len(a.pathways) for a in ARCHETYPES),
          "pathways;", len(s), "seed listings;", len({t.lower() for t, _, _ in s}),
          "distinct titles")
    print("ambiguous:", ambiguous_seed_titles())

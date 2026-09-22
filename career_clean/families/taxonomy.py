"""Occupation-family taxonomy (spec P4), ported verbatim from the sibling clean-room build
(~/from_scratch_humanities_workforce/pipeline/taxonomy.py, 2026-09-15): 52 families keyed
by a rules classifier over raw job titles, each with a SOC major-group anchor used ONLY as a
propose-only pooled-major proposal where the deterministic coder and the jury both abstained.

Contract: do not add or move codes here without a gate result in
career_clean/results/family_gate.json. NEVER_LAND families never write a pooled major:
the four non-occupation forms plus the four anchors the 2026-09-22 pre-review judged
dishonest as a single major (trades_logistics bundles 47/49/51/53; founder_owner is an
employment form that would override functional_cluster; hospitality_food mixes 13/35/37/39/43;
banking_insurance mixes 13/41/43).
"""
from __future__ import annotations

FAMILIES = {
    # code: (label, group, soc_major_group)
    'executive':          ('Executive / C-suite / president', 'management', '11'),
    'founder_owner':      ('Founder / owner / self-employed', 'management', '11'),
    'general_management': ('General & operations management', 'management', '11'),
    'project_program_mgmt': ('Project / program management', 'management', '13'),
    'consulting':         ('Consulting', 'business_ops', '13'),
    'business_analysis':  ('Business / operations analyst', 'business_ops', '13'),
    'hr_recruiting':      ('Human resources & recruiting', 'business_ops', '13'),
    'admin_support':      ('Administrative & office support', 'admin', '43'),
    'customer_service':   ('Customer service & support', 'admin', '43'),
    'sales':              ('Sales & business development', 'sales', '41'),
    'retail':             ('Retail & store', 'sales', '41'),
    'marketing':          ('Marketing & brand', 'comms_creative', '13'),
    'pr_communications':  ('Public relations & communications', 'comms_creative', '27'),
    'writing_editing':    ('Writing, editing & publishing', 'comms_creative', '27'),
    'journalism_media':   ('Journalism & broadcast media', 'comms_creative', '27'),
    'design_ux':          ('Design, UX & visual production', 'comms_creative', '27'),
    'arts_performance':   ('Artists, performers & musicians', 'comms_creative', '27'),
    'museum_library':     ('Museums, libraries & archives', 'education', '25'),
    'teaching_k12':       ('K-12 teaching', 'education', '25'),
    'school_admin':       ('School & district administration', 'education', '11'),
    'higher_ed_faculty':  ('College faculty, lecturers & postdocs', 'education', '25'),
    'higher_ed_staff':    ('Higher-ed administration & student services', 'education', '11'),
    'other_education':    ('Tutors, trainers, instructors (other)', 'education', '25'),
    'research':           ('Research (assistant/associate/scientist non-lab)', 'science', '19'),
    'data_analytics':     ('Data science & analytics', 'tech', '15'),
    'software':           ('Software engineering & development', 'tech', '15'),
    'it_support':         ('IT support, systems & networks', 'tech', '15'),
    'product_management': ('Product management', 'tech', '11'),
    'engineering':        ('Engineering (non-software)', 'science', '17'),
    'science_lab':        ('Scientists & lab technicians', 'science', '19'),
    'finance_accounting': ('Finance & accounting', 'finance', '13'),
    'banking_insurance':  ('Banking, insurance & financial advising', 'finance', '13'),
    'real_estate':        ('Real estate', 'sales', '41'),
    'legal_attorney':     ('Attorneys & judges', 'legal', '23'),
    'legal_support':      ('Paralegals & legal support', 'legal', '23'),
    'government_policy':  ('Government, policy & public affairs', 'public', '13'),
    'nonprofit_program':  ('Nonprofit & community programs', 'public', '21'),
    'social_services':    ('Social work, counseling & case management', 'public', '21'),
    'clergy':             ('Clergy & ministry', 'public', '21'),
    'healthcare_clinical':('Clinical healthcare (nurses, physicians, therapists)', 'health', '29'),
    'healthcare_support': ('Healthcare support & admin', 'health', '31'),
    'military':           ('Military', 'protective', '55'),
    'protective_services':('Police, fire, security', 'protective', '33'),
    'hospitality_food':   ('Hospitality, food service & events', 'service', '35'),
    'personal_care_fitness': ('Personal care, fitness & coaching', 'service', '39'),
    'trades_logistics':   ('Trades, production, transport & logistics', 'trades', '51'),
    'translation_language': ('Translation & interpretation', 'comms_creative', '27'),
    'student':            ('Student / graduate student', 'non_employment', None),
    'intern':             ('Intern (function unspecified)', 'non_employment', None),
    'volunteer_board':    ('Volunteer / board member', 'non_employment', None),
    'not_working':        ('Retired / career break / unemployed', 'non_employment', None),
    'unclassified':       ('Unclassified', 'none', None),
}

SENIORITY = ['intern', 'entry', 'mid', 'senior', 'manager', 'director', 'vp', 'c_suite', 'owner']


NEVER_LAND = frozenset({
    "student", "intern", "volunteer_board", "not_working", "unclassified",
    "trades_logistics", "founder_owner", "hospitality_food", "banking_insurance",
})

"""
Generate 100 realistic test documents for locallab stress testing.
Outputs: 60 .txt files + 40 .pdf files in the target directory.
Run: python scripts/gen_test_docs.py
"""
import random
import textwrap
from pathlib import Path
from fpdf import FPDF

OUT_DIR = Path(__file__).parent.parent.parent / "UniversityOfColorodoBoulder" / "test_docs"
OUT_DIR.mkdir(parents=True, exist_ok=True)

random.seed(42)

# ── DATA POOLS ────────────────────────────────────────────────────
PEOPLE = [
    "Sarah Chen", "Marcus Webb", "Priya Nair", "James Okafor", "Elena Vasquez",
    "Tom Harrington", "Aisha Patel", "David Kim", "Rachel Goldstein", "Carlos Mendoza",
    "Fiona O'Brien", "Raj Krishnamurthy", "Natalie Bloom", "Owen Fitzgerald", "Mei Lin",
]
COMPANIES = [
    "Apex Dynamics LLC", "Greenfield Capital Partners", "NovaTech Solutions Inc",
    "Meridian Consulting Group", "Blackrock Engineering", "SunPath Ventures",
    "ClearWave Analytics", "Ironside Manufacturing", "PolarStar Holdings",
    "Brightline Medical Group", "Cascade Software Ltd", "TerraVerde Properties",
]
AMOUNTS = ["$45,000", "$120,000", "$8,500/month", "$250,000", "$1.2M", "$35,000", "$500/hr", "$75,000"]
DATES = ["March 15, 2025", "June 1, 2025", "December 31, 2024", "January 1, 2026",
         "April 30, 2025", "September 15, 2025", "February 28, 2025"]

# ── DOCUMENT TEMPLATES ────────────────────────────────────────────
def contract(i):
    p1, p2 = random.sample(PEOPLE, 2)
    c1, c2 = random.sample(COMPANIES, 2)
    amt = random.choice(AMOUNTS)
    d1, d2 = random.sample(DATES, 2)
    return f"""SERVICE AGREEMENT

This Service Agreement ("Agreement") is entered into as of {d1}, by and between:

{c1} ("Client"), a Delaware limited liability company with its principal place of
business at 450 Market Street, Suite 900, San Francisco, CA 94105, represented by
{p1}, Chief Executive Officer; and

{c2} ("Service Provider"), a Texas corporation with offices at 1200 Commerce Drive,
Austin, TX 78701, represented by {p2}, Managing Director.

1. SERVICES
Service Provider agrees to deliver software development and consulting services
as described in Exhibit A attached hereto. The scope includes system architecture
design, implementation of API integrations, and quality assurance testing.

2. COMPENSATION
Client shall pay Service Provider {amt} upon completion of each milestone as set
forth in the project schedule. Invoices are due net-30. Late payments incur 1.5%
monthly interest.

3. TERM
This Agreement commences on {d1} and continues through {d2} unless terminated
earlier pursuant to Section 8.

4. CONFIDENTIALITY
Each party agrees to maintain the confidentiality of the other party's proprietary
information, trade secrets, and business data for a period of three (3) years following
the termination of this Agreement.

5. INTELLECTUAL PROPERTY
All work product developed under this Agreement shall be considered work-for-hire
and shall be the exclusive property of the Client upon full payment of all fees.

6. LIMITATION OF LIABILITY
In no event shall either party be liable for indirect, incidental, or consequential
damages. Service Provider's total liability shall not exceed the total fees paid in
the three (3) months preceding the claim.

7. GOVERNING LAW
This Agreement shall be governed by the laws of the State of California.

8. TERMINATION
Either party may terminate this Agreement with thirty (30) days written notice.
Client may terminate immediately for cause upon material breach by Service Provider.

IN WITNESS WHEREOF, the parties have executed this Agreement as of the date first
written above.

{c1}                          {c2}
By: {p1}                By: {p2}
Title: CEO                         Title: Managing Director
Date: {d1}                   Date: {d1}
"""

def meeting_notes(i):
    attendees = random.sample(PEOPLE, random.randint(3, 6))
    company = random.choice(COMPANIES)
    date = random.choice(DATES)
    topics = random.sample([
        "Q3 budget review", "product roadmap update", "hiring plan",
        "customer escalation", "partnership opportunities", "security audit findings",
        "go-to-market strategy", "technical debt", "OKR review", "board presentation prep",
    ], 3)
    return f"""MEETING NOTES
{company} — {topics[0].title()} Meeting
Date: {date}
Attendees: {', '.join(attendees)}
Facilitator: {attendees[0]}

AGENDA
1. {topics[0].title()}
2. {topics[1].title()}
3. {topics[2].title()}
4. Action items and next steps

DISCUSSION

1. {topics[0].upper()}
{attendees[0]} opened the meeting by presenting the current status of {topics[0]}.
The team reviewed key metrics and identified three priority areas for improvement.
{attendees[1]} raised concerns about timeline, noting that the current pace puts
the team at risk of missing the {date} deadline. After discussion, the group agreed
to increase weekly check-ins and assign {attendees[2]} as the lead coordinator.

2. {topics[1].upper()}
{attendees[1]} presented the updated roadmap, highlighting three new features
planned for the next release cycle. The team discussed resource allocation and
dependencies on the infrastructure team. {attendees[-1]} confirmed that engineering
capacity would be available starting next sprint.

3. {topics[2].upper()}
A brief review of {topics[2]} was conducted. The group agreed that further analysis
is needed before making a final recommendation. {attendees[0]} will prepare a
summary document for review before the next meeting.

ACTION ITEMS
- {attendees[0]}: Draft revised timeline by end of week
- {attendees[1]}: Schedule follow-up with stakeholders
- {attendees[2]}: Compile data for next meeting presentation
- {attendees[-1]}: Send calendar invites for next three check-ins

NEXT MEETING: Two weeks from today, same time.
Notes recorded by: {attendees[-1]}
"""

def resume(i):
    person = random.choice(PEOPLE)
    companies = random.sample(COMPANIES, 3)
    skills = random.sample([
        "Python", "JavaScript", "SQL", "React", "AWS", "Docker", "Kubernetes",
        "Machine Learning", "Data Analysis", "Project Management", "Agile", "Scrum",
        "Product Strategy", "Financial Modeling", "Contract Negotiation", "Tableau",
    ], random.randint(6, 9))
    return f"""RESUME

{person}
Email: {person.lower().replace(' ', '.')[:6]}@email.com | LinkedIn: linkedin.com/in/{person.lower().replace(' ','-')}
Location: San Francisco Bay Area

PROFESSIONAL SUMMARY
Results-driven professional with 8+ years of experience in technology and operations.
Track record of leading cross-functional teams and delivering complex projects on time
and within budget. Skilled communicator with strong analytical capabilities.

EXPERIENCE

Senior Manager — {companies[0]}
January 2022 – Present
• Led a team of 12 engineers across three product lines, increasing delivery velocity by 35%
• Managed annual budget of {random.choice(AMOUNTS)} and negotiated vendor contracts saving $180K/year
• Spearheaded migration to cloud infrastructure, reducing operating costs by 28%
• Established quarterly OKR framework adopted across the department

Manager — {companies[1]}
March 2019 – December 2021
• Directed end-to-end product development cycles for B2B SaaS platform
• Grew user base from 5,000 to 42,000 accounts in 18 months
• Collaborated with sales and marketing on go-to-market strategies for 3 product launches
• Mentored 5 junior team members, two of whom were promoted to senior roles

Associate — {companies[2]}
June 2016 – February 2019
• Supported due diligence processes for M&A transactions totaling $2.4B in value
• Built financial models and prepared presentations for executive leadership
• Coordinated cross-departmental projects with up to 20 stakeholders

EDUCATION
B.S. Computer Science — University of California, Berkeley — 2016
MBA — Stanford Graduate School of Business — 2019

SKILLS
{' | '.join(skills)}

CERTIFICATIONS
AWS Certified Solutions Architect | PMP Certified | CFA Level I
"""

def invoice(i):
    vendor = random.choice(COMPANIES)
    client = random.choice([c for c in COMPANIES if c != vendor])
    person = random.choice(PEOPLE)
    amt = random.choice(["$12,500", "$8,200", "$45,000", "$3,750", "$22,000"])
    date = random.choice(DATES)
    items = random.sample([
        ("Software development — API module", "$6,500"),
        ("UX design and prototyping", "$4,200"),
        ("Infrastructure setup and configuration", "$3,800"),
        ("Security audit and penetration testing", "$8,000"),
        ("Data migration services", "$5,500"),
        ("Staff training (2 sessions)", "$2,400"),
        ("Project management", "$3,200"),
        ("Documentation and technical writing", "$1,800"),
    ], 3)
    subtotal = sum(int(p.replace('$','').replace(',','')) for _, p in items)
    tax = int(subtotal * 0.085)
    return f"""INVOICE

FROM: {vendor}
TO:   {client}
      Attn: {person}

Invoice #: INV-{2025000+i}
Issue Date: {date}
Due Date: Net 30 from invoice date

SERVICES RENDERED

Item                                              Amount
{'─'*52}
{items[0][0]:<48} {items[0][1]:>8}
{items[1][0]:<48} {items[1][1]:>8}
{items[2][0]:<48} {items[2][1]:>8}
{'─'*52}
Subtotal                                        ${subtotal:>7,}
Tax (8.5%)                                      ${tax:>7,}
{'═'*52}
TOTAL DUE                                       ${subtotal+tax:>7,}

PAYMENT INSTRUCTIONS
Wire Transfer: Routing 021000021 | Account 4892017463
Check payable to: {vendor}
ACH/Zelle: payments@{vendor.split()[0].lower()}.com

Questions? Contact: {random.choice(PEOPLE)} | billing@{vendor.split()[0].lower()}.com

Thank you for your business.
"""

def policy_doc(i):
    company = random.choice(COMPANIES)
    topics = [
        ("Remote Work Policy", "remote work arrangements, home office requirements, and communication expectations"),
        ("Data Retention Policy", "data classification, retention schedules, and secure disposal procedures"),
        ("Expense Reimbursement Policy", "eligible expenses, approval workflows, and reimbursement timelines"),
        ("Code of Conduct", "professional behavior, conflict of interest, and reporting mechanisms"),
        ("Information Security Policy", "access controls, password requirements, and incident response"),
    ]
    title, desc = random.choice(topics)
    person = random.choice(PEOPLE)
    date = random.choice(DATES)
    return f"""{company.upper()}
{title.upper()}

Effective Date: {date}
Approved by: {person}, Chief People Officer
Version: 2.{i % 5}

PURPOSE
This policy establishes guidelines for {desc} at {company}. All employees,
contractors, and third-party vendors are expected to comply with this policy.
Violations may result in disciplinary action up to and including termination.

SCOPE
This policy applies to all personnel employed by or contracted with {company},
including full-time employees, part-time employees, temporary workers, interns,
and independent contractors who access company systems or handle company data.

POLICY DETAILS

Section 1 — General Requirements
All covered personnel must acknowledge receipt of this policy annually. New employees
are required to review and sign acknowledgment within their first 5 business days.
{company} reserves the right to update this policy at any time with 30 days notice.

Section 2 — Responsibilities
Department managers are responsible for ensuring their teams understand and comply
with this policy. HR is responsible for maintaining records of acknowledgments.
The compliance team will conduct quarterly audits to verify adherence.

Section 3 — Enforcement
Non-compliance will be addressed through the standard progressive discipline process:
verbal warning, written warning, final written warning, and termination. In cases
of intentional or severe violations, immediate termination may occur.

Section 4 — Exceptions
Requests for exceptions must be submitted in writing to {person} and require
approval from department leadership and legal review. Approved exceptions are
valid for no more than 12 months and must be renewed.

CONTACT
Questions regarding this policy should be directed to HR at hr@{company.split()[0].lower()}.com
or to the Office of General Counsel.

ACKNOWLEDGMENT
I have read and understood the {title} and agree to comply with its terms.

Employee Name: _______________________  Date: ___________
Signature: ___________________________
"""

GENERATORS = [contract, meeting_notes, resume, invoice, policy_doc]
TYPE_NAMES  = ["contract", "meeting-notes", "resume", "invoice", "policy"]

def make_pdf(text, path):
    # Strip non-latin-1 characters to stay compatible with Courier font
    text = text.replace('\u2014', '--').replace('\u2013', '-').replace('\u2019', "'").replace('\u201c', '"').replace('\u201d', '"')
    text = text.encode('latin-1', errors='replace').decode('latin-1')
    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.add_page()
    pdf.set_font("Courier", size=9)
    for line in text.split('\n'):
        wrapped = textwrap.wrap(line, width=110) if line.strip() else ['']
        for wl in wrapped:
            pdf.cell(0, 4.5, text=wl, new_x="LMARGIN", new_y="NEXT")
    pdf.output(str(path))

print(f"Generating 100 test documents → {OUT_DIR}")
for i in range(100):
    gen = GENERATORS[i % len(GENERATORS)]
    type_name = TYPE_NAMES[i % len(TYPE_NAMES)]
    content = gen(i)
    idx = str(i+1).zfill(3)

    if i < 60:
        # .txt files
        fname = f"test_{type_name}_{idx}.txt"
        (OUT_DIR / fname).write_text(content)
    else:
        # .pdf files
        fname = f"test_{type_name}_{idx}.pdf"
        make_pdf(content, OUT_DIR / fname)

    if (i+1) % 10 == 0:
        print(f"  {i+1}/100 done")

print(f"\nDone. Files written to:\n  {OUT_DIR}")
print(f"\nTo ingest all of them, add this path in the Watch Folders modal or use:")
print(f"  POST /api/ingest  body: {{\"paths\": [\"{OUT_DIR}\"]}}")

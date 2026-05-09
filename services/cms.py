import json
import os
import uuid
from pathlib import Path

import psycopg2
from psycopg2.extras import RealDictCursor


DATABASE_URL = os.environ.get("DATABASE_URL")
UPLOAD_DIR = Path(__file__).resolve().parent.parent / "static" / "uploads" / "cms"


DEFAULT_NEWS = [
    {
        "date_label": "Mar 2026",
        "title": "SSPred v2.0 Launched",
        "body": "Updated with support for 8 prediction servers, real-time progress tracking, PDB structure integration, and consensus majority voting.",
        "link_text": "",
        "link_url": "",
    },
    {
        "date_label": "2025",
        "title": "Guest Editor — MDPI Pathogens",
        "body": 'Prof. Singh serves as guest editor of the Special Issue "Computational Approaches in Mechanisms of Pathogenesis" in the open-access journal Pathogens.',
        "link_text": "",
        "link_url": "",
    },
    {
        "date_label": "2025",
        "title": "New Publication in Pathogens",
        "body": 'Chou et al. (including Singh S.) publish "Venomous Cargo: Diverse Toxin-Related Proteins Are Associated with Extracellular Vesicles in Parasitoid Wasp Venom." Pathogens 14(3). doi: 10.3390/pathogens14030255.',
        "link_text": "doi: 10.3390/pathogens14030255",
        "link_url": "https://doi.org/10.3390/pathogens14030255",
    },
]

DEFAULT_PUBLICATIONS = [
    {
        "year": "2025",
        "citation": "Chou J, Li MZ, Wey B, Mumtaz M, Ramroop JR, Singh S, Govind S. Venomous Cargo: Diverse Toxin-Related Proteins Are Associated with Extracellular Vesicles in Parasitoid Wasp Venom. Pathogens. 2025 Mar 5;14(3).",
        "link_label": "doi: 10.3390/pathogens14030255 · PubMed: 40137740",
        "link_url": "https://doi.org/10.3390/pathogens14030255",
    },
    {
        "year": "2025",
        "citation": "Aksoy M, Krupitskaya M, Singh SM. A Genome-Wide Modeling and Characterization Study of Pleckstrin Homology Domains in Chlamydomonas reinhardtii. Plants (Basel). 2025 Aug 22;14(17).",
        "link_label": "doi: 10.3390/plants14172607 · PubMed: 40941772",
        "link_url": "https://doi.org/10.3390/plants14172607",
    },
    {
        "year": "2025",
        "citation": "Eichner AS, Zimmerman N, San A, Singh S. In Silico Analysis of Human NEK10 Reveals Novel Domain Architecture and Protein-Protein Interactions. Proteins. 2025 Oct 3. [Epub ahead of print]",
        "link_label": "doi: 10.1002/prot.70067 · PubMed: 41044802",
        "link_url": "https://doi.org/10.1002/prot.70067",
    },
    {
        "year": "2025",
        "citation": 'Guest editor of Special Issue "Computational Approaches in Mechanisms of Pathogenesis" for the open-access MDPI journal Pathogens, 2025.',
        "link_label": "",
        "link_url": "",
    },
    {
        "year": "2024",
        "citation": "Power KM, Nguyen KC, Silva A, Singh S, Hall DH, Rongo C, Barr MM. NEKL-4 regulates microtubule stability and mitochondrial health in ciliated neurons. J Cell Biol. 2024 Sep 2;223(9).",
        "link_label": "doi: 10.1083/jcb.202402006 · PubMed: 38767515",
        "link_url": "https://doi.org/10.1083/jcb.202402006",
    },
    {
        "year": "2023",
        "citation": "Arguelles J, Lee J, Cardenas LV, Govind S, Singh S. In Silico Analysis of a Drosophila Parasitoid Venom Peptide Reveals Prevalence of the Cation-Polar-Cation Clip Motif in Knottin Proteins. Pathogens 2023, 12, 143.",
        "link_label": "doi: 10.3390/pathogens12010143",
        "link_url": "https://doi.org/10.3390/pathogens12010143",
    },
    {
        "year": "2022",
        "citation": "Jalali S, Yang Y, Mahmoudinobar F, Singh SM, Nilsson B, Dias C. Using large-scale and long-time all-atom simulations to study the aggregation of amphipathic peptides into amyloid-like fibrils. Journal of Molecular Liquids 347, 118283.",
        "link_label": "",
        "link_url": "",
    },
    {
        "year": "2021",
        "citation": "Murph M, Singh S, Schvarzstein M. The Centrosomal Swiss Army Knife: A combined in silico and in vivo approach to the structure-function annotation of SPD-2 provides mechanistic insight into its functional diversity. Cell Cycle (In press; preprint available from bioRxiv 2021.04.22.441031).",
        "link_label": "",
        "link_url": "",
    },
]

DEFAULT_TEAM = [
    {
        "section": "members",
        "name": "[Graduate Student Name]",
        "role": "Ph.D. Student, Computational Biology",
        "bio": "Research: [Placeholder — e.g., deep learning methods for protein structure prediction and domain annotation].",
        "initials": "GS",
        "image_path": "",
    },
]

DEFAULT_PAGES = {
    "team": {
        "title": "Team",
        "subtitle": "Faculty, graduate students, postdocs, and undergraduates in the Singh Lab.",
        "extra": {
            "pi_name": "Shaneen Singh",
            "pi_title": "Professor of Biology · Brooklyn College, CUNY",
            "pi_bio": 'Shaneen Singh is a professor of biology. Her doctoral thesis was titled "Biochemical Studies in Growing Bamboo, Dendrocalamus strictus." Although trained as an experimental biologist, she has transitioned into the field of computational biology. The long-term research goal of her lab is to apply computer modeling to address important biological questions.',
            "pi_education": [
                "B.S., Punjabi University (Patiala, India) — Life Sciences, 1991",
                "M.S., Punjabi University (Patiala, India) — Biotechnology, 1993",
                "Ph.D., Thapar Institute of Engineering and Technology (Patiala, India) — Biotechnology, 1998",
            ],
            "join_text": "We welcome motivated students and researchers interested in computational biology and bioinformatics.",
        },
    },
    "contact": {
        "title": "Contact & Joining the Lab",
        "subtitle": "Get in touch or learn about opportunities to join the Singh Lab.",
        "extra": {
            "address": "Department of Biology, Brooklyn College\n2900 Bedford Ave, Brooklyn, NY 11210",
            "email": "Update with lab contact email",
            "institution": "Brooklyn College, City University of New York (CUNY)",
            "graduate_text": "Prospective Ph.D. students should apply through the CUNY Graduate Center or Brooklyn College graduate programs in Biology or Computational Sciences.",
            "undergrad_text": "Brooklyn College undergraduate students interested in computational biology research are encouraged to contact Prof. Singh directly.",
            "postdoc_text": "Postdoctoral positions are filled as funding allows. Interested applicants should send a CV and short research statement.",
        },
    },
    "research": {
        "title": "Research",
        "subtitle": "Computational approaches to structure, function, and evolution of biological molecules.",
        "extra": {},
    },
}


def enabled():
    return bool(DATABASE_URL)


def ensure_tables():
    if not DATABASE_URL:
        return
    statements = [
        """
        CREATE TABLE IF NOT EXISTS cms_users (
            email TEXT PRIMARY KEY,
            role TEXT NOT NULL DEFAULT 'editor',
            active BOOLEAN NOT NULL DEFAULT TRUE,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS cms_pages (
            slug TEXT PRIMARY KEY,
            title TEXT NOT NULL DEFAULT '',
            subtitle TEXT NOT NULL DEFAULT '',
            body TEXT NOT NULL DEFAULT '',
            extra_json TEXT NOT NULL DEFAULT '{}',
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS cms_news (
            id SERIAL PRIMARY KEY,
            date_label TEXT NOT NULL DEFAULT '',
            title TEXT NOT NULL DEFAULT '',
            body TEXT NOT NULL DEFAULT '',
            link_text TEXT NOT NULL DEFAULT '',
            link_url TEXT NOT NULL DEFAULT '',
            sort_order INTEGER NOT NULL DEFAULT 0,
            active BOOLEAN NOT NULL DEFAULT TRUE
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS cms_team_members (
            id SERIAL PRIMARY KEY,
            section TEXT NOT NULL DEFAULT 'members',
            name TEXT NOT NULL DEFAULT '',
            role TEXT NOT NULL DEFAULT '',
            bio TEXT NOT NULL DEFAULT '',
            initials TEXT NOT NULL DEFAULT '',
            image_path TEXT NOT NULL DEFAULT '',
            sort_order INTEGER NOT NULL DEFAULT 0,
            active BOOLEAN NOT NULL DEFAULT TRUE
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS cms_publications (
            id SERIAL PRIMARY KEY,
            year TEXT NOT NULL DEFAULT '',
            citation TEXT NOT NULL DEFAULT '',
            link_label TEXT NOT NULL DEFAULT '',
            link_url TEXT NOT NULL DEFAULT '',
            sort_order INTEGER NOT NULL DEFAULT 0,
            active BOOLEAN NOT NULL DEFAULT TRUE
        )
        """,
    ]
    with _conn() as conn:
        with conn.cursor() as cur:
            for statement in statements:
                cur.execute(statement)
        conn.commit()


def get_page(slug):
    default = DEFAULT_PAGES.get(slug, {"title": slug.title(), "subtitle": "", "extra": {}})
    if not DATABASE_URL:
        return {"slug": slug, "title": default["title"], "subtitle": default["subtitle"], "body": "", "extra": default.get("extra", {})}
    with _conn() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SELECT * FROM cms_pages WHERE slug = %s", (slug,))
            row = cur.fetchone()
    if not row:
        return {"slug": slug, "title": default["title"], "subtitle": default["subtitle"], "body": "", "extra": default.get("extra", {})}
    extra = _safe_json(row.get("extra_json"), default.get("extra", {}))
    return {
        "slug": slug,
        "title": row.get("title") or default["title"],
        "subtitle": row.get("subtitle") or default["subtitle"],
        "body": row.get("body") or "",
        "extra": extra,
    }


def save_page(slug, title, subtitle, body, extra):
    ensure_tables()
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO cms_pages (slug, title, subtitle, body, extra_json, updated_at)
                VALUES (%s, %s, %s, %s, %s, CURRENT_TIMESTAMP)
                ON CONFLICT (slug) DO UPDATE SET
                    title = EXCLUDED.title,
                    subtitle = EXCLUDED.subtitle,
                    body = EXCLUDED.body,
                    extra_json = EXCLUDED.extra_json,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (slug, title or "", subtitle or "", body or "", json.dumps(extra or {})),
            )
        conn.commit()


def list_news():
    if not DATABASE_URL:
        return [dict(item, id=idx + 1) for idx, item in enumerate(DEFAULT_NEWS)]
    with _conn() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SELECT * FROM cms_news WHERE active = TRUE ORDER BY sort_order ASC, id ASC")
            rows = cur.fetchall()
    if rows:
        return rows
    return [dict(item, id=idx + 1) for idx, item in enumerate(DEFAULT_NEWS)]


def upsert_news(news_id, date_label, title, body, link_text, link_url, sort_order):
    ensure_tables()
    with _conn() as conn:
        with conn.cursor() as cur:
            if news_id:
                cur.execute(
                    """
                    UPDATE cms_news
                    SET date_label=%s, title=%s, body=%s, link_text=%s, link_url=%s, sort_order=%s, active=TRUE
                    WHERE id=%s
                    """,
                    (date_label, title, body, link_text, link_url, sort_order, news_id),
                )
            else:
                cur.execute(
                    """
                    INSERT INTO cms_news (date_label, title, body, link_text, link_url, sort_order, active)
                    VALUES (%s, %s, %s, %s, %s, %s, TRUE)
                    """,
                    (date_label, title, body, link_text, link_url, sort_order),
                )
        conn.commit()


def delete_news(news_id):
    _soft_delete("cms_news", news_id)


def list_publications():
    if not DATABASE_URL:
        return [dict(item, id=idx + 1) for idx, item in enumerate(DEFAULT_PUBLICATIONS)]
    with _conn() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SELECT * FROM cms_publications WHERE active = TRUE ORDER BY sort_order ASC, id ASC")
            rows = cur.fetchall()
    if rows:
        return rows
    return [dict(item, id=idx + 1) for idx, item in enumerate(DEFAULT_PUBLICATIONS)]


def upsert_publication(pub_id, year, citation, link_label, link_url, sort_order):
    ensure_tables()
    with _conn() as conn:
        with conn.cursor() as cur:
            if pub_id:
                cur.execute(
                    """
                    UPDATE cms_publications
                    SET year=%s, citation=%s, link_label=%s, link_url=%s, sort_order=%s, active=TRUE
                    WHERE id=%s
                    """,
                    (year, citation, link_label, link_url, sort_order, pub_id),
                )
            else:
                cur.execute(
                    """
                    INSERT INTO cms_publications (year, citation, link_label, link_url, sort_order, active)
                    VALUES (%s, %s, %s, %s, %s, TRUE)
                    """,
                    (year, citation, link_label, link_url, sort_order),
                )
        conn.commit()


def delete_publication(pub_id):
    _soft_delete("cms_publications", pub_id)


def list_team_members():
    if not DATABASE_URL:
        return [dict(item, id=idx + 1, sort_order=idx) for idx, item in enumerate(DEFAULT_TEAM)]
    with _conn() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SELECT * FROM cms_team_members WHERE active = TRUE ORDER BY sort_order ASC, id ASC")
            rows = cur.fetchall()
    if rows:
        return rows
    return [dict(item, id=idx + 1, sort_order=idx) for idx, item in enumerate(DEFAULT_TEAM)]


def upsert_team_member(member_id, section, name, role, bio, initials, sort_order, image_path=""):
    ensure_tables()
    with _conn() as conn:
        with conn.cursor() as cur:
            if member_id:
                if image_path:
                    cur.execute(
                        """
                        UPDATE cms_team_members
                        SET section=%s, name=%s, role=%s, bio=%s, initials=%s, image_path=%s, sort_order=%s, active=TRUE
                        WHERE id=%s
                        """,
                        (section, name, role, bio, initials, image_path, sort_order, member_id),
                    )
                else:
                    cur.execute(
                        """
                        UPDATE cms_team_members
                        SET section=%s, name=%s, role=%s, bio=%s, initials=%s, sort_order=%s, active=TRUE
                        WHERE id=%s
                        """,
                        (section, name, role, bio, initials, sort_order, member_id),
                    )
            else:
                cur.execute(
                    """
                    INSERT INTO cms_team_members (section, name, role, bio, initials, image_path, sort_order, active)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, TRUE)
                    """,
                    (section, name, role, bio, initials, image_path or "", sort_order),
                )
        conn.commit()


def delete_team_member(member_id):
    _soft_delete("cms_team_members", member_id)


def list_users():
    if not DATABASE_URL:
        return []
    with _conn() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SELECT email, role, active, created_at FROM cms_users ORDER BY email ASC")
            return cur.fetchall()


def upsert_user(email, role="editor", active=True):
    ensure_tables()
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO cms_users (email, role, active)
                VALUES (%s, %s, %s)
                ON CONFLICT (email) DO UPDATE SET role = EXCLUDED.role, active = EXCLUDED.active
                """,
                (email.lower().strip(), role, bool(active)),
            )
        conn.commit()


def delete_user(email):
    if not DATABASE_URL:
        return
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM cms_users WHERE email = %s", (email.lower().strip(),))
        conn.commit()


def find_user(email):
    if not DATABASE_URL or not email:
        return None
    with _conn() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SELECT email, role, active FROM cms_users WHERE email = %s", (email.lower().strip(),))
            return cur.fetchone()


def is_allowed_email(email):
    if not email:
        return False
    user = find_user(email)
    if user and user.get("active"):
        return True
    allowed = {item.strip().lower() for item in os.environ.get("CMS_ALLOWED_EMAILS", "").split(",") if item.strip()}
    return email.lower().strip() in allowed


def bootstrap_role(email):
    admins = {item.strip().lower() for item in os.environ.get("CMS_BOOTSTRAP_ADMINS", "").split(",") if item.strip()}
    return "admin" if email.lower().strip() in admins else "editor"


def save_upload(file_storage):
    if not file_storage or not getattr(file_storage, "filename", ""):
        return ""
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    suffix = Path(file_storage.filename).suffix.lower()[:10]
    filename = f"{uuid.uuid4().hex[:16]}{suffix}"
    path = UPLOAD_DIR / filename
    file_storage.save(path)
    return f"/static/uploads/cms/{filename}"


def _soft_delete(table, row_id):
    if not DATABASE_URL or not row_id:
        return
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute(f"UPDATE {table} SET active = FALSE WHERE id = %s", (row_id,))
        conn.commit()


def _safe_json(value, default):
    try:
        parsed = json.loads(value or "{}")
        if isinstance(parsed, dict):
            return parsed
    except Exception:
        pass
    return default


def _conn():
    return psycopg2.connect(DATABASE_URL)

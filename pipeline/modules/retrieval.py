"""
Sequence retrieval module.

Supports three input modes:
  1. raw_fasta  — user pasted a FASTA or raw amino-acid string
  2. uniprot    — fetch by UniProt accession via official REST API
  3. ncbi       — fetch by NCBI protein accession via Entrez efetch

APIs used (all official, confirmed):
  UniProt: GET https://rest.uniprot.org/uniprotkb/{accession}.fasta  (no key needed)
  NCBI:    Biopython Bio.Entrez.efetch  (official E-utilities wrapper)  (no key needed)
"""

import re
import requests

try:
    from Bio import Entrez, SeqIO
    _BIOPYTHON = True
except ImportError:
    _BIOPYTHON = False

from pipeline.utils import fasta as fasta_utils

# NCBI requires an email for Entrez calls.  The value is informational — any
# valid-looking address works.  Set to the lab address once known.
ENTREZ_EMAIL = "singhlab.notify@gmail.com"


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def run(input_data: dict, job_dir: str) -> dict:
    """
    Args:
        input_data: {
            "input_type": "raw_fasta" | "uniprot" | "ncbi",
            "sequence_input": str   # the raw text from the form
        }
        job_dir: absolute path to this job's output folder

    Returns:
        {
            "status": "ok" | "error",
            "sequence": str,        # clean uppercase sequence
            "header": str,          # description / accession
            "source": str,          # "raw" | "uniprot" | "ncbi"
            "organism": str,        # empty if unavailable
            "error": str
        }
    """
    input_type = input_data.get("input_type", "auto")
    raw = (input_data.get("sequence_input") or "").strip()

    if not raw:
        return _err("No input provided.")

    if input_type == "auto":
        input_type = _detect_input_type(raw)

    if input_type == "uniprot":
        return _fetch_uniprot(raw)
    if input_type == "ncbi":
        return _fetch_ncbi(raw)
    # Default: treat as raw FASTA / sequence
    return _parse_raw(raw)


# ---------------------------------------------------------------------------
# Raw FASTA
# ---------------------------------------------------------------------------

def _parse_raw(raw: str) -> dict:
    result = fasta_utils.parse_input(raw)
    if not result["ok"]:
        return _err(result["error"])
    return {
        "status": "ok",
        "sequence": result["sequence"],
        "header": result["header"] or "User-submitted sequence",
        "source": "raw",
        "organism": "",
        "error": "",
    }


# ---------------------------------------------------------------------------
# UniProt REST API
# Endpoint: https://rest.uniprot.org/uniprotkb/{accession}.fasta
# Method: GET   Auth: none   Confirmed: HIGH confidence
# ---------------------------------------------------------------------------

def _fetch_uniprot(accession: str) -> dict:
    accession = accession.strip().upper()
    if _looks_like_ncbi_identifier(accession):
        return _fetch_ncbi(accession)
    url = f"https://rest.uniprot.org/uniprotkb/{accession}.fasta"
    try:
        r = requests.get(url, timeout=20)
        if r.status_code == 404:
            return _err(f"UniProt accession not found: {accession}")
        r.raise_for_status()
    except requests.RequestException as e:
        return _err(f"UniProt fetch failed: {e}")

    text = r.text.strip()
    if not text or not text.startswith(">"):
        return _err(f"UniProt returned unexpected content for {accession}")

    parsed = fasta_utils.parse_input(text)
    if not parsed["ok"]:
        return _err(f"Could not parse UniProt FASTA: {parsed['error']}")

    # Extract organism from header  e.g. "sp|P12345|... OS=Homo sapiens OX=9606 ..."
    organism = ""
    m = re.search(r"OS=([^=]+?)(?:\s+OX=|\s+GN=|\s*$)", parsed["header"])
    if m:
        organism = m.group(1).strip()

    return {
        "status": "ok",
        "sequence": parsed["sequence"],
        "header": parsed["header"],
        "source": "uniprot",
        "organism": organism,
        "error": "",
    }


# ---------------------------------------------------------------------------
# NCBI Entrez efetch
# Uses Biopython wrapper around the official E-utilities API.
# Endpoint: https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi
# Method: GET/POST   Auth: none (email recommended)   Confirmed: HIGH confidence
# ---------------------------------------------------------------------------

def _fetch_ncbi(accession: str) -> dict:
    if not _BIOPYTHON:
        return _err("Biopython is not installed. Run: pip install biopython")

    Entrez.email = ENTREZ_EMAIL
    accession = accession.strip()
    if _looks_like_uniprot_identifier(accession):
        return _fetch_uniprot(accession)

    # ------------------------------------------------------------------
    # Accession type detection and resolution
    #
    # Protein prefixes  → fetch directly (NP_, XP_, WP_, YP_, AP_, ZP_)
    # mRNA/RNA          → nuccore→protein elink (NM_, XM_, NR_, XR_)
    # Genomic/WGS       → nuccore→protein elink (NG_, NC_, NW_, NZ_, NT_,
    #                      or 4-6 letter + 8+ digit WGS contigs like GAJC…)
    # Gene ID           → gene→protein elink (4–10 digit numeric)
    # Unknown           → try nuccore elink first, then direct protein fetch
    # ------------------------------------------------------------------
    resolved_from = None
    resolved_how  = None
    resolved      = None
    acc_to_fetch  = accession

    protein_pattern = re.compile(r'^(NP_|XP_|WP_|YP_|AP_|ZP_)', re.IGNORECASE)
    mrna_pattern    = re.compile(r'^(NM_|XM_|NR_|XR_)', re.IGNORECASE)
    genomic_pattern = re.compile(r'^(NG_|NC_|NW_|NZ_|NT_)', re.IGNORECASE)
    wgs_pattern     = re.compile(r'^[A-Z]{4,6}\d{6,}', re.IGNORECASE)
    gene_id_pattern = re.compile(r'^\d{4,10}$')

    if protein_pattern.match(accession):
        # Known protein accession — fetch directly
        pass

    elif mrna_pattern.match(accession) or genomic_pattern.match(accession) or wgs_pattern.match(accession):
        # mRNA, genomic reference, or WGS contig — resolve via nuccore→protein elink
        resolved = _resolve_nucleotide_to_protein(accession)
        if resolved:
            resolved_from = accession
            acc_to_fetch  = resolved["protein_acc"]
            resolved_how  = resolved["how"]
            print(f"[retrieval] resolved nucleotide {accession} → protein {acc_to_fetch} ({resolved_how})")
        else:
            return _err(
                f"Could not resolve '{accession}' to a protein record via NCBI elink. "
                "If this is a WGS contig it may lack annotated CDS protein records. "
                "Supported: protein (NP_, XP_, WP_), mRNA (NM_, XM_), "
                "WGS contigs (e.g. GAJC01020720.1), gene IDs (numeric), or paste FASTA directly."
            )

    elif gene_id_pattern.match(accession):
        # Bare NCBI gene ID
        resolved = _resolve_gene_to_protein(accession)
        if resolved:
            resolved_from = accession
            acc_to_fetch  = resolved["protein_acc"]
            resolved_how  = resolved["how"]
            print(f"[retrieval] resolved gene ID {accession} → protein {acc_to_fetch}")
        else:
            return _err(
                f"No linked protein record found for gene ID '{accession}'. "
                "Please submit a protein accession (NP_/XP_) or paste your FASTA directly."
            )

    else:
        # Unrecognized format — try nuccore elink first, fall through to direct protein fetch
        resolved = _resolve_nucleotide_to_protein(accession)
        if resolved:
            resolved_from = accession
            acc_to_fetch  = resolved["protein_acc"]
            resolved_how  = resolved["how"]
            print(f"[retrieval] resolved '{accession}' via nucleotide elink → {acc_to_fetch}")
        else:
            # Last resort: attempt direct protein fetch (handles unusual protein acc formats)
            print(f"[retrieval] unrecognized accession format '{accession}' — attempting direct protein fetch")

    try:
        handle = Entrez.efetch(db="protein", id=acc_to_fetch, rettype="fasta", retmode="text")
        record = SeqIO.read(handle, "fasta")
        handle.close()
    except Exception as e:
        return _err(f"NCBI Entrez fetch failed for '{acc_to_fetch}': {e}")

    sequence = str(record.seq).upper()
    parsed = fasta_utils.parse_input(sequence)
    if not parsed["ok"]:
        return _err(f"Sequence validation failed: {parsed['error']}")

    # Try to extract organism from Entrez FASTA header
    organism = ""
    desc = record.description or ""
    org_m = re.search(r'\[([^\[\]]+)\]\s*$', desc)
    if org_m:
        organism = org_m.group(1).strip()

    result = {
        "status": "ok",
        "sequence": parsed["sequence"],
        "header": record.description,
        "source": "ncbi",
        "organism": organism,
        "error": "",
    }
    if resolved_from:
        result["resolved_from"]      = resolved_from
        result["resolved_acc"]       = acc_to_fetch
        result["resolved_how"]       = resolved_how
        result["resolved_proteins"]  = (resolved or {}).get("all_candidates", [])
    return result


def _resolve_nucleotide_to_protein(nuc_acc: str) -> dict | None:
    """
    Given any nucleotide/mRNA/WGS accession, find linked protein records via
    NCBI nuccore→protein elink and return the best one (longest sequence).

    Works for NM_, XM_, NR_, XR_, NG_, NC_, NW_, NZ_, NT_, and WGS contigs
    like GAJC01020720.1.

    Returns {"protein_acc": str, "how": str, "all_candidates": list} or None.
    """
    mrna_acc = nuc_acc  # kept for compatibility with body below
    try:
        # Use elink to find nucleotide → protein links
        handle = Entrez.elink(dbfrom="nucleotide", db="protein", id=mrna_acc, linkname="nuccore_protein")
        records = Entrez.read(handle)
        handle.close()

        if not records or not records[0].get("LinkSetDb"):
            return None

        link_ids = [link["Id"] for link in records[0]["LinkSetDb"][0]["Link"]]
        if not link_ids:
            return None

        # Prefer XP_ (predicted), then NP_ (RefSeq curated), then any
        # Fetch summaries to get accession strings
        id_str = ",".join(link_ids[:20])  # limit to 20
        summary_handle = Entrez.esummary(db="protein", id=id_str)
        summaries = Entrez.read(summary_handle)
        summary_handle.close()

        xp_candidates = []
        np_candidates = []
        other_candidates = []

        for s in summaries:
            acc = str(s.get("AccessionVersion", ""))
            length = int(s.get("Length", 0))
            title = str(s.get("Title", ""))
            entry = {"accession": acc, "length": length, "description": title}
            if acc.startswith("XP_"):
                xp_candidates.append(entry)
            elif acc.startswith("NP_"):
                np_candidates.append(entry)
            else:
                other_candidates.append(entry)

        # Sort each class by length desc
        for grp in [xp_candidates, np_candidates, other_candidates]:
            grp.sort(key=lambda x: -x["length"])

        # All candidates ordered XP_ → NP_ → other (up to 10)
        all_candidates = (xp_candidates + np_candidates + other_candidates)[:10]

        # Pick the longest among preferred class
        for candidates in [xp_candidates, np_candidates, other_candidates]:
            if candidates:
                best = candidates[0]
                prefix_class = "XP_" if xp_candidates and candidates is xp_candidates else (
                    "NP_" if np_candidates and candidates is np_candidates else "protein"
                )
                return {
                    "protein_acc": best["accession"],
                    "how": f"linked {prefix_class} protein (longest, {best['length']} aa) via NCBI elink",
                    "all_candidates": all_candidates,
                }
    except Exception as e:
        print(f"[retrieval] nucleotide→protein resolution failed for {nuc_acc}: {e}")
    return None


def _resolve_gene_to_protein(gene_id: str) -> dict | None:
    """
    Given an NCBI gene ID, find linked protein records and return the best one.
    """
    try:
        handle = Entrez.elink(dbfrom="gene", db="protein", id=gene_id, linkname="gene_protein_refseq")
        records = Entrez.read(handle)
        handle.close()

        if not records or not records[0].get("LinkSetDb"):
            return None

        link_ids = [link["Id"] for link in records[0]["LinkSetDb"][0]["Link"]]
        if not link_ids:
            return None

        id_str = ",".join(link_ids[:10])
        summary_handle = Entrez.esummary(db="protein", id=id_str)
        summaries = Entrez.read(summary_handle)
        summary_handle.close()

        candidates = [
            {"accession": str(s.get("AccessionVersion", "")),
             "length": int(s.get("Length", 0)),
             "description": str(s.get("Title", ""))}
            for s in summaries if s.get("AccessionVersion")
        ]
        if not candidates:
            return None

        candidates.sort(key=lambda x: -x["length"])
        best = candidates[0]
        return {
            "protein_acc": best["accession"],
            "how": f"linked RefSeq protein (longest, {best['length']} aa) via NCBI gene elink",
            "all_candidates": candidates[:10],
        }
    except Exception as e:
        print(f"[retrieval] gene→protein resolution failed for {gene_id}: {e}")
    return None


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def _err(msg: str) -> dict:
    return {"status": "error", "sequence": "", "header": "", "source": "", "organism": "", "error": msg}


def _detect_input_type(raw: str) -> str:
    text = raw.strip()
    if not text:
        return "raw_fasta"
    if text.startswith(">") or "\n" in text or " " in text:
        return "raw_fasta"
    if _looks_like_ncbi_identifier(text):
        return "ncbi"
    if _looks_like_uniprot_identifier(text):
        return "uniprot"
    return "raw_fasta"


def _looks_like_ncbi_identifier(text: str) -> bool:
    token = text.strip().upper()
    if not token:
        return False
    if re.match(r'^(NP_|XP_|WP_|YP_|AP_|ZP_|NM_|XM_|NR_|XR_|NG_|NC_|NW_|NZ_|NT_)', token):
        return True
    if re.match(r'^[A-Z]{4,6}\d{6,}(?:\.\d+)?$', token):
        return True
    if re.match(r'^\d{4,10}$', token):
        return True
    return False


def _looks_like_uniprot_identifier(text: str) -> bool:
    token = text.strip().upper()
    return bool(
        re.match(r'^[OPQ][0-9][A-Z0-9]{3}[0-9](?:-\d+)?$', token) or
        re.match(r'^[A-NR-Z][0-9][A-Z0-9]{3}[0-9](?:-\d+)?$', token) or
        re.match(r'^[A-Z0-9]{10}$', token)
    )

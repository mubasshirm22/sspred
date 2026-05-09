"""
UniProtKB feature fetcher.

Pulls curated positional features from the official UniProt REST API and
normalizes them into ProtPipe's shared annotation schema.
"""

import re

import requests


BASE_URL = "https://rest.uniprot.org/uniprotkb"
TIMEOUT = 30

_TYPE_MAP = {
    "Domain": "domain",
    "Repeat": "repeat",
    "Region": "domain",
    "Zinc finger": "domain",
    "Motif": "motif",
    "Binding site": "binding_site",
    "Active site": "active_site",
    "Site": "site",
    "Metal binding": "metal_binding",
    "Disulfide bond": "disulfide",
    "Helix": "helix",
    "Beta strand": "strand",
    "Turn": "strand",
    "Compositional bias": "low_complexity",
    "Transmembrane": "transmembrane",
    "Intramembrane": "transmembrane",
    "Signal peptide": "signal_peptide",
    "Transit peptide": "signal_peptide",
    "Coiled coil": "coiled_coil",
}


def run(sequence: str, job_dir: str, accession: str = "") -> dict:
    uniprot_acc = infer_uniprot_accession(accession)
    if not uniprot_acc:
        return {"status": "error", "data": {}, "error": "No UniProt accession available for UniProtKB feature mapping."}

    try:
        response = requests.get(f"{BASE_URL}/{uniprot_acc}.json", timeout=TIMEOUT)
        if response.status_code == 404:
            return {"status": "error", "data": {}, "error": f"UniProt accession not found: {uniprot_acc}"}
        response.raise_for_status()
        payload = response.json()
    except requests.RequestException as exc:
        return {"status": "error", "data": {}, "error": f"UniProt feature fetch failed: {exc}"}
    except ValueError as exc:
        return {"status": "error", "data": {}, "error": f"UniProt returned invalid JSON: {exc}"}

    annotations = _parse_features(payload.get("features") or [])
    return {
        "status": "ok",
        "data": {
            "accession": payload.get("primaryAccession", uniprot_acc),
            "annotations": annotations,
        },
        "error": "",
    }


def infer_uniprot_accession(value: str) -> str:
    text = (value or "").strip()
    if not text:
        return ""
    sp_match = re.search(r"\b(?:sp|tr)\|([A-Z0-9]{6,10})\|", text, re.IGNORECASE)
    if sp_match:
        return sp_match.group(1).upper()
    url_match = re.search(r"/([A-Z0-9]{6,10})(?:[/?#]|$)", text, re.IGNORECASE)
    if url_match and _looks_like_uniprot(url_match.group(1)):
        return url_match.group(1).upper()
    token_match = re.search(r"\b([A-Z0-9]{6,10})\b", text, re.IGNORECASE)
    if token_match and _looks_like_uniprot(token_match.group(1)):
        return token_match.group(1).upper()
    return ""


def _looks_like_uniprot(text: str) -> bool:
    token = (text or "").strip().upper()
    if re.fullmatch(r"[OPQ][0-9][A-Z0-9]{3}[0-9](?:-\d+)?", token):
        return True
    if re.fullmatch(r"[A-NR-Z][0-9][A-Z0-9]{3}[0-9](?:-\d+)?", token):
        return True
    if re.fullmatch(r"[A-Z0-9]{10}", token):
        return True
    return False


def _parse_features(features: list) -> list:
    output = []
    for feature in features:
        annotation = _feature_to_annotation(feature)
        if annotation:
            output.append(annotation)
    return output


def _feature_to_annotation(feature: dict):
    feature_type = feature.get("type", "")
    mapped = _TYPE_MAP.get(feature_type)
    if not mapped:
        return None

    start = _pos(feature.get("location", {}).get("start"))
    end = _pos(feature.get("location", {}).get("end"))
    if start is None or end is None:
        return None
    if mapped in {"binding_site", "active_site", "site", "metal_binding"}:
        end = start

    description = (feature.get("description") or "").strip()
    ligand = ((feature.get("ligand") or {}).get("name") or "").strip()
    label = description or ligand or feature_type
    evidence = feature_type
    if ligand and ligand not in label:
        evidence = f"{feature_type} ({ligand})"

    return {
        "source": "UniProtKB",
        "feature_type": mapped,
        "start": start,
        "end": end,
        "label": label[:80],
        "accession": feature.get("featureId", "") or feature_type,
        "description": description[:200],
        "e_value": None,
        "score": None,
        "evidence": evidence[:120],
        "display_priority": 30,
        "source_support": ["UniProtKB"],
    }


def _pos(item):
    if not isinstance(item, dict):
        return None
    value = item.get("value")
    try:
        return int(value)
    except (TypeError, ValueError):
        return None

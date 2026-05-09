import re


_TRACK_ORDER = {
    "topology": 0,
    "domains": 1,
    "motifs": 2,
    "sites": 3,
    "supplementary": 4,
}

_TYPE_META = {
    "signal_peptide": {"track": "topology", "color": "#0f766e", "label": "Signal peptide"},
    "transmembrane": {"track": "topology", "color": "#1d4ed8", "label": "TM helix"},
    "domain": {"track": "domains", "color": "#7c3aed", "label": "Domain"},
    "family": {"track": "domains", "color": "#6d28d9", "label": "Family"},
    "repeat": {"track": "domains", "color": "#8b5cf6", "label": "Repeat"},
    "coiled_coil": {"track": "domains", "color": "#ea580c", "label": "Coiled-coil"},
    "low_complexity": {"track": "supplementary", "color": "#ca8a04", "label": "Low complexity"},
    "motif": {"track": "motifs", "color": "#db2777", "label": "Motif"},
    "active_site": {"track": "sites", "color": "#dc2626", "label": "Active site"},
    "binding_site": {"track": "sites", "color": "#b91c1c", "label": "Binding site"},
    "metal_binding": {"track": "sites", "color": "#be123c", "label": "Metal-binding site"},
    "disulfide": {"track": "sites", "color": "#ef4444", "label": "Disulfide"},
    "site": {"track": "sites", "color": "#f43f5e", "label": "Site"},
}


def build(summary: dict, job_id: str) -> dict:
    retrieval = summary.get("retrieval", {}) or {}
    properties = summary.get("properties", {}) or {}
    annotations = summary.get("annotations", []) or []
    blast_hits = (summary.get("blast", {}) or {}).get("hits", []) or []

    sequence = retrieval.get("sequence", "") or ""
    length = len(sequence) or properties.get("length") or _max_end(annotations)
    features = _normalize_features(annotations, length)
    tracks = _group_tracks(features)
    links = _external_links(retrieval, blast_hits)

    return {
        "job_id": job_id,
        "title": _title_for_summary(retrieval, job_id),
        "length": length,
        "sequence": sequence,
        "retrieval": retrieval,
        "properties": properties,
        "links": links,
        "features": features,
        "tracks": tracks,
        "stats": {
            "domains": sum(1 for item in features if item["track"] == "domains"),
            "motifs": sum(1 for item in features if item["track"] == "motifs"),
            "sites": sum(1 for item in features if item["track"] == "sites"),
            "topology": sum(1 for item in features if item["track"] == "topology"),
        },
    }


def _title_for_summary(retrieval: dict, job_id: str) -> str:
    return (
        retrieval.get("header")
        or retrieval.get("resolved_acc")
        or retrieval.get("accession")
        or retrieval.get("resolved_from")
        or f"ProtPipe job {job_id}"
    )


def _normalize_features(annotations, length):
    output = []
    for item in annotations:
        try:
            start = int(item.get("start", 0))
            end = int(item.get("end", 0))
        except (TypeError, ValueError):
            continue
        if not start or not end or end < start:
            continue
        meta = _TYPE_META.get(item.get("feature_type"), {"track": "supplementary", "color": "#64748b", "label": item.get("feature_type", "Feature").replace("_", " ").title()})
        left = round(((start - 1) / max(length, 1)) * 100, 3)
        width = round((max(1, end - start + 1) / max(length, 1)) * 100, 3)
        output.append({
            "label": item.get("label") or meta["label"],
            "feature_type": item.get("feature_type", "feature"),
            "track": meta["track"],
            "track_label": meta["track"].replace("_", " ").title(),
            "color": meta["color"],
            "start": start,
            "end": end,
            "width": width,
            "left": left,
            "source": item.get("source") or (item.get("source_support") or [""])[0],
            "description": item.get("description", ""),
            "score": item.get("score"),
            "evalue": item.get("evalue"),
        })
    output.sort(key=lambda row: (_TRACK_ORDER.get(row["track"], 99), row["start"], row["end"], row["label"]))
    return output


def _group_tracks(features):
    grouped = []
    for track_name in ("topology", "domains", "motifs", "sites", "supplementary"):
        items = [item for item in features if item["track"] == track_name]
        if items:
            grouped.append({
                "name": track_name,
                "label": track_name.replace("_", " ").title(),
                "items": items,
            })
    return grouped


def _external_links(retrieval: dict, blast_hits: list) -> dict:
    header = retrieval.get("header", "") or ""
    resolved_acc = retrieval.get("resolved_acc", "") or ""
    input_acc = retrieval.get("accession", "") or ""

    uniprot_acc = _infer_uniprot_accession(header) or _infer_uniprot_accession(resolved_acc) or _infer_uniprot_accession(input_acc)
    ncbi_acc = _infer_ncbi_accession(header) or _infer_ncbi_accession(resolved_acc) or _infer_ncbi_accession(input_acc)

    links = {}
    if uniprot_acc:
        links["uniprot"] = {
            "label": f"UniProt {uniprot_acc}",
            "url": f"https://www.uniprot.org/uniprotkb/{uniprot_acc}",
        }
        links["alphafold"] = {
            "label": "AlphaFold DB",
            "url": f"https://alphafold.ebi.ac.uk/entry/{uniprot_acc}",
        }
    if ncbi_acc:
        links["ncbi"] = {
            "label": f"NCBI Protein {ncbi_acc}",
            "url": f"https://www.ncbi.nlm.nih.gov/protein/{ncbi_acc}",
        }
    if blast_hits:
        top = blast_hits[0]
        accession = top.get("accession")
        if accession:
            links["blast_top"] = {
                "label": f"Top BLAST hit {accession}",
                "url": f"https://www.ncbi.nlm.nih.gov/protein/{accession}",
            }
    return links


def _infer_uniprot_accession(value: str) -> str:
    text = (value or "").strip()
    if not text:
        return ""
    sp_match = re.search(r"\b(?:sp|tr)\|([A-Z0-9]{6,10})\|", text, re.IGNORECASE)
    if sp_match:
        return sp_match.group(1).upper()
    plain_match = re.fullmatch(r"[A-Z0-9]{6,10}", text, re.IGNORECASE)
    if plain_match and not _infer_ncbi_accession(text):
        return plain_match.group(0).upper()
    return ""


def _infer_ncbi_accession(value: str) -> str:
    text = (value or "").strip()
    if not text:
        return ""
    match = re.search(r"\b([A-Z]{1,3}_[0-9]+(?:\.[0-9]+)?)\b", text, re.IGNORECASE)
    if match:
        return match.group(1)
    return ""


def _max_end(annotations) -> int:
    best = 0
    for item in annotations or []:
        try:
            best = max(best, int(item.get("end", 0)))
        except (TypeError, ValueError):
            continue
    return best

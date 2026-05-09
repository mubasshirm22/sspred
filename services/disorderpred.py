from statistics import mean

from services import netsurf, iupred


def run(sequence: str, accession: str = "") -> dict:
    raw_data, error = netsurf.fetch_raw_prediction(sequence)
    if raw_data is None:
        return {"status": "error", "data": {}, "error": error or "NetSurf disorder run failed."}

    disorder = _float_list(raw_data.get("disorder") or [])
    q3 = (raw_data.get("q3") or "").upper()
    if not disorder:
        return {"status": "error", "data": {}, "error": "NetSurf returned no disorder values."}

    residues = []
    for idx, aa in enumerate(sequence):
        residues.append({
            "pos": idx + 1,
            "aa": aa,
            "disorder": round(disorder[idx], 4) if idx < len(disorder) else None,
            "ss": q3[idx] if idx < len(q3) else "",
        })

    disordered_regions = _score_regions(disorder, threshold=0.5, minimum=8, label="Disordered region")
    highly_disordered_regions = _score_regions(disorder, threshold=0.7, minimum=6, label="Highly disordered region")
    low_complexity_regions = _low_complexity_regions(sequence)
    comparisons = _comparison_sources(sequence, accession)

    payload = {
        "sequence": sequence,
        "length": len(sequence),
        "mean_disorder": round(mean(disorder), 4),
        "max_disorder": round(max(disorder), 4),
        "disordered_fraction": round(sum(1 for value in disorder if value >= 0.5) / len(disorder), 4),
        "residues": residues,
        "disordered_regions": disordered_regions,
        "high_disorder_regions": highly_disordered_regions,
        "low_complexity_regions": low_complexity_regions,
        "secondary_structure": q3,
        "comparisons": comparisons,
    }
    return {"status": "ok", "data": payload, "error": ""}


def _float_list(values):
    output = []
    for value in values:
        try:
            output.append(float(value))
        except (TypeError, ValueError):
            return []
    return output


def _score_regions(scores, threshold=0.5, minimum=8, label="Region"):
    regions = []
    start = None
    for idx, score in enumerate(scores, start=1):
        if score >= threshold and start is None:
            start = idx
        elif score < threshold and start is not None:
            end = idx - 1
            if end - start + 1 >= minimum:
                segment = scores[start - 1:end]
                regions.append({
                    "start": start,
                    "end": end,
                    "label": label,
                    "mean_score": round(mean(segment), 4),
                })
            start = None
    if start is not None:
        end = len(scores)
        if end - start + 1 >= minimum:
            segment = scores[start - 1:end]
            regions.append({
                "start": start,
                "end": end,
                "label": label,
                "mean_score": round(mean(segment), 4),
            })
    return regions


def _low_complexity_regions(sequence, window=12, entropy_threshold=1.8, minimum=10):
    hits = []
    if len(sequence) < window:
        return hits
    flags = [False] * len(sequence)
    for start in range(0, len(sequence) - window + 1):
        segment = sequence[start:start + window]
        entropy = _shannon_entropy(segment)
        if entropy <= entropy_threshold:
            for idx in range(start, start + window):
                flags[idx] = True
    seg_start = None
    for idx, flagged in enumerate(flags, start=1):
        if flagged and seg_start is None:
            seg_start = idx
        elif not flagged and seg_start is not None:
            end = idx - 1
            if end - seg_start + 1 >= minimum:
                hits.append({"start": seg_start, "end": end, "label": "Low complexity"})
            seg_start = None
    if seg_start is not None:
        end = len(flags)
        if end - seg_start + 1 >= minimum:
            hits.append({"start": seg_start, "end": end, "label": "Low complexity"})
    return hits


def _shannon_entropy(segment):
    counts = {}
    for aa in segment:
        counts[aa] = counts.get(aa, 0) + 1
    total = len(segment)
    entropy = 0.0
    for count in counts.values():
        p = count / total
        entropy -= p * _safe_log2(p)
    return entropy


def _safe_log2(value):
    import math
    return math.log(value, 2) if value > 0 else 0.0


def infer_uniprot_accession(value: str) -> str:
    import re
    text = (value or "").strip()
    if not text:
        return ""
    sp_match = re.search(r"\b(?:sp|tr)\|([A-Z0-9]{6,10})\|", text, re.IGNORECASE)
    if sp_match:
        return sp_match.group(1).upper()
    plain_match = re.fullmatch(r"[A-Z0-9]{6,10}", text, re.IGNORECASE)
    if plain_match:
        return plain_match.group(0).upper()
    return ""


def _comparison_sources(sequence: str, accession: str):
    acc = infer_uniprot_accession(accession)
    output = []
    for mode in ("long", "short", "anchor"):
        result = iupred.run(sequence="", accession=acc, context=mode) if acc else {"status": "error", "data": {}, "error": "No accession available."}
        if result.get("status") != "ok":
            retry = iupred.run(sequence=sequence, accession="", context=mode) if sequence else result
            result = retry
        if result.get("status") != "ok":
            output.append({
                "name": "ANCHOR2" if mode == "anchor" else f"IUPred3 {mode}",
                "status": "error",
                "error": result.get("error", ""),
                "regions": [],
                "mean_score": None,
                "disordered_fraction": None,
            })
            continue
        data = result.get("data", {})
        output.append({
            "name": "ANCHOR2" if mode == "anchor" else f"IUPred3 {mode}",
            "status": "ok",
            "regions": data.get("anchor_regions", []) if mode == "anchor" else data.get("regions", []),
            "mean_score": data.get("mean_score"),
            "disordered_fraction": data.get("disordered_fraction"),
            "scores": data.get("anchor_scores", []) if mode == "anchor" else data.get("scores", []),
            "accession": data.get("accession", ""),
        })
    return output

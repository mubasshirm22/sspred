from concurrent.futures import ThreadPoolExecutor, wait

from services import batchtools, disorderpred, jpred, netsurf, predator, psi, sable, ss, sspro, yaspin


_SSPRED_SERVICES = [
    ("JPred", jpred),
    ("PSI", psi),
    ("Sable", sable),
    ("SSPro", sspro),
    ("Yaspin", yaspin),
    ("Predator", predator),
    ("NetSurf", netsurf),
]


def run_disorder(seq, job_dir=None, accession=""):
    return disorderpred.run(seq, accession=accession)


def run_sspred_consensus(seq, job_dir=None, timeout=900):
    sequence = (seq or "").strip().upper()
    if not sequence:
        return {"status": "error", "data": {}, "error": "No sequence provided for SSPred companion analysis."}

    results = {}
    with ThreadPoolExecutor(max_workers=len(_SSPRED_SERVICES)) as executor:
        futures = {
            executor.submit(_call_service, name, module, sequence): name
            for name, module in _SSPRED_SERVICES
        }
        done, not_done = wait(futures, timeout=timeout)
        for future in done:
            name = futures[future]
            try:
                results[name] = future.result()
            except Exception as exc:
                results[name] = _error_obj(name, f"Unexpected companion error: {exc}")
        for future in not_done:
            name = futures[future]
            results[name] = _error_obj(name, f"Timed out after {int(timeout // 60)} minutes.")

    ordered = [results.get(name, _error_obj(name, "No result returned.")) for name, _ in _SSPRED_SERVICES]
    valid = [item for item in ordered if item.status in (1, 3) and len(item.pred or "") == len(sequence)]
    if not valid:
        return {"status": "error", "data": {}, "error": "No SSPred companion services returned a usable prediction."}

    consensus = batchtools.majorityVote(sequence, ordered)
    consensus_mode = "majority_vote"
    if not consensus:
        consensus = valid[0].pred
        consensus_mode = "single_predictor_fallback"

    confidence = _consensus_confidence(consensus, valid)
    counts = _structure_counts(consensus)
    service_rows = [_service_payload(item, len(sequence)) for item in ordered]

    return {
        "status": "ok",
        "data": {
            "sequence": sequence,
            "consensus": consensus,
            "confidence": confidence,
            "mode": consensus_mode,
            "contributors": [item.name for item in valid],
            "service_count": len(valid),
            "counts": counts,
            "regions": _regions(consensus),
            "services": service_rows,
        },
        "error": "",
    }


def _call_service(name, module, sequence):
    result = module.get(sequence)
    if not isinstance(result, ss.SS):
        return _error_obj(name, "Service returned an unexpected response type.")
    if not getattr(result, "name", ""):
        result.name = name
    return result


def _error_obj(name, message):
    item = ss.SS(name)
    item.status = 2
    item.conf = message
    item.pred = ""
    return item


def _service_payload(item, expected_len):
    raw_error = (item.conf if item.status == 2 else "") or (item.pred if item.status == 2 else "")
    payload = {
        "name": item.name,
        "status": _status_name(item.status, item.pred, expected_len),
        "label": _status_label(item.status, item.pred, expected_len),
        "prediction": item.pred if len(item.pred or "") == expected_len else "",
        "confidence": item.conf if len(item.conf or "") == expected_len else "",
        "raw_error": (raw_error or "").strip()[:500],
    }
    return payload


def _status_name(status, pred, expected_len):
    if status in (1, 3) and len(pred or "") == expected_len:
        return "ok"
    if status == 4:
        return "rejected"
    return "error"


def _status_label(status, pred, expected_len):
    if status == 1 and len(pred or "") == expected_len:
        return "Complete"
    if status == 3 and len(pred or "") == expected_len:
        return "Prediction only"
    if status == 4:
        return "Rejected"
    return "Error"


def _consensus_confidence(consensus, valid):
    digits = []
    total = max(1, len(valid))
    for idx, call in enumerate(consensus):
        if call not in {"H", "E", "C"}:
            digits.append("0")
            continue
        votes = sum(1 for item in valid if idx < len(item.pred or "") and item.pred[idx] == call)
        score = max(0, min(9, round((votes / total) * 9)))
        digits.append(str(score))
    return "".join(digits)


def _structure_counts(consensus):
    length = max(1, len(consensus or ""))
    return {
        "helix": sum(1 for c in consensus if c == "H"),
        "strand": sum(1 for c in consensus if c == "E"),
        "coil": sum(1 for c in consensus if c == "C"),
        "length": len(consensus or ""),
        "helix_fraction": round(sum(1 for c in consensus if c == "H") / length, 4),
        "strand_fraction": round(sum(1 for c in consensus if c == "E") / length, 4),
        "coil_fraction": round(sum(1 for c in consensus if c == "C") / length, 4),
    }


def _regions(consensus):
    regions = []
    start = 0
    current = ""
    for idx, call in enumerate(consensus, start=1):
        if call != current:
            if current in {"H", "E", "C"}:
                regions.append({"type": current, "start": start, "end": idx - 1})
            current = call
            start = idx
    if current in {"H", "E", "C"}:
        regions.append({"type": current, "start": start, "end": len(consensus)})
    return regions

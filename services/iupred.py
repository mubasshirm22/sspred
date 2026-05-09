import json
import re

import requests


BASE_URL = "https://iupred3.elte.hu"
THRESHOLD = 0.5


def run(sequence: str = "", accession: str = "", context: str = "long") -> dict:
    context = (context or "long").strip().lower()
    if context not in {"long", "short", "anchor"}:
        context = "long"
    if not sequence and not accession:
        return {"status": "error", "data": {}, "error": "No sequence or accession available for IUPred3."}

    try:
        session = requests.Session()
        home = session.get(f"{BASE_URL}/", timeout=30)
        home.raise_for_status()
        match = re.search(r'name="csrfmiddlewaretoken" value="([^"]+)"', home.text)
        if not match:
            return {"status": "error", "data": {}, "error": "IUPred3 CSRF token could not be located."}
        csrf = match.group(1)
        payload = {
            "csrfmiddlewaretoken": csrf,
            "accession": (accession or "").strip(),
            "email": "",
            "inp_seq": (sequence or "").strip(),
            "context": context,
            "smoothing": "savgol",
        }
        result = session.post(
            f"{BASE_URL}/plot",
            data=payload,
            headers={"Referer": f"{BASE_URL}/"},
            timeout=60,
        )
        result.raise_for_status()
        link_match = re.search(r'href="(/raw_json%3F\d+)"', result.text)
        if not link_match:
            return {"status": "error", "data": {}, "error": "IUPred3 raw JSON link was not found in the result page."}
        raw_json = session.get(f"{BASE_URL}{link_match.group(1)}", timeout=60)
        raw_json.raise_for_status()
        parsed = raw_json.json()
    except requests.RequestException as exc:
        return {"status": "error", "data": {}, "error": f"IUPred3 request failed: {exc}"}
    except (ValueError, json.JSONDecodeError) as exc:
        return {"status": "error", "data": {}, "error": f"IUPred3 returned invalid JSON: {exc}"}

    scores = _float_list(parsed.get("iupred2") or [])
    if not scores:
        return {"status": "error", "data": {}, "error": "IUPred3 returned no disorder scores."}

    payload = {
        "accession": (accession or "").strip(),
        "mode": context,
        "sequence": parsed.get("sequence", "") or (sequence or ""),
        "scores": scores,
        "regions": _score_regions(scores, threshold=THRESHOLD, minimum=8),
        "mean_score": round(sum(scores) / len(scores), 4),
        "disordered_fraction": round(sum(1 for value in scores if value >= THRESHOLD) / len(scores), 4),
    }

    anchor_scores = _float_list(parsed.get("anchor2") or [])
    if anchor_scores:
        payload["anchor_scores"] = anchor_scores
        payload["anchor_regions"] = _score_regions(anchor_scores, threshold=THRESHOLD, minimum=6)

    return {"status": "ok", "data": payload, "error": ""}


def _float_list(values):
    output = []
    for value in values:
        try:
            output.append(float(value))
        except (TypeError, ValueError):
            return []
    return output


def _score_regions(scores, threshold=0.5, minimum=8):
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
                    "mean_score": round(sum(segment) / len(segment), 4),
                })
            start = None
    if start is not None:
        end = len(scores)
        if end - start + 1 >= minimum:
            segment = scores[start - 1:end]
            regions.append({
                "start": start,
                "end": end,
                "mean_score": round(sum(segment) / len(segment), 4),
            })
    return regions

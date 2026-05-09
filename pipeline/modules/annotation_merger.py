"""
Annotation merger — normalizes and deduplicates annotations from all sources.

Input: raw result dicts from hmmer, phobius, cdd, scanprosite, smart, interproscan
Output: a clean list of unified Annotation dicts, sorted and deduplicated

Merge strategy:
1. Pull annotations from each source (they all share the same dict schema).
2. Normalize hmmer and phobius output into the shared schema.
3. Quality filter: split into high-confidence, low-confidence, and discarded.
   - Site-type features (active_site, binding_site, metal_binding, disulfide) are ALWAYS kept.
   - Low-confidence = real parsed hits that don't meet the strict threshold.
     These are returned separately so the UI can display them in Section D.
   - Discarded = truly uninformative (generic labels, malformed coordinates).
4. Deduplicate: if two annotations cover nearly the same region (start/end within
   ±15 residues) and have the same general feature category, keep the better one
   and record source_support from both.
5. Sort: signal/TM first, then domains by start position, then sites.
6. Return debug counts + filter_log so the UI can show exactly what happened.
"""

from typing import Optional

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_SITE_TYPES = frozenset({
    "active_site", "binding_site", "metal_binding", "disulfide", "site"
})

_PRIORITY_MAP = {
    "signal_peptide": 10,
    "transmembrane":  20,
    "domain":         30,
    "family":         35,
    "repeat":         40,
    "coiled_coil":    45,
    "helix":          47,
    "strand":         48,
    "low_complexity": 50,
    "motif":          60,
    "active_site":    70,
    "binding_site":   75,
    "metal_binding":  80,
    "disulfide":      85,
    "site":           90,
}

_GENERIC_LABELS = frozenset({
    "uncharacterized protein",
    "protein of unknown function",
    "hypothetical protein",
    "domain of unknown function",
})

_OVERLAP_THRESHOLD = 15   # residues


# ---------------------------------------------------------------------------
# Merge entry point
# ---------------------------------------------------------------------------

def merge(
    hmmer_result:        Optional[dict] = None,
    phobius_result:      Optional[dict] = None,
    signalp_result:      Optional[dict] = None,
    cdd_result:          Optional[dict] = None,
    scanprosite_result:  Optional[dict] = None,
    uniprot_result:      Optional[dict] = None,
    smart_result:        Optional[dict] = None,
    interproscan_result: Optional[dict] = None,
    coils_result:        Optional[dict] = None,
) -> dict:
    """
    Merge all source annotations into one clean list.

    Returns:
        {
          "status": "ok",
          "annotations":            [ {unified annotation dict}, ... ],   # high-confidence
          "low_confidence_annotations": [ {annotation + filter_reason}, ... ],
          "source_summary":         { "HMMER": N_raw, ... },              # raw parsed counts
          "debug": {
              "raw_total": int,
              "validated": int,
              "high_confidence": int,
              "low_confidence": int,
              "discarded": int,
              "deduped": int,
              "raw_per_source": {...},
              "filtered_per_source": {...},
              "deduped_per_source": {...},
              "filter_log": [ {source, label, start, end, reason}, ... ],
          }
        }
    """
    all_annotations = []
    raw_source_counts = {}

    def _collect(result, source_name, normalize_fn=None):
        if not result:
            return
        anns = normalize_fn(result) if normalize_fn else (
            (result.get("data") or {}).get("annotations") or []
        )
        raw_source_counts[source_name] = len(anns)
        all_annotations.extend(anns)

    _collect(hmmer_result,        "HMMER",        _normalize_hmmer)
    _collect(phobius_result,      "Phobius",       _normalize_phobius)
    _collect(signalp_result,      "SignalP",       _normalize_signalp)
    _collect(cdd_result,          "CDD")
    _collect(scanprosite_result,  "ScanProsite")
    _collect(uniprot_result,      "UniProtKB")
    _collect(smart_result,        "SMART")
    _collect(interproscan_result, "InterProScan")
    _collect(coils_result,        "LUPAS")

    # ------------------------------------------------------------------
    # Step 1 — Validate (drop malformed coordinates only)
    # ------------------------------------------------------------------
    validated = []
    filter_log = []

    for a in all_annotations:
        v, reason = _validate_with_reason(a)
        if v is None:
            filter_log.append({
                "source": a.get("source", "?"),
                "label":  str(a.get("label", ""))[:60],
                "start":  a.get("start"),
                "end":    a.get("end"),
                "reason": f"malformed: {reason}",
                "bucket": "discarded",
            })
        else:
            validated.append(v)

    # Snapshot for raw display — validated but NOT yet quality-filtered
    raw_snapshot = [dict(a) for a in validated]

    # ------------------------------------------------------------------
    # Step 2 — Quality filter: split into high-confidence / low-confidence / discarded
    # ------------------------------------------------------------------
    high_confidence = []
    low_confidence  = []

    for a in validated:
        passes, reason = _passes_quality_with_reason(a)
        if passes:
            high_confidence.append(a)
        else:
            # noise: / generic_label: → discard silently (not informative)
            if "noise:" in reason or "generic_label" in reason:
                filter_log.append({
                    "source": a["source"],
                    "label":  a["label"][:60],
                    "start":  a["start"],
                    "end":    a["end"],
                    "reason": reason,
                    "bucket": "discarded",
                })
            else:
                # Borderline real hit — show inline in sections with warning label
                lc = dict(a)
                lc["filter_reason"] = reason
                low_confidence.append(lc)
                filter_log.append({
                    "source": a["source"],
                    "label":  a["label"][:60],
                    "start":  a["start"],
                    "end":    a["end"],
                    "reason": reason,
                    "bucket": "low_confidence",
                })

    # ------------------------------------------------------------------
    # Step 3 — Deduplicate high-confidence annotations
    # ------------------------------------------------------------------
    deduped = _deduplicate(high_confidence)

    # Set display priorities and sort
    for a in deduped:
        a["display_priority"] = _PRIORITY_MAP.get(a["feature_type"], 60)
    deduped.sort(key=lambda a: (a["display_priority"], a["start"]))

    for a in low_confidence:
        a["display_priority"] = _PRIORITY_MAP.get(a["feature_type"], 60)
    low_confidence.sort(key=lambda a: (a["display_priority"], a["start"]))

    # ------------------------------------------------------------------
    # Build per-source counts for the three stages
    # ------------------------------------------------------------------
    def _count_per_source(anns):
        counts = {}
        for a in anns:
            src = a.get("source", "?")
            counts[src] = counts.get(src, 0) + 1
        return counts

    filtered_per_source = _count_per_source(high_confidence)
    deduped_per_source  = {}
    for a in deduped:
        for src in (a.get("source_support") or [a["source"]]):
            deduped_per_source[src] = deduped_per_source.get(src, 0) + 1

    discarded_count = len(filter_log) - len(low_confidence)

    print(
        f"[merger] {len(all_annotations)} raw → "
        f"{len(high_confidence)} high-conf → "
        f"{len(low_confidence)} low-conf → "
        f"{len(deduped)} deduped"
    )

    return {
        "status":                    "ok",
        "annotations":               deduped,
        "low_confidence_annotations": low_confidence,
        "raw_annotations":           raw_snapshot,
        "source_summary":            raw_source_counts,
        "debug": {
            "raw_total":           len(all_annotations),
            "validated":           len(validated),
            "high_confidence":     len(high_confidence),
            "low_confidence":      len(low_confidence),
            "discarded":           discarded_count,
            "deduped":             len(deduped),
            "raw_per_source":      raw_source_counts,
            "filtered_per_source": filtered_per_source,
            "deduped_per_source":  deduped_per_source,
            "filter_log":          filter_log,
        },
    }


# ---------------------------------------------------------------------------
# Source normalizers
# ---------------------------------------------------------------------------

def _normalize_hmmer(result: dict) -> list:
    domains = (result.get("data") or {}).get("domains") or []
    out = []
    for d in domains:
        out.append({
            "source":          "HMMER",
            "feature_type":    "domain",
            "start":           int(d.get("seq_start", 0)),
            "end":             int(d.get("seq_end", 0)),
            "label":           d.get("name", ""),
            "accession":       d.get("name", ""),
            "description":     d.get("description", ""),
            "e_value":         float(d["e_value"]) if d.get("e_value") is not None else None,
            "score":           None,
            "evidence":        f"HMMER/Pfam  {d.get('name','')}",
            "display_priority": 30,
            "source_support":  ["HMMER"],
        })
    return out


def _normalize_phobius(result: dict) -> list:
    data = (result.get("data") or {})
    out  = []
    has_sp = data.get("has_signal_peptide", False)
    sp_end = data.get("signal_peptide_end", 0) or 0
    if has_sp and sp_end > 0:
        out.append({
            "source":          "Phobius",
            "feature_type":    "signal_peptide",
            "start":           1,
            "end":             sp_end,
            "label":           "Signal peptide",
            "accession":       "",
            "description":     f"Signal peptide (Phobius), cleavage after residue {sp_end}",
            "e_value":         None,
            "score":           None,
            "evidence":        f"Phobius  SP 1–{sp_end}",
            "display_priority": 10,
            "source_support":  ["Phobius"],
        })
    for helix in (data.get("tm_helices") or []):
        out.append({
            "source":          "Phobius",
            "feature_type":    "transmembrane",
            "start":           int(helix.get("start", 0)),
            "end":             int(helix.get("end", 0)),
            "label":           "Transmembrane helix",
            "accession":       "",
            "description":     "Transmembrane helix (Phobius)",
            "e_value":         None,
            "score":           None,
            "evidence":        f"Phobius  TM {helix.get('start')}–{helix.get('end')}",
            "display_priority": 20,
            "source_support":  ["Phobius"],
        })
    return out


def _normalize_signalp(result: dict) -> list:
    data   = (result.get("data") or {})
    out    = []
    has_sp = data.get("has_signal_peptide", False)
    sp_end = data.get("signal_peptide_end", 0) or 0
    if has_sp and sp_end > 0:
        d_score = data.get("d_score", None)
        out.append({
            "source":          "SignalP",
            "feature_type":    "signal_peptide",
            "start":           1,
            "end":             sp_end,
            "label":           "Signal peptide",
            "accession":       "",
            "description":     (
                f"Signal peptide (SignalP), residues 1–{sp_end}"
                + (f", D-score {d_score:.3f}" if d_score else "")
            ),
            "e_value":         None,
            "score":           d_score,
            "evidence":        f"SignalP  SP 1–{sp_end}",
            "display_priority": 10,
            "source_support":  ["SignalP"],
        })
    return out


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def _validate_with_reason(a: dict):
    """Return (validated_dict, None) or (None, reason_str)."""
    try:
        start = int(a.get("start", 0))
        end   = int(a.get("end",   0))
    except (TypeError, ValueError):
        return None, "non-integer start/end"

    if start <= 0 or end <= 0:
        return None, f"non-positive coordinates ({start},{end})"
    if end < start and a.get("feature_type") not in _SITE_TYPES:
        return None, f"end < start ({start},{end})"

    if end < start:
        end = start

    return {
        "source":          str(a.get("source", "unknown")),
        "feature_type":    str(a.get("feature_type", "domain")),
        "start":           start,
        "end":             end,
        "label":           str(a.get("label", ""))[:80],
        "accession":       str(a.get("accession", "")),
        "description":     str(a.get("description", ""))[:200],
        "e_value":         a.get("e_value"),
        "score":           a.get("score"),
        "evidence":        str(a.get("evidence", "")),
        "display_priority": int(a.get("display_priority", 60)),
        "source_support":  list(a.get("source_support") or [a.get("source", "unknown")]),
    }, None


def _validate(a: dict) -> Optional[dict]:
    v, _ = _validate_with_reason(a)
    return v


# ---------------------------------------------------------------------------
# Quality filter — returns (passes: bool, reason: str)
# ---------------------------------------------------------------------------

def _passes_quality_with_reason(a: dict) -> tuple:
    label_lower = (a["label"] or "").lower()
    desc_lower  = (a["description"] or "").lower()

    # Fully generic / uninformative labels → discard
    for generic in _GENERIC_LABELS:
        if generic in label_lower or generic in desc_lower:
            return False, f"generic_label: '{generic}'"

    ftype  = a["feature_type"]
    evalue = a.get("e_value")
    span   = a["end"] - a["start"] + 1

    # Site-type features: ALWAYS keep (single-residue by nature)
    if ftype in _SITE_TYPES:
        return True, ""

    # Signal peptide / TM / structural features: always keep
    if ftype in ("signal_peptide", "transmembrane", "coiled_coil", "helix", "strand"):
        return True, ""

    # Domain / family
    if ftype in ("domain", "family"):
        if evalue is not None:
            if evalue > 1.0:
                # e-value >> 1 is pure noise — discard, don't show anywhere
                return False, f"noise: evalue_extreme ({evalue:.2e} >> 1.0)"
            if evalue > 1e-2:
                return False, f"evalue_too_high ({evalue:.2e} > 1e-2)"
        if span < 10:
            return False, f"span_too_small ({span} aa < 10)"

    # Motif
    if ftype == "motif":
        if evalue is not None:
            if evalue > 1.0:
                return False, f"noise: motif_evalue_extreme ({evalue:.2e} >> 1.0)"
            if evalue > 1e-1:
                return False, f"motif_evalue_too_high ({evalue:.2e} > 0.1)"

    # DUF entries
    if "DUF" in a["label"] or "duf" in a["accession"].lower():
        if evalue is not None and evalue > 1e-3:
            return False, f"duf_evalue_weak ({evalue:.2e} > 1e-3)"

    # Low-complexity: always keep (informative for display, no e-value)
    if ftype == "low_complexity":
        return True, ""

    return True, ""


def _passes_quality(a: dict) -> bool:
    passes, _ = _passes_quality_with_reason(a)
    return passes


# ---------------------------------------------------------------------------
# Deduplication
# ---------------------------------------------------------------------------

def _deduplicate(annotations: list) -> list:
    if not annotations:
        return []
    sites      = [a for a in annotations if a["feature_type"] in _SITE_TYPES]
    structural = [a for a in annotations if a["feature_type"] not in _SITE_TYPES]
    return _merge_group(structural) + _dedup_sites(sites)


def _merge_group(annotations: list) -> list:
    if not annotations:
        return []
    anns = sorted(annotations, key=lambda a: (a["start"], -(a["end"] - a["start"])))
    used = [False] * len(anns)
    result = []
    for i, a in enumerate(anns):
        if used[i]:
            continue
        group = [a]
        used[i] = True
        for j in range(i + 1, len(anns)):
            if used[j]:
                continue
            b = anns[j]
            if (abs(a["start"] - b["start"]) <= _OVERLAP_THRESHOLD and
                    abs(a["end"]   - b["end"])   <= _OVERLAP_THRESHOLD):
                group.append(b)
                used[j] = True
        best = _pick_best(group)
        all_sources = []
        for ann in group:
            for s in ann.get("source_support") or [ann["source"]]:
                if s not in all_sources:
                    all_sources.append(s)
        best["source_support"] = all_sources
        result.append(best)
    return result


def _pick_best(group: list) -> dict:
    def sort_key(a):
        ev = a.get("e_value")
        ev_score = ev if ev is not None else 1.0
        span = -(a["end"] - a["start"])
        return (ev_score, span)
    return dict(sorted(group, key=sort_key)[0])


def _dedup_sites(sites: list) -> list:
    seen = {}
    for s in sites:
        key = (s.get("accession", ""), s["start"], s["end"])
        if key not in seen:
            seen[key] = dict(s)
            seen[key]["source_support"] = list(s.get("source_support") or [s["source"]])
        else:
            existing = seen[key]["source_support"]
            for src in (s.get("source_support") or [s["source"]]):
                if src not in existing:
                    existing.append(src)
    return list(seen.values())

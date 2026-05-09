"""
Pipeline orchestrator.

submit_job()  — called by the Flask route; starts a background thread and
                returns a job_id immediately so the user can be redirected.

_run()        — runs in the background thread; calls each module in sequence,
                writes results to the job folder, updates status.json at every step.

Module execution order:
  1. retrieval      — fetch/validate sequence (MUST succeed; others are skipped if it fails)
  2. properties     — instant local calculation
  3. blast          — SLOW (~2-10 min), runs concurrently with all annotation tools
  4. hmmer          — EBI HMMER/Pfam API
  5. phobius        — EBI Phobius API (signal peptide + TM topology)
  6. cdd            — NCBI CDD Batch Web CD-Search
  7. scanprosite    — ExPASy ScanProsite (patterns, profiles, sites)
  8. smart          — SMART web adapter (HTML, best-effort)
  9. interproscan   — EBI InterProScan REST (integrative, slowest)
  10. annotation_merger — merges all annotation sources into unified schema

NOTE: Figure generation is NOT automatic. The user selects annotations on the
results page and clicks "Generate Figure" to invoke the mydomains module
on-demand via a separate Flask route.

HMMER, Phobius, CDD, ScanProsite, SMART, and InterProScan run in parallel
sub-threads. BLAST runs concurrently but is joined AFTER the annotation merge
so a slow BLAST run does not delay the results page.
"""

import os
import json
import time
import threading
from datetime import datetime, timezone

from pipeline.utils import jobs as job_store
from services import disorderpred as disorder_service, protpipe_companions, telemetry
from pipeline.modules import (
    retrieval, properties, blast, hmmer, phobius, signalp,
    cdd, scanprosite, smart, interproscan, coils, uniprot_features,
    annotation_merger,
)

try:
    from pipeline.modules.motif_search import run_motif_analysis as _run_motifs
    _HAS_MOTIF = True
except ImportError:
    _HAS_MOTIF = False

# Keep old figures module import for backward compatibility (not used in new pipeline)
try:
    from pipeline.modules import figures as _figures_legacy
    _HAS_LEGACY_FIGURES = True
except ImportError:
    _HAS_LEGACY_FIGURES = False


def submit_job(input_data: dict) -> str:
    """
    Create a job directory, spawn a background thread, and return the job_id.
    Never raises — errors are written to status.json.
    """
    job_id = job_store.new_job_id()
    job_dir = job_store.create_job_dir(job_id)
    enabled_modules = []
    for key, label in (
        ("run_blast", "BLAST"),
        ("run_hmmer", "HMMER"),
        ("run_phobius", "Phobius"),
        ("run_cdd", "CDD"),
        ("run_scanprosite", "ScanProsite"),
        ("run_uniprot_features", "UniProtKB features"),
        ("run_coils", "Coils"),
        ("run_smart", "SMART"),
        ("run_interproscan", "InterProScan"),
        ("run_signalp", "SignalP"),
        ("run_disorderpred", "DisorderPred"),
        ("run_sspred_companion", "SSPred consensus"),
    ):
        if input_data.get(key):
            enabled_modules.append(label)
    runtime_hint = "Usually the first useful results appear within 30-90 seconds."
    if "SSPred consensus" in enabled_modules:
        runtime_hint = "Likely 5-15 minutes depending on remote queues. SSPred companion waits on multiple external predictors."
    elif "InterProScan" in enabled_modules or ("BLAST" in enabled_modules and len(enabled_modules) >= 7):
        runtime_hint = "Likely 5-15 minutes depending on remote queues."
    elif "DisorderPred" in enabled_modules:
        runtime_hint = "Usually the main ProtPipe annotations appear quickly; DisorderPred companion may take a few extra minutes."
    elif any(item in enabled_modules for item in ("BLAST", "SMART", "SignalP")):
        runtime_hint = "Likely 3-10 minutes depending on remote queues."
    job_store.write_result(job_id, "request.json", {
        "input_type": input_data.get("input_type", "raw_fasta"),
        "submitted_value": (input_data.get("sequence_input") or "").strip()[:200],
        "submitted_at": datetime.now(timezone.utc).isoformat(),
        "enabled_modules": enabled_modules,
        "runtime_hint": runtime_hint,
    })
    telemetry.record_job_event("protpipe", job_id, "submitted", input_data.get("input_type", "raw_fasta"))

    t = threading.Thread(target=_run, args=(input_data, job_id, job_dir), daemon=True)
    t.name = f"protpipe-{job_id}"
    t.start()
    return job_id


def get_status(job_id: str) -> dict:
    """Return status dict for the given job."""
    return job_store.get_status(job_id)


def get_summary(job_id: str) -> dict:
    """Return the combined summary dict once the job is complete."""
    return job_store.get_summary(job_id)


# ---------------------------------------------------------------------------
# Background worker
# ---------------------------------------------------------------------------

def _run(input_data: dict, job_id: str, job_dir: str):
    try:
        job_store.set_status(job_id, "running")
        telemetry.record_job_event("protpipe", job_id, "running", "Pipeline worker started")

        # ----------------------------------------------------------------
        # Step 1 — sequence retrieval (serial, must succeed first)
        # ----------------------------------------------------------------
        job_store.set_module_status(job_id, "retrieval", "running")
        retrieval_start = time.time()
        job_store.set_module_detail(
            job_id,
            "retrieval",
            status="running",
            summary="Validating input and fetching the primary sequence.",
            started_at=datetime.now(timezone.utc).isoformat(),
        )
        ret = retrieval.run(input_data, job_dir)

        if ret["status"] != "ok":
            job_store.write_result(job_id, "retrieval.json", ret)
            job_store.set_module_status(job_id, "retrieval", "error")
            _record_module_detail(job_id, "retrieval", ret, retrieval_start, "Could not retrieve a protein sequence.")
            telemetry.record_job_event("protpipe", job_id, "error", ret["error"])
            job_store.set_status(job_id, "error", error=ret["error"])
            return

        job_store.write_result(job_id, "retrieval.json", ret)
        job_store.set_module_status(job_id, "retrieval", "complete")
        _record_module_detail(job_id, "retrieval", ret, retrieval_start, "Sequence retrieved successfully.")
        seq = ret["sequence"]

        # ----------------------------------------------------------------
        # Step 2 — basic properties (instant, serial)
        # ----------------------------------------------------------------
        job_store.set_module_status(job_id, "properties", "running")
        properties_start = time.time()
        job_store.set_module_detail(
            job_id,
            "properties",
            status="running",
            summary="Calculating sequence-level physicochemical properties.",
            started_at=datetime.now(timezone.utc).isoformat(),
        )
        prop_result = properties.run(seq, job_dir)
        job_store.write_result(job_id, "properties.json", prop_result)
        job_store.set_module_status(
            job_id, "properties",
            "complete" if prop_result["status"] == "ok" else "error"
        )
        _record_module_detail(job_id, "properties", prop_result, properties_start, "Computed sequence properties.")

        # ----------------------------------------------------------------
        # Step 2b — motif search (instant, local — runs only if queries given)
        # ----------------------------------------------------------------
        motif_queries = input_data.get("motif_queries") or []
        motif_results_list = []
        if motif_queries and _HAS_MOTIF:
            try:
                motif_out = _run_motifs(seq, motif_queries)
                motif_results_list = motif_out.get("data", {}).get("motif_results", [])
                job_store.write_result(job_id, "motifs.json", motif_out)
                total_hits = sum(m.get("hit_count", 0) for m in motif_results_list)
                print(f"[runner] motif search: {len(motif_queries)} pattern(s), {total_hits} total hits")
            except Exception as _me:
                print(f"[runner] motif search error: {_me}")

        # ----------------------------------------------------------------
        # Steps 3–9 — annotation tools in parallel; BLAST runs independently
        #
        # BLAST does NOT feed annotation_merger — it goes straight into the
        # summary dict. So we start it in a separate thread and only join it
        # AFTER the merge step, so slow BLAST runs don't block annotations.
        # ----------------------------------------------------------------
        results = {
            "blast": None, "hmmer": None, "phobius": None, "signalp": None,
            "cdd": None, "scanprosite": None, "smart": None, "interproscan": None,
            "coils": None, "uniprot_features": None, "disorderpred": None, "sspred_companion": None,
        }

        run_blast        = input_data.get("run_blast",        True)
        run_hmmer        = input_data.get("run_hmmer",        True)
        run_phobius      = input_data.get("run_phobius",      True)
        run_signalp      = input_data.get("run_signalp",      False)  # EBI endpoint unavailable
        run_cdd          = input_data.get("run_cdd",          True)
        run_scanprosite  = input_data.get("run_scanprosite",  True)
        run_uniprot_features = input_data.get("run_uniprot_features", True)
        run_smart        = input_data.get("run_smart",        True)
        run_interproscan = input_data.get("run_interproscan", False)   # very slow, opt-in only
        run_coils        = input_data.get("run_coils",        True)
        run_disorderpred = input_data.get("run_disorderpred", False)
        run_sspred       = input_data.get("run_sspred_companion", False)
        blast_max_hits   = input_data.get("blast_max_hits",   10)
        blast_database   = input_data.get("blast_database",   "swissprot")
        disorder_accession = (
            ret.get("header")
            or ret.get("resolved_acc")
            or ret.get("accession")
            or ""
        )
        uniprot_feature_acc = uniprot_features.infer_uniprot_accession(disorder_accession)

        # BLAST thread — started immediately but joined after merge
        blast_thread = None
        if run_blast:
            job_store.set_module_status(job_id, "blast", "running")
            job_store.set_module_detail(
                job_id,
                "blast",
                status="running",
                summary=f"Submitting BLAST search against {blast_database}.",
                started_at=datetime.now(timezone.utc).isoformat(),
            )
            blast_thread = threading.Thread(
                target=_run_module,
                args=(blast.run, seq, job_dir, "blast", results, job_id),
                kwargs={"max_hits": blast_max_hits, "database": blast_database},
                daemon=True,
            )
            blast_thread.start()
        else:
            job_store.set_module_status(job_id, "blast", "skipped")
            job_store.set_module_detail(job_id, "blast", status="skipped", summary="BLAST was disabled for this job.")

        # Annotation threads — joined before merge
        ann_threads = []

        def _add(module_fn, key, run_flag, **kwargs):
            if run_flag:
                job_store.set_module_status(job_id, key, "running")
                job_store.set_module_detail(
                    job_id,
                    key,
                    status="running",
                    summary=_running_summary_for_module(key),
                    started_at=datetime.now(timezone.utc).isoformat(),
                )
                ann_threads.append(threading.Thread(
                    target=_run_module,
                    args=(module_fn, seq, job_dir, key, results, job_id),
                    kwargs=kwargs,
                    daemon=True,
                ))
            else:
                job_store.set_module_status(job_id, key, "skipped")
                job_store.set_module_detail(job_id, key, status="skipped", summary="Module was disabled for this job.")

        _add(hmmer.run,        "hmmer",        run_hmmer)
        _add(phobius.run,      "phobius",      run_phobius)
        _add(signalp.run,      "signalp",      run_signalp)
        _add(cdd.run,          "cdd",          run_cdd)
        _add(scanprosite.run,  "scanprosite",  run_scanprosite)
        if run_uniprot_features and not uniprot_feature_acc:
            job_store.set_module_status(job_id, "uniprot_features", "skipped")
            job_store.set_module_detail(
                job_id,
                "uniprot_features",
                status="skipped",
                summary="UniProtKB features require a resolvable UniProt accession.",
            )
        else:
            _add(uniprot_features.run, "uniprot_features", run_uniprot_features, accession=uniprot_feature_acc)
        _add(smart.run,        "smart",        run_smart)
        _add(interproscan.run, "interproscan", run_interproscan)
        _add(coils.run,        "coils",        run_coils)
        _add(protpipe_companions.run_disorder, "disorderpred", run_disorderpred, accession=disorder_accession)
        _add(protpipe_companions.run_sspred_consensus, "sspred_companion", run_sspred)

        for t in ann_threads:
            t.start()

        # All annotation threads share a single 10-minute deadline.
        # args passed to _run_module: (module_fn, seq, job_dir, key, results, job_id)
        #                                          idx:  0       1     2        3  4       5
        # args tuple passed to _run_module: (module_fn, seq, job_dir, key, results, job_id)
        # so key is at index 3.
        _MODULE_TIMEOUT = 600   # 10 minutes total shared deadline
        _deadline = time.time() + _MODULE_TIMEOUT
        for t in ann_threads:
            remaining = max(1.0, _deadline - time.time())
            t.join(timeout=remaining)
            if t.is_alive():
                key = t._args[3] if hasattr(t, '_args') and len(t._args) > 3 else "unknown"
                print(f"[runner] module '{key}' timed out — continuing without it")
                job_store.set_module_status(job_id, key, "error")
                if isinstance(key, str) and key in results:
                    results[key] = {"status": "error", "data": {}, "error": f"Module timed out after {_MODULE_TIMEOUT // 60} min"}
                    job_store.set_module_detail(
                        job_id,
                        key,
                        status="error",
                        summary=f"{key} timed out while waiting for the upstream service.",
                        raw_error=results[key]["error"],
                    )
                    telemetry.record_component_run(
                        "protpipe",
                        key,
                        job_id,
                        "timeout",
                        summary=f"{key} timed out while waiting for the upstream service.",
                        raw_error=results[key]["error"],
                        duration_seconds=_MODULE_TIMEOUT,
                    )

        # ----------------------------------------------------------------
        # Step 10 — merge all annotation sources
        # ----------------------------------------------------------------
        job_store.set_module_status(job_id, "annotations", "running")
        merge_start = time.time()
        job_store.set_module_detail(
            job_id,
            "annotations",
            status="running",
            summary="Merging and deduplicating annotations from all completed sources.",
            started_at=datetime.now(timezone.utc).isoformat(),
        )
        merged = annotation_merger.merge(
            hmmer_result        = results.get("hmmer"),
            phobius_result      = results.get("phobius"),
            signalp_result      = results.get("signalp"),
            cdd_result          = results.get("cdd"),
            scanprosite_result  = results.get("scanprosite"),
            uniprot_result      = results.get("uniprot_features"),
            smart_result        = results.get("smart"),
            interproscan_result = results.get("interproscan"),
            coils_result        = results.get("coils"),
        )
        job_store.write_result(job_id, "annotations.json", merged)
        job_store.set_module_status(job_id, "annotations", "complete")
        job_store.set_module_detail(
            job_id,
            "annotations",
            status="complete",
            summary=f"Kept {len(merged.get('annotations', []))} high-confidence annotations.",
            duration_seconds=round(time.time() - merge_start, 2),
            finished_at=datetime.now(timezone.utc).isoformat(),
        )
        telemetry.record_component_run(
            "protpipe",
            "annotations",
            job_id,
            "complete",
            summary=f"Kept {len(merged.get('annotations', []))} high-confidence annotations.",
            duration_seconds=time.time() - merge_start,
        )

        # ----------------------------------------------------------------
        # Wait for BLAST — give it up to 10 more minutes after annotations finish.
        # If it's still alive after that, mark error and continue writing summary.
        # ----------------------------------------------------------------
        if blast_thread is not None:
            blast_thread.join(timeout=600)
            if blast_thread.is_alive():
                print(f"[runner] BLAST timed out — writing summary without BLAST results")
                results["blast"] = {
                    "status": "error",
                    "data":   {},
                    "error":  "BLAST timed out after 10 minutes. Try a smaller sequence or a faster database (SwissProt).",
                }
                job_store.set_module_status(job_id, "blast", "error")
                job_store.set_module_detail(
                    job_id,
                    "blast",
                    status="error",
                    summary="BLAST timed out before the remote search completed.",
                    raw_error=results["blast"]["error"],
                )
                telemetry.record_component_run(
                    "protpipe",
                    "blast",
                    job_id,
                    "timeout",
                    summary="BLAST timed out before the remote search completed.",
                    raw_error=results["blast"]["error"],
                    duration_seconds=600,
                )

        # ----------------------------------------------------------------
        # Write combined summary
        # ----------------------------------------------------------------
        annotation_list  = merged.get("annotations", [])
        low_conf_list    = merged.get("low_confidence_annotations", [])
        raw_ann_list     = merged.get("raw_annotations", [])
        ann_debug        = merged.get("debug", {})
        domain_count = sum(1 for a in annotation_list
                           if a.get("feature_type") in ("domain", "family", "repeat"))
        site_count   = sum(1 for a in annotation_list
                           if a.get("feature_type") in
                           ("active_site", "binding_site", "metal_binding", "disulfide", "site"))
        tm_count     = sum(1 for a in annotation_list if a.get("feature_type") == "transmembrane")
        has_sp       = any(a.get("feature_type") == "signal_peptide" for a in annotation_list)

        blast_result_data = (results.get("blast") or {}).get("data", {})
        blast_result_data["max_hits_requested"] = blast_max_hits

        # Carry through resolved protein candidates list (from mRNA/gene resolution)
        if ret.get("resolved_proteins"):
            pass  # already in ret dict, passed through below

        errors, warnings = _collect_messages(results, prop_result, merged)
        summary = {
            "job_id":        job_id,
            "completed_at":  datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
            "retrieval":     ret,
            "properties":    prop_result.get("data", {}),
            "blast":         blast_result_data,
            "hmmer":         (results.get("hmmer")   or {}).get("data", {}),
            "phobius":       (results.get("phobius") or {}).get("data", {}),
            "signalp":       (results.get("signalp") or {}).get("data", {}),
            "uniprot_features": (results.get("uniprot_features") or {}).get("data", {}),
            "motif_results":           motif_results_list,
            "companion_disorder":      (results.get("disorderpred") or {}).get("data", {}),
            "companion_sspred":        (results.get("sspred_companion") or {}).get("data", {}),
            "annotations":            annotation_list,
            "low_confidence_annotations": low_conf_list,
            "raw_annotations":        raw_ann_list,
            "annotation_summary": {
                "domain_count":   domain_count,
                "site_count":     site_count,
                "tm_helix_count": tm_count,
                "has_signal_peptide": has_sp,
                "source_summary": merged.get("source_summary", {}),
            },
            "annotation_debug": ann_debug,
            "figure_ok":     False,
            "figure_renderer": "none",
            "module_errors": errors,
            "module_warnings": warnings,
        }
        job_store.write_result(job_id, "summary.json", summary)
        job_store.set_status(job_id, "complete")
        telemetry.record_job_event("protpipe", job_id, "complete", f"{len(annotation_list)} annotations")
        print(f"[runner] job {job_id} complete — {len(annotation_list)} annotations")

    except Exception as e:
        import traceback
        msg = f"Unexpected pipeline error: {e}\n{traceback.format_exc()}"
        print(f"[runner] ERROR in job {job_id}: {msg}")
        telemetry.record_job_event("protpipe", job_id, "error", str(e))
        job_store.set_status(job_id, "error", error=msg)


def _run_module(module_fn, seq, job_dir, key, results_dict, job_id, **kwargs):
    """Thread target: run one module function, store result."""
    started_at = time.time()
    try:
        result = module_fn(seq, job_dir, **kwargs)
        results_dict[key] = result
        job_store.write_result(job_id, f"{key}.json", result)
        # parse_warning is a soft failure — don't mark as error
        if result.get("status") in ("ok", "parse_warning"):
            status = "complete"
        elif result.get("status") == "endpoint_unverified":
            status = "error"
        else:
            status = "error"
        job_store.set_module_status(job_id, key, status)
        _record_module_detail(job_id, key, result, started_at, _success_summary_for_module(key, result))
    except Exception as e:
        import traceback
        results_dict[key] = {"status": "error", "data": {}, "error": str(e)}
        job_store.set_module_status(job_id, key, "error")
        job_store.set_module_detail(
            job_id,
            key,
            status="error",
            summary=f"{key} raised an unexpected exception.",
            raw_error=str(e),
            duration_seconds=round(time.time() - started_at, 2),
            finished_at=datetime.now(timezone.utc).isoformat(),
        )
        telemetry.record_component_run(
            "protpipe",
            key,
            job_id,
            "error",
            summary=f"{key} raised an unexpected exception.",
            raw_error=str(e),
            duration_seconds=time.time() - started_at,
        )
        print(f"[runner] module {key} raised: {e}\n{traceback.format_exc()}")


def _collect_messages(results: dict, prop_result: dict, merged: dict) -> tuple[dict, dict]:
    errors = {}
    warnings = {}
    for key, val in results.items():
        if not val:
            continue
        status = val.get("status")
        if status == "parse_warning":
            warnings[key] = val.get("error", "parser warning")
        elif status not in ("ok", None):
            errors[key] = val.get("error", "unknown error")
    if prop_result.get("status") != "ok":
        errors["properties"] = prop_result.get("error", "")
    return errors, warnings


def _running_summary_for_module(key: str) -> str:
    descriptions = {
        "hmmer": "Submitting the sequence to the EBI HMMER service.",
        "phobius": "Submitting the sequence to Phobius for topology prediction.",
        "signalp": "Submitting the sequence to SignalP for signal peptide prediction.",
        "cdd": "Submitting the sequence to NCBI CDD.",
        "scanprosite": "Submitting the sequence to ScanProsite.",
        "uniprot_features": "Fetching curated feature annotations from UniProtKB.",
        "smart": "Submitting the sequence to SMART.",
        "interproscan": "Submitting the sequence to InterProScan.",
        "coils": "Submitting the sequence to LUPAS for coiled-coil prediction.",
        "blast": "Submitting the sequence to NCBI BLAST.",
        "disorderpred": "Running DisorderPred companion analysis on the resolved sequence.",
        "sspred_companion": "Running the SSPred companion consensus bundle on the resolved sequence.",
    }
    return descriptions.get(key, "Running module.")


def _success_summary_for_module(key: str, result: dict) -> str:
    data = result.get("data", {}) if isinstance(result, dict) else {}
    if result.get("status") == "parse_warning":
        return f"{key} completed with a parser warning."
    counts = {
        "blast": len(data.get("hits", [])),
        "hmmer": len(data.get("domains", [])),
        "phobius": data.get("tm_count", 0),
        "signalp": 1 if data.get("has_signal_peptide") else 0,
        "cdd": len(data.get("annotations", [])),
        "scanprosite": len(data.get("annotations", [])),
        "uniprot_features": len(data.get("annotations", [])),
        "smart": len(data.get("annotations", [])),
        "interproscan": len(data.get("annotations", [])),
        "coils": len(data.get("annotations", [])),
        "disorderpred": len(data.get("disordered_regions", [])),
        "sspred_companion": data.get("service_count", 0),
    }
    if key == "blast":
        return f"BLAST returned {counts[key]} hit(s)."
    if key == "hmmer":
        return f"HMMER returned {counts[key]} domain hit(s)."
    if key == "phobius":
        return f"Phobius predicted {counts[key]} transmembrane helix/helix-like segment(s)."
    if key == "disorderpred":
        return f"DisorderPred identified {counts[key]} disordered region(s)."
    if key == "sspred_companion":
        return f"SSPred consensus finished with {counts[key]} contributing service(s)."
    if key == "signalp":
        return "SignalP finished." if counts[key] else "SignalP did not detect a signal peptide."
    if key in {"cdd", "scanprosite", "uniprot_features", "smart", "interproscan", "coils"}:
        return f"{key} returned {counts[key]} annotation(s)."
    return f"{key} completed successfully."


def _record_module_detail(job_id: str, key: str, result: dict, started_at: float, default_summary: str):
    duration = round(time.time() - started_at, 2)
    status = result.get("status", "error")
    raw_error = result.get("error", "")
    if status == "ok":
        display_status = "complete"
        event_status = "complete"
        summary = default_summary
    elif status == "parse_warning":
        display_status = "complete"
        event_status = "warning"
        summary = raw_error or f"{key} completed with a parser warning."
    elif status == "endpoint_unverified":
        display_status = "error"
        event_status = "error"
        summary = raw_error or f"{key} endpoint needs verification."
    else:
        display_status = "error"
        event_status = "error"
        summary = raw_error or f"{key} failed."
    job_store.set_module_detail(
        job_id,
        key,
        status=display_status,
        summary=summary,
        raw_error=raw_error,
        duration_seconds=duration,
        finished_at=datetime.now(timezone.utc).isoformat(),
    )
    telemetry.record_component_run(
        "protpipe",
        key,
        job_id,
        event_status,
        summary=summary,
        raw_error=raw_error,
        duration_seconds=duration,
    )

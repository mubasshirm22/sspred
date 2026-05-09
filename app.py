import json
import time
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from lxml import html
from services import ss, psi, jpred, raptorx, pss, sable, sspro, yaspin, phdpsi, profsec, predator, netsurf, emailtools, htmlmaker, batchtools, telemetry, disorderjobs, disorderpred as disorder_service, structmap as structmap_service, cms
from datetime import datetime

from forms import SubmissionForm
from flask import Flask, render_template, request, current_app, send_file, redirect, url_for, jsonify, session
import threading
import secrets
import requests
from google_auth_oauthlib.flow import Flow

import psycopg2
from psycopg2.extras import RealDictCursor
from psycopg2 import sql

DATABASE_URL = os.environ.get('DATABASE_URL')



def dbselect(rowid):
	conn = psycopg2.connect(DATABASE_URL)
	cursor = conn.cursor(cursor_factory=RealDictCursor)
	cursor.execute("SELECT * FROM seqtable WHERE ID = (%s)",(rowid,))
	jsonresults = json.dumps(cursor.fetchall(), indent=2)
	cursor.close()
	return jsonresults


def dbfetch(rowid):
	conn = psycopg2.connect(DATABASE_URL)
	cursor = conn.cursor(cursor_factory=RealDictCursor)
	cursor.execute("SELECT * FROM seqtable WHERE ID = (%s)", (rowid,))
	row = cursor.fetchone()
	cursor.close()
	return row

def dbdelete():
	conn = psycopg2.connect(DATABASE_URL)
	cursor = conn.cursor()
	cursor.execute("SELECT COUNT(*) FROM seqtable")
	numrowsdb = cursor.fetchall()
	numrowsdb = numrowsdb[0][0]

	if numrowsdb > 8000:
		cursor.execute(
				'''
				DELETE FROM seqtable
				WHERE ID = any (array(SELECT ID FROM seqtable ORDER BY convert_to(ID, 'SQL_ASCII') ASC LIMIT 1000))
				''')
		conn.commit()
	cursor.close()

def dbinsert(rowid, rowseq):
	conn = psycopg2.connect(DATABASE_URL)
	dbdelete() #Deletes 1000 oldest rows if table is larger than 8000 rows
	cursor = conn.cursor()
	cursor.execute("INSERT INTO seqtable (ID, SEQ) VALUES (%s, %s)", (rowid, rowseq))
	conn.commit()
	cursor.close()

def dbupdate(rowid, rowcol, rowval):
	conn = psycopg2.connect(DATABASE_URL)
	cursor = conn.cursor()
	cursor.execute(
		sql.SQL("UPDATE seqtable SET {} = (%s) WHERE ID = (%s)")
		.format(sql.Identifier(rowcol.lower())),(rowval, rowid))
	conn.commit()
	cursor.close()

def _ensure_db_columns():
	"""Add any missing columns to seqtable. Safe to call on every startup."""
	new_columns = [
		("netsurfpred", "TEXT"),
		("netsurfconf", "TEXT"),
		("netsurfstat", "INTEGER"),
		("netsurfmsg",  "TEXT"),
	]
	try:
		conn = psycopg2.connect(DATABASE_URL)
		cursor = conn.cursor()
		for col, col_type in new_columns:
			cursor.execute(
				f"ALTER TABLE seqtable ADD COLUMN IF NOT EXISTS {col} {col_type}"
			)
		conn.commit()
		cursor.close()
		conn.close()
	except Exception as e:
		print(f"[startup] DB migration warning: {e}")


_SERVICE_STATUS_TTL = 300
_SERVICE_STATUS_CACHE = {"expires_at": 0.0, "data": {}}
_SERVICE_STATUS_LOCK = threading.Lock()
_PROTPIPE_STATUS_TTL = 300
_PROTPIPE_STATUS_CACHE = {"expires_at": 0.0, "data": {}}
_PROTPIPE_STATUS_LOCK = threading.Lock()
_DISORDER_STATUS_TTL = 300
_DISORDER_STATUS_CACHE = {"expires_at": 0.0, "data": {}}
_DISORDER_STATUS_LOCK = threading.Lock()


def _probe_http_service(url, ok_statuses=(200, 301, 302, 405), timeout=8):
	try:
		response = requests.get(url, timeout=timeout, allow_redirects=True)
		return "UP" if response.status_code in ok_statuses else "DOWN"
	except Exception:
		return "DOWN"


def _probe_stride_service():
	try:
		return "UP" if batchtools.pdbget("1CRN", "A") else "DOWN"
	except Exception:
		return "DOWN"


def _fetch_service_health():
	status = {
		"PHDpsi": "RETIRED",
		"PROFsec": "RETIRED",
	}
	checks = {
		"JPred": lambda: _probe_http_service("http://www.compbio.dundee.ac.uk/jpred4/"),
		"PSI": lambda: _probe_http_service("http://bioinf.cs.ucl.ac.uk/psipred/"),
		"Sable": lambda: _probe_http_service("http://sable.cchmc.org/"),
		"SSPro": lambda: _probe_http_service("http://scratch.proteomics.ics.uci.edu/"),
		"Yaspin": lambda: _probe_http_service("http://www.ibi.vu.nl/programs/yaspinwww/"),
		"Predator": lambda: _probe_http_service("https://npsa-prabi.ibcp.fr/cgi-bin/secpred_preda.pl"),
		"NetSurf": lambda: _probe_http_service("https://services.healthtech.dtu.dk/cgi-bin/webface2.cgi"),
		"STRIDE": _probe_stride_service,
	}
	with ThreadPoolExecutor(max_workers=len(checks)) as executor:
		futures = {executor.submit(probe): name for name, probe in checks.items()}
		for future in as_completed(futures):
			name = futures[future]
			try:
				status[name] = future.result()
			except Exception:
				status[name] = "DOWN"
	return status


def check_service_health():
	"""
	Check reachability of each service by hitting its actual submission endpoint.
	Results are cached briefly so the SSPred page does not block on health probes.
	"""
	now = time.time()
	with _SERVICE_STATUS_LOCK:
		if _SERVICE_STATUS_CACHE["data"] and now < _SERVICE_STATUS_CACHE["expires_at"]:
			return dict(_SERVICE_STATUS_CACHE["data"])

	status = _fetch_service_health()
	with _SERVICE_STATUS_LOCK:
		_SERVICE_STATUS_CACHE["data"] = status
		_SERVICE_STATUS_CACHE["expires_at"] = now + _SERVICE_STATUS_TTL
	return dict(status)


def _fetch_protpipe_service_health():
	status = {
		"BLAST": {
			"status": _probe_http_service("https://blast.ncbi.nlm.nih.gov/Blast.cgi", ok_statuses=(200, 301, 302, 405)),
			"tier": "core",
			"note": "NCBI BLAST remote search",
		},
		"HMMER": {
			"status": _probe_http_service("https://www.ebi.ac.uk/Tools/hmmer/"),
			"tier": "core",
			"note": "Pfam domain scan",
		},
		"Phobius": {
			"status": _probe_http_service("https://www.ebi.ac.uk/Tools/services/rest/phobius/parameters"),
			"tier": "core",
			"note": "Signal peptide and TM topology",
		},
		"CDD": {
			"status": _probe_http_service("https://www.ncbi.nlm.nih.gov/Structure/bwrpsb/bwrpsb.cgi", ok_statuses=(200, 301, 302, 405)),
			"tier": "core",
			"note": "NCBI conserved domains",
		},
		"ScanProsite": {
			"status": _probe_http_service("https://prosite.expasy.org/cgi-bin/prosite/PSScan.cgi", ok_statuses=(200, 301, 302, 405)),
			"tier": "core",
			"note": "Patterns and functional sites",
		},
		"UniProtKB features": {
			"status": _probe_http_service("https://rest.uniprot.org/uniprotkb/P04637.json", ok_statuses=(200, 301, 302)),
			"tier": "core",
			"note": "Curated UniProt positional features for domains, motifs, regions, and sites",
		},
		"Coils": {
			"status": _probe_http_service("https://npsa-prabi.ibcp.fr/cgi-bin/primanal_lupas.pl", ok_statuses=(200, 301, 302, 405)),
			"tier": "core",
			"note": "LUPAS coiled-coil prediction",
		},
		"SMART": {
			"status": _probe_http_service("https://smart.embl.de/"),
			"tier": "experimental",
			"note": "Best-effort HTML parsing",
		},
		"InterProScan": {
			"status": _probe_http_service("https://www.ebi.ac.uk/Tools/services/rest/iprscan5/parameters"),
			"tier": "slow",
			"note": "Broad integrative annotation",
		},
		"SignalP": {
			"status": "OFFLINE",
			"tier": "offline",
			"note": "Upstream endpoint currently unavailable",
		},
		"DisorderPred": {
			"status": check_service_health().get("NetSurf", "DOWN"),
			"tier": "companion",
			"note": "Companion disorder profile using NetSurf plus IUPred3 / ANCHOR2 comparison.",
		},
		"SSPred consensus": {
			"status": "UP" if any(check_service_health().get(name) == "UP" for name in ("JPred", "PSI", "Sable", "SSPro", "Yaspin", "Predator", "NetSurf")) else "DOWN",
			"tier": "companion",
			"note": "Optional secondary-structure consensus bundle using the SSPred service adapters.",
		},
	}
	return status


def check_protpipe_service_health():
	now = time.time()
	with _PROTPIPE_STATUS_LOCK:
		if _PROTPIPE_STATUS_CACHE["data"] and now < _PROTPIPE_STATUS_CACHE["expires_at"]:
			return dict(_PROTPIPE_STATUS_CACHE["data"])

	status = _fetch_protpipe_service_health()
	with _PROTPIPE_STATUS_LOCK:
		_PROTPIPE_STATUS_CACHE["data"] = status
		_PROTPIPE_STATUS_CACHE["expires_at"] = now + _PROTPIPE_STATUS_TTL
	return dict(status)


def _fetch_disorderpred_service_health():
	return {
		"NetSurfP-2.0": {
			"status": check_service_health().get("NetSurf", "DOWN"),
			"role": "primary",
			"note": "Primary disorder profile plus secondary-structure overlay.",
		},
		"IUPred3 / ANCHOR2": {
			"status": _probe_http_service("https://iupred3.elte.hu/"),
			"role": "comparison",
			"note": "Comparison disorder modes and binding-region scoring.",
		},
	}


def check_disorderpred_service_health():
	now = time.time()
	with _DISORDER_STATUS_LOCK:
		if _DISORDER_STATUS_CACHE["data"] and now < _DISORDER_STATUS_CACHE["expires_at"]:
			return dict(_DISORDER_STATUS_CACHE["data"])

	status = _fetch_disorderpred_service_health()
	with _DISORDER_STATUS_LOCK:
		_DISORDER_STATUS_CACHE["data"] = status
		_DISORDER_STATUS_CACHE["expires_at"] = now + _DISORDER_STATUS_TTL
	return dict(status)


def _compact_text(value, limit=240):
	if value is None:
		return ""
	text = " ".join(str(value).split())
	return text[:limit].rstrip()


def _sspred_raw_error(temp_ss):
	if temp_ss is None:
		return ""
	if temp_ss.status in (1, 3):
		return ""
	if temp_ss.pred and "No confidence" not in temp_ss.pred:
		return _compact_text(temp_ss.pred, limit=500)
	if temp_ss.conf:
		return _compact_text(temp_ss.conf, limit=500)
	return ""


def _sspred_status_summary(name, temp_ss, elapsed_seconds):
	elapsed_min = max(0, int(round(elapsed_seconds / 60.0)))
	raw_error = _sspred_raw_error(temp_ss)
	if temp_ss.status in (1, 3):
		conf_note = "" if temp_ss.status == 1 else " (prediction only; no confidence scores)"
		return "success", f"{name} – finished successfully in {elapsed_min} minutes.{conf_note}", raw_error
	if temp_ss.status == -1:
		return "queue_full", f"{name} – did not run because the remote queue is full.", raw_error or "Queue Full"
	if temp_ss.status == 4:
		return "rejected", f"{name} – sequence was not accepted by the upstream server.", raw_error or "sequence not accepted"
	if temp_ss.status == 2:
		raw_lower = raw_error.lower()
		if "queue full" in raw_lower:
			return "queue_full", f"{name} – did not run because the remote queue is full.", raw_error
		if "failed to respond" in raw_lower or "timed out" in raw_lower:
			return "timeout", f"{name} – remote job timed out after {elapsed_min} minutes.", raw_error
		if raw_error:
			return "error", f"{name} – upstream error: {raw_error}", raw_error
		return "error", f"{name} – upstream service failed without a detailed error message.", raw_error
	return "running", f"{name} – still waiting after {elapsed_min} minutes.", raw_error


def _sspred_failure_panels(row):
	panels = []
	for service_name in siteDict:
		status = row.get(service_name.lower() + "stat")
		if status in (2, 4, -1):
			panels.append({
				"name": service_name,
				"status": status,
				"summary": row.get(service_name.lower() + "msg", ""),
				"raw": _compact_text(row.get(service_name.lower() + "pred", ""), limit=500),
			})
	return panels


def _arg_bool(name, default=False):
	value = request.args.get(name)
	if value is None:
		return default
	return str(value).lower() in {"1", "true", "yes", "on"}


def _sspred_figure_options():
	from services import sspred_figure

	options = sspred_figure.default_options()
	options.update({
		"row_length": request.args.get("row_length", options["row_length"]),
		"style": request.args.get("style", options["style"]),
		"palette": request.args.get("palette", options["palette"]),
		"show_sequence": _arg_bool("show_sequence", True),
		"show_consensus": _arg_bool("show_consensus", True),
		"show_pdb": _arg_bool("show_pdb", True),
		"show_confidence": _arg_bool("show_confidence", True),
		"legend": _arg_bool("legend", True),
		"clean": _arg_bool("clean", False),
		"compare": _arg_bool("compare", False),
		"title": request.args.get("title", options["title"]),
		"predictors": [item.strip() for item in request.args.get("predictors", "").split(",") if item.strip()],
		"regions": sspred_figure.parse_region_text(request.args.get("regions", "")),
	})
	return options

#Dictionary containing sites and their classes
siteDict = {
	"JPred":    jpred,
	"PSI":      psi,
	#"PSS":    pss,       # disabled
	#"RaptorX": raptorx, # disabled
	"Sable":    sable,
	"Yaspin":   yaspin,
	"SSPro":    sspro,
	#"PHDpsi":  phdpsi,  # permanently removed from EBI Job Dispatcher
	#"PROFsec": profsec, # permanently removed from EBI Job Dispatcher
	"Predator": predator,
	"NetSurf":  netsurf,
}

siteLimit = {
	"JPred":    20,
	"PSI":      20,
	#"PSS":    3,
	#"RaptorX": 20,
	"Sable":    20,
	"Yaspin":   3,
	"SSPro":    5,
	#"PHDpsi":  5,
	#"PROFsec": 5,
	"Predator": 5,
	"NetSurf":  5,
}


app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET')
if app.config['SECRET_KEY'] is None:
	app.config['SECRET_KEY'] = secrets.token_urlsafe(16)


@app.context_processor
def inject_global_template_state():
	return {
		"cms_current_user": _cms_current_user(),
		"cms_google_enabled": _cms_google_enabled(),
	}

#Login to email account to be able to send emails
#email_service = emailtools.login()
#email = emailtools.getEmailAddress(email_service)

#Url of hosted site
siteurl = os.environ.get('SITE_URL')
if siteurl is None :
	siteurl = ""

_ensure_db_columns()
try:
	cms.ensure_tables()
except Exception as e:
	print(f"[startup] CMS migration warning: {e}")


def _cms_google_enabled():
	return bool(os.environ.get("GOOGLE_CLIENT_ID") and os.environ.get("GOOGLE_CLIENT_SECRET") and siteurl)


def _cms_client_config():
	return {
		"web": {
			"client_id": os.environ.get("GOOGLE_CLIENT_ID", ""),
			"client_secret": os.environ.get("GOOGLE_CLIENT_SECRET", ""),
			"auth_uri": "https://accounts.google.com/o/oauth2/auth",
			"token_uri": "https://oauth2.googleapis.com/token",
			"redirect_uris": [f"{siteurl.rstrip('/')}/admin/auth/google/callback"],
		}
	}


def _cms_current_user():
	email = session.get("cms_email")
	if not email:
		return None
	user = cms.find_user(email) or {"email": email, "role": session.get("cms_role", "editor"), "active": True}
	user["role"] = user.get("role") or session.get("cms_role", "editor")
	user["email"] = user.get("email") or email
	return user


def _cms_require_user(admin=False):
	user = _cms_current_user()
	if not user:
		return None, redirect(url_for('admin_login', next=request.path))
	if admin and user.get("role") != "admin":
		return user, ("Forbidden", 403)
	return user, None


def _cms_page_bundle():
	return {
		"team": cms.get_page("team"),
		"contact": cms.get_page("contact"),
		"research": cms.get_page("research"),
		"news": cms.list_news(),
		"team_members": cms.list_team_members(),
		"publications": cms.list_publications(),
	}

# ---------------------------------------------------------------------------
# Lab site routes
# ---------------------------------------------------------------------------

@app.route('/')
def lab_home():
	bundle = _cms_page_bundle()
	return render_template('lab/home.html', cms_news=bundle["news"])

@app.route('/research')
def lab_research():
	bundle = _cms_page_bundle()
	return render_template('lab/research.html',
		cms_page=bundle["research"],
		cms_publications=bundle["publications"])

@app.route('/team')
def lab_team():
	bundle = _cms_page_bundle()
	return render_template('lab/team.html',
		cms_page=bundle["team"],
		cms_team_members=bundle["team_members"])

@app.route('/tools')
def lab_tools():
	return render_template('lab/tools.html')

@app.route('/tutorials')
def lab_tutorials():
	return render_template('lab/tutorials.html')

@app.route('/contact')
def lab_contact():
	bundle = _cms_page_bundle()
	return render_template('lab/contact.html', cms_page=bundle["contact"])


@app.route('/admin/login')
def admin_login():
	return render_template('lab/admin_login.html',
		google_enabled=_cms_google_enabled(),
		current_user=_cms_current_user())


@app.route('/admin/logout')
def admin_logout():
	session.pop("cms_email", None)
	session.pop("cms_role", None)
	session.pop("cms_google_state", None)
	return redirect(url_for('admin_login'))


@app.route('/admin/auth/google/start')
def admin_google_start():
	if not _cms_google_enabled():
		return redirect(url_for('admin_login'))
	flow = Flow.from_client_config(
		_cms_client_config(),
		scopes=["openid", "https://www.googleapis.com/auth/userinfo.email", "https://www.googleapis.com/auth/userinfo.profile"],
	)
	flow.redirect_uri = f"{siteurl.rstrip('/')}{url_for('admin_google_callback')}"
	auth_url, state = flow.authorization_url(access_type="offline", include_granted_scopes="true", prompt="select_account")
	session["cms_google_state"] = state
	return redirect(auth_url)


@app.route('/admin/auth/google/callback')
def admin_google_callback():
	if not _cms_google_enabled():
		return redirect(url_for('admin_login'))
	state = session.get("cms_google_state")
	if not state or request.args.get("state") != state:
		return redirect(url_for('admin_login'))
	flow = Flow.from_client_config(
		_cms_client_config(),
		scopes=["openid", "https://www.googleapis.com/auth/userinfo.email", "https://www.googleapis.com/auth/userinfo.profile"],
		state=state,
	)
	flow.redirect_uri = f"{siteurl.rstrip('/')}{url_for('admin_google_callback')}"
	flow.fetch_token(authorization_response=request.url)
	token = flow.credentials.token
	userinfo = requests.get(
		"https://www.googleapis.com/oauth2/v2/userinfo",
		headers={"Authorization": f"Bearer {token}"},
		timeout=20,
	).json()
	email = (userinfo.get("email") or "").lower().strip()
	if not cms.is_allowed_email(email):
		return render_template('lab/admin_login.html',
			google_enabled=_cms_google_enabled(),
			current_user=None,
			error=f"{email or 'That account'} is not approved for CMS access."), 403
	user = cms.find_user(email)
	if not user:
		cms.upsert_user(email, cms.bootstrap_role(email), active=True)
		user = cms.find_user(email) or {"email": email, "role": cms.bootstrap_role(email)}
	session["cms_email"] = email
	session["cms_role"] = user.get("role", "editor")
	return redirect(url_for('admin_cms'))


@app.route('/admin/cms', methods=['GET', 'POST'])
def admin_cms():
	user, response = _cms_require_user()
	if response:
		return response

	if request.method == 'POST':
		actions = request.form.getlist("action")
		action = actions[-1] if actions else ""
		if action == "save_team_page":
			cms.save_page("team",
				request.form.get("title", ""),
				request.form.get("subtitle", ""),
				"",
				{
					"pi_name": request.form.get("pi_name", ""),
					"pi_title": request.form.get("pi_title", ""),
					"pi_bio": request.form.get("pi_bio", ""),
					"pi_education": [line.strip() for line in request.form.get("pi_education", "").splitlines() if line.strip()],
					"join_text": request.form.get("join_text", ""),
				})
		elif action == "save_contact_page":
			cms.save_page("contact",
				request.form.get("title", ""),
				request.form.get("subtitle", ""),
				"",
				{
					"address": request.form.get("address", ""),
					"email": request.form.get("email", ""),
					"institution": request.form.get("institution", ""),
					"graduate_text": request.form.get("graduate_text", ""),
					"undergrad_text": request.form.get("undergrad_text", ""),
					"postdoc_text": request.form.get("postdoc_text", ""),
				})
		elif action == "save_research_page":
			cms.save_page("research",
				request.form.get("title", ""),
				request.form.get("subtitle", ""),
				request.form.get("body", ""),
				{})
		elif action == "save_news":
			cms.upsert_news(
				request.form.get("news_id") or None,
				request.form.get("date_label", ""),
				request.form.get("title", ""),
				request.form.get("body", ""),
				request.form.get("link_text", ""),
				request.form.get("link_url", ""),
				int(request.form.get("sort_order") or 0),
			)
		elif action == "delete_news":
			cms.delete_news(request.form.get("news_id"))
		elif action == "save_publication":
			cms.upsert_publication(
				request.form.get("pub_id") or None,
				request.form.get("year", ""),
				request.form.get("citation", ""),
				request.form.get("link_label", ""),
				request.form.get("link_url", ""),
				int(request.form.get("sort_order") or 0),
			)
		elif action == "delete_publication":
			cms.delete_publication(request.form.get("pub_id"))
		elif action == "save_team_member":
			image_path = ""
			if 'image_file' in request.files and request.files['image_file'].filename:
				image_path = cms.save_upload(request.files['image_file'])
			cms.upsert_team_member(
				request.form.get("member_id") or None,
				request.form.get("section", "members"),
				request.form.get("name", ""),
				request.form.get("role", ""),
				request.form.get("bio", ""),
				request.form.get("initials", ""),
				int(request.form.get("sort_order") or 0),
				image_path=image_path,
			)
		elif action == "delete_team_member":
			cms.delete_team_member(request.form.get("member_id"))
		elif action == "save_user":
			admin_user, admin_response = _cms_require_user(admin=True)
			if admin_response:
				return admin_response
			cms.upsert_user(
				request.form.get("email", ""),
				request.form.get("role", "editor"),
				active=(request.form.get("active", "1") == "1"),
			)
		elif action == "delete_user":
			admin_user, admin_response = _cms_require_user(admin=True)
			if admin_response:
				return admin_response
			cms.delete_user(request.form.get("email", ""))
		return redirect(url_for('admin_cms'))

	bundle = _cms_page_bundle()
	return render_template('lab/admin_cms.html',
		current_user=user,
		team_page=bundle["team"],
		contact_page=bundle["contact"],
		research_page=bundle["research"],
		news_items=bundle["news"],
		team_members=bundle["team_members"],
		publications=bundle["publications"],
		cms_users=cms.list_users())


@app.route('/admin/debug')
def admin_debug():
	telemetry_snapshot = telemetry.snapshot()
	recent_counts = telemetry.recent_job_counts(hours=24)
	service_status = check_service_health()
	protpipe_service_status = check_protpipe_service_health()
	active_threads = []
	for thread in threading.enumerate():
		if thread.getName() in siteDict or str(thread.getName()).startswith("protpipe-") or str(thread.getName()).startswith("disorderpred-"):
			active_threads.append(thread.getName())

	protpipe_recent = []
	if _PIPELINE_AVAILABLE:
		from pipeline.utils.jobs import list_jobs
		protpipe_recent = list_jobs(limit=20)

	return render_template(
		'lab/debug.html',
		service_status=service_status,
		protpipe_service_status=protpipe_service_status,
		telemetry_snapshot=telemetry_snapshot,
		recent_counts=recent_counts,
		active_threads=active_threads,
		protpipe_recent=protpipe_recent,
	)


# ---------------------------------------------------------------------------
# SSPred tool routes (moved from / to /tools/sspred)
# ---------------------------------------------------------------------------

@app.route('/tools/sspred', methods = ['GET', 'POST'])
def sspred_index(name=None):
	form = SubmissionForm()
	print(threading.activeCount())
	runningCounter = {
		"JPred": 0,
		"PSI": 0,
		#"PSS": 0,
		#"RaptorX": 0,
		"Sable": 0,
		"Yaspin": 0,
		"SSPro": 0,
		"Predator": 0,
		"NetSurf": 0
	}
	for t in threading.enumerate():
		if t.getName() in runningCounter.keys():
			runningCounter[t.getName()] += 1

	# Check service health
	serviceStatus = check_service_health()

	if form.validate_on_submit():

		if threading.activeCount() > 100:
			return redirect(url_for('sspred_error'))
		# Normalize the typed sequence (remove whitespace) up front
		clean_seq = ''.join(form.seqtext.data.split())
		print("DEBUG: original form sequence length:", len(form.seqtext.data or ""))
		print("DEBUG: cleaned form sequence length:", len(clean_seq))

		post_data = {
			'seqtext': clean_seq,
			'email': form.email.data,
			'JPred': form.JPred.data,
			'PSI':   form.PSI.data,
			#'PSS':   form.PSS.data,
			#'RaptorX': form.RaptorX.data,
			'Sable':   form.Sable.data,
			'Yaspin':   form.Yaspin.data,
			'SSPro':   form.SSPro.data,
			'PHDpsi':   form.PHDpsi.data,
			'PROFsec':   form.PROFsec.data,
			'Predator':   form.Predator.data,
			'NetSurf':    form.NetSurf.data,
			'submitbtn': 'Submit'
			}

		total_sites = validate_sites(post_data)
		post_data.update({'total_sites' : total_sites, 'completed': 0}) # add total into to post_data dictionary and a completed prediction counter
		print(post_data)
		seq = post_data['seqtext']
		print("DEBUG: initial seq length used for prediction:", len(seq))

		startTime = batchtools.randBase62()

		#Stores currently completed predictions
		ssObject = []
		job_lock = threading.Lock()

		# Insert initial sequence (may be empty; will be updated if PDB succeeds)
		dbinsert(startTime, seq)
		telemetry.record_job_event("sspred", startTime, "submitted", f"{total_sites} services selected")
		for service_name in siteDict:
			if post_data.get(service_name):
				dbupdate(startTime, service_name + "stat", 0)
				dbupdate(startTime, service_name + "msg", service_name + " – queued for submission...")

		pdbdata = None
		if form.structureId.data is not None:
			# Auto-convert PDB ID to uppercase (PDB IDs are always uppercase)
			pdb_id = form.structureId.data.upper().strip()
			chain_id = form.chainId.data.upper().strip() if form.chainId.data else None
			pdbdata = batchtools.pdbget(pdb_id, chain_id)
			if pdbdata is not None:
				dbupdate(startTime, 'pdb', json.dumps(pdbdata))
				dbupdate(startTime, 'seq', pdbdata['primary'])
				seq = pdbdata['primary']
				print("DEBUG: using PDB-derived sequence, length:", len(seq))
			else:
				print("DEBUG: pdbget returned None for", pdb_id, chain_id)

		# If after PDB lookup we still have no sequence, abort cleanly
		if not seq:
			statusMsg = "No valid sequence found. Please provide a sequence or a valid structure ID and chain."
			return redirect(url_for('sspred_dboutput', var=startTime))

		sendData(seq, startTime, ssObject, post_data, pdbdata, job_lock)
		return redirect(url_for('sspred_dboutput', var=startTime))

	return render_template('index.html', form=form, counter=runningCounter, serviceStatus=serviceStatus)

@app.route('/tools/sspred/error/')
def sspred_error():
	return('There are too many jobs running, please try again later')

@app.route('/tools/sspred/archive/<page>')
def sspred_archive(page):
	if page[0] == '0':
		return("Page not found")
	if page.isdigit():
		if int(page) >= 1:
			namelist = []
			timelist= []
			seqlist= []
			conn = psycopg2.connect(DATABASE_URL)
			cursor = conn.cursor(cursor_factory=RealDictCursor)
			limit = 20
			offset = int(page) -1
			offset = offset * limit
			cursor.execute('''
					SELECT id, seq
					FROM seqtable
					ORDER BY ID DESC LIMIT %s OFFSET %s
			''',(limit, offset))
			jsonresults = json.dumps(cursor.fetchall(), indent=2)

			cursor.close()

			return render_template('archives.html', data=jsonresults, pagenum=page)
	else:
		return("Page not found")

@app.route('/tools/sspred/archive')
def sspred_archive_redirect():
	return redirect(url_for('sspred_archive', page=1))

@app.route('/tools/sspred/output/<var>')
def sspred_output(var):
	print('output/'+var+'/'+var+'.html')
	try:
		return send_file('output/'+var+'/'+var+'.html')
	except Exception as e:
		return "not found"

@app.route('/tools/sspred/dboutput/<var>')
def sspred_dboutput(var):
	outputjson = dbselect(var)
	if outputjson == "[]":
		return "not found"
	try:
		if request.args.get('json') == '1':
			return outputjson
		row = json.loads(outputjson)[0]
		return render_template('dboutput.html', data=outputjson, failure_panels=_sspred_failure_panels(row))
	except Exception as e:
		return "not found"


@app.route('/tools/sspred/figure/<var>.<fmt>')
def sspred_publication_figure(var, fmt):
	row = dbfetch(var)
	if not row:
		return ("Job not found", 404)
	try:
		from services import sspred_figure
		options = _sspred_figure_options()
		scale = float(request.args.get("scale", 3))
		buffer, mimetype = sspred_figure.export_figure(row, options=options, output_format=fmt, scale=scale)
		download = _arg_bool("download", False)
		filename = f"sspred_{var}_figure.{fmt}"
		return send_file(
			buffer,
			mimetype=mimetype,
			as_attachment=download,
			download_name=filename,
		)
	except RuntimeError as exc:
		return (str(exc), 503)
	except ValueError as exc:
		return (str(exc), 400)
	except Exception as exc:
		return (f"Figure generation failed: {exc}", 500)


# ---------------------------------------------------------------------------
# Legacy 301 redirects (backward compatibility for bookmarked/shared links)
# ---------------------------------------------------------------------------

@app.route('/archive')
def legacy_archive():
	return redirect(url_for('sspred_archive_redirect'), 301)

@app.route('/archive/<page>')
def legacy_showall(page):
	return redirect(url_for('sspred_archive', page=page), 301)

@app.route('/output/<var>')
def legacy_output(var):
	return redirect(url_for('sspred_output', var=var), 301)

@app.route('/dboutput/<var>')
def legacy_dboutput(var):
	return redirect(url_for('sspred_dboutput', var=var), 301)

@app.route('/error/')
def legacy_error():
	return redirect(url_for('sspred_error'), 301)


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def run(predService, seq, name, ssObject,
 startTime, post_data, pdbdata, job_lock):
	try:
		tcount = 0
		for t in threading.enumerate():
			if t.getName() == name:
				tcount += 1

		if tcount > siteLimit[name]:
			tempSS = ss.SS(name)
			tempSS.pred = "Queue Full"
			tempSS.conf = "Queue Full"
			tempSS.status = -1
			status_key, status_msg, raw_error = _sspred_status_summary(name, tempSS, 0)
			dbupdate(startTime, name + "msg", status_msg)
			telemetry.record_component_run("sspred", name, startTime, status_key, summary=status_msg, raw_error=raw_error, duration_seconds=0)
		else:
			import time as time_module
			start_time = time_module.time()
			dbupdate(startTime, name + "msg", name + " – submitting job to remote server...")
			try:
				#tempSS = predService.get(seq, tcount)
				tempSS = predService.get(seq)
				elapsed_seconds = time_module.time() - start_time
				status_key, status_msg, raw_error = _sspred_status_summary(name, tempSS, elapsed_seconds)
				dbupdate(startTime, name + "msg", status_msg)
				telemetry.record_component_run("sspred", name, startTime, status_key, summary=status_msg, raw_error=raw_error, duration_seconds=elapsed_seconds)
			except Exception as e:
				tempSS = ss.SS(name)
				tempSS.pred = "Service Error: " + str(e)
				tempSS.conf = "Service Error: " + str(e)
				tempSS.status = 2
				elapsed_seconds = time_module.time() - start_time
				status_key, status_msg, raw_error = _sspred_status_summary(name, tempSS, elapsed_seconds)
				dbupdate(startTime, name + "msg", status_msg)
				telemetry.record_component_run("sspred", name, startTime, status_key, summary=status_msg, raw_error=raw_error, duration_seconds=elapsed_seconds)
				print(name + " failed with exception: " + str(e))

		dbupdate(startTime, tempSS.name + "pred", tempSS.pred)
		dbupdate(startTime, tempSS.name + "conf", tempSS.conf)
		dbupdate(startTime, tempSS.name + "stat", tempSS.status)

		with job_lock:
			ssObject.append(tempSS)
			majority = batchtools.majorityVote(seq, ssObject)
			dbupdate(startTime, 'majorityvote', majority)
			post_data['completed'] += 1
			is_finished = post_data['completed'] == post_data['total_sites']
		if is_finished:
			print("All predictions completed.")
			statusMsg = "All services complete."
			failedServices = []
			for ssobj in ssObject:
				if ssobj.status != 1 and ssobj.status != 3:
					if ssobj.status == -1:
						failedServices.append(ssobj.name + " didn't run because queue is full")
					elif ssobj.status == 2:
						if "Service Error" in ssobj.pred:
							failedServices.append(ssobj.name + " didn't run because " + ssobj.pred.replace("Service Error: ", ""))
						else:
							failedServices.append(ssobj.name + " didn't run because " + ssobj.pred)
					elif ssobj.status == 4:
						failedServices.append(ssobj.name + " didn't run because sequence not accepted")
					else:
						failedServices.append(ssobj.name + " didn't complete")
			if failedServices:
				statusMsg += " " + ". ".join(failedServices) + "."
			# dbupdate(startTime, 'status', statusMsg)  # Commented out: status column doesn't exist in database
			telemetry.record_job_event("sspred", startTime, "complete", statusMsg)
			if post_data['email'] != "": #if all completed and user email is not empty, send email
				print("Sending results notification to " + post_data['email'])
				emailtools.send_job_notification(post_data['email'], startTime, siteurl)
	except Exception as e:
		# Catch any unexpected errors to ensure thread completes
		print(name + " thread failed with unexpected error: " + str(e))
		import traceback
		traceback.print_exc()
		try:
			tempSS = ss.SS(name)
			tempSS.pred = "Thread Error: " + str(e)
			tempSS.conf = "Thread Error: " + str(e)
			tempSS.status = 2
			status_key, status_msg, raw_error = _sspred_status_summary(name, tempSS, 0)
			dbupdate(startTime, name + "msg", status_msg)
			dbupdate(startTime, tempSS.name + "pred", tempSS.pred)
			dbupdate(startTime, tempSS.name + "conf", tempSS.conf)
			dbupdate(startTime, tempSS.name + "stat", tempSS.status)
			telemetry.record_component_run("sspred", name, startTime, status_key, summary=status_msg, raw_error=raw_error, duration_seconds=0)
			# Check if this service is already in ssObject by name
			found = False
			for ssobj in ssObject:
				if ssobj.name == name:
					found = True
					break
			if not found:
				with job_lock:
					ssObject.append(tempSS)
			with job_lock:
				post_data['completed'] += 1
				is_finished = post_data['completed'] == post_data['total_sites']
			if is_finished:
				statusMsg = "All services complete. " + name + " didn't run because thread error: " + str(e) + "."
				telemetry.record_job_event("sspred", startTime, "error", statusMsg)
				# dbupdate(startTime, 'status', statusMsg)  # Commented out: status column doesn't exist in database
		except Exception as e2:
			print("Failed to update database after thread error for " + name + ": " + str(e2))
			import traceback
			traceback.print_exc()


#Sends sequence based off whatever was selected before submission
def sendData(seq, startTime, ssObject, post_data, pdbdata, job_lock):
	for key in post_data.keys():
		if key in siteDict:
			if post_data[key]:
				mythread = threading.Thread(target=run, args=(siteDict[key], seq, key, ssObject, startTime, post_data, pdbdata, job_lock))
				mythread.setName(key)
				mythread.start()
				print("Sending sequence to " + key)

#Takes a form from post and returns the number of sites selected.
def validate_sites(form):
	count = 0
	for key in siteDict.keys():
		if form[key]:
			count += 1
	return count

# ---------------------------------------------------------------------------
# ProtPipe — protein analysis pipeline routes
# ---------------------------------------------------------------------------

try:
	from pipeline.runner import submit_job as _pipe_submit, get_status as _pipe_status, get_summary as _pipe_summary
	_PIPELINE_AVAILABLE = True
except ImportError as _pipe_err:
	_PIPELINE_AVAILABLE = False
	print(f"[protpipe] pipeline not available: {_pipe_err}")

try:
	from pipeline.modules import retrieval as _retrieval_module
	_DISORDER_RETRIEVAL_AVAILABLE = True
except ImportError as _retrieval_err:
	_DISORDER_RETRIEVAL_AVAILABLE = False
	_retrieval_module = None
	print(f"[disorderpred] retrieval module not available: {_retrieval_err}")


def _protpipe_enabled_modules(input_data):
	modules = []
	if input_data.get('run_blast'):
		modules.append('BLAST')
	if input_data.get('run_hmmer'):
		modules.append('HMMER')
	if input_data.get('run_phobius'):
		modules.append('Phobius')
	if input_data.get('run_cdd'):
		modules.append('CDD')
	if input_data.get('run_scanprosite'):
		modules.append('ScanProsite')
	if input_data.get('run_uniprot_features'):
		modules.append('UniProtKB features')
	if input_data.get('run_coils'):
		modules.append('Coils')
	if input_data.get('run_smart'):
		modules.append('SMART')
	if input_data.get('run_interproscan'):
		modules.append('InterProScan')
	if input_data.get('run_signalp'):
		modules.append('SignalP')
	if input_data.get('run_disorderpred'):
		modules.append('DisorderPred')
	if input_data.get('run_sspred_companion'):
		modules.append('SSPred consensus')
	return modules


def _protpipe_runtime_hint(enabled_modules):
	slow = [item for item in enabled_modules if item in {'BLAST', 'InterProScan', 'SMART', 'SignalP', 'SSPred consensus'}]
	if 'SSPred consensus' in enabled_modules:
		return "Likely 5-15 minutes depending on remote queues. SSPred companion waits on multiple external predictors."
	if 'InterProScan' in enabled_modules or 'BLAST' in enabled_modules and len(enabled_modules) >= 7:
		return "Likely 5-15 minutes depending on remote queues."
	if 'DisorderPred' in enabled_modules:
		return "Usually the main ProtPipe annotations appear quickly; DisorderPred companion may take a few extra minutes."
	if slow:
		return "Likely 3-10 minutes depending on remote queues."
	if enabled_modules:
		return "Usually the first useful results appear within 30-90 seconds."
	return "Local property calculation only."


def _disorder_submit(input_data):
	job_id = disorderjobs.new_job_id()
	disorderjobs.create_job(job_id)
	enabled = ["NetSurfP-2.0 disorder", "Secondary-structure overlay"]
	disorderjobs.write_result(job_id, "request.json", {
		"input_type": input_data.get("input_type", "auto"),
		"submitted_value": (input_data.get("sequence_input") or "").strip()[:200],
		"submitted_at": datetime.utcnow().isoformat() + "Z",
		"enabled_modules": enabled,
		"runtime_hint": "NetSurf jobs are usually slower than SSPred; expect a few minutes depending on DTU queue time.",
	})
	telemetry.record_job_event("disorderpred", job_id, "submitted", input_data.get("input_type", "auto"))
	thread = threading.Thread(target=_run_disorder_job, args=(input_data, job_id), daemon=True)
	thread.name = f"disorderpred-{job_id}"
	thread.start()
	return job_id


def _run_disorder_job(input_data, job_id):
	job_dir = disorderjobs.job_dir(job_id)
	try:
		disorderjobs.write_status(job_id, {
			"status": "running",
			"started": datetime.utcnow().isoformat() + "Z",
			"stage": "retrieval",
			"summary": "Validating input and resolving the sequence.",
		})
		telemetry.record_job_event("disorderpred", job_id, "running", "Resolving sequence input")

		if not _DISORDER_RETRIEVAL_AVAILABLE:
			disorderjobs.write_status(job_id, {
				"status": "error",
				"started": datetime.utcnow().isoformat() + "Z",
				"finished": datetime.utcnow().isoformat() + "Z",
				"error": "Sequence retrieval module is not available.",
			})
			telemetry.record_job_event("disorderpred", job_id, "error", "Sequence retrieval module is not available.")
			return

		retrieval_result = _retrieval_module.run(input_data, job_dir)
		disorderjobs.write_result(job_id, "retrieval.json", retrieval_result)
		if retrieval_result.get("status") != "ok":
			error = retrieval_result.get("error", "Could not retrieve sequence.")
			disorderjobs.write_status(job_id, {
				"status": "error",
				"started": datetime.utcnow().isoformat() + "Z",
				"finished": datetime.utcnow().isoformat() + "Z",
				"stage": "retrieval",
				"summary": "Could not retrieve a protein sequence.",
				"error": error,
			})
			telemetry.record_job_event("disorderpred", job_id, "error", error)
			telemetry.record_component_run("disorderpred", "retrieval", job_id, "error", summary="Could not retrieve a protein sequence.", raw_error=error)
			return

		telemetry.record_component_run("disorderpred", "retrieval", job_id, "complete", summary="Sequence retrieved successfully.")
		disorderjobs.write_status(job_id, {
			"status": "running",
			"started": datetime.utcnow().isoformat() + "Z",
			"stage": "netsurf",
			"summary": "Sequence retrieved. Waiting for NetSurfP-2.0 disorder output.",
		})

		disorder_accession = (
			retrieval_result.get("header")
			or retrieval_result.get("resolved_acc")
			or retrieval_result.get("accession")
			or ""
		)
		disorder_result = disorder_service.run(retrieval_result.get("sequence", ""), accession=disorder_accession)
		disorderjobs.write_result(job_id, "result.json", disorder_result)
		if disorder_result.get("status") != "ok":
			error = disorder_result.get("error", "NetSurf disorder run failed.")
			disorderjobs.write_status(job_id, {
				"status": "error",
				"started": datetime.utcnow().isoformat() + "Z",
				"finished": datetime.utcnow().isoformat() + "Z",
				"stage": "netsurf",
				"summary": "NetSurfP-2.0 did not return a usable disorder profile.",
				"error": error,
			})
			telemetry.record_job_event("disorderpred", job_id, "error", error)
			telemetry.record_component_run("disorderpred", "netsurf", job_id, "error", summary="NetSurfP-2.0 did not return a usable disorder profile.", raw_error=error)
			return

		payload = disorder_result.get("data", {})
		disorderjobs.write_result(job_id, "summary.json", {
			"job_id": job_id,
			"completed_at": datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC"),
			"retrieval": retrieval_result,
			"disorder": payload,
		})
		disorderjobs.write_status(job_id, {
			"status": "complete",
			"started": datetime.utcnow().isoformat() + "Z",
			"finished": datetime.utcnow().isoformat() + "Z",
			"stage": "complete",
			"summary": "Disorder profile and secondary-structure overlay are ready.",
		})
		telemetry.record_job_event("disorderpred", job_id, "complete", f"{len(payload.get('disordered_regions', []))} disorder regions")
		telemetry.record_component_run("disorderpred", "netsurf", job_id, "complete", summary="Disorder profile and secondary-structure overlay are ready.")
	except Exception as exc:
		disorderjobs.write_status(job_id, {
			"status": "error",
			"started": datetime.utcnow().isoformat() + "Z",
			"finished": datetime.utcnow().isoformat() + "Z",
			"error": str(exc),
			"summary": "Unexpected DisorderPred failure.",
		})
		telemetry.record_job_event("disorderpred", job_id, "error", str(exc))
		telemetry.record_component_run("disorderpred", "worker", job_id, "error", summary="Unexpected DisorderPred failure.", raw_error=str(exc))


def _disorder_partial_summary(job_id):
	request_data = disorderjobs.read_result(job_id, "request.json") or {}
	retrieval_data = disorderjobs.read_result(job_id, "retrieval.json") or {}
	payload = disorderjobs.read_result(job_id, "summary.json") or {}
	return {
		"request": request_data if isinstance(request_data, dict) else {},
		"retrieval": retrieval_data if isinstance(retrieval_data, dict) else {},
		"summary": payload if isinstance(payload, dict) else {},
	}


@app.route('/tools/protpipe', methods=['GET', 'POST'])
def protpipe_index():
	if not _PIPELINE_AVAILABLE:
		return render_template('protpipe/unavailable.html',
			reason="Pipeline dependencies not installed. Run: pip install biopython svgwrite"), 503

	if request.method == 'POST':
		# Build motif queries list from optional motif section
		motif_queries = []
		if 'run_motif_search' in request.form and _MOTIF_AVAILABLE:
			# Preset motifs (multiple checkboxes named motif_presets)
			selected_presets = request.form.getlist('motif_presets')
			preset_map = {p['id']: p for p in _MOTIF_PRESETS} if _MOTIF_AVAILABLE else {}
			for pid in selected_presets:
				if pid in preset_map:
					p = preset_map[pid]
					motif_queries.append({'name': p['name'], 'pattern': p['pattern']})
			# Custom motif
			custom_pattern = request.form.get('motif_custom_pattern', '').strip()
			custom_name    = request.form.get('motif_custom_name', '').strip() or 'Custom motif'
			if custom_pattern:
				motif_queries.append({'name': custom_name, 'pattern': custom_pattern})

		try:
			blast_max_hits = int(request.form.get('blast_max_hits', 10))
			blast_max_hits = max(5, min(50, blast_max_hits))
		except (ValueError, TypeError):
			blast_max_hits = 10

		blast_db = request.form.get('blast_database', 'swissprot')
		if blast_db not in {'swissprot', 'refseq_protein', 'pdb', 'nr'}:
			blast_db = 'swissprot'

		input_data = {
			'input_type':        request.form.get('input_type', 'auto'),
			'sequence_input':    request.form.get('sequence_input', '').strip(),
			'run_blast':         'run_blast'         in request.form,
			'run_hmmer':         'run_hmmer'         in request.form,
			'run_phobius':       'run_phobius'       in request.form,
			'run_signalp':       'run_signalp'       in request.form,
			'run_cdd':           'run_cdd'           in request.form,
			'run_scanprosite':   'run_scanprosite'   in request.form,
			'run_uniprot_features': 'run_uniprot_features' in request.form,
			'run_smart':         'run_smart'         in request.form,
			'run_interproscan':  'run_interproscan'  in request.form,
			'run_coils':         'run_coils'         in request.form,
			'run_disorderpred':  'run_disorderpred'  in request.form,
			'run_sspred_companion': 'run_sspred_companion' in request.form,
			'blast_max_hits':    blast_max_hits,
			'blast_database':    blast_db,
			'motif_queries':     motif_queries,
		}
		enabled_modules = _protpipe_enabled_modules(input_data)
		if not input_data['sequence_input']:
			service_status = check_protpipe_service_health()
			return render_template('protpipe/index.html',
				error="Please enter a sequence or accession.",
				presets=_MOTIF_PRESETS if _MOTIF_AVAILABLE else [],
				service_status=service_status,
				initial_run_plan={
					"enabled_modules": enabled_modules,
					"runtime_hint": _protpipe_runtime_hint(enabled_modules),
				})

		job_id = _pipe_submit(input_data)
		return redirect(url_for('protpipe_results', job_id=job_id))

	service_status = check_protpipe_service_health()
	default_modules = _protpipe_enabled_modules({
		'run_blast': True,
		'run_hmmer': True,
		'run_phobius': True,
		'run_cdd': True,
		'run_scanprosite': True,
		'run_uniprot_features': True,
		'run_interproscan': True,
		'run_coils': True,
		'run_disorderpred': False,
		'run_sspred_companion': False,
	})
	return render_template('protpipe/index.html', error=None,
		presets=_MOTIF_PRESETS if _MOTIF_AVAILABLE else [],
		service_status=service_status,
		initial_run_plan={
			"enabled_modules": default_modules,
			"runtime_hint": _protpipe_runtime_hint(default_modules),
		})


@app.route('/tools/protpipe/results/<job_id>')
def protpipe_results(job_id):
	if not _PIPELINE_AVAILABLE:
		return render_template('protpipe/unavailable.html',
			reason="Pipeline dependencies not installed."), 503

	status_data = _pipe_status(job_id)
	if status_data.get('status') == 'not_found':
		default_modules = _protpipe_enabled_modules({
			'run_blast': True,
			'run_hmmer': True,
			'run_phobius': True,
			'run_cdd': True,
			'run_scanprosite': True,
			'run_uniprot_features': True,
			'run_interproscan': True,
			'run_coils': True,
			'run_disorderpred': False,
			'run_sspred_companion': False,
		})
		return render_template(
			'protpipe/index.html',
			error=f"Job '{job_id}' not found.",
			service_status=check_protpipe_service_health(),
			presets=_MOTIF_PRESETS if _MOTIF_AVAILABLE else [],
			initial_run_plan={
				"enabled_modules": default_modules,
				"runtime_hint": _protpipe_runtime_hint(default_modules),
			},
		), 404

	summary = {}
	if status_data.get('status') == 'complete':
		summary = _pipe_summary(job_id)
		from pipeline.utils.jobs import read_result as _pipe_read_result
		summary["_request"] = _pipe_read_result(job_id, "request.json") or {}
	elif status_data.get('status') == 'running':
		summary = _pipe_partial_summary(job_id)

	return render_template('protpipe/results.html',
		job_id=job_id,
		status_data=status_data,
		summary=summary,
		service_status=check_protpipe_service_health(),
	)


@app.route('/tools/protpipe/status/<job_id>')
def protpipe_status_api(job_id):
	"""JSON polling endpoint — called by the results page every few seconds."""
	if not _PIPELINE_AVAILABLE:
		return jsonify({"status": "error"})
	data = _pipe_status(job_id)
	if data.get("status") in {"running", "pending"}:
		data["partial"] = _pipe_partial_summary(job_id)
	return jsonify(data)


@app.route('/tools/protpipe/figure/<job_id>')
def protpipe_figure(job_id):
	"""
	Serve the domain architecture figure for a completed job.
	Checks for PNG (from PROSITE MyDomains) first, then SVG (internal fallback).
	"""
	import os
	from pipeline.utils.jobs import job_dir as _jdir
	jd = _jdir(job_id)
	png_path = os.path.join(jd, "domain_figure.png")
	if os.path.exists(png_path):
		return send_file(png_path, mimetype="image/png")
	svg_path = os.path.join(jd, "domain_figure.svg")
	if os.path.exists(svg_path):
		return send_file(svg_path, mimetype="image/svg+xml")
	return ("Figure not available", 404)


@app.route('/tools/protpipe/annotations/<job_id>')
def protpipe_annotations_json(job_id):
	"""Return the merged annotations JSON for a completed job."""
	if not _PIPELINE_AVAILABLE:
		return jsonify({"error": "Pipeline not available"}), 503
	from pipeline.utils.jobs import get_summary
	summary = get_summary(job_id)
	if not summary:
		return jsonify({"error": "Job not found"}), 404
	return jsonify({
		"annotations": summary.get("annotations", []),
		"annotation_summary": summary.get("annotation_summary", {}),
	})


@app.route('/tools/protpipe/figure/<job_id>/generate', methods=['POST'])
def protpipe_generate_figure(job_id):
	"""Regenerate the domain figure with user-selected annotations."""
	if not _PIPELINE_AVAILABLE:
		return jsonify({"error": "Pipeline not available"}), 503
	from pipeline.utils.jobs import get_summary, job_dir as _job_dir, set_module_status, write_result
	from pipeline.modules import mydomains
	import time as _time

	summary = get_summary(job_id)
	if not summary:
		return jsonify({"error": "Job not found"}), 404

	# Combined pool: high-conf (index 0..N-1) + low-conf (index N..N+M-1)
	hi_anns = summary.get("annotations", [])
	lc_anns = summary.get("low_confidence_annotations", [])
	combined = hi_anns + lc_anns
	seq = (summary.get("retrieval") or {}).get("sequence", "")
	if not seq:
		return jsonify({"error": "Sequence not found in job summary"}), 400

	try:
		body = request.get_json(force=True) or {}
		raw_indices = body.get("indices")
		custom_commands = str(body.get("custom_commands") or "").strip()
		if raw_indices is None:
			selected = hi_anns   # default: only high-confidence
		else:
			selected = [combined[i] for i in raw_indices
						if isinstance(i, int) and 0 <= i < len(combined)]
	except Exception as e:
		return jsonify({"error": f"Invalid request body: {e}"}), 400

	jd = _job_dir(job_id)
	try:
		fig_result = mydomains.run(seq, selected, jd, extra_commands=custom_commands)
		t = int(_time.time())
		if fig_result.get("status") == "ok":
			summary["figure_ok"] = True
			summary["figure_renderer"] = fig_result.get("renderer", "mydomains")
			summary["figure_generated_at"] = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")
			write_result(job_id, "summary.json", summary)
			set_module_status(job_id, "figures", "complete")
			return jsonify({"ok": True, "url": f"/tools/protpipe/figure/{job_id}?t={t}"})
		summary["figure_ok"] = False
		summary["figure_renderer"] = "none"
		write_result(job_id, "summary.json", summary)
		set_module_status(job_id, "figures", "error")
		return jsonify({"ok": False, "error": fig_result.get("error", "Figure generation failed")})
	except Exception as e:
		set_module_status(job_id, "figures", "error")
		return jsonify({"ok": False, "error": str(e)}), 500


@app.route('/tools/protpipe/archive')
def protpipe_archive():
	server_jobs = []
	if _PIPELINE_AVAILABLE:
		from pipeline.utils.jobs import list_jobs
		server_jobs = list_jobs(limit=100)
	return render_template('protpipe/archive.html', server_jobs=server_jobs)


def _pipe_partial_summary(job_id):
	from pipeline.utils.jobs import read_result

	request_data = read_result(job_id, "request.json") or {}
	ret_data = read_result(job_id, "retrieval.json") or {}
	prop_data = read_result(job_id, "properties.json") or {}
	partial = {
		'request': request_data if isinstance(request_data, dict) else {},
		'retrieval': ret_data.get('data', ret_data) if isinstance(ret_data, dict) else {},
		'properties': prop_data.get('data', prop_data) if isinstance(prop_data, dict) else {},
		'_partial': True,
	}
	return partial


@app.route('/tools/protpipe/download/<job_id>/json')
def protpipe_download_json(job_id):
	if not _PIPELINE_AVAILABLE:
		return ("Pipeline not available", 503)
	from pipeline.utils.jobs import job_dir, get_summary
	import io
	summary = get_summary(job_id)
	if not summary:
		return ("Job not found", 404)
	data = json.dumps(summary, indent=2)
	return send_file(
		io.BytesIO(data.encode()),
		mimetype="application/json",
		as_attachment=True,
		attachment_filename=f"protpipe_{job_id}.json",
	)


@app.route('/tools/protpipe/download/<job_id>/figure')
def protpipe_download_figure(job_id):
	"""Download domain figure — PNG preferred (MyDomains), SVG fallback."""
	if not _PIPELINE_AVAILABLE:
		return ("Pipeline not available", 503)
	from pipeline.utils.jobs import job_dir as _job_dir
	jd = _job_dir(job_id)
	png_path = os.path.join(jd, "domain_figure.png")
	if os.path.exists(png_path):
		return send_file(
			png_path,
			mimetype="image/png",
			as_attachment=True,
			attachment_filename=f"protpipe_{job_id}_figure.png",
		)
	svg_path = os.path.join(jd, "domain_figure.svg")
	if os.path.exists(svg_path):
		return send_file(
			svg_path,
			mimetype="image/svg+xml",
			as_attachment=True,
			attachment_filename=f"protpipe_{job_id}_figure.svg",
		)
	return ("Figure not available", 404)


# Keep old SVG-only route for backward compat
@app.route('/tools/protpipe/download/<job_id>/svg')
def protpipe_download_svg(job_id):
	return protpipe_download_figure(job_id)


@app.route('/tools/protpipe/download/<job_id>/txt')
def protpipe_download_txt(job_id):
	if not _PIPELINE_AVAILABLE:
		return ("Pipeline not available", 503)
	from pipeline.utils.jobs import get_summary
	import io
	summary = get_summary(job_id)
	if not summary:
		return ("Job not found", 404)
	lines = _make_text_report(job_id, summary)
	return send_file(
		io.BytesIO(lines.encode()),
		mimetype="text/plain",
		as_attachment=True,
		attachment_filename=f"protpipe_{job_id}.txt",
	)


def _make_text_report(job_id, summary):
	"""Generate a plain-text summary report from a completed pipeline job.

	Note: summary["properties"], summary["blast"], summary["hmmer"], and
	summary["phobius"] are the raw data dicts (no outer "status" wrapper) —
	that unwrapping happens in runner.py when summary.json is assembled.
	summary["retrieval"] IS the full module result including "status".
	"""
	lines = []
	lines.append("=" * 60)
	lines.append("ProtPipe — Protein Analysis Report")
	lines.append(f"Job ID : {job_id}")
	lines.append(f"Date   : {summary.get('completed_at', 'N/A')}")
	lines.append("=" * 60)

	# Retrieval (full result dict with status key)
	ret = summary.get("retrieval", {})
	if ret.get("status") == "ok":
		lines.append(f"\nSequence Source : {ret.get('source','N/A')}")
		lines.append(f"Header          : {ret.get('header','N/A')}")
		lines.append(f"Organism        : {ret.get('organism','N/A')}")
		seq = ret.get("sequence","")
		lines.append(f"Length          : {len(seq)} aa")
		if seq:
			lines.append(f"\nSequence:\n{seq}")

	# Properties (data dict directly — no status key)
	prop = summary.get("properties", {})
	if prop:
		lines.append("\n--- Physicochemical Properties ---")
		if prop.get('molecular_weight_da'): lines.append(f"Molecular Weight : {prop['molecular_weight_da']} Da")
		if prop.get('isoelectric_point'):   lines.append(f"Isoelectric Point: {prop['isoelectric_point']}")
		if prop.get('gravy') is not None:   lines.append(f"GRAVY            : {prop['gravy']}")
		if prop.get('instability_index') is not None: lines.append(f"Instability Index: {prop['instability_index']}")
		if prop.get('aromaticity') is not None: lines.append(f"Aromaticity      : {prop['aromaticity']}")

	# BLAST (data dict with "hits" key directly)
	hits = summary.get("blast", {}).get("hits", [])
	if hits:
		lines.append(f"\n--- BLAST Homology ({len(hits)} hits) ---")
		for i, h in enumerate(hits, 1):
			lines.append(
				f"{i:2}. {h.get('accession','?')}  {h.get('title','?')[:50]}"
				f"  E={h.get('e_value','?')}  Id={h.get('identity_pct','?')}%  Cov={h.get('coverage_pct','?')}%"
			)

	# HMMER (data dict with "domains" key directly)
	domains = summary.get("hmmer", {}).get("domains", [])
	if domains:
		lines.append(f"\n--- Pfam Domains ({len(domains)} found) ---")
		for d in domains:
			lines.append(
				f"  {d.get('name','?')}  [{d.get('seq_start','?')}-{d.get('seq_end','?')}]"
				f"  E={d.get('e_value','?')}  {d.get('description','')}"
			)

	# Phobius (data dict with topology keys directly)
	phob = summary.get("phobius", {})
	if phob:
		lines.append("\n--- Signal Peptide & TM Topology ---")
		sp = "Yes, cleavage after position " + str(phob.get('signal_peptide_end')) if phob.get('has_signal_peptide') else "Not detected"
		lines.append(f"Signal Peptide : {sp}")
		lines.append(f"TM Helices     : {phob.get('tm_count', 0)}")
		if phob.get('topology'):
			lines.append(f"Topology       : {phob['topology']}")

	lines.append("\n" + "=" * 60)
	lines.append("Generated by ProtPipe — Singh Lab, Brooklyn College")
	lines.append("=" * 60)
	return "\n".join(lines)


# ---------------------------------------------------------------------------
# StructMap — map completed ProtPipe annotations into a cleaner architecture
# ---------------------------------------------------------------------------

@app.route('/tools/structmap', methods=['GET', 'POST'])
def structmap_index():
	recent_jobs = []
	if _PIPELINE_AVAILABLE:
		from pipeline.utils.jobs import list_jobs
		recent_jobs = [job for job in list_jobs(limit=12) if job.get('status') == 'complete']

	if request.method == 'POST':
		job_id = (request.form.get('job_id') or '').strip()
		if not job_id:
			return render_template('structmap/index.html', error="Enter a completed ProtPipe job ID.", recent_jobs=recent_jobs), 400
		return redirect(url_for('structmap_results', job_id=job_id))

	return render_template('structmap/index.html', error=None, recent_jobs=recent_jobs)


@app.route('/tools/structmap/<job_id>')
def structmap_results(job_id):
	if not _PIPELINE_AVAILABLE:
		return render_template('protpipe/unavailable.html',
			reason="Pipeline dependencies not installed."), 503

	from pipeline.utils.jobs import get_summary

	summary = get_summary(job_id)
	if not summary:
		return render_template('structmap/index.html', error=f"ProtPipe job '{job_id}' was not found or is not complete.", recent_jobs=[]), 404

	map_data = structmap_service.build(summary, job_id)
	return render_template('structmap/results.html', job_id=job_id, summary=summary, map_data=map_data)


# ---------------------------------------------------------------------------
# DisorderPred — NetSurf-backed disorder prediction with SS overlay
# ---------------------------------------------------------------------------

@app.route('/tools/disorderpred', methods=['GET', 'POST'])
def disorderpred_index():
	service_status = check_disorderpred_service_health()
	if request.method == 'POST':
		input_data = {
			'input_type': request.form.get('input_type', 'auto'),
			'sequence_input': request.form.get('sequence_input', '').strip(),
		}
		if not input_data['sequence_input']:
			return render_template('disorderpred/index.html', error="Please enter a sequence or accession.", service_status=service_status), 400
		job_id = _disorder_submit(input_data)
		return redirect(url_for('disorderpred_results', job_id=job_id))

	return render_template('disorderpred/index.html', error=None, service_status=service_status)


@app.route('/tools/disorderpred/results/<job_id>')
def disorderpred_results(job_id):
	status_data = disorderjobs.read_status(job_id)
	if status_data.get('status') == 'not_found':
		return render_template('disorderpred/index.html', error=f"DisorderPred job '{job_id}' not found.", service_status=check_disorderpred_service_health()), 404

	summary = disorderjobs.read_result(job_id, "summary.json") or {}
	if status_data.get('status') in {'running', 'pending'}:
		summary = _disorder_partial_summary(job_id)

	return render_template('disorderpred/results.html', job_id=job_id, status_data=status_data, summary=summary)


@app.route('/tools/disorderpred/status/<job_id>')
def disorderpred_status_api(job_id):
	status = disorderjobs.read_status(job_id)
	if status.get('status') in {'running', 'pending'}:
		status['partial'] = _disorder_partial_summary(job_id)
	return jsonify(status)


# ---------------------------------------------------------------------------
# Motif Search — standalone tool + API endpoint
# ---------------------------------------------------------------------------

try:
	from pipeline.modules.motif_search import (
		search as _motif_search,
		validate_sequence as _motif_validate_seq,
		parse_advanced as _motif_parse,
		segments_to_prosite as _motif_to_prosite,
		segments_to_human as _motif_to_human,
		PRESETS as _MOTIF_PRESETS,
	)
	_MOTIF_AVAILABLE = True
except ImportError as _me:
	_MOTIF_AVAILABLE = False
	print(f"[motif] motif_search not available: {_me}")


@app.route('/tools/motif', methods=['GET'])
def motif_index():
	"""Standalone motif search tool."""
	return render_template('motif/index.html', presets=_MOTIF_PRESETS if _MOTIF_AVAILABLE else [])


@app.route('/tools/motif/search', methods=['POST'])
def motif_search_api():
	"""
	AJAX endpoint for standalone motif search.

	Accepts JSON:
	  {
	    "sequence": str,
	    "pattern":  str,          PROSITE/regex syntax (optional if segments given)
	    "segments": [...],        visual builder output (optional)
	    "name":     str           label for this query (optional)
	  }

	Returns JSON:
	  {
	    "ok":        bool,
	    "hits":      [{start, end, match}, ...],
	    "hit_count": int,
	    "regex":     str,
	    "prosite":   str,
	    "human":     str,
	    "error":     str
	  }
	"""
	if not _MOTIF_AVAILABLE:
		return jsonify({"ok": False, "error": "Motif search module not available."}), 503

	body = request.get_json(force=True) or {}
	raw_seq  = body.get("sequence", "")
	pattern  = body.get("pattern", "")
	segments = body.get("segments")

	# Validate sequence
	seq, seq_err = _motif_validate_seq(raw_seq)
	if seq_err:
		return jsonify({"ok": False, "error": seq_err, "hits": [], "hit_count": 0})

	# Determine the pattern to use
	if segments:
		result = _motif_search(seq, segments)
		# Build human / prosite representations for display
		from pipeline.modules.motif_search import segments_to_prosite, segments_to_human
		prosite_str = segments_to_prosite(segments)
		human_str   = segments_to_human(segments)
	elif pattern:
		result      = _motif_search(seq, pattern)
		segs, _     = _motif_parse(pattern)
		prosite_str = _motif_to_prosite(segs)
		human_str   = _motif_to_human(segs)
	else:
		return jsonify({"ok": False, "error": "No motif pattern provided.", "hits": [], "hit_count": 0})

	if result["status"] != "ok":
		return jsonify({"ok": False, "error": result["error"], "hits": [], "hit_count": 0})

	return jsonify({
		"ok":        True,
		"hits":      result["hits"],
		"hit_count": result["hit_count"],
		"regex":     result["regex_used"],
		"prosite":   prosite_str,
		"human":     human_str,
		"error":     "",
	})


if __name__ == "__main__":
	app.run(debug=True) #Run on localhost 127.0.0.1:5000
	#app.run(host='0.0.0.0', debug=True) #Run online on public IP:5000

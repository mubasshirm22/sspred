import io
import re
import time
import json
import requests
from urllib.parse import urljoin

from services import ss

_WEBFACE_URL  = 'https://services.healthtech.dtu.dk/cgi-bin/webface2.cgi'
_TMP_BASE_URL = 'https://services.healthtech.dtu.dk/services/NetSurfP-2.0/tmp/'
_CONFIG_FILE  = '/var/www/services/services/NetSurfP-2.0/webface.cf'
_POLL_SLEEP   = 20   # seconds between poll attempts
_CANCEL_AFTER = 1500 # 25 minutes total

# q8 → q3 mapping (NetSurf-P 2.0 8-state to 3-state)
_Q8_TO_Q3 = {'H': 'H', 'G': 'H', 'I': 'H',  # helix types
              'E': 'E', 'B': 'E',              # strand types
              'C': 'C', 'S': 'C', 'T': 'C'}   # coil types


def get(seq):
	SS = ss.SS("NetSurf")
	SS.status = 0

	result_data, result_error = fetch_raw_prediction(seq)
	if result_data is None:
		SS.pred   = "NetSurf job timed out or returned no result"
		if result_error:
			SS.pred = result_error
		SS.conf = SS.pred
		SS.status = 2
		print("NetSurf failed:", SS.pred)
		return SS

	# ── 3. Parse result → pred string ──────────────────────────────────────
	result = _parse_result(result_data, len(seq))
	if result is None:
		SS.pred   = "Could not parse NetSurf prediction output"
		SS.conf   = SS.pred
		SS.status = 2
		print("NetSurf failed: parse error. Data:", str(result_data)[:500])
		return SS

	SS.pred = result["pred"]
	if result.get("conf"):
		SS.conf = result["conf"]
		SS.status = 1
	else:
		SS.conf = "No confidence (NetSurf)"
		SS.status = 3
	print("NetSurf complete, pred length:", len(SS.pred))
	print("NETSURF::")
	print(SS.pred)
	return SS


def fetch_raw_prediction(seq):
	if len(seq) < 10 or len(seq) > 4000:
		print("NetSurf failed: sequence length out of range")
		return None, "Sequence length must be between 10 and 4000 amino acids"

	fasta_text = ">query\n" + seq + "\n"
	fasta_bytes = fasta_text.encode()

	files = {
		'uploadfile': ('query.fasta', io.BytesIO(fasta_bytes), 'text/plain'),
	}
	data = {
		'configfile': _CONFIG_FILE,
	}

	try:
		r = requests.post(
			_WEBFACE_URL,
			data=data,
			files=files,
			allow_redirects=True,
			timeout=60,
		)
	except requests.RequestException as e:
		print("NetSurf failed (submit):", e)
		return None, "Network error during submission: " + str(e)

	jobid = _extract_jobid(r)
	if not jobid:
		print("NetSurf failed: no jobid found. Final URL:", r.url)
		print("NetSurf response (first 500):", r.text[:500])
		return None, "Could not obtain job ID from NetSurf server"

	print("NetSurf jobid:", jobid)
	return _poll(jobid)


# ── helpers ────────────────────────────────────────────────────────────────

def _extract_jobid(response):
	"""Pull jobid from redirect URL or response HTML."""
	# Try final URL query param  ?jobid=XXXX
	m = re.search(r'[?&]jobid=([A-Za-z0-9_\-]+)', response.url)
	if m:
		return m.group(1)
	# Try body
	m = re.search(r'[?&]jobid=([A-Za-z0-9_\-]+)', response.text)
	if m:
		return m.group(1)
	# Some servers embed it as  jobid = "XXXX"
	m = re.search(r'jobid\s*[=:]\s*["\']?([A-Za-z0-9_\-]{6,})["\']?', response.text, re.IGNORECASE)
	if m:
		return m.group(1)
	return None


def _poll(jobid):
	"""Poll the ajax endpoint until results are available.
	Returns (parsed_result_data, error_message)."""
	deadline = time.time() + _CANCEL_AFTER
	last_error = ""
	while time.time() < deadline:
		time.sleep(_POLL_SLEEP)
		try:
			r = requests.get(
				_WEBFACE_URL,
				params={'ajax': '1', 'jobid': jobid, 'wait': '20'},
				timeout=60,
				allow_redirects=True,
			)
		except requests.RequestException as e:
			print("NetSurf poll error:", e)
			continue

		text = r.text.strip()
		print("NetSurf poll response (first 200):", text[:200])
		job = None

		# Try JSON first (new API format: {q8: "...", q8_prob: [...], ...})
		if text.startswith('{') or text.startswith('['):
			try:
				data = json.loads(text)
				if isinstance(data, list):
					data = data[0]
				if 'q8' in data or 'q3' in data:
					return data, ""
				if isinstance(data, dict):
					job = data
			except (json.JSONDecodeError, IndexError, KeyError):
				pass

		# Fallback: CSV format
		if _looks_like_csv(text):
			return {'_csv': text}, ""

		if job and str(job.get("status", "")).lower() == "finished":
			summary = _fetch_summary(jobid)
			if summary:
				result = _fetch_prediction_from_summary(jobid, summary)
				if result is not None:
					return result, ""
			last_error = _fetch_job_error(jobid) or "NetSurf finished but no prediction JSON was available."

	return None, last_error or "NetSurf job timed out or returned no result"


def _fetch_summary(jobid):
	summary_url = urljoin(_TMP_BASE_URL, f"{jobid}/summary.json")
	try:
		response = requests.get(summary_url, timeout=60, allow_redirects=True)
		if not response.ok:
			return None
		return response.json()
	except (requests.RequestException, json.JSONDecodeError):
		return None


def _fetch_prediction_from_summary(jobid, summary):
	preds = summary.get("preds") or []
	for pred in preds:
		filename = pred.get("filename")
		if not filename:
			continue
		result_url = urljoin(_TMP_BASE_URL, f"{jobid}/{filename}")
		try:
			response = requests.get(result_url, timeout=60, allow_redirects=True)
			if not response.ok:
				continue
			data = response.json()
			if isinstance(data, dict) and ('q3' in data or 'q8' in data):
				return data
		except (requests.RequestException, json.JSONDecodeError):
			continue
	return None


def _fetch_job_error(jobid):
	try:
		response = requests.get(_WEBFACE_URL, params={'jobid': jobid}, timeout=60, allow_redirects=True)
		response.raise_for_status()
	except requests.RequestException:
		return ""
	match = re.search(r'<pre id="mainProgramOutput"[^>]*>(.*?)</pre>', response.text, re.DOTALL)
	if not match:
		return ""
	lines = [line.strip() for line in match.group(1).splitlines() if line.strip()]
	if not lines:
		return ""
	cleaned = []
	for line in lines:
		line = re.sub(r'^#\s*\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}\s+NetSurfP2 Web:\s*ERROR\s*', '', line)
		cleaned.append(line)
	return " ".join(cleaned).strip()


def _looks_like_csv(text):
	if not text or len(text) < 20:
		return False
	for line in text.splitlines():
		if line.startswith('#') or not line.strip():
			continue
		parts = line.split(',')
		if len(parts) >= 4 and parts[3].strip() in ('H', 'E', 'C'):
			return True
	return False


def _parse_result(data, expected_len):
	"""Parse NetSurf result dict (JSON) or CSV into an H/E/C prediction string."""
	# JSON path: use q3 if available, else convert q8 → q3
	if isinstance(data, dict) and '_csv' not in data:
		q_str = data.get('q3') or data.get('q8', '')
		if not q_str:
			return None
		if data.get('q8') and not data.get('q3'):
			# convert 8-state to 3-state
			pred = ''.join(_Q8_TO_Q3.get(c.upper(), 'C') for c in q_str)
		else:
			pred = q_str.upper()
		pred = ''.join(c if c in ('H', 'E', 'C') else 'C' for c in pred)
		if abs(len(pred) - expected_len) > 5:
			print(f"NetSurf length mismatch: expected {expected_len}, got {len(pred)}")
			return None
		return {
			'pred': pred,
			'conf': _build_confidence_string(data, len(pred)),
		}

	# CSV fallback
	csv_text = data.get('_csv', '') if isinstance(data, dict) else ''
	residues = {}
	for line in csv_text.splitlines():
		line = line.strip()
		if not line or line.startswith('#'):
			continue
		parts = line.split(',')
		if len(parts) < 4:
			continue
		try:
			n  = int(parts[1].strip())
			q3 = parts[3].strip().upper()
		except (ValueError, IndexError):
			continue
		if q3 in ('H', 'E', 'C'):
			residues[n] = q3
	if not residues:
		return None
	max_idx = max(residues.keys())
	pred = ''.join(residues.get(i, 'C') for i in range(1, max_idx + 1))
	if abs(len(pred) - expected_len) > 5:
		print(f"NetSurf length mismatch: expected {expected_len}, got {len(pred)}")
		return None
	return {'pred': pred, 'conf': ''}


def _build_confidence_string(data, expected_len):
	probabilities = data.get('q3_prob')
	if not isinstance(probabilities, list):
		probabilities = data.get('q8_prob') or []
	if not isinstance(probabilities, list):
		return ''

	conf_digits = []
	for row in probabilities[:expected_len]:
		if not isinstance(row, list):
			return ''
		numeric_values = []
		for value in row:
			try:
				numeric_values.append(float(value))
			except (TypeError, ValueError):
				return ''
		if not numeric_values:
			return ''
		max_prob = max(0.0, min(1.0, max(numeric_values)))
		conf_digits.append(str(int(round(max_prob * 9))))

	if len(conf_digits) != expected_len:
		return ''
	return ''.join(conf_digits)

import requests
import time
from guerrillamail import GuerrillaMailSession

from services import ss, batchtools


def get(seq):

	SS = ss.SS("PSI")

	if (len(seq) < 30 or len(seq) > 1500):
		if len(seq) < 30:
			SS.pred += "Sequence is too short (minimum 30 amino acids)"
			SS.conf += "Sequence is too short (minimum 30 amino acids)"
		else:
			SS.pred += "Sequence is too long (maximum 1500 amino acids)"
			SS.conf += "Sequence is too long (maximum 1500 amino acids)"
		SS.status = 2
		return SS

	email_address, session = batchtools.get_temp_email()

	fasta_seq = ">query\n" + seq

	try:
		r = requests.post(
			'https://bioinf.cs.ucl.ac.uk/psipred/api/submission/',
			data={
				'job': 'psipred',
				'submission_name': 'sspred',
				'email': email_address,
			},
			files={
				'input_data': ('sequence.fasta', fasta_seq.encode(), 'text/plain')
			},
			headers={'accept': 'application/json'},
			timeout=30
		)

		if r.status_code not in (200, 201):
			SS.pred += "PSIPRED server returned HTTP " + str(r.status_code)
			SS.conf += "PSIPRED server returned HTTP " + str(r.status_code)
			SS.status = 2
			print("PsiPred failed: HTTP", r.status_code)
			return SS

		print("PSI raw response body:", repr(r.text[:500]))

		try:
			uuid = r.json()['UUID']
		except Exception as e:
			SS.pred += "Could not parse PSIPRED submit response: " + str(e)
			SS.conf += "Could not parse PSIPRED submit response: " + str(e)
			SS.status = 2
			print("PsiPred failed: bad submit response:", repr(r.text[:300]))
			return SS

		print("PSI job submitted, UUID:", uuid)

		# Poll submission status until Complete
		# PSIPred uses ?format=json (no trailing slash) for the status endpoint
		poll_url = 'https://bioinf.cs.ucl.ac.uk/psipred/api/submission/' + uuid + '?format=json'
		stime = time.time()
		state = ''
		data = {}

		while state != 'Complete' and time.time() < stime + 2700:
			print('PsiPred Not Ready')
			resp = requests.get(poll_url, headers={'accept': 'application/json'}, timeout=30)
			print("PSI poll status:", resp.status_code, "body:", repr(resp.text[:300]))
			try:
				data = resp.json()
			except Exception:
				print("PSI poll response not JSON, retrying in 20s...")
				time.sleep(20)
				continue
			state = data.get('state', '')
			print("PSI job state:", state)
			if state == 'Error':
				SS.pred += "PSIPRED job failed on server"
				SS.conf += "PSIPRED job failed on server"
				SS.status = 2
				print("PsiPred failed: server-side error")
				return SS
			if state != 'Complete':
				time.sleep(20)

		if state != 'Complete':
			SS.pred += "PSIPRED job timed out after 45 minutes"
			SS.conf += "PSIPRED job timed out after 45 minutes"
			SS.status = 2
			print("PsiPred failed: timed out")
			return SS

		# Structure: data['submissions'][0]['results'] is a list of {name, data_path, ...}
		# data_path is a relative path like /submissions/{uuid}.horiz
		horiz_url = None
		for sub in data.get('submissions', []):
			for result_file in sub.get('results', []):
				data_path = result_file.get('data_path', '')
				if data_path.endswith('.horiz'):
					horiz_url = 'https://bioinf.cs.ucl.ac.uk/psipred/api' + data_path
					break
			if horiz_url:
				break

		if not horiz_url:
			SS.pred += "Could not find .horiz result file"
			SS.conf += "Could not find .horiz result file"
			SS.status = 2
			print("PsiPred failed: no .horiz file in results")
			return SS

		horiz = requests.get(horiz_url, timeout=30)
		print("PSI horiz URL:", horiz_url)
		print("PSI horiz status:", horiz.status_code)
		print("PSI horiz content:", repr(horiz.text[:400]))
		parsed = _parse_horiz_output(horiz.text)
		if parsed is None:
			SS.pred += "Could not parse PSIPRED .horiz output"
			SS.conf += "Could not parse PSIPRED .horiz output"
			SS.status = 2
			print("PsiPred failed: horiz parse error")
		else:
			SS.pred = parsed["pred"]
			SS.conf = parsed["conf"]
			SS.status = 1
			print("PsiPred Complete")

	except requests.RequestException as e:
		SS.pred += "Network error: " + str(e)
		SS.conf += "Network error: " + str(e)
		SS.status = 2
		print("PsiPred failed:", str(e))
	except Exception as e:
		SS.pred += "Error: " + type(e).__name__ + ": " + str(e)
		SS.conf += "Error: " + type(e).__name__ + ": " + str(e)
		SS.status = 4
		print("PsiPred failed:", str(e))
		import traceback
		traceback.print_exc()

	print("PSI::")
	print(SS.pred)
	print(SS.conf)

	return SS


def _parse_horiz_output(text):
	pred = ""
	conf = ""
	for raw_line in text.splitlines():
		line = raw_line.strip()
		if line.startswith("Conf"):
			conf += line[6:].strip()
		elif line.startswith("Pred"):
			pred += line[6:].strip()
	if pred and conf:
		return {"pred": pred, "conf": conf}
	return None

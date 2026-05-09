import requests
import time
from guerrillamail import GuerrillaMailSession

from services import ss, batchtools

def get(seq):

	SS = ss.SS("Yaspin")
	SS.status = 0

	if (len(seq) > 4000):
		SS.pred += "Sequence longer than 4000"
		SS.conf += "Sequence longer than 4000"
		SS.status = 2 #error status
		print("YASPIN failed: Sequence longer than 4000")
		return SS #return SS so it will be readable as an ssObject
		
	email_address, session = batchtools.get_temp_email()
	
	fasta_seq = '>testprot\n' + seq

	payload = {'seq': fasta_seq,
	'mbjob[description]': 'testprot',
	'nnmethod': 'dssp',
	'smethod': 'nr',
	'yaspin_align': 'YASPIN prediction',
	'email': email_address}

	fasta = {'seq_file': ('', b'', 'application/octet-stream'), 'pssm_file': ('', b'', 'application/octet-stream')}
	r= requests.post('https://zeus.few.vu.nl/programs/yaspinwww/', data = payload, files = fasta)
	
	if (r.status_code == 500):
		SS.pred += "Server Down"
		SS.conf += "Server Down"
		SS.status = 2
		print("Yaspin Failed: Server Down")
		return SS
	
	result_url = r.url + 'results.out'
	
	# Yaspin can be slow; wait up to 45 minutes (2700s) like other services
	requesturl = batchtools.requestWait(result_url, 'Yaspin Not Ready', 20, 2700)
	
	if requesturl:
		# Help debug by printing a snippet of the raw Yaspin output
		try:
			print("Yaspin RAW (first 400 chars):", requesturl.text[:400])
		except Exception:
			pass
		parsed = _parse_results_output(requesturl.text)
		if parsed is None:
			SS.pred += "Could not parse YASPIN results.out output"
			SS.conf += "Could not parse YASPIN results.out output"
			SS.status = 2
			print("YASPIN failed: parse error")
		else:
			SS.pred = parsed["pred"]
			SS.conf = parsed["conf"]
			SS.status = 1
			print("Yaspin Complete")
	else:
		SS.pred += "failed to respond in time (Yaspin results.out did not become available)"
		SS.conf += "failed to respond in time (Yaspin results.out did not become available)"
		SS.status = 2 #error status
		print("YASPIN failed: No response")
	return SS


def _parse_results_output(text):
	pred = ""
	conf = ""
	for raw_line in text.splitlines():
		if raw_line.startswith(" Pred:"):
			pred += raw_line[6:].strip()
		elif raw_line.startswith(" Conf:"):
			conf += raw_line[6:].strip()
	if not pred:
		return None
	return {
		"pred": pred.replace('-', 'C'),
		"conf": conf,
	}

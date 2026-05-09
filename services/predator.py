import requests
import re

from services import ss

def get(seq):

	SS = ss.SS("Predator")
	SS.status = 0

	if (len(seq) < 10 or len(seq) > 4000):
		SS.pred += "Sequence length must be between 10 and 4000 amino acids"
		SS.conf += "Sequence length must be between 10 and 4000 amino acids"
		SS.status = 2
		print("Predator failed: Sequence length issue")
		return SS

	payload = {
		'title': 'testprot',
		'notice': seq,
		'ali_width': '70',
		'predatorssmat': 'dssp'
	}

	try:
		r = requests.post(
			'https://npsa-prabi.ibcp.fr/cgi-bin/secpred_preda.pl',
			data=payload,
			timeout=180
		)

		if r.status_code != 200:
			SS.pred += "Server returned HTTP " + str(r.status_code)
			SS.conf += "Server returned HTTP " + str(r.status_code)
			SS.status = 2
			print("Predator failed: HTTP", r.status_code)
			return SS

		print("Predator RAW (first 2000 chars):", r.text[:2000])

		full_pred = _parse_html_response(r.text)
		if full_pred:
			SS.pred = full_pred.replace('-', 'C')
			SS.conf = "No confidence (Predator)"
			SS.status = 1
			print("Predator Complete, pred length:", len(SS.pred))
		else:
			SS.pred += "Could not parse prediction from response"
			SS.conf += "Could not parse prediction from response"
			SS.status = 2
			print("Predator failed: no H/E/C lines found in <pre> blocks")

	except requests.RequestException as e:
		SS.pred += "Network error: " + str(e)
		SS.conf += "Network error: " + str(e)
		SS.status = 2
		print("Predator failed:", str(e))
	except Exception as e:
		SS.pred += "Error: " + str(e)
		SS.conf += "Error: " + str(e)
		SS.status = 2
		print("Predator failed:", str(e))
		import traceback
		traceback.print_exc()

	print("PREDATOR::")
	print(SS.pred)
	return SS


def _parse_html_response(text):
	pre_blocks = re.findall(r'<pre[^>]*>(.*?)</pre>', text, re.DOTALL | re.IGNORECASE)
	full_pred = ''
	for block in pre_blocks:
		clean = re.sub(r'<[^>]+>', '', block)
		for line in clean.splitlines():
			line_stripped = line.strip()
			if line_stripped and re.match(r'^[HEChec ]+$', line_stripped):
				full_pred += line_stripped.upper().replace(' ', '')
	return full_pred or None

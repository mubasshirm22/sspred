import requests
import time
from guerrillamail import GuerrillaMailSession

from services import ss, batchtools


def get(seq):

	SS = ss.SS("JPred")
	
	if (len(seq) < 20 or len(seq) > 800): #Shorter than 20 shouldnt happen with input validation
		SS.pred += "Sequence is longer than 800"
		SS.conf += "Sequence is longer than 800"
		SS.status = 2 #error status
		print("JPred failed: Sequence is longer than 800")
		'''
		SS.pred += "Sequence is shorter than 20 or longer than 800"
		SS.conf += "Sequence is shorter than 20 or longer than 800"
		SS.status = 2 #error status
		print("JPred failed: Sequence is shorter than 20 or longer than 800")
		'''
		return SS
	
	email_address, _session = batchtools.get_temp_email()
	
	payload = {'email': email_address, 
		'queryName': 'testprot', 
		'input': 'seq', 
		'pdb': '1', 
		'.submit': 'continue', 
		'seq': seq}

	r= requests.post('http://www.compbio.dundee.ac.uk/jpred4/cgi-bin/jpred_form', data=payload)

	try: #try/catch in case a nucleotide/invalid sequence is entered
		response = r.headers['Refresh'].split('?')
		jobid = response[1]

		joburl = 'http://www.compbio.dundee.ac.uk/jpred4/results/' + jobid + '/' + jobid + '.jnet'

		page = requests.get(joburl).text

		'''
		#No cancel
		while page[0] == '<':
			print("JpredSS Not Ready")
			time.sleep(20)
			page = requests.get(joburl).text
		'''

		#Cancel after 45 min (increased timeout)
		stime  = time.time()
		timeout = 2700  # 45 minutes
		check_count = 0
		while page[0] == '<' and time.time() < stime + timeout:
			print("JpredSS Not Ready")
			check_count += 1
			if check_count % 3 == 0:  # Every 3 checks (1 minute), update status
				elapsed = int((time.time() - stime) / 60)
				print("JPred still trying... (" + str(elapsed) + " minutes elapsed)")
			time.sleep(20)
			if time.time() < stime + timeout:  # Only fetch if still within timeout
				try:
					page = requests.get(joburl, timeout=10).text
				except:
					page = '<'  # Keep trying if request fails

		if page[0] != '<' and time.time() < stime + timeout:
			parsed = _parse_jnet_output(page)
			if parsed is None:
				SS.pred += "Could not parse JPred .jnet output"
				SS.conf += "Could not parse JPred .jnet output"
				SS.status = 2
				print("JPred failed: parse error")
			else:
				SS.pred = parsed["pred"]
				SS.conf = parsed["conf"]
				SS.status = 1
				print("JPred Complete")
		else:
			elapsed_min = int((time.time() - stime) / 60)
			SS.pred += "failed to respond after " + str(elapsed_min) + " minutes"
			SS.conf += "failed to respond after " + str(elapsed_min) + " minutes"
			SS.status = 2 #error status
			print("JPred failed: No response after " + str(elapsed_min) + " minutes")
	except:
		SS.pred += "sequence not accepted"
		SS.conf += "sequence not accepted"
		SS.status = 4
		print("JPred failed: sequence not accepted")

	print("JPRED::")
	print(SS.pred)
	print(SS.conf)
	
	return SS


def _parse_jnet_output(text):
	raw = text.splitlines()
	pred = ""
	conf = ""
	for line in raw:
		line = line.strip()
		if line.startswith('jnetpred:'):
			pred += line.replace('jnetpred:', '').replace('-', 'C').replace(',', '').strip()
		elif line.startswith('JNETCONF:'):
			conf += line.replace('JNETCONF:', '').replace(',', '').strip()
	if pred and conf:
		return {"pred": pred, "conf": conf}
	return None

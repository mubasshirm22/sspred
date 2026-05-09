import os
import requests
import time
import io
import re
import html
from guerrillamail import GuerrillaMailSession

from services import ss, batchtools

def get(seq):
	
	SS = ss.SS("Sable")
	if len(seq) <= 12: #<=12 shouldnt happen with input validation
		SS.status = 2
		SS.pred += "Sequence is shorter than or equal to 12"
		SS.conf += "Sequence is shorter than or equal to 12"
		print("SABLE failed: Sequence is shorter than or equal to 12")
		
	SS.status = 0
	
	randName = batchtools.randBase62()
	email_address, session = batchtools.get_temp_email()

	payload = {'txtSeq': seq, 
	'seqName': randName,
	'email': email_address, 
	'fileName':'', 
	'SS':'SS', 
	'version':'sable2', 
	'SAaction': 'wApproximator',
	'SAvalue':'REAL'}
	
	r = requests.post('http://sable.cchmc.org/cgi-bin/sable_server_July2003.cgi', data = payload)
	
	#sable uses multiple emails to send results
	query = 'from:(sable) subject:(sable result) query: ' + randName

	#Length 4000 takes around 10 min
	message  = ''
	stime  = time.time()
	email_id = False
	
	'''
	#Waits indefinitely until results are out
	email_id, message = batchtools.emailRequestWait(session, query, "Query:", randName, "Sable Not Ready", 30)
	'''
	
	#Cancel in 45 min (increased timeout)
	email_id, message = batchtools.emailRequestWait(session, query, "Query:", randName, "Sable Not Ready", 30, 2700)
	
	if email_id:
		parsed = _parse_email_message(message)
		if parsed is None:
			SS.pred += "Could not parse SABLE email output"
			SS.conf += "Could not parse SABLE email output"
			SS.status = 2
			print("SABLE failed: parse error")
		else:
			SS.pred = parsed["pred"]
			SS.conf = parsed["conf"]
			SS.hconf = parsed["hconf"]
			SS.econf = parsed["econf"]
			SS.cconf = parsed["cconf"]
			SS.status = 1
			print(SS.pred)
			print(SS.conf)
			print("Sable Complete")
	else:
		SS.pred += "failed to respond after 45 minutes"
		SS.conf += "failed to respond after 45 minutes"
		SS.status = 2 #error status
		print("Sable failed: No response after 45 minutes")
	return SS


def _parse_email_message(message):
	message_parts = message.splitlines()
	pred = ""
	conf = ""
	index = 0
	while index < len(message_parts) and message_parts[index][:11] != 'END_SECTION':
		if message_parts[index].startswith('>') and index + 3 < len(message_parts):
			pred += message_parts[index + 2].strip()
			conf += message_parts[index + 3].strip()
		index += 1
	if not pred or not conf:
		return None
	index += 1
	helix_prob = ''
	beta_prob = ''
	coil_prob = ''
	while index < len(message_parts) and message_parts[index][:11] != 'END_SECTION':
		if message_parts[index].startswith('>') and index + 4 < len(message_parts):
			helix_prob += message_parts[index + 2][3:].strip() + ' '
			beta_prob += message_parts[index + 3][3:].strip() + ' '
			coil_prob += message_parts[index + 4][3:].strip() + ' '
		index += 1
	return {
		"pred": pred,
		"conf": conf,
		"hconf": helix_prob.split(),
		"econf": beta_prob.split(),
		"cconf": coil_prob.split(),
	}

import os
import requests
import time
import io
import re
from bs4 import BeautifulSoup
from guerrillamail import GuerrillaMailSession

from services import ss, batchtools

def get(seq):
	
	SS = ss.SS("SSPro")
	SS.status = 0
	
	if (len(seq) > 400):
		SS.pred += "Sequence is longer than 400"
		SS.conf += "Sequence is longer than 400"
		SS.status = 2 #error status
		print("SSPro failed: Sequence longer than 400")
		return SS #return SS so it will be readable as an ssObject
	
	randName = batchtools.randBase62()
	email_address, session = batchtools.get_temp_email()
	
	payload = {'amino_acids': seq,
	'query_name': randName, 
	'email': email_address,
	'ss':'on'}
	
	r = requests.post('http://scratch.proteomics.ics.uci.edu/cgi-bin/new_server/sql_predict.cgi', data = payload)
	
	soup = BeautifulSoup(r.text, 'html.parser')
	msg = soup.find('p')
	if msg == None:
		SS.pred += "Failed to Submit"
		SS.conf += "Failed to Submit"
		SS.status = 2 #error status
		print("SSPro Failed to Submit")
		return SS

	if msg.text.split()[0] == 'ERROR:':
		SS.pred += "Queue Full"
		SS.conf += "Queue Full"
		SS.status = 2 #error status
		print("SSPro Queue Full")
		return SS
	
	query = 'from:(baldig@ics.uci.edu) subject:(Protein Structure Predictions for ' + randName + ')'
	stime  = time.time()
	email_id = False
	
	'''
	#Waits indefinitely until results are out
	email_id, message = batchtools.emailRequestWait(session, query, "Name:", randName, "SSPro Not Ready", 60)
	'''
	
	#Cancels after 45 min (increased timeout). Length 400 sequences take 10-15 min in a batch
	email_id, message = batchtools.emailRequestWait(session, query, "Name:", randName, "SSPro Not Ready", 60, 2700)
	
	if email_id:
		pred = _parse_email_message(message)
		if pred:
			SS.pred = pred
			SS.conf = "SSPro Does Not Provide Any Conf" 
			SS.status = 3
			print("SSpro Complete")
		else:
			SS.pred += "Could not parse SSPro email output"
			SS.conf += "Could not parse SSPro email output"
			SS.status = 2
			print("SSPro failed: parse error")
	else:
		SS.pred += "failed to respond after 45 minutes"
		SS.conf += "failed to respond after 45 minutes"
		SS.status = 2 #error status
		print("SSPro failed: No response after 45 minutes")
	return SS


def _parse_email_message(message):
	message_parts = message.splitlines()
	index = 0
	pred = []
	while index < len(message_parts):
		if message_parts[index] == "Predicted Secondary Structure (3 Class):":
			index += 1
			while index < len(message_parts) and message_parts[index]:
				line = message_parts[index].strip()
				if line and not line.startswith("Confidence"):
					pred.append(line)
				index += 1
			break
		index += 1
	output = "".join(pred)
	return output or None

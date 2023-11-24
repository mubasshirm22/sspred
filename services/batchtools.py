import time
import math
import requests
from guerrillamail import GuerrillaMailSession
import html
from bs4 import BeautifulSoup
#Contains functions related to output that are meant to be applied to multiple scripts

#Creates a random string to use for a prediction name. Can take a time and create a string from that
def randBase62(givenTime = None):
	if givenTime:
		integer = round(givenTime * 100000)
	else:
		integer = round(time.time() * 100000)
	chars = '0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz'
	result = ''
	while integer > 0:
		integer, remainder = divmod(integer, 62)
		result = chars[remainder]+result
	return result
	
#Takes current completed outputs and conducts a majority vote then returns it. If a majority vote results in an equal value, currently defaults to 'X'
def majorityVote(seq, ssObject):
	output = ''
	
	count = 0 #success counter
	for index in ssObject:
		if index.status == 1 or index.status == 3:
			count += 1
	
	
	if count >= 2: #vote only if at least 2 ssObjects are completed
		#create a counter for each character appearance
		seqLength = len(seq)
		cCount = [0] * seqLength
		hCount = [0] * seqLength
		eCount = [0] * seqLength
		
		for i in ssObject:
			if i.status == 1 or i.status == 3:
				for j in range(0, seqLength):
					if i.pred[j] == 'C':
						cCount[j] += 1
					elif i.pred[j] == 'E':
						eCount[j] += 1
					elif i.pred[j] == 'H':
						hCount[j] += 1

		for i in range(0, seqLength):
			if eCount[i] > hCount[i] and eCount[i] > cCount[i]:
				output += 'E'
			elif hCount[i] > cCount[i] and hCount[i] > eCount[i]:
				output += 'H'
			elif cCount[i] > hCount[i] and cCount[i] > eCount[i]:
				output += 'C'
			else:
				output += 'X' #use X if unsure - typically shows when not all predictions are completed
	else:
		return None
	return output

def pdbget(pdbid, chain):
	
    data = {
    "pdbid": pdbid, # replace with pdbid variable
    "paste_field": "",
    "action": "compute",
    "contact_threshold": "6",
    "sensitive": "true"
    }
    
    url = 'https://webclu.bio.wzw.tum.de/cgi-bin/stride/stridecgi.py'
    response = requests.post(url, data=data, headers="")


    lines = response.text.split('\n')

    selected_str_lines = []
    selected_seq_lines = []
    color = []
    # --------------- Isolate sequence and structure lines  between a certain chain ID section

    # Initialize a flag to indicate when we are between CHN lines with identifier A
    in_section_a = False
    variable_char = chain
    for line in lines:
        # Check if the line starts with CHN and contains the identifier A
        if line.startswith('CHN') and f' {variable_char} ' in line: # replace B with chainID
            in_section_a = True  # Start capturing STR lines
        elif line.startswith('CHN') and f' {variable_char} ' not in line:
            in_section_a = False  # Stop capturing STR lines
        # If we are in the right section and the line starts with STR, add it to the list
        if in_section_a and line.startswith('STR'):
            selected_str_lines.append(line)
        if in_section_a and line.startswith('SEQ'):
            selected_seq_lines.append(line)

    # Now 'selected_str_lines' contains the STR lines between CHN lines with identifier A
    # Now 'selected_seq_lines' contains the SEQ lines between CHN lines with identifier A


    # ----------------------------------------------------




    # --------- For Isolating Sequence From Chain ID section
    new = ''
    for line in selected_seq_lines:
        new = new + "\n" + line
    # print(line)

    print(new)

    sequences = []
    for line in new.strip().split('\n'):
        parts = line.split()  # Split the line into parts
        if parts[0] == 'SEQ':  # Check if the line starts with 'SEQ'
            sequence = parts[2]  # The sequence is the third element (index 2)
            sequences.append(sequence)  # Add the sequence to the list
    finalseq = ''.join(sequences)

    print('final seq' + finalseq)

    # -----------------------------------



    # ------ For Isolating Structure From Chain ID section

    # ------ Get the amount of residues so that it can be used to isolate Structure

    # Get the last element
    last_element = selected_seq_lines[-1]

    # Split by whitespace and reverse the list
    parts = last_element.split()
    reversed_parts = reversed(parts)

    # Find the last number
    last_number = None
    for part in reversed_parts:
        if part.isdigit():
            last_number = int(part)
            break

    print(last_number)

    residue_count = last_number
    residue_count = residue_count%50
    # residue_count now has the amount of residues that must be present in the last structure 
    # ---------------------


    v = ''
    for line in selected_str_lines:
        v = v + "\n" + line

    # The final string to accumulate the results
    final_string = ""

    # Variable number of characters for the last element
    variable_chars = residue_count  # Replace with the actual number you want

    # Iterate through all but the last string to add 50 characters from each
    for i in range(len(selected_str_lines) - 1):
        final_string += selected_str_lines[i][10:10+50]

    # Add the variable number of characters from the last string
    final_string += selected_str_lines[-1][10:10+variable_chars]

    print('"' + final_string + '"')
    finalstr = final_string.replace(" ", "C")
    print(finalstr)

    # data to return
    sequence = finalseq
    secondary = finalstr

    # --  errors to test
    # capitalization/lackthereof
    # spaces in chain id etc
    # spaces in pdbid?
    result = {
            'pdbid': pdbid, 
            'chain': chain,
            'primary': sequence,
            'color': color,
            'secondary': secondary
    }
    return result

'''
#No auto canceling, infinite wait time

#Takes url to check, optional message for printing and optional sleep time in seconds. Defaults to 20 sec sleep time
#Returns the url when successful
def requestWait(requesturl, message = None, sleepTime = 20):
	while not requests.get(requesturl).ok:
		print(message)
		time.sleep(sleepTime)		
	return requests.get(requesturl)
	
#Takes a guerillamail session, search query, identifier line (Name: or Query:), and input name. Optional print message, and time to wait between checks
#Returns the bool email id and message when successful
def emailRequestWait(session, query, findLine, randName, printmsg = '', sleepTime = 60):
	message  = ''
	email_id = False
	
	while message == '': #loops until desired email is found or 15 min elapse
		print(printmsg)
		time.sleep(sleepTime)
		for e in session.get_email_list():			#For each email in inbox
			data = session.get_email(e.guid).body	#gets body of email
			if data is not None:					#Checks if email body is empty
				for dline in data.splitlines():		#Splits body into lines
					if findLine in dline:			#Checks if Query: line exists
						if dline[len(findLine):].strip() == randName:	#Checks if query is same as inputed seq name
							message = html.unescape(data)	#Sets message variable to email contents
							email_id = True			
	return email_id, message
'''

#Auto canceling versions
#Takes url to check, optional message for printing, and optional sleep time and cancel time in seconds. Defaults to 20 sec sleep time, 15 min wait to cancel
#Returns the url when successful
#Returns the url when successful
def requestWait(requesturl, message = None, sleepTime = 20 , cancelAfter = 1500):
	stime  = time.time()
	
	while not requests.get(requesturl).ok and time.time() < stime + cancelAfter: #loops until requesturl is found or cancelAfter min elapse
		print(message)
		time.sleep(sleepTime)
	return requests.get(requesturl)
	
#Takes a guerillamail session, search query, identifier line (Name: or Query:), and input name. Optional print message, time to wait between checks, and how long to wait until cancelling (both in seconds)
#Returns the bool email id and message when successful
def emailRequestWait(session, query, findLine, randName, printmsg = '', sleepTime = 15, cancelAfter = 1500):
	message  = ''
	stime = time.time()
	email_id = False
	
	while message == '' and time.time() < stime + cancelAfter: #loops until desired email is found or cancelAfter min elapse
		print(printmsg)
		time.sleep(sleepTime)
		try:
			print(session.get_email_list())
			for e in session.get_email_list():			#For each email in inbox
				data = session.get_email(e.guid).body	#gets body of email
				if data is not None:					#Checks if email body is empty
					for dline in data.splitlines():		#Splits body into lines
						if findLine in dline:			#Checks if Query: line exists
							if dline[len(findLine):].strip() == randName:	#Checks if query is same as inputed seq name
								message = html.unescape(data)	#Sets message variable to email contents
								email_id = True
		except:
			None
	return email_id, message
import time
import math
import requests
from bs4 import BeautifulSoup
#Contains functions related to output that are meant to be applied to multiple scripts

#Creates a random string to use for a prediction name. Based off current time.
def randBase62():
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
	if len(ssObject) >= 2: #vote only if more than 2 ssObjects exist (at least 2 predictions)
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
	url = 'https://www.rcsb.org/pdb/explore/sequenceText.do?structureId=' + pdbid + '&chainId=' + chain

	r = requests.get(url)

	soup = BeautifulSoup(r.text, 'html.parser')

	cells = soup.findAll("td", {"class": "reportsequence"}) #get all rows with class name reportsequence

	if cells == []:
		#For invalid input
		return None

	sequence = ''
	color = []
	secondary = ''

	count = -4
	for cell in cells:
		if cell.has_attr('title'): # sequence rows have a title attribute
			letters = cell.findChildren("font") 
			#gets all elements with font attribute; these are all the letters in the primary sequence
			for letter in letters:
				#append letters and colors to list
				sequence += letter.text
				color.append(letter.attrs['color'])
		else:
			#every 6th cell after the 4th cell displays secondary structure
			if count %6 == 0:
				secondary+=cell.text
			count += 1


	secondary = secondary.replace('\n','') #remove all newlines
	secondarylist = list(secondary) #convert string to list
	del secondarylist[10::11] #remove every 11th element (spacing dividers)

	#convert list back to string
	secondary = '' 

	for i in secondarylist:
		secondary += i

	result = {
		'title': pdbid + chain,
		'primary': sequence,
		'color': color,
		'secondary': secondary
	}


	return result

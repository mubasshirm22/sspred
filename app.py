import json
import time
import os
from lxml import html
from services import ss, psi, jpred, raptorx, pss, sable, sspro, yaspin, emailtools, htmlmaker, batchtools, maketable
from datetime import datetime

from forms import SubmissionForm
from flask import Flask, render_template, request, current_app,send_file, redirect, url_for
import threading
import secrets

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

#Dictionary containing sites and their classes
siteDict = {
	"JPred": jpred,
	"PSI": psi,
	#"PSS": pss,
	#"RaptorX": raptorx,
	"Sable": sable,
	#"Yaspin": yaspin,
	"SSPro": sspro
}

siteLimit = {
	"JPred": 20,
	"PSI": 20,
	#"PSS": 3,
	#"RaptorX": 20,
	"Sable": 20,
	#"Yaspin": 3,
	"SSPro": 5
}


app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET')
if app.config['SECRET_KEY'] is None:
	app.config['SECRET_KEY'] = secrets.token_urlsafe(16)

#Login to email account to be able to send emails
#email_service = emailtools.login()
#email = emailtools.getEmailAddress(email_service)

#Url of hosted site
siteurl = os.environ.get('SITE_URL')
if siteurl is None :
	siteurl = ""


@app.route('/', methods = ['GET', 'POST'])
def hello(name=None):
	form = SubmissionForm()
	print(threading.activeCount())
	runningCounter = {
		"JPred": 0,
		"PSI": 0,
		#"PSS": 0,
		#"RaptorX": 0,
		"Sable": 0,
		#"Yaspin": 0,
		"SSPro": 0
	}
	for t in threading.enumerate():
		if t.getName() in runningCounter.keys():
			runningCounter[t.getName()] += 1

	if form.validate_on_submit():

		if threading.activeCount() > 100:
			return redirect(url_for('errorpage'))
		post_data = {
			'seqtext': ''.join(form.seqtext.data.split()),
			'email': form.email.data,
			'JPred': form.JPred.data,
			'PSI':   form.PSI.data,
			#'PSS':   form.PSS.data,
			#'RaptorX': form.RaptorX.data,
			'Sable':   form.Sable.data,
			#'Yaspin':   form.Yaspin.data,
			'SSPro':   form.SSPro.data,
			'submitbtn': 'Submit'
			}

		total_sites = validate_sites(post_data)
		post_data.update({'total_sites' : total_sites, 'completed': 0}) # add total into to post_data dictionary and a completed prediction counter
		print(post_data)
		seq = post_data['seqtext']

		startTime = batchtools.randBase62()		

		#if post_data['email'] != "": #send email to let users know input was received
		#	emailtools.sendEmail(email_service, post_data['email'],"Prediction Input Received", "<div>Input received for the following sequence:</div><div>" + seq + "</div><div>Results with customization options will be displayed at the following link as soon as they are available:</div><div>" + siteurl + "/dboutput/" + startTime +"</div>")

		#Stores currently completed predictions
		ssObject = []

		dbinsert(startTime, seq)

		pdbdata = None
		if form.structureId.data is not None:
			pdbdata = batchtools.pdbget(form.structureId.data, form.chainId.data)
			if pdbdata is not None:
				dbupdate(startTime, 'pdb', json.dumps(pdbdata))
				dbupdate(startTime, 'seq', pdbdata['primary'])
				seq = pdbdata['primary']
		
		sendData(seq, startTime, ssObject, post_data, pdbdata)
		return redirect(url_for('showdboutput', var = startTime))
		
	return render_template('index.html', form = form, counter = runningCounter) #default submission page

@app.route('/error/')
def errorpage():
	return('There are too many jobs running, please try again later')


@app.route('/archive/<page>')
def showall(page):
	if page[0] == '0':
		return("Page not found")
	if page.isdigit():
		if int(page) >= 1:
			#'''
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

			return render_template('archives.html', data = jsonresults, pagenum = page)
			'''
			return(page)
			'''
	else:
		return("Page not found")

@app.route('/archive')
def redarchive():
	return redirect(url_for('showall', page = 1))


@app.route('/output/<var>')
def showoutput(var):
	#print("showing output")
	print('output/'+var+'/'+var+'.html')
	try:
		return send_file('output/'+var+'/'+var+'.html')
	except Exception as e:
		return "not found"

@app.route('/dboutput/<var>')
def showdboutput(var):
	outputjson = dbselect(var)
	if outputjson == "[]":
		return "not found"
	try:
		return render_template('dboutput.html', data = outputjson)
	except Exception as e:
		return "not found"

def run(predService, seq, name, ssObject,
 startTime, post_data, pdbdata):

	tcount = 0
	for t in threading.enumerate():
		if t.getName() == name:
			tcount += 1

	if tcount > siteLimit[name]:
		tempSS = ss.SS(name)
		tempSS.pred = "Queue Full"
		tempSS.conf = "Queue Full"
		tempSS.status = -1
	else:
		#tempSS = predService.get(seq, tcount)
		tempSS = predService.get(seq)
	
	dbupdate(startTime, tempSS.name + "pred", tempSS.pred)
	dbupdate(startTime, tempSS.name + "conf", tempSS.conf)
	dbupdate(startTime, tempSS.name + "stat", tempSS.status)

	ssObject.append(tempSS)
	majority = batchtools.majorityVote(seq, ssObject)
	dbupdate(startTime, 'majorityvote', majority)

	post_data['completed'] += 1
	if post_data['completed'] == post_data['total_sites']:
		print("All predictions completed.")
		if post_data['email'] != "": #if all completed and user email is not empty, send email
			print ("Sending results to " + post_data['email'])
			#create HTML and store it in post_data
			post_data.update({'output' : htmlmaker.createHTML(ssObject, seq, pdbdata, majority)})
			emailtools.sendEmail(email_service, post_data['email'],"Prediction Results", post_data['output'])


#Sends sequence based off whatever was selected before submission
def sendData(seq, startTime, ssObject, post_data, pdbdata):
	for key in post_data.keys():
		if key in siteDict:
			if post_data[key]:
				mythread = threading.Thread(target = run, args = (siteDict[key], seq, key, ssObject, startTime, post_data, pdbdata))
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

if __name__ == "__main__":
	#app.run(debug=True) #Run on localhost 127.0.0.1:5000
	app.run(host='0.0.0.0', debug=True) #Run online on public IP:5000
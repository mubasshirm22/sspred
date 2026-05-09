from flask_wtf import FlaskForm
from wtforms import TextAreaField, SubmitField, StringField, BooleanField, validators, ValidationError
from wtforms.widgets import TextArea

import re

class SubmissionForm(FlaskForm):
	
	# Sequence is now optional if a valid structureId+chainId is provided.
	seqtext = TextAreaField('Sequence', [
		validators.Optional(),
		validators.Length(min=40,max=4000, message="Sequence must be between 40 and 4000 characters"),
		validators.Regexp(regex='^[ARNDCEQGHILKMFPSTWYV\s]*$', flags = re.IGNORECASE, message="Invalid Characters")],
		widget=TextArea(), default= "")
	email = StringField('Email (Optional):', [validators.Email(), validators.Optional()])
	
	JPred = BooleanField('JPred', [validators.Optional()],default="checked")
	PSI = BooleanField('PSIPred', [validators.Optional()], default="checked")
	PSS = BooleanField('PSSPred', [validators.Optional()], default="checked")
	RaptorX = BooleanField('RaptorX', [validators.Optional()], default="checked")
	Sable = BooleanField('SABLE', [validators.Optional()], default="checked")
	Yaspin = BooleanField('YASPIN', [validators.Optional()], default="checked")
	SSPro = BooleanField('SSPRO', [validators.Optional()], default="checked")
	PHDpsi = BooleanField('PHDpsi', [validators.Optional()], default=False)
	PROFsec = BooleanField('PROFsec', [validators.Optional()], default=False)
	Predator = BooleanField('Predator', [validators.Optional()], default=False)
	NetSurf  = BooleanField('NetSurf',  [validators.Optional()], default=False)
	
	structureId = StringField('Structure Id:',[ 
		validators.Optional(),
		validators.Length(min=4,max=4, message="StructureID must be 4 characters"),
		validators.Regexp(regex='^[A-Z0-9]*$', flags = re.IGNORECASE, message="Invalid Characters")],
		render_kw={'style':'width:80px'})
	chainId = StringField('Chain Id:',[ 
		validators.Optional(),
		validators.Length(min=1,max=1, message="Chain ID must be single letter"),
		validators.Regexp(regex='^[A-Z]*$', flags = re.IGNORECASE, message="Invalid Characters")],
		 render_kw={'style':'width:50px'})
	
	submitbtn = SubmitField('Submit')
	
	#Override default validate
	def validate(self, extra_validators=None):
		if not FlaskForm.validate(self, extra_validators=extra_validators):
			return False
		
		validated = True
		active_services = (
			self.JPred.data,
			self.PSI.data,
			self.Sable.data,
			self.Yaspin.data,
			self.SSPro.data,
			self.Predator.data,
			self.NetSurf.data,
		)
		
		#Check if at least one site selected
		if not any(active_services):
			self.JPred.errors.append('At least one site must be selected.')
			validated = False

		# Require either a sequence OR a complete structure+chain pair
		seq_filled = bool(self.seqtext.data and self.seqtext.data.strip())
		has_pdb = bool(self.structureId.data and self.chainId.data)
		if not seq_filled and not has_pdb:
			self.seqtext.errors.append('Provide either a sequence or a structure ID and chain.')
			validated = False
		
		#If at least one field is filled, the other must be filled as well
		if (self.structureId.data and not self.chainId.data) or (self.chainId.data and not self.structureId.data):
			self.structureId.errors.append('A chain id must be provided with a structure id.')
			validated = False
		
		return validated

#!/usr/bin/python
###############################################################################
#
#
###############################################################################

import os
import re
import sys
import ssl
import time
import socket
import httplib
import argparse
from datetime import datetime
import xml.etree.ElementTree as ET

def tcp_to_splunk (host,port,data):
	#TODO: Wrap this in a try/except
	s = socket.socket()
	s.connect((host, port))
	s.send(data)
	s.close


class TaniumQuestion:
	
	def __init__(self,host,username,password):
		self.host     = host
		self.username = username
		self.password = password
		self.last_id  = ""
		self.path     = os.path.dirname(os.path.realpath(__file__))
		self.path     = self.path.replace('\\','/')
		
		with open(self.path+'/xml/getresult_template.xml') as x: 
			self.GETRESULT_TEMPLATE = x.read()
			
		with open(self.path+'/xml/submit_template.xml') as x: 
			self.SUBMIT_TEMPLATE = x.read()
			
	def check_xml_error (self,xml_text):
		"""
		NOTE: Do no use this error check on the final results xml.
		The keyword 'ERROR' may be a valid sensor response!
		TODO: Fix the problem in the NOTE!
		"""
		   
		if re.search('ERROR',xml_text)!= None:
			sys.stderr.write("THERE WAS AN ERROR PROCESSING THE XML REQUEST")
			sys.stderr.write(xml_text)
			print "ERROR,ERROR,ERROR"
			print "There was an error processing the xml request," +\
				  "Please run the script on the command line and check" +\
				  str(xml_text).replace(',','_')
			sys.exit(0)
		
	def make_soap_connection (self,soap_message):
		"""
		TODO: wrap this in a try/except
		"""
		
		webservice = httplib.HTTPSConnection(self.host,context = ssl._create_unverified_context())
		webservice.putrequest("POST", "/soap")
		webservice.putheader("Host", self.host)
		webservice.putheader("User-Agent", "Python post")
		webservice.putheader("Content-type", "text/xml; charset=\"UTF-8\"")
		webservice.putheader("Content-length", "%d" % len(soap_message))
		webservice.putheader("SOAPAction", "\"\"")
		webservice.endheaders()
		webservice.send(soap_message)
		
		res = webservice.getresponse()
		#print res.status, res.reason
		data = res.read()
		webservice.close()
		return data

	def xml_from_tanium_to_csv_list (self,xml):
		
		root        = ET.fromstring(xml)
		result_list = []	
		col_head    = ""
		col_line    = ""
		col_list    = ""
		col_val     = ""
		
		#This is result[0] and it has the csv header.
		for col_group in root.findall(".//cs"):
			for col_name in col_group.findall(".//dn"):
				col_head = col_head + "," + col_name.text
			col_head = col_head.lstrip(",")
		
		result_list.append(col_head)
			
		for col_group in root.findall(".//rs"):
			for col_res in col_group.findall(".//r"):
				for col_col in col_res.findall(".//c"):
					for col_val in col_col.findall(".//v"):
						if col_val.text != None:
							col_line = col_line + ";" + col_val.text
						else:
							col_line = col_line + ";" + "no results"
					col_line = col_line.replace(',',';')
					col_line = col_line.lstrip(';')
					result_list.append(col_line)
					col_line = ""
		
		return result_list

	def csv_list_to_syslog_list (self,result_list):
		"""
		TODO: The header is list[0]. Check to make sure the len of list[0]
		is the same as the other lines.
		"""
		
		syslog_list = []
		date_stamp  = datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%S.%fZ')
		syslog_str  = "<134>1 " + date_stamp + " " + self.host + " " +\
					  "Tanium" + " - - " + "["
		list_line  = ""
		list_count = 0
		head       = result_list[0].split(',')
		head_len   = len(head)
		
		for i in range(1,len(result_list)):
			list_line = list_line + "," + head[list_count]+ '=' + result_list[i]
			list_count = list_count + 1
			if list_count == head_len:
				list_line = list_line.lstrip(',')
				list_line = syslog_str + list_line + "]"
				syslog_list.append(list_line)
				list_line = ""
				list_count = 0
		
		return syslog_list
				
	def loop_poll_tanium (self,id_num,timeout=10):
		"""
		This loop poll function will keep reconnecting to the Tanium server, and
		will ask the server if it has finished getting all responses from a 
		running sensor. There are two cases when this function will stop 
		reconnecting to the server. The first end case is when the Tanium server 
		responds that it has finished getting all sensor results, and the second
		end case is after a time-out period. Time-outs are groups of 10 second 
		intervals, between reconnects. For example a time-out of 5 will 
		reconnect to the server 5 times with a 10 second wait between each 
		reconnect, this give a total time of 50 seconds. 
		
		Note xml.etree cant extract the xml in comments, so a regex with a 
		back-reference is used to extract the state totals is used.
		"""
		
		soap_message = self.GETRESULT_TEMPLATE%(self.username,self.password,\
												"GetResultInfo",id_num)
		
		timeout         = int(timeout)
		count           = 0
		flag            = 0
		est_total_regex = '(\<estimated_total\>)(.*?)(\<\/estimated_total\>)'
		mr_passed_regex = '(\<mr_passed\>)(.*?)(\<\/mr_passed\>)'

		while count < timeout and flag == 0:
		
			if count > 0: time.sleep(10)
			
			is_complete_xml = self.make_soap_connection(soap_message)
			self.check_xml_error(is_complete_xml)
			
			est_total = re.search(est_total_regex,is_complete_xml)
			est_total = est_total.group(2)
			
			mr_passed = re.search(mr_passed_regex,is_complete_xml)
			mr_passed = mr_passed.group(2)
			
			if str(est_total)== str(mr_passed):
				flag = 1
				
			count = count + 1
			
		if flag != 0:
			return "Complete"
		else:
			return "Timeout"
		
	def get_xml_results_from_tanium (self,id_num):
		"""
		This function will get the results of sensor question via Tanium id
		number. The exact content of results is encapsulated as xml in a xml
		comment. Since xml.etree can't extract xml comments, regex and 
		back-references are used to extract the needed result content.
		
		TODO: Check regex to make sure that there is a result set!
		"""
		
		soap_message = self.GETRESULT_TEMPLATE%(self.username,self.password,\
											"GetResultData",id_num)
		
		results = self.make_soap_connection (soap_message)
		
		result_regex  = '(\<ResultXML\>)(.*?)(\<\/ResultXML\>)'
		comment_regex = '(\<\!\[CDATA\[)(.*?)(\]\]\>)'
		results       = re.search(result_regex,results,re.DOTALL)
		results       = results.group(2)
		results       = re.search(comment_regex,results,re.DOTALL)
		results       = results.group(2)
		
		return results
		
		
	def send_request_to_tanium (self,sensors):	
		""" 
		This function kicks off a request to a Tanium server. The request is an
		unfiltered call to a particular sensor. Since the sensor request is 
		unfiltered the sensor will run on all hosts that the Tanium server is
		supporting.
		"""	
		
		all_sensors_in_xml = ""
		id_ext_regex = '(\<result_object\>\<question\>\<id\>)(.*?)(\<\/id\>)'
		
		SENSOR_HERE_DOC = """<select>
								<sensor>
									<name>%s</name>
								</sensor>
							</select>"""

	
		
		for sensor in sensors:
			all_sensors_in_xml = all_sensors_in_xml + SENSOR_HERE_DOC%(sensor)
			
		soap_message = self.SUBMIT_TEMPLATE%(self.username,self.password,\
												all_sensors_in_xml)
												
		submitted_xml = self.make_soap_connection (soap_message)
		self.check_xml_error (submitted_xml)
		
		id_num = re.search(id_ext_regex,submitted_xml)
		id_num = id_num.group(2)
		return id_num

		
	def ask_tanium_a_question (self,sensors,timeout):

		self.last_id = self.send_request_to_tanium (sensors)
		status = self.loop_poll_tanium (self.last_id,timeout)
		if status == "Complete":
			return self.get_xml_results_from_tanium (self.last_id)
		else:
			return "Timeout"

#------------------------------MAIN MODULE--------------------------------------
def main ():
	#sys.stderr = open('err.txt', 'w+')
	#Redirect error to out, so we can see any errors
	sys.stderr=sys.stdout
	
	parser = argparse.ArgumentParser(description='Tanium Splunk Run Sensor')
	
	parser.add_argument(
		'--tanium',
		metavar = 'TANIUM',
		required = True,
		help = 'Tanium server')
		
	parser.add_argument(
		'--user',
		metavar = 'USER',
		required = True,
		help = 'user name')
		
	parser.add_argument(
		'--password',
		metavar = 'PASSWORD',
		required = True,
		help = 'user password')
		
	parser.add_argument(
		'--sensors',
		metavar = 'SENSORS',
		required = True,
		help = 'sensor names')
		
	parser.add_argument(
		'--timeout',
		metavar = 'TIMEOUT',
		required = False,
		default = "3",
		help = 'sensor poll timeout')
		
	parser.add_argument(
		'--splunk',
		metavar = 'SPLUNK',
		required = False,
		help = 'Splunk server to TCP to')
		
	parser.add_argument(
		'--splunk_port',
		metavar = 'SPLUNK_PORT',
		required = False,
		default = "9999",
		help = 'Splunk server TCP port')
		
	args = vars(parser.parse_args())
	
	tanium = args['tanium']
	user = args['user']
	password = args['password']
	sensors = args['sensors'].split(',')
	timeout = args['timeout']
	splunk  = args['splunk']
	splunk_port = int(args['splunk_port'])
	
	#end processing args now inst the Tanium class
	my_tanium = TaniumQuestion(tanium,user,password)
	
	#send the question to Tanium
	xml_response = my_tanium.ask_tanium_a_question(sensors,timeout)
	
	#check to make sure the result is good.
	if xml_response == "Timeout":
		print "Alert,Suggestion"
		print "The request timed out, Try setting a higher timeout"
	else:
		#translate the results to a user friendly list.
		list_response = my_tanium.xml_from_tanium_to_csv_list(xml_response)
		
		list_line  = ""
		list_count = 0
		head_len   = len(list_response[0].split(','))
		print list_response[0]
		for i in range(1,len(list_response)):
			list_line = list_line + "," + list_response[i]
			list_count = list_count + 1
			if list_count == head_len:
				print list_line.lstrip(',')
				list_line = ""
				list_count = 0
			
		#if requested send the data to a TCP indexer BROKEN!
		if splunk != None:
			syslog_list = my_tanium.csv_list_to_syslog_list(list_response)
			for element in syslog_list:
				tcp_to_splunk (splunk,splunk_port,element)
			
#----------------------------MAIN ENTRY POINT-----------------------------------

if __name__ == '__main__':
	main()
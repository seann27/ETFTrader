# imports
from datetime import datetime
import time, requests, hmac, hashlib, base64
from requests.exceptions import SSLError, ConnectionError
from OpenSSL import SSL

class KucoinAPI:

	def __init__(self,key=None,secret=None,passphrase=None):
		self.key = key
		self.secret = secret
		self.passphrase = passphrase
		self.url = 'https://api.kucoin.com'

	def add_params(self,uri,params):
		uri += '?'
		for k,v in params.items():
			uri += f"{k}={v}&"
		return uri[:-1]

	def public_get(self,uri,params=None):
		if params != None:
			uri = self.add_params(uri,params)
		conn = False
		while conn == False:
			try:
				response = requests.get(self.url+uri,headers={'User-Agent': 'Mozilla/5.0'})
				if response.status_code == 200 and response.json() != None:
					conn = True
			except (ConnectionError, SSLError, SSL.SysCallError) as e:
				print(e)
				time.sleep(2)
		return response

	def get(self,uri,params=None):
		if self.key == None or self.secret == None or self.passphrase == None:
			return "Error! Please specify user credentials"
		now = int(time.time() * 1000)
		if params != None:
			uri = self.add_params(uri,params)
		url = self.url + uri
		str_to_sign = str(now) + 'GET' + uri
		signature = base64.b64encode(
		hmac.new(self.secret.encode('utf-8'), str_to_sign.encode('utf-8'), hashlib.sha256).digest())
		passphrase = base64.b64encode(hmac.new(self.secret.encode('utf-8'), self.passphrase.encode('utf-8'), hashlib.sha256).digest())
		headers = {
			"KC-API-SIGN": signature,
			"KC-API-TIMESTAMP": str(now),
			"KC-API-KEY": self.key,
			"KC-API-PASSPHRASE": passphrase,
			"KC-API-KEY-VERSION": "2",
			'User-Agent': 'Mozilla/5.0'
		}
		# print(url,headers)
		conn = False
		while conn == False:
			try:
				response = requests.request('get', url, headers=headers)
				conn = True
			except (ConnectionError, SSLError) as e:
				print(e)
				conn = False
				time.sleep(3)
		# print(response)
		# print(response.status_code)
		# print(response.json()['data']['price'])
		return response

	def get_ticker(self,symbol,attempts=0):
		retries = attempts
		params = {
			'symbol':f"{symbol}-USDT"
		}
		response = self.public_get('/api/v1/market/orderbook/level1',params)
		if response.status_code == 200:
			return float(response.json()['data']['price'])
		else:
			# retry
			retries += 1
			if attempts > 100:
				print(f"GT Error {response.status_code}")
				return 0
			else:
				self.get_ticker(self,symbol,attempts=retries)

	def get_ticker_pair(self,symbol,pair,attempts=0):
		params = {
			'symbol':f"{symbol}-{pair}"
		}
		response = self.public_get('/api/v1/market/orderbook/level1',params)
		if response.status_code == 200:
			return float(response.json()['data']['price'])
		else:
			# retry
			attempts += 1
			if attempts > 100:
				print(f"GT Error {response.status_code}")
				return 0
			else:
				self.get_ticker(self,symbol,attempts=attempts)

	def get_all_symbols(self):
		response = self.public_get('/api/v1/symbols')
		return response.json()

	def get_all_tickers(self):
		response = self.public_get('/api/v1/market/allTickers')
		return response.json()

	def get_market_price(self,symbol,mode='buy'):
		sc = 0
		res = None
		attempts = 0

		params = {
			'symbol':f"{symbol}-USDT"
		}

		while sc != 200 or res is None:
			response = self.public_get('/api/v1/market/orderbook/level1',params)
			sc = response.status_code
			if sc == 200:
				if mode == 'buy':
					res = float(response.json()['data']['bestAsk'])
					if res is None:
						print("Nonetype returned for bestAsk")
				if mode == 'sell':
					res = float(response.json()['data']['bestBid'])
					if res is None:
						print("Nonetype returned for bestBid")
			else:
				print(f"Retrying API call for {symbol}")
				print(f"Attempts made: {attempts}")
				print(f"Mode: {mode}")
				print(f"Previous status code: {sc}")
				# retry
				attempts += 1
				if attempts > 100:
					print(f"GT Error {response.status_code}")
					return 0

		return res

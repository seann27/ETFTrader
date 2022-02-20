from pymongo import MongoClient
import certifi
from datetime import datetime
from math import floor
import xml.etree.ElementTree as ET

def parse_creds():
	tree = ET.parse('credentials.xml')
	root = tree.getroot()
	username = root.find('username').text
	password = root.find('password').text
	database = root.find('database').text
	dburi = root.find('dburi').text
	return (username,password,database,dburi)

'''
db.createCollection('appconfig')
db.updateOne({},{$set: {'status':'running'}})
'''

class CryptoDB:

	def __init__(self):
		(username,password,database,dburi) = parse_creds()
		ca = certifi.where()
		client = MongoClient(f"mongodb+srv://{username}:{password}@{dburi}/{database}?retryWrites=true&w=majority",tlsCAFile=ca)
		self.db = client.CryptoTradingDB

	def getAppStatus(self):
		return self.db.appconfig.find_one()['status']

	def configureApp(self,config):
		self.db.appconfig.update_one({},{'$set': config},upsert=True)

	def updateETFMetrics(self,etf,config):
		self.db.etfs.update_one({'asset':etf},{'$set': config})

	def createBot(self,name,capital):
		bot = {
			'botid': name,
			'starting_capital':float(capital),
			'rebalance_capital':float(capital),
			'cash': float(capital),
			'funds_in_trade':0,
			'realized_profit':0,
			'wins':0,
			'losses':0,
			'created_timestamp':datetime.now(),
			'status':'idle',
			'trades':[]
		}
		self.db.bots.insert_one(bot)

	def cloneBot(self,src_botid,clone_botid):
		clone = self.getBot(src_botid)
		del clone['_id']
		clone['botid'] = clone_botid
		clone['created_timestamp'] = datetime.now()
		for trade in clone['trades']:
			trade['tradeid'] = trade['tradeid'].replace(src_botid,clone_botid)
			for txn in trade['txns']:
				txn['txnid'] = txn['txnid'].replace(src_botid,clone_botid)

		self.db.bots.insert_one(clone)

	def getBot(self,botid):
		return self.db.bots.find_one({'botid':botid})

	def updateBot(self,botid,key,value):
		self.db.bots.update_one({'botid':botid},{"$set":{key:value}})

	def createTrade(self,botid,asset,settings):
		bot = self.db.bots.find_one({'botid':botid})
		numtrades = len(bot['trades'])
		capital = bot['cash']
		tradeid = f"{botid}-{numtrades+1}"
		trade = {
			'tradeid':tradeid,
			'created_time':datetime.now(),
			'last_updated':datetime.now(),
			'asset':asset,
			'asset_amount':0,
			'last_price':0,
			'last_bid':0,
			'value':0,
			'profit':'',
			'total_value':0,
			'total_profit':0,
			'status':'pending',
			'starting_capital':capital,
			'cash':capital,
			'single_trade':float("{:.4f}".format(capital/20)),
			'buy_limits':[],
			'sell_limit':float('inf'),
			'stoploss':0,
			'avgprice':0,
			'txns':[],
			"settings":settings
		}
		self.db.bots.update_one({'botid':botid},{'$push':{'trades':trade}})
		self.updateBot(botid,'funds_in_trade',capital)
		self.updateBot(botid,'cash',0)
		return tradeid

	def updateTrade(self,tradeid,key,value):
		self.db.bots.update_one({'trades.tradeid':tradeid},{"$set":{f"trades.$.{key}":value}})

	def getTrade(self,tradeid):
		trade = self.db.bots.find_one({"trades.tradeid":tradeid},{"trades":{"$elemMatch":{"tradeid":tradeid}}})
		return trade['trades'][0]

	def getLastPrice(self,tradeid):
		trade = self.getTrade(tradeid)
		return float(trade['last_price'])

	def getTradeStatus(self,tradeid):
		trade = self.getTrade(tradeid)
		return trade['status']

	def setBotStatus(self,botid):
		botstatus = self.db.appconfig.find_one()['botStatus']
		self.updateBot(botid,"status",botstatus)

	def insertTxn(self,tradeid,txn):
		trade = self.getTrade(tradeid)
		txn['txnid'] = tradeid+"-"+str(len(trade['txns'])+1)
		txn['timestamp'] = datetime.now()
		self.db.bots.update_one({'trades.tradeid':tradeid},{'$push':{'trades.$.txns':txn}})

	def get_idle_bot(self):
		bot = db.bots.find_one({"status":"idle"})
		return bot['botid']

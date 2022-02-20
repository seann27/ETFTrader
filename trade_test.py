import asyncio, time, telegram_send, traceback, sys
from kucoin.client import WsToken
from kucoin.ws_client import KucoinWsClient
from MongoDBHandle import CryptoDB
from datetime import datetime
import concurrent.futures
from utilities import try_request
from math import ceil
from UpsideMomemtum import get_kucoin_data

def restart_trade(botid,tradeid):
	print(f"Re-evaluating trade {tradeid}")
	api = CryptoDB()
	trade = api.getTrade(tradeid)
	asset = trade['asset']
	take_profit = trade['settings']['take_profit']
	volatility=trade['settings']['volatility']
	limits=trade['settings']['num_limits']
	apply_fee=trade['settings']['after_fees']
	tradeobj = Trade(botid,asset,take_profit,tradeid,volatility,limits,apply_fee)
	timestamp = ceil(trade['last_updated'].timestamp())

	df = get_kucoin_data(asset,'5min',start=timestamp)

	trade_status = 'open'
	api.updateTrade(tradeid,'status','open')

	def eval_row(price):
		tradeobj.update_prices(bestAsk=price,bestBid=price,sleep=0)
		tradeobj.evalPrice()
		trade_status = api.getTradeStatus(tradeid)
		if trade_status == 'closed':
			return True
		return False

	for idx,row in df.iterrows():
		if eval_row(row['high']):
			break
		if eval_row(row['low']):
			break

	return tradeobj, api.getTradeStatus(tradeid)

class Trade:

	def __init__(self,botid,asset,take_profit,tradeid=None,volatility=0.28,limits=19,apply_fee=0.999):
		self.botid = botid
		self.api = CryptoDB()
		if tradeid == None:
			print(f"Creating trade for {botid}: {asset}")
			settings = {
				"volatility":volatility,
				"num_limits":limits,
				"after_fees":apply_fee,
				"take_profit":take_profit
			}
			self.tradeid = self.api.createTrade(botid,asset,settings)
		else:
			self.tradeid = tradeid
		self.asset = asset
		self.volatility = volatility
		self.limits = limits # including market purchase makes it 20 buys total
		self.take_profit = take_profit
		self.apply_fee = apply_fee

	def enter_trade(self):
		avgprice = self.purchase_etf()
		# set buy and sell limits
		self.setLimits(avgprice)
		self.api.updateTrade(self.tradeid,'status','open')
		self.api.updateBot(self.botid,'status','active')

	def purchase_etf(self):
		trade = self.api.getTrade(self.tradeid)
		total_amt = trade['asset_amount']
		cash = trade['cash']
		liq = trade['single_trade']
		amt = liq*self.apply_fee/trade['last_price']
		txn = {
			'mode':'buy',
			'price':trade['last_price'],
			'amt':amt,
			'cost':liq
		}
		message = "{} purchasing {:.4f} of {} @ {}, cost: ${:.2f}".format(self.botid.upper(),amt,self.asset,trade['last_price'],liq)
		print(message)
		telegram_send.send(messages=[message])
		self.api.insertTxn(self.tradeid,txn)
		self.api.updateTrade(self.tradeid,'asset_amount',amt+total_amt)
		self.api.updateTrade(self.tradeid,'cash',(cash-liq))
		trade = self.api.getTrade(self.tradeid)
		avgprice = (trade['starting_capital']-trade['cash'])/trade['asset_amount']
		self.api.updateTrade(self.tradeid,'avgprice',avgprice)
		self.api.updateTrade(self.tradeid,'sell_limit',avgprice*self.take_profit)
		return avgprice

	def exit_trade(self):
		trade = self.api.getTrade(self.tradeid)
		bot = self.api.getBot(self.botid)
		amt = trade['asset_amount']
		sale = amt*self.apply_fee*trade['last_bid']
		cash = trade['cash'] + sale
		profit = cash - trade['starting_capital']
		txn = {
			'mode':'sell',
			'price':trade['last_bid'],
			'amt':amt,
			'cost':sale
		}
		message = "{} selling {:.4f} of {} @ {}, sale: ${:.2f}, profit: ${:.2f}\n".format(self.botid.upper(),amt,self.asset,trade['last_bid'],sale,profit)
		if profit > 0:
			message += "Trade Won!"
		else:
			message += "Trade Lost :("
		print(message)
		telegram_send.send(messages=[message])
		self.api.insertTxn(self.tradeid,txn)

		self.api.updateTrade(self.tradeid,'cash',cash)
		self.api.updateTrade(self.tradeid,'asset_amount',0)
		self.api.updateBot(self.botid,'cash',cash)
		self.api.updateBot(self.botid,'funds_in_trade',0)
		self.api.updateBot(self.botid,'realized_profit',cash-bot['rebalance_capital'])
		if cash > trade['starting_capital']:
			self.api.updateBot(self.botid,'wins',bot['wins']+1)
		elif cash < trade['starting_capital']:
			self.api.updateBot(self.botid,'losses',bot['losses']+1)
		self.api.updateTrade(self.tradeid,'status','closed')
		self.api.updateBot(self.botid,'status','idle')

	def setLimits(self,avgprice):
		limits = []
		increment = 1/self.limits
		for i in range(self.limits):
			limits.append((1 - self.volatility*3*(1-(i*increment)))*avgprice)

		self.api.updateTrade(self.tradeid,'buy_limits',limits)
		self.api.updateTrade(self.tradeid,'stoploss',limits[0] - (avgprice * self.volatility * 3  * increment))
		self.api.updateTrade(self.tradeid,'sell_limit',avgprice*self.take_profit)

	def evalPrice(self):
		# exit trade if price >= sell limit or price < stoploss
		trade = self.api.getTrade(self.tradeid)
		sell_limit = trade['sell_limit']
		stoploss = trade['stoploss']
		if trade['last_bid'] >= sell_limit or trade['last_bid'] < stoploss:
			self.exit_trade()
		elif len(trade['buy_limits']) > 0:
		# purchase etf if price <= limits[-1], remove limit from list
			if trade['last_price'] <= trade['buy_limits'][-1]:
				self.purchase_etf()
				trade['buy_limits'].pop()
				self.api.updateTrade(self.tradeid,'buy_limits',trade['buy_limits'])

	def update_prices(self,bestAsk=None,bestBid=None,sleep=1.25):
		# status = "open"
		# while status == "open":
		if bestAsk == None or bestBid == None:
			url = f"https://api.kucoin.com/api/v1/market/orderbook/level1?symbol={self.asset}"
			response = try_request(url)
			if bestAsk == None:
				bestAsk = float(response.json()['data']['bestAsk'])
			if bestBid == None:
				bestBid = float(response.json()['data']['bestBid'])
		self.api.updateTrade(self.tradeid,'last_price',bestAsk)
		self.api.updateTrade(self.tradeid,'last_bid',bestBid)
		amt = self.api.getTrade(self.tradeid)['asset_amount']
		self.api.updateTrade(self.tradeid,'value',amt*bestBid)
		trade = self.api.getTrade(self.tradeid)
		pctprofit = "0%"
		if (trade['starting_capital']-trade['cash']) != 0:
			pctprofit = "{:.4f}%".format(100*(trade['value']-(trade['starting_capital']-trade['cash']))/(trade['starting_capital']-trade['cash']))
		self.api.updateTrade(self.tradeid,'profit',pctprofit)
		self.api.updateTrade(self.tradeid,'total_value',trade['value']+trade['cash'])
		self.api.updateTrade(self.tradeid,'total_profit',trade['value']+trade['cash']-trade['starting_capital'])
		self.api.updateTrade(self.tradeid,'last_updated',datetime.now())
		if sleep > 0:
			time.sleep(sleep)

	def run(self):
		if self.api == None:
			self.api = CryptoDB()
			# status = trade['status']
		# async def deal_msg(msg):
		# 	try:
		# 		if msg['topic'] == f"/market/ticker:{self.asset}":
		# 			lastprice = float(msg['data']['bestAsk'])
		# 			lastbid = float(msg['data']['bestBid'])
		# 			self.api.updateTrade(self.tradeid,'last_price',lastprice)
		# 			self.api.updateTrade(self.tradeid,'last_bid',lastbid)
		# 			amt = self.api.getTrade(self.tradeid)['asset_amount']
		# 			self.api.updateTrade(self.tradeid,'value',amt*lastbid)
		# 			trade = self.api.getTrade(self.tradeid)
		# 			pctprofit = "0%"
		# 			if (trade['starting_capital']-trade['cash']) != 0:
		# 				pctprofit = "{:.4f}%".format(100*(trade['value']-(trade['starting_capital']-trade['cash']))/(trade['starting_capital']-trade['cash']))
		# 			self.api.updateTrade(self.tradeid,'profit',pctprofit)
		# 			self.api.updateTrade(self.tradeid,'total_value',trade['value']+trade['cash'])
		# 			self.api.updateTrade(self.tradeid,'total_profit',trade['value']+trade['cash']-trade['starting_capital'])
		# 	except:
		# 		traceback.print_exception(*sys.exc_info())
		#
		# 	self.api.updateTrade(self.tradeid,'last_updated',datetime.now())
		# client = WsToken()
		# ws_client = await KucoinWsClient.create(None, client, deal_msg, private=False)
		# await ws_client.subscribe(f'/market/ticker:{self.asset},BTC-USDT,AVAX-USDT,ADA-USDT')
		trade_status = self.api.getTradeStatus(self.tradeid)
		while (trade_status != 'closed' and trade_status != 'paused'):
			self.update_prices()
			# await asyncio.sleep(1)
			trade = self.api.getTrade(self.tradeid)
			if trade_status == 'pending' and trade['asset_amount'] == 0 and trade['last_price'] > 0:
				self.enter_trade()
			else:
				self.evalPrice()
			trade_status = self.api.getTradeStatus(self.tradeid)

def trade_main(botid,asset,take_profit):
	trade = Trade(botid,asset,take_profit)
	# asyncio.run(trade.run())
	# await trade.run()
	trade.run()

if __name__ == "__main__":
	trade_main('botguy','ETH3L-USDT',1.022)
	# trade_main('elliebot','BTC3L-USDT',1.022)

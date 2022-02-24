# imports
from MongoDBHandle import CryptoDB
from ScanETFS import insert_update_etfs, run
from math import floor,ceil
from multiprocessing import Process
from datetime import datetime, timedelta
import telegram_send,time
from trade_test import Trade, restart_trade, trade_main

def check_incomplete_trades(client):
	open_trades = []
	# get list of open trades
	open_bots = client.db.bots.find({"$or":[{"trades.status":"open"},{"trades.status":"paused"}]})
	for o in open_bots:
		for t in o['trades']:
			if (t['status'] == "open" or t['status'] == 'paused') and (o['status'] == 'idle' or o['status'] == 'active'):
				trade, status = restart_trade(o['botid'],t['tradeid'])
				if status == 'open':
					print(f"Interrupted trade found: {t['tradeid']}")
					open_trades.append(trade)

	return open_trades

def notify_trades(client,mode="long"):
	query = client.db.etfs.find({"$and":[{"um_15m":{"$lte":35}}, {"um_4h":{"$lte":10}}]})
	if mode == "short":
		query = client.db.etfs.find({"$and":[{"um_15m":{"$gte":65}}, {"um_4h":{"$gte":90}}]})
	# query = client.db.etfs.find({"$and":[{"um_15m":{"$lte":10}},{"$or":[{"um_4h":{"$lte":10}},{"bitcoin_pair_recc":{"$gt":0}}]},{"um_4h":{"$lt":70}}]})
	# if mode == "short":
	# 	query = client.db.etfs.find({"$and":[{"um_15m":{"$gte":90}},{"$or":[{"um_4h":{"$gte":90}},{"bitcoin_pair_recc":{"$lt":0}}]},{"um_4h":{"$gt":30}}]})
	message = ''
	numresults = 0
	for q in query:
		numresults += 1
		message += "######  {}   ||   {:.4f}%\n".format(q[mode],q['atr_4h_pct']/2)
	if numresults > 0:
		message = f"###### AVAILABLE {mode.upper()}S ######\n\n" + message + "\n###########################\n\n"

	return message

def send_good_trades(client):
	message = notify_trades(client)
	message += notify_trades(client,mode='short')
	if message:
		telegram_send.send(messages=[message])

def generate_asset_lists(client):
	binance = {}
	coinbase = {}
	etfs = client.db.etfs.find({'coinbase':None})
	for e in etfs:
		binance[e['asset']] = e['binance']

	etfs = client.db.etfs.find({'coinbase':{"$ne":None}})
	for e in etfs:
		# if len(binance) < floor(client.db.etfs.count_documents({}) / 2) and e['asset'] != 'XRP':
		# 	binance[e['asset']] = e['binance']
		# else:
		# 	coinbase[e['asset']] = e['coinbase']
		coinbase[e['asset']] = e['coinbase']

	return (coinbase,binance)

def check_processes(processes,client):
	for p in processes:
		if len(processes) > 10:
			print("Error! Process loop detected!")
			client.configureApp({'status':'appClose'})
			return False
		elif p.is_alive():
			return True
	print("All processes closed.")
	return False

if __name__ == "__main__":
	client = CryptoDB()
	# get any open trades and close them
	# set application status
	client.configureApp({'status':'running'})
	app_status = 'running'

	# insert/update list of etfs
	print("Inserting/Updating ETFs")
	insert_update_etfs(client)
	print("Generating asset lists")
	(coinbase,binance) = generate_asset_lists(client)

	processes = []

	print("Creating etf scanning processes")
	processes.append(Process(target=run,args=(coinbase,'coinbase'),daemon=True))
	processes.append(Process(target=run,args=(binance,'binance'),daemon=True))

	print("Searching for interrupted open trades")
	open_trades = check_incomplete_trades(client)
	if len(open_trades) > 0:
		for t in open_trades:
			client.updateBot(t.botid,'status','active')
			t.api = None
			processes.append(Process(target=t.run,daemon=True))

	print("Starting all processes")
	for p in processes:
		p.start()

	runningProcesses = check_processes(processes,client)
	start = datetime.now()
	while app_status != 'appClose':
		while runningProcesses:
			not_ready = client.db.etfs.find_one({"scanStatus":"reset"})
			if not_ready == None and app_status != "appClose":
				# get available bots
				available_bots = []
				search = client.db.bots.find({'status':'idle'})
				for bot in search:
					# if bot['botid'] not in available_bots:
					# 	available_bots.append(bot['botid'])
					available_bots.append(bot['botid'])

				# if rebalancing is turned on
				if client.db.appconfig.find_one()['rebalance']:
					available_funds = 0
					rebalance_capital = 0
					for a in available_bots:
						ab = client.getBot(a)
						available_funds += ab['cash']
						rebalance_capital += ab['starting_capital']
					for a in available_bots:
						client.updateBot(a,'cash',available_funds/len(available_bots))
						client.updateBot(a,'rebalance_capital',rebalance_capital/len(available_bots))

				# get current trade assets
				unavailable_trades = []
				search = client.db.bots.find({"$or":[{'trades.status':'open'},{'trades.status':'pending'}]})
				for bot in search:
					for t in bot['trades']:
						if t['status'] == 'open' or t['status'] == 'pending':
							unavailable_trades.append(t['asset'])

				# query trades
				if len(available_bots) > 0:
					# query_longs = client.db.etfs.find({"$and":[{"um_15m":{"$lte":10}},{"$or":[{"um_4h":{"$lte":10}},{"bitcoin_pair_recc":{"$gt":0}}]},{"um_4h":{"$lt":70}}]})
					query_longs = client.db.etfs.find({"$and":[{"$or":[{"$and":[{"um_15m":{"$lt":50}}, {"um_4h":{"$lte":10}}]},{"$and":[{"um_15m":{"$lte":10}},{"bitcoin_pair_recc":{"$gt":0}}]}]},{"um_4h":{"$lt":70}}]})
					for long in query_longs:
						if long['long'] not in unavailable_trades:
							target = 1.022
							if long['um_4h'] <= 10:
								target = (long['atr_4h_pct']/2/100)+1
							print("Trade found. Launching {} on {}, target of {:.2f}% profit".format(long['long'],available_bots[-1],(target-1)*100))
							p = Process(target=trade_main,args=(available_bots[-1],long['long'],target),daemon=True)
							p.start()
							wait = True
							while wait:
								status = client.getBot(available_bots[-1])['status']
								if status == 'active':
									wait = False
							# processes.append(p)
							available_bots.pop()
							unavailable_trades.append(long['long'])
							if len(available_bots) == 0:
								break

				if len(available_bots) > 0:
					# query_shorts = client.db.etfs.find({"$and":[{"um_15m":{"$gte":90}},{"$or":[{"um_4h":{"$gte":90}},{"bitcoin_pair_recc":{"$lt":0}}]},{"um_4h":{"$gt":30}}]})
					query_shorts = client.db.etfs.find({"$and":[{"$or":[{"$and":[{"um_15m":{"$gt":50}}, {"um_4h":{"$gte":90}}]},{"$and":[{"um_15m":{"$gte":90}},{"bitcoin_pair_recc":{"$lt":0}}]}]},{"um_4h":{"$gt":30}}]})
					for short in query_shorts:
						if short['short'] not in unavailable_trades:
							target = 1.022
							if short['um_4h'] >= 90:
								target = (short['atr_4h_pct']/2/100)+1
							print("Trade found. Launching {} on {}, target of {:.2f}% profit".format(short['short'],available_bots[-1],(target-1)*100))
							p = Process(target=trade_main,args=(available_bots[-1],short['short'],target),daemon=True)
							p.start()
							wait = True
							while wait:
								status = client.getBot(available_bots[-1])['status']
								if status == 'active':
									wait = False
							# processes.append(p)
							available_bots.pop()
							unavailable_trades.append(short['short'])
							if len(available_bots) == 0:
								break

				time.sleep(5)

			# every 15 minutes, send telegram message with good trades
			end = datetime.now()
			if (end-start).seconds >= 900:
				send_good_trades(client)
				start = end

			# check application and process status
			runningProcesses = check_processes(processes,client)
			app_status = client.getAppStatus()

	print("Exiting application")

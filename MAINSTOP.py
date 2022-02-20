# imports
from MongoDBHandle import CryptoDB
import argparse, time
from datetime import datetime

def closeTrades(api):
	# api = CryptoDB()
	allbots = api.db.bots.find()
	for bot in allbots:
		api.updateBot(bot['botid'],'status','inactive')
		for trade in bot['trades']:
			if trade['status'] == 'open':
				api.updateTrade(trade['tradeid'],'status','paused')
	time.sleep(1)

def process_commandline():
	parser = argparse.ArgumentParser(description='Check for bot reset')
	parser.add_argument('--reset_bots',action='store_true')
	args = parser.parse_args()
	return args

if __name__ == "__main__":
	args = process_commandline()
	# set application status to shutdown
	api = CryptoDB()
	closeTrades(api)
	api.configureApp({'status':'appClose'})

	if args.reset_bots:
		bots = api.db.bots.find({})
		for bot in bots:
			botid = bot['botid']
			cap = bot['starting_capital']
			api.updateBot(botid,'cash',cap)
			api.updateBot(botid,'funds_in_trade',0)
			api.updateBot(botid,'realized_profit',0)
			api.updateBot(botid,'wins',0)
			api.updateBot(botid,'losses',0)
			api.updateBot(botid,'created_timestamp',datetime.now())
			api.updateBot(botid,'status','idle')
			api.updateBot(botid,'trades',[])

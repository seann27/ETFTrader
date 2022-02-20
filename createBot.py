import argparse
from MongoDBHandle import CryptoDB


'''
Create bot and upload to database

args:
- starting capital
- name

properties:
- id
- cash
- cash_in_trade
- current_profit
- wins
- losses
- created_timestamp
- trades
- txns
- status
	- in_trade
	- idle
	- inactive
'''
def process_commandline():
	parser = argparse.ArgumentParser(description='Create new bot and insert to mongodb')
	parser.add_argument('--name',default='bot1',help='')
	parser.add_argument('--capital',default=200)
	args = parser.parse_args()
	return (args.name,args.capital)

if __name__ == '__main__':
	(name,capital) = process_commandline()
	client = CryptoDB()
	client.createBot(name,capital)

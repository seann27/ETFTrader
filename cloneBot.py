import argparse
from MongoDBHandle import CryptoDB


'''
Clone bot and upload to database

args:
- botid of bot to be cloned
- name of cloned bot

'''
def process_commandline():
	parser = argparse.ArgumentParser(description='Clone new bot and insert to mongodb')
	parser.add_argument('--old_bot')
	parser.add_argument('--new_bot')
	parser.add_argument('--set_idle',action='store_true')
	args = parser.parse_args()
	return (args.old_bot,args.new_bot,args.set_idle)

if __name__ == '__main__':
	(old,new,idle) = process_commandline()
	client = CryptoDB()
	client.cloneBot(old,new)
	if idle:
		client.updateBot(new,'status','idle')

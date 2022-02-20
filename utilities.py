import time, requests
import pandas as pd

def try_request(url):
	status = 0
	attempts = 0
	while status != 200:
		try:
			response = requests.get(url,headers={'User-Agent': 'Mozilla/5.0'})
			status = response.status_code
			attempts += 1
			if attempts % 10 == 0:
				if status != 200:
					print(f"Error {response.status_code}! {url}")
				time.sleep(5)
		except Exception as e:
			print(e)
		if attempts > 200:
			print(f"Error getting response from {url}")
			exit()
	return response

def init_df(suffix=''):
	cols = ['timestamp','date',f'open{suffix}',f'high{suffix}',f'low{suffix}',f'close{suffix}',f'volume{suffix}']
	return pd.DataFrame(columns=cols)

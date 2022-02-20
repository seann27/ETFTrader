import sys, os, re, time
import pandas as pd
import pandas_ta as ta
from kucoinapi import KucoinAPI
from utilities import try_request
from datetime import datetime
from tradingview_ta import TA_Handler, Interval, Exchange
from UpsideMomemtum import get_upside_momemtum, backfill_data, get_coinbase_data, get_binance_data
from MongoDBHandle import CryptoDB

def get_etfs():
	# get kucoin tickers
	tickers = KucoinAPI().get_all_tickers()

	# generate reference
	kucoin_asset_reference = []
	for t in tickers['data']['ticker']:
		if re.search('-USDT',t['symbol']) and t['symbol'] != 'XRP-USDT':
			kucoin_asset_reference.append(t['symbol'])

	# parse out etfs
	etf_assets = {}
	for t in tickers['data']['ticker']:
		etf_search = re.search("(\w+)(3[L|S])-USDT",t['symbol'])
		if etf_search:
			name = etf_search.group(1)
			pos = etf_search.group(2)
			if f"{name}-USDT" in kucoin_asset_reference:
				if name not in etf_assets.keys():
					etf_assets[name] = {
						'kucoin':f"{name}-USDT",
						'long':None,
						'short':None,
						'coinbase':None,
						'binance':None
					}

				if pos == "3L":
					etf_assets[name]['long'] = f"{name}3L-USDT"
				elif pos == "3S":
					etf_assets[name]['short'] = f"{name}3S-USDT"

	# crossreference coinbase assets
	response = try_request("https://api.exchange.coinbase.com/products")
	for asset in response.json():
		if asset['quote_currency'] == 'USD' and asset['base_currency'] in etf_assets.keys():
			etf_assets[asset['base_currency']]['coinbase'] = asset['id']

	# crossreference binance assets
	response = try_request("https://api.binance.us/api/v3/ticker/price")
	for asset in response.json():
		s = re.search("(\w+)USD$",asset['symbol'])
		if s:
			if s.group(1) in etf_assets.keys():
				etf_assets[s.group(1)]['binance'] = asset['symbol']

	# filter out incompatible etfs
	for key in list(etf_assets):
		if etf_assets[key]['coinbase'] == None and etf_assets[key]['binance'] == None:
			del etf_assets[key]

	return etf_assets

def insert_update_etfs(client):
	etfs = get_etfs()

	# insert update the etfs into mongodb
	rows = []
	for k,v in etfs.items():
		v['asset'] = k
		v['um_15m'] = 0
		v['um_4h'] = 0
		v['volatility_28d'] = 0
		v['volatility_4h'] = 0
		v['atr_4h_pct'] = 0
		v['volume_24h'] = 0
		v['recc_buy'] = 0
		v['recc_sell'] = 0
		v['scanStatus'] = 'reset'
		v['lastUpdated'] = None
		rows.append(v)

	db = client.db

	for r in rows:
		db.etfs.update_one({'asset':r['asset']},{"$set":r},upsert=True)

def calculate_upside_momemtum(asset,datasource):
	# calculate upside momemtum on 15m and 4h time frames
	# get 15m candles from either coinbase or binance
	data = []
	interval = "15m"
	suffix_15m = "_15m"
	suffix_4h = "_4h"
	rollnum = 16
	granularity = 900
	if datasource == 'coinbase':
		data = get_coinbase_data(asset,granularity)
	elif datasource == 'binance':
		data = get_binance_data(asset,interval)

	# calculate upside momemtum for both 15m and 4h, return tuple of latest value
	umdf = get_upside_momemtum(data,suffix_15m,return_df=True)
	umdf = backfill_data(umdf,rollnum,suffix_15m,suffix_4h)

	rdf = pd.DataFrame(columns=umdf.columns)

	for i in range(rollnum):
		four_df = umdf.iloc[i::rollnum,:].copy().reset_index()
		umdf_4h = get_upside_momemtum(four_df,suffix=suffix_4h,return_df=True)
		umdf_4h.ta.atr(close="close_4h",high="high_4h",low="low_4h",append=True,length=14)
		umdf_4h['atr_4h_pct'] = umdf_4h['ATRr_14'] / umdf_4h['ohlc4_4h'].rolling(14).mean() * 100 * 3
		umdf_4h.reset_index(inplace=True,drop=True)
		umdf_4h.set_index('index',inplace=True)
		rdf = pd.concat([rdf,umdf_4h])

	rdf = rdf.reset_index()
	rdf = rdf.set_index('index').sort_index()

	upside_momemtum_15m = rdf.iloc[-1]['upside_momemtum_15m']
	last_4h_idx = umdf[umdf['high_4h'].isna()].iloc[0].name - 1
	upside_momemtum_4h = rdf.iloc[last_4h_idx]['upside_momemtum_4h']
	standard_4h_volatility = rdf.iloc[last_4h_idx]['ATRr_14']
	atr_4h_pct = rdf.iloc[last_4h_idx]['atr_4h_pct']

	rdf['volume_24h'] = rdf.iloc[::-1].rolling(96)['volume_15m'].sum()
	lastidx = rdf[rdf['volume_24h'].isna()].iloc[0].name - 1
	volume_24h = rdf.iloc[lastidx]['volume_24h']
	return (upside_momemtum_15m,upside_momemtum_4h,volume_24h,standard_4h_volatility,atr_4h_pct)

def calculate_28d_volatility(asset,datasource):
	# calculate 28d volatility
	# get 28 daily candles, calculate ATR using a length of 28
	data = []
	length = 28
	if datasource == 'coinbase':
		data = get_coinbase_data(asset,86400)
	elif datasource == 'binance':
		data = get_binance_data(asset,'1d')
	if len(data) < length:
		length = len(data)
	data.ta.atr(close="close_1d",high="high_1d",low="low_1d",append=True,length=length)
	return data.iloc[-1][f'ATRr_{length}']

def get_recommendation(asset,datasource):
	# get current trend (buy/sell, longs/shorts)
	buy = 0
	sell = 0
	retry = True
	attempts = 0
	xc = "BinanceUS"
	if datasource == "coinbase":
		xc = "Coinbase"
	for i in ["1d","4h"]:
		try:
			handler = TA_Handler(
				symbol=f"{asset}USD",
				exchange=xc,
				screener="crypto",
				interval=i,
				timeout=None
			)
			while retry and attempts < 200:
				try:
					analysis = handler.get_analysis().summary
					retry = False
				except Exception as e:
					print(f"{asset},{i},{xc} - Error while getting tradingview data!")
					attempts += 1
					# print("TA Connection error, retrying...")
			buy += analysis['BUY']
			sell += analysis['SELL']
		except TypeError:
			continue
		# time.sleep()
	# if buy > sell:
	# 	return 1
	# elif buy < sell:
	# 	return -1
	# else:
	# 	return 0
	return (buy,sell)
	# potential "bull "score" metric:
		# tradingview recommendation for both asset and bitcoin
		# ta recommendation on bitfinex shorts + longs for both asset and bitcoin
		# inverse 4h upside momemtum for both asset and bitcoin

def get_btcpair_recc(client,asset):
	asset_etf = client.db.etfs.find_one({'asset':asset})
	asset_buy = asset_etf['recc_buy']
	asset_sell = asset_etf['recc_sell']
	btc_etf = client.db.etfs.find_one({'asset':'BTC'})
	btc_buy = btc_etf['recc_buy']
	btc_sell = btc_etf['recc_sell']
	return (asset_buy + btc_buy - asset_sell - btc_sell)

def update_metrics(client,asset,assetpair,datasource):
	# print(f"{assetpair} - Calculating upside momemtum")
	(um15,um4,vol24h,atr_4h,atr_4h_pct) = calculate_upside_momemtum(assetpair,datasource)
	tostring = "\n----------------------------------------------------\n"
	tostring += f"{assetpair} - um15: {um15}\n"
	tostring += f"{assetpair} - um4: {um4}\n"
	tostring += f"{assetpair} - vol24h: {vol24h}\n"
	# print(f"{assetpair} - Calculating volatility")
	v28d = calculate_28d_volatility(assetpair,datasource)
	tostring += f"{assetpair} - v28d: {v28d}\n"
	# print(f"{asset} - Getting recommendation")
	(recc_buy,recc_sell) = get_recommendation(asset,datasource)
	bitcoin_pair_recc = get_btcpair_recc(client,asset)

	tostring += f"{assetpair} - recc: {recc_buy - recc_sell}"
	tostring += "\n----------------------------------------------------\n"

	# update database metrics for asset
	client.updateETFMetrics(asset,{
		'um_15m':um15,
		'um_4h':um4,
		'volume_24h':vol24h,
		'volatility_28d':v28d,
		'volatility_4h':atr_4h,
		'atr_4h_pct':atr_4h_pct,
		'recc_buy':recc_buy,
		'recc_sell':recc_sell,
		'bitcoin_pair_recc':bitcoin_pair_recc,
		'datasource':datasource,
		'scanStatus':'updated',
		'lastUpdated':datetime.now()
	})

	# print(tostring)

def run(assets,datasource,client=None):
	if client == None:
		client = CryptoDB()
	app_status = client.getAppStatus()
	while app_status == "running":
		update_metrics(client,'BTC','BTC-USD','coinbase')
		for a,n in assets.items():
			if a != 'BTC':
				update_metrics(client,a,n,datasource)
				time.sleep(0.4)
			app_status = client.getAppStatus()
			if app_status != "running":
				break
	print(f"App status changed to: \'{app_status}\', shutting down scanner")

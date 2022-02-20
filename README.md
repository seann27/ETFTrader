# ETFTrader
Project that automates scalp trading of cryptocurrency ETFs on Kucoin (paper trading only)

Required Packages:

multiprocessing
telegram_send
requests
pandas
numpy
certifi
pymongo

Once all packages have been installed:
1) set up a mongo database and enter the credentials in the credentials.xml file
2) Build appConfig collection (script currently in development)
3) configure the telegram_send package by following the instructions in this article:
  https://medium.com/@robertbracco1/how-to-write-a-telegram-bot-to-send-messages-with-python-bcdf45d0a580
4) Create bots (name and capital)
  $ python3 createBot.py --name hello_world_bot --capital 500
5) Run program
  $ python MAINSTART.py
  
To terminate the program:

$ python MAINSTOP.py

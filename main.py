import logging

logging.basicConfig(level=logging.INFO)

import os
from dotenv import load_dotenv
load_dotenv()

import bot

bot.app.run(token=os.getenv("DISCORD_BOT_TOKEN"))

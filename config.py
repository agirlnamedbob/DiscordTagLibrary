import os
from dotenv import load_dotenv

load_dotenv()

DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
DATABASE_URL = os.getenv("DATABASE_URL")
COMMAND_PREFIX = "/"

if not DISCORD_TOKEN:
    raise ValueError("DISCORD_TOKEN not found in environment variables")
if not DATABASE_URL:
    raise ValueError("DATABASE_URL not found in environment variables")

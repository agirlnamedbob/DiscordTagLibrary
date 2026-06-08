import discord
from discord.ext import commands
import os
from dotenv import load_dotenv
from utils.database import db
import asyncio
from aiohttp import web

load_dotenv()

# ==========================================
# DUMMY WEB SERVER FOR RENDER HEALTH CHECKS
# ==========================================
async def handle_health_check(request):
    """Responds to Render's pings to prove the app is awake"""
    return web.Response(text="Bot is alive and running!")

async def start_web_server():
    """Starts a non-blocking web server on Render's designated port"""
    app = web.Application()
    app.router.add_get("/", handle_health_check)
    runner = web.AppRunner(app)
    await runner.setup()

    port = int(os.getenv("PORT", 10000))
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    print(f"✅ Render health-check server listening on port {port}")

intents = discord.Intents.default()
intents.message_content = True

bot = commands.Bot(command_prefix="/", intents=intents, help_command=None)

@bot.event
async def on_ready():
    print(f"✅ Bot {bot.user} is online!")
    try:
        synced = await bot.tree.sync()
        print(f"✅ Synced {len(synced)} command(s)")
    except Exception as e:
        print(f"❌ Error syncing commands: {e}")

async def load_cogs():
    """Load all cog files"""
    for filename in os.listdir("./cogs"):
        if filename.endswith(".py"):
            await bot.load_extension(f"cogs.{filename[:-3]}")
            print(f"✅ Loaded {filename}")

async def main():
    """Start web server, bot, and connect to database"""
    async with bot:
        await start_web_server()
        await db.connect()
        await load_cogs()
        await bot.start(os.getenv("DISCORD_TOKEN"))

if __name__ == "__main__":
    asyncio.run(main())

import os
import datetime
import aiohttp
import asyncio
import discord
from discord.ext import commands

DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
ROBLOX_GROUP = os.getenv("ROBLOX_GROUP")

intents = discord.Intents.default()
intents.message_content = True
intents.members = True

bot = commands.Bot(command_prefix='=', intents=intents)
def get_msg_info(message):
    server = message.guild
    channel = message.channel
    user = message.author

    return (
        server.name, server.owner, channel.name,
        channel.topic if channel.topic else "None",
        datetime.datetime.now(), user.name,
        user.status if user.status else "offline",
        [role.name for role in user.roles],
        user.activities if user.activities else [], user.id
    )

@bot.event
async def on_ready():
    print(f'Logged in as {bot.user}')

@bot.command()
async def ping(ctx):
    await ctx.send('Pong!')

if __name__ == "__main__":
    if DISCORD_TOKEN:
        bot.run(DISCORD_TOKEN)
    else:
        print("Fatal error: DISCORD_TOKEN environment variable is not configured.")
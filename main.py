import os
import datetime
import requests
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

async def fetch_roblox_items():
    url = f"https://catalog.roblox.com/v2/search/items/details?SortType=3&CreatorType=2&CreatorTargetId={ROBLOX_GROUP}&limit=10&sortOrder=Desc"
    headers = {"accept": "application/json"}

    response = await asyncio.to_thread(requests.get, url, headers=headers)
    response.raise_for_status()
    return response.json()


def format_item_message(item):
    name = item.get("name", "Unnamed item")
    description = item.get("description", "No description provided.")
    description = " ".join(description.split())
    if len(description) > 500:
        description = description[:497] + "..."
    return f"**{name}**\n{description}"

@bot.event
async def on_ready():
    print(f'Logged in as {bot.user}')

@bot.command()
async def ping(ctx):
    await ctx.send('Pong!')

@bot.command()
async def roblox(ctx):
    try:
        items = await fetch_roblox_items()
        data = items.get("data", [])

        if not data:
            await ctx.send("No Roblox items found.")
            return

        for item in data:
            await ctx.send(format_item_message(item))
    except Exception as e:
        await ctx.send(f"Failed to fetch Roblox items: {e}")

if __name__ == "__main__":
    if DISCORD_TOKEN:
        bot.run(DISCORD_TOKEN)
    else:
        print("Fatal error: DISCORD_TOKEN environment variable is not configured.")
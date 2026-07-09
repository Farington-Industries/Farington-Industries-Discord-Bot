import os
import json
import datetime
import random
import requests
import asyncio
import time
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
import discord
from discord.ext import commands

DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
ROBLOX_GROUP = os.getenv("ROBLOX_GROUP")
CHANNEL_ID = os.getenv("CHANNEL_ID")
SEEN_UGC_FILE = os.path.join(os.path.dirname(__file__), "seen_ugc_names.json")
NEW_UGC_MSGS_FILE = os.path.join(os.path.dirname(__file__), "new_ugc_msgs.json")

intents = discord.Intents.default()
intents.message_content = True
intents.members = True

bot = commands.Bot(command_prefix='=', intents=intents)


class WebsiteHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path in ("/", "/health"):
            response = "<html><body><h1>Farington Industries</h1><p>The bot service is running.</p></body></html>".encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(response)))
            self.end_headers()
            self.wfile.write(response)
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, format, *args):
        return


def start_web_server():
    port = int(os.getenv("PORT", "4000"))
    server = HTTPServer(("0.0.0.0", port), WebsiteHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    print(f"Web server started on port {port}")
    return server


def normalize_name(name):
    return str(name).strip().lower()


def load_seen_ugc_names():
    if not os.path.exists(SEEN_UGC_FILE):
        return {}

    try:
        with open(SEEN_UGC_FILE, "r", encoding="utf-8") as file:
            data = json.load(file)
            if isinstance(data, list):
                return {
                    normalize_name(name): str(name).strip()
                    for name in data
                    if str(name).strip()
                }
    except (json.JSONDecodeError, OSError):
        return {}

    return {}


def save_seen_ugc_names(seen_names):
    with open(SEEN_UGC_FILE, "w", encoding="utf-8") as file:
        json.dump(list(seen_names.values()), file, indent=2)


def get_random_ugc_message(file_path=NEW_UGC_MSGS_FILE):
    if not os.path.exists(file_path):
        return None

    try:
        with open(file_path, "r", encoding="utf-8") as file:
            messages = json.load(file)
    except (json.JSONDecodeError, OSError):
        return None

    if isinstance(messages, list) and messages:
        return random.choice(messages)

    return None


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


async def fetch_roblox_thumbs(assetID):
    url = f"https://thumbnails.roblox.com/v1/assets?assetIds={assetID}&returnPolicy=PlaceHolder&size=700x700&format=Png&isCircular=false"
    headers = {"accept": "application/json"}

    response = await asyncio.to_thread(requests.get, url, headers=headers)
    response.raise_for_status()
    return response.json()


def format_item_description(item):
    description = item.get("description", "No description provided.")
    description = " ".join(description.split())
    if len(description) > 200:
        description = description[:197] + "..."
    return description

## new
async def build_release_embeds(items):
    store_url = "https://www.roblox.com/communities/513244608/Farington-Industries#!/store"
    embed = discord.Embed(
        color=5814783,
        url=store_url,
        title="UGC RELEASES",
        description="New UGC releases from Farington Industries",
    )
    
    img_embeds = []

    for item in items:
        name = item.get("name", "Unnamed item")
        description = format_item_description(item)
        asset_id = item.get("id") or item.get("assetId") or item.get("asset_id")
        image_url = ""

        if asset_id:
            try:
                thumbnail_response = await fetch_roblox_thumbs(asset_id)
                thumb_data = thumbnail_response.get("data", [])
                if thumb_data:
                    image_url = thumb_data[0].get("imageUrl", "")
            except Exception as e:
                print(f"Failed to fetch thumbnail for asset ID {asset_id}: {e}")

        embed.add_field(name=name, value=description, inline=False)
        if image_url and len(items) < 5:
            img = discord.Embed(
                url=store_url,
            ).set_image(url=image_url)
            img_embeds.append(img)

    return [embed] + img_embeds

async def check_ugc():
    try:
        items = await fetch_roblox_items()
        data = items.get("data", [])

        if not data:
            return

        seen_names = load_seen_ugc_names()
        new_items = []
        seen_in_this_run = set()

        for item in data:
            name = item.get("name", "Unnamed item")
            normalized_name = normalize_name(name)
            if normalized_name in seen_names or normalized_name in seen_in_this_run:
                continue

            new_items.append(item)
            seen_in_this_run.add(normalized_name)

        if not new_items:
            return
        
        random_msg = get_random_ugc_message()
        embeds = await build_release_embeds(new_items)

        # Send to configured channel ID instead of using ctx
        try:
            content = f"{random_msg}" if random_msg else ""
            if CHANNEL_ID:
                try:
                    cid = int(CHANNEL_ID)
                    channel = bot.get_channel(cid)
                    if channel is None:
                        channel = await bot.fetch_channel(cid)
                    await channel.send(content, embeds=embeds)
                except Exception as e:
                    print(f"Failed to send to channel {CHANNEL_ID}: {e}")
            else:
                print("CHANNEL_ID not set; skipping send.")
        except Exception as e:
            print(f"Failed to send message: {e}")

        for item in new_items:
            name = item.get("name", "Unnamed item")
            seen_names[normalize_name(name)] = str(name).strip()

        save_seen_ugc_names(seen_names)
    except Exception as e:
        print(f"Failed to fetch Roblox items: {e}")

old_status = ""
BOT_STATUS = os.getenv("BOT_STATUS", "🐾")
async def bot_status_update():
    if DISCORD_TOKEN and bot.is_ready() and BOT_STATUS:
        if BOT_STATUS != old_status:
            await bot.change_presence(
                activity=discord.Game(name=BOT_STATUS),
                status=discord.Status.online,
            )

threading.Timer(1800, lambda: asyncio.run(check_ugc)).start()  # Check every 30 minutes
threading.Timer(60, lambda: asyncio.run(bot_status_update)).start()  # Check every 30 minutes

@bot.event
async def on_ready():
    print(f'Logged in as {bot.user}')
    await bot_status_update()
    await check_ugc()  # Check for UGC releases when the bot starts

@bot.command()
async def ping(ctx):
    await ctx.send('Pong!')

if __name__ == "__main__":
    start_web_server()

    if DISCORD_TOKEN:
        bot.run(DISCORD_TOKEN)
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            print("Bot stopped by user.")
    else:
        print("DISCORD_TOKEN not set; web server is running without the bot.")
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            print("Server stopped by user.")
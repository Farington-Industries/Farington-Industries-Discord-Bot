import os
import json
import random
import requests
import asyncio
import threading
import html
from urllib.parse import parse_qs
from http.server import BaseHTTPRequestHandler, HTTPServer
import discord
from discord.ext import commands, tasks
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
ROBLOX_GROUP = os.getenv("ROBLOX_GROUP")
CHANNEL_ID = os.getenv("CHANNEL_ID")
SEEN_UGC_FILE = os.path.join(os.path.dirname(__file__), "seen_ugc_names.json")
NEW_UGC_MSGS_FILE = os.path.join(os.path.dirname(__file__), "new_ugc_msgs.json")
STATUS_FILE = os.path.join(os.path.dirname(__file__), "bot_status.json")
DEFAULT_BOT_STATUS = os.getenv("BOT_STATUS", "🐾")
STATUS_UPDATE_PASSWORD = os.getenv("STATUS_UPDATE_PASSWORD", "").strip()

# Bot setup
intents = discord.Intents.default()
intents.message_content = True
intents.members = True

bot = commands.Bot(command_prefix='=', intents=intents)


class WebsiteHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        path = self.path.split("?", 1)[0]
        if path in ("/", "/health"):
            current_status = get_current_status()
            current_status_html = html.escape(current_status)
            response_html = f"""
            <html>
              <body>
                <h1>Farington Industries</h1>
                <p>The bot service is running.</p>
                <p><strong>Current status:</strong> {current_status_html}</p>
                <form action="/status" method="post">
                  <label for="status">Status</label><br>
                  <input type="text" id="status" name="status" value="{current_status_html}" maxlength="100" required><br><br>
                  <label for="password">Password</label><br>
                  <input type="password" id="password" name="password" maxlength="100"><br><br>
                  <button type="submit">Update status</button>
                </form>
              </body>
            </html>
            """
            self._send_html(200, response_html)
        else:
            self._send_html(404, "<h1>Not Found</h1>")

    def do_POST(self):
        path = self.path.split("?", 1)[0]
        if path != "/status":
            self._send_html(404, "<h1>Not Found</h1>")
            return

        length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(length).decode("utf-8") if length else ""
        fields = parse_qs(body, keep_blank_values=True)
        status_value = fields.get("status", [""])[0].strip()
        password_value = fields.get("password", [""])[0].strip()

        if not is_status_update_authorized(password_value):
            self._send_html(403, "<h1>Forbidden</h1><p>Incorrect password.</p>")
            return

        if not status_value:
            self._send_html(400, "<h1>Bad Request</h1><p>Status cannot be empty.</p>")
            return

        save_status_value(status_value)
        self._send_html(
            200, f"<h1>Status updated</h1><p>New status: {html.escape(status_value)}</p><a href=\"/\">Back</a>"
        )
    
    def do_HEAD(self):
        path = self.path.split("?", 1)[0]
        if path in ("/", "/health"):
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
        else:
            self.send_response(404)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()

    def _send_html(self, status_code, body_text):
        response = body_text.encode("utf-8")
        self.send_response(status_code)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(response)))
        self.end_headers()
        self.wfile.write(response)

    def log_message(self, format, *args):
        return  # Suppress default server spam in console


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
                return {normalize_name(name): str(name).strip() for name in data if str(name).strip()}
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


def load_status_value(file_path=STATUS_FILE, fallback_status=DEFAULT_BOT_STATUS):
    if not os.path.exists(file_path):
        return fallback_status
    try:
        with open(file_path, "r", encoding="utf-8") as file:
            data = json.load(file)
    except (json.JSONDecodeError, OSError):
        return fallback_status

    if isinstance(data, str):
        return data.strip() or fallback_status

    if isinstance(data, dict):
        status_value = data.get("status")
        if isinstance(status_value, str):
            return status_value.strip() or fallback_status
    return fallback_status


def save_status_value(status_value, file_path=STATUS_FILE):
    normalized_status = str(status_value or "").strip() or DEFAULT_BOT_STATUS
    with open(file_path, "w", encoding="utf-8") as file:
        json.dump(normalized_status, file)
    return normalized_status


def get_current_status():
    return load_status_value()


def is_status_update_authorized(password_value):
    if STATUS_UPDATE_PASSWORD:
        return password_value == STATUS_UPDATE_PASSWORD
    print("Warning: STATUS_UPDATE_PASSWORD environment variable is not set!")
    return False


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
            img = discord.Embed(url=store_url).set_image(url=image_url)
            img_embeds.append(img)

    return [embed] + img_embeds


@tasks.loop(minutes=30)
async def check_ugc_loop():
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

        content = f"{random_msg}" if random_msg else ""
        if CHANNEL_ID:
            try:
                cid = int(CHANNEL_ID)
                channel = bot.get_channel(cid) or await bot.fetch_channel(cid)
                await channel.send(content, embeds=embeds)
            except Exception as e:
                print(f"Failed to send to channel {CHANNEL_ID}: {e}")
        else:
            print("CHANNEL_ID not set; skipping send.")

        for item in new_items:
            name = item.get("name", "Unnamed item")
            seen_names[normalize_name(name)] = str(name).strip()

        save_seen_ugc_names(seen_names)
    except Exception as e:
        print(f"Failed to fetch Roblox items: {e}")


old_status = ""


@tasks.loop(seconds=5)
async def bot_status_loop():
    global old_status
    current_status = get_current_status()
    if DISCORD_TOKEN and bot.is_ready() and current_status:
        if current_status != old_status:
            print(f"Updating bot status to: {current_status}")
            await bot.change_presence(
                activity=discord.Game(name=current_status),
                status=discord.Status.online,
            )
            old_status = current_status


@bot.event
async def on_ready():
    print(f'Logged in as {bot.user}')
    if not bot_status_loop.is_running():
        bot_status_loop.start()
    if not check_ugc_loop.is_running():
        check_ugc_loop.start()


@bot.command()
async def ping(ctx):
    await ctx.send('Pong!')


if __name__ == "__main__":
    start_web_server()

    if DISCORD_TOKEN:
        bot.run(DISCORD_TOKEN)
    else:
        print("DISCORD_TOKEN not set; web server is running solo.")
        import time
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            print("Server stopped by user.")
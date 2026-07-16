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
            
            seen_items_dict = load_seen_ugc_names()
            seen_items_list = list(seen_items_dict.values())
            
            if seen_items_list:
                items_html = "".join(f"<li>{html.escape(item)}</li>" for item in seen_items_list)
                seen_section_html = f"<h3>Logged UGC Items ({len(seen_items_list)}):</h3><ul>{items_html}</ul>"
            else:
                seen_section_html = "<h3>Logged UGC Items:</h3><p>No items seen yet! 🐾</p>"
            
            response_html = f"""
            <html>
              
              <head>
                <title>Kara Control Panel</title>
                
                <style>
                  body {{ font-family: sans-serif; margin: 20px; line-height: 1.5; }}
                  form {{ background: #f4f4f9; padding: 15px; border-radius: 5px; max-width: 400px; }}
                  ul {{ max-height: 200px; overflow-y: auto; background: #fafafa; padding: 15px 30px; border: 1px solid #ddd; border-radius: 5px; }}
                </style>
                
              </head>
              
              <body>
              
                <h1>Farington Industries</h1>
                
                <p>The bot service is running.</p>
                
                <p><strong>Current status:</strong> {current_status_html}</p>
                
                <h3>Update Bot Status</h3>
                <form action="/status" method="post">
                  <label for="status">Status</label><br>
                  <input type="text" id="status" name="status" value="{current_status_html}" maxlength="100" required><br><br>
                  <label for="password">Password</label><br>
                  <input type="password" id="password" name="password" maxlength="100"><br><br>
                  <button type="submit">Update status</button>
                </form>

                <h3>Send Message to Channel</h3>
                <form action="/send_message" method="post">
                  <label for="channel_id">Channel ID</label><br>
                  <input type="text" id="channel_id" name="channel_id" placeholder="e.g., 123456789012345678" required><br><br>
                  <label for="message">Message</label><br>
                  <textarea id="message" name="message" rows="4" style="width: 100%; max-width: 100%; box-sizing: border-box;" placeholder="Type your message here..." required></textarea><br><br>
                  <label for="msg_password">Password</label><br>
                  <input type="password" id="msg_password" name="password" maxlength="100"><br><br>
                  <button type="submit">Send Message</button>
                </form>
                
                <hr>
                {seen_section_html}
                
              </body>
            </html>
            """
            self._send_html(200, response_html)
        else:
            self._send_html(404, "<h1>Not Found</h1>")

    def do_POST(self):
        path = self.path.split("?", 1)[0]
        if path == "/status":
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
        elif path == "/send_message":
            length = int(self.headers.get("Content-Length", "0"))
            body = self.rfile.read(length).decode("utf-8") if length else ""
            fields = parse_qs(body, keep_blank_values=True)
            channel_id_value = fields.get("channel_id", [""])[0].strip()
            message_value = fields.get("message", [""])[0].strip()
            password_value = fields.get("password", [""])[0].strip()

            if not is_status_update_authorized(password_value):
                self._send_html(403, "<h1>Forbidden</h1><p>Incorrect password.</p>")
                return

            if not channel_id_value or not message_value:
                self._send_html(400, "<h1>Bad Request</h1><p>Channel ID and Message cannot be empty.</p>")
                return

            # Try parsing message_value as JSON to see if it's our custom embed format
            embed_data = None
            content_text = message_value
            
            if message_value.startswith("{") and message_value.endswith("}"):
                try:
                    parsed_json = json.loads(message_value)
                    # Support parsing if it contains the "data" wrapper or directly at root
                    payload = parsed_json.get("data", parsed_json) if isinstance(parsed_json, dict) else parsed_json
                    
                    if isinstance(payload, dict) and "embeds" in payload:
                        embed_data = payload.get("embeds", [])
                        content_text = payload.get("content", "")
                except json.JSONDecodeError:
                    pass # Not valid JSON, treat it as a normal plain-text message string!

            # Execute the discord async logic safely from the HTTP thread
            success, err = send_discord_message_sync(channel_id_value, content_text, embed_data)
            
            if success:
                self._send_html(
                    200, f"<h1>Message Sent!</h1><p>Successfully dispatched payload to channel {html.escape(channel_id_value)}.</p><a href=\"/\">Back</a>"
                )
            else:
                self._send_html(
                    500, f"<h1>Internal Server Error</h1><p>Failed to send message: {html.escape(err)}</p><a href=\"/\">Back</a>"
                )
        else:
            self._send_html(404, "<h1>Not Found</h1>")
    
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


async def async_send_message(channel_id_str, text_message, embed_data_list=None):
    """Internal helper targeting Discord event loop from server requests."""
    if not bot.is_ready():
        return False, "Bot is not ready or logged in yet."
    try:
        cid = int(channel_id_str)
        channel = bot.get_channel(cid) or await bot.fetch_channel(cid)
        
        discord_embeds = []
        if embed_data_list:
            for emb in embed_data_list:
                title = emb.get("title")
                description = emb.get("description")
                color = emb.get("color")
                
                # Setup base embed parameters safely
                kwargs = {}
                if title: kwargs["title"] = title
                if description: kwargs["description"] = description
                if isinstance(color, int): kwargs["color"] = color
                
                e = discord.Embed(**kwargs)
                
                # Author sub-object parsing
                author = emb.get("author")
                if isinstance(author, dict) and author.get("name"):
                    e.set_author(
                        name=author.get("name"),
                        icon_url=author.get("icon_url") or None
                    )
                
                # Image sub-object parsing
                image = emb.get("image")
                if isinstance(image, dict) and image.get("url"):
                    e.set_image(url=image.get("url"))
                    
                # Footer sub-object parsing
                footer = emb.get("footer")
                if isinstance(footer, dict) and footer.get("text"):
                    e.set_footer(text=footer.get("text"))
                    
                # Fields array parsing
                fields = emb.get("fields", [])
                for field in fields:
                    if isinstance(field, dict):
                        e.add_field(
                            name=field.get("name", "Field"),
                            value=field.get("value", "Value"),
                            inline=field.get("inline", False)
                        )
                
                discord_embeds.append(e)

        # Build payload conditionally
        send_kwargs = {}
        if text_message:
            send_kwargs["content"] = text_message
        if discord_embeds:
            send_kwargs["embeds"] = discord_embeds

        if not send_kwargs:
            return False, "Cannot send an empty message."

        await channel.send(**send_kwargs)
        return True, None
    except ValueError:
        return False, "Invalid Channel ID format (Must be an integer)."
    except Exception as e:
        return False, str(e)


def send_discord_message_sync(channel_id_str, text_message, embed_data_list=None):
    try:
        future = asyncio.run_coroutine_threadsafe(
            async_send_message(channel_id_str, text_message, embed_data_list), bot.loop
        )
        return future.result()
    except Exception as e:
        return False, str(e)


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

        content = f"<@&1525694598603735142> {random_msg}" if random_msg else ""
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
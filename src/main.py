"""Main entry point"""
import os
import shutil
import signal
import sys
import threading
import asyncio
import json
from pathlib import Path
from flask import Flask, jsonify, send_from_directory
import discord
# fix so it can run both as a pip module and locally
try:
    from .logger import Logger
except ImportError:
    from logger import Logger
logger = Logger(name="betterbio", log_level="INFO").logger

USER_ONLINE_STATUS = None
STATUS_TEXT = None
STATUS_EMOJI = None
AVATAR_URL = None
BANNER_URL = None
PROFILE_COLOR = None
AVATAR_DECORATION = None
JOINDATE_STRING = ""
CONFIG = {}
BOT_CONFIG = {}

SHUTDOWN_EVENT = threading.Event()

def load_config():
    """Load configuration from config.json"""
    global CONFIG
    global BOT_CONFIG
    data_dir = os.path.join(os.path.expanduser("~"), ".betterbio")
    config_path = os.path.join(data_dir, "config.json")

    try:
        with open(config_path, 'r', encoding='utf-8') as f:
            CONFIG = json.load(f)
            logger.debug("Configuration loaded successfully")
    except (FileNotFoundError, json.JSONDecodeError, PermissionError) as e:
        logger.error("Failed to load configuration: %s", e)
        exit(1)
    
    BOT_CONFIG = CONFIG.get("bot", {})

def signal_handler(signum, frame):
    """Handle termination signals"""
    logger.info("Received termination signal. Shutting down...")
    SHUTDOWN_EVENT.set()
    sys.exit(0)

def ensure_files():
    """Ensure necessary files and directories exist"""
    data_dir = os.path.join(os.path.expanduser("~"), ".betterbio")
    os.makedirs(data_dir, exist_ok=True)
    config_path = os.path.join(data_dir, "config.json")
    if not os.path.exists(config_path):
        # copy internal config.json
        src_dir = Path(__file__).parent
        internal_config = src_dir / "config.json"

        if internal_config.exists():
            shutil.copy2(internal_config, config_path)
            logger.info("No config.json found - Created one @ %s/config.json", data_dir)
        else:
            logger.warning("No config.json found")
    new_dir = os.path.join(data_dir, "static")
    if not os.path.exists(new_dir):
        os.makedirs(new_dir, exist_ok=True)
    new_dir = os.path.join(data_dir, "pages")
    if not os.path.exists(new_dir):
        os.makedirs(new_dir, exist_ok=True)

class DiscordBot(discord.Client):
    """Discord online status integration"""
    def __init__(self):
        intents = discord.Intents.default()
        intents.presences = True
        intents.members = True
        super().__init__(intents=intents)
    
    async def update_status(self):
        """Update users status"""
        global USER_ONLINE_STATUS
        global STATUS_TEXT
        global STATUS_EMOJI
        global AVATAR_URL
        global BANNER_URL
        await self.wait_until_ready()
        user_id = CONFIG.get("bot", {}).get("user_id")
        
        if not user_id:
            logger.error("No user_id specified in config for Discord bot.")
            return

        while not SHUTDOWN_EVENT.is_set():
            try:
                await self._update_user_data(user_id)
            except Exception as e:
                logger.error("Error updating status: %s", e)
            
            await asyncio.sleep(30)
    
    async def _update_user_data(self, user_id):
        """Helper method to update user data"""
        global USER_ONLINE_STATUS, AVATAR_URL, BANNER_URL, JOINDATE_STRING
        global PROFILE_COLOR, AVATAR_DECORATION
        
        user = await self.fetch_user(user_id)
        if not user:
            return
                
        # Update avatar and banner URLs
        AVATAR_URL = user.avatar.url if user.avatar else None
        BANNER_URL = user.banner.url if user.banner else None
        JOINDATE_STRING = user.created_at.strftime("%d %B %Y")
        logger.debug("Updated user PFP to %s", AVATAR_URL)
        logger.debug("Updated user banner to %s", BANNER_URL)
        
        if user.accent_color:
            PROFILE_COLOR = str(user.accent_color)
        else:
            PROFILE_COLOR = None

        if user.avatar_decoration:
            AVATAR_DECORATION = user.avatar_decoration.with_size(256).url
        else:
            AVATAR_DECORATION = None

        # Find member in any guild to get status and activities
        member = self._find_member_in_guilds(user_id)
        if not member:
            return
                
        USER_ONLINE_STATUS = str(member.status)
        logger.debug("Updated user status to %s", USER_ONLINE_STATUS)
        
        # Update custom activity
        self._update_custom_activity(member)
    
    def _find_member_in_guilds(self, user_id):
        """Find member in any guild"""
        for guild in self.guilds:
            member = guild.get_member(user_id)
            if member:
                return member
        return None
    
    def _update_custom_activity(self, member):
        """Update custom activity status and emoji"""
        global STATUS_TEXT, STATUS_EMOJI
        
        for act in member.activities:
            if isinstance(act, discord.CustomActivity):
                STATUS_TEXT = str(act.name) if act.name else ""
                logger.debug("Emoji = %s", act.emoji)
                STATUS_EMOJI = self._process_emoji(act.emoji)
                return
        
        # Reset if no custom activity found
        STATUS_TEXT = ""
        STATUS_EMOJI = None
    
    def _process_emoji(self, emoji):
        """Process emoji and return appropriate URL or string"""
        if not emoji:
            return None
            
        if isinstance(emoji, str):
            return emoji
            
        if hasattr(emoji, 'name') and emoji.name:
            # Handle PartialEmoji objects
            if emoji.id is None:
                # Unicode emoji - convert to Twemoji URL
                codepoint = hex(ord(emoji.name))[2:]
                return f"https://twemoji.maxcdn.com/v/latest/72x72/{codepoint}.png"
            else:
                # Custom Discord emoji
                return emoji.url
        
        return str(emoji)
    
    async def on_ready(self):
        logger.info("Discord bot logged in as %s", self.user)
        self.loop.create_task(self.update_status())

def run_bot():
    """Run the Discord bot"""
    global AVATAR_URL, BANNER_URL
    if not BOT_CONFIG.get('enabled', False):
        AVATAR_URL = CONFIG.get("userdata", {}).get("pfp")
        BANNER_URL = CONFIG.get("userdata", {}).get("banner")
        logger.info("Discord bot integration is disabled in config.")
        return
    
    token = BOT_CONFIG.get('token')
    if not token:
        AVATAR_URL = CONFIG.get("userdata", {}).get("pfp")
        BANNER_URL = CONFIG.get("userdata", {}).get("banner")
        logger.error("Discord bot token not found in config.")
        return
    
    bot = DiscordBot()

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    try:
        loop.run_until_complete(bot.start(token))
    except Exception as e:
        AVATAR_URL = CONFIG.get("userdata", {}).get("pfp")
        BANNER_URL = CONFIG.get("userdata", {}).get("banner")
        logger.error("Discord bot encountered an error: %s", e)
    finally:
        loop.close()

def main():
    """flask,,"""
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    ensure_files()
    load_config()

    app = Flask(__name__)

    @app.route('/api/status/online')
    def onlinetype():
        return jsonify(USER_ONLINE_STATUS or "")
    
    @app.route('/api/status/text')
    def statustext():
        return jsonify(STATUS_TEXT or "")
    
    @app.route('/api/status/emoji')
    def statusemoji():
        return jsonify(STATUS_EMOJI or "")
    
    @app.route('/api/profile/theme')
    def profiletheme():
        theme_data = CONFIG.get("theme", {}).copy()
        if PROFILE_COLOR:
            theme_data["profile_color"] = PROFILE_COLOR
        return jsonify(theme_data)
    
    @app.route('/api/profile/info')
    def profileinfo():
        return jsonify(CONFIG.get("userdata", {}))

    @app.route('/api/profile/avatar')
    def profileavatar():
        return jsonify(AVATAR_URL or "")
    
    @app.route('/api/profile/banner')
    def profilebanner():
        return jsonify(BANNER_URL or "")

    @app.route('/api/profile/decoration')
    def profiledecoration():
        if AVATAR_DECORATION:
            return jsonify(AVATAR_DECORATION)
        return jsonify(CONFIG.get("userdata", {}).get("avatar_decoration") or "")
    
    @app.route('/api/profile/joindate')
    def profilejoindate():
        return jsonify(JOINDATE_STRING or "")
    
    @app.route('/')
    def index():
        src_dir = Path(__file__).parent / "html"
        index_path = src_dir / "index.html"
        if index_path.exists():
            return send_from_directory(src_dir, "index.html")
        else:
            return "<h1>BetterBio</h1><p>index.html not found in package</p>", 404

    @app.route('/files/<path:path>')
    def static_files(path):
        file_dir = os.path.join(os.path.expanduser("~"), ".betterbio", "static")
        full_path = os.path.join(file_dir, path)
        logger.debug("Attempting to serve static file: %s", full_path)
        logger.debug("File exists: %s", os.path.exists(full_path))
        return send_from_directory(file_dir, path)
    
    @app.route('/pages')
    def list_pages():
        pages_dir = os.path.join(os.path.expanduser("~"), ".betterbio", "pages")
        try:
            files = os.listdir(pages_dir)
            md_files = [f[:-3] for f in files if f.endswith('.md')]
            return jsonify(md_files)
        except OSError:
            return jsonify([])


    @app.route('/page/<path:path>')
    def serve_pages(path):
        file_dir = os.path.join(os.path.expanduser("~"), ".betterbio", "pages")
        full_path = os.path.join(file_dir, path + ".md")
        logger.debug("Attempting to serve page: %s", full_path)
        logger.debug("Page exists: %s", os.path.exists(full_path))
        try:
            return send_from_directory(file_dir, path + ".md")
        except FileNotFoundError:
            return "Page not found", 404
    
    @app.route('/favicon.ico')
    def favicon():
        user_favicon = os.path.join(os.path.expanduser("~"), ".betterbio", "favicon.ico")
        if os.path.exists(user_favicon):
            return send_from_directory(os.path.dirname(user_favicon), "favicon.ico")

        src_dir = Path(__file__).parent / "html"
        return send_from_directory(src_dir, "favicon.ico")

    bot_thread = threading.Thread(target=run_bot, daemon=True)
    bot_thread.start()

    try:
        app.run(host=CONFIG.get("host", "0.0.0.0"), port=CONFIG.get("port", 8080), static_files=None, debug=False)
    except KeyboardInterrupt:
        logger.info("Shutting down Flask server...")
    finally:
        SHUTDOWN_EVENT.set()

if __name__ == "__main__":
    main()

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
CLIENT_STATUS = {}
STATUS_TEXT = None
STATUS_EMOJI = None
AVATAR_URL = None
BANNER_URL = None
PROFILE_COLOR = None
AVATAR_DECORATION = None
JOINDATE_STRING = ""
DISPLAY_NAME = None
USERNAME = None
PRONOUNS = None
BIO = None
BADGES = []
CLAN_TAG = None
CLAN_BADGE_URL = None
SPOTIFY = None
ACTIVITIES = []
CONFIG = {}
DEFAULT_CONFIG = {}
BOT_CONFIG = {}

SHUTDOWN_EVENT = threading.Event()

BADGE_FLAGS = {
    "staff":                       "Discord Staff",
    "partner":                     "Partnered Server Owner",
    "hypesquad":                   "HypeSquad Events",
    "bug_hunter":                  "Bug Hunter Level 1",
    "hypesquad_bravery":           "HypeSquad Bravery",
    "hypesquad_brilliance":        "HypeSquad Brilliance",
    "hypesquad_balance":           "HypeSquad Balance",
    "early_supporter":             "Early Supporter",
    "bug_hunter_level_2":          "Bug Hunter Level 2",
    "verified_bot_developer":      "Early Verified Bot Developer",
    "discord_certified_moderator": "Certified Moderator",
    "active_developer":            "Active Developer",
}

BADGE_ICON_URLS = {
    "Discord Staff":                "https://cdn.discordapp.com/badge-icons/5e74e9b61934fc1f67c65515d1f7e60d.png",
    "Partnered Server Owner":       "https://cdn.discordapp.com/badge-icons/3f9748e53446a137a052f3454e2de41e.png",
    "HypeSquad Events":             "https://cdn.discordapp.com/badge-icons/bf01d1073931f921909045f3a39fd264.png",
    "Bug Hunter Level 1":           "https://cdn.discordapp.com/badge-icons/2717692c7dca7289b35297368a940dd0.png",
    "HypeSquad Bravery":            "https://cdn.discordapp.com/badge-icons/8a88d63823d8a71cd5e390baa45efa02.png",
    "HypeSquad Brilliance":         "https://cdn.discordapp.com/badge-icons/011940fd013082d85d96680709bab45e.png",
    "HypeSquad Balance":            "https://cdn.discordapp.com/badge-icons/3aa41de486fa12454c3761e8e223442e.png",
    "Early Supporter":              "https://cdn.discordapp.com/badge-icons/7060786766c9c840eb3019e725d2b358.png",
    "Bug Hunter Level 2":           "https://cdn.discordapp.com/badge-icons/848f79194d4be5ff5f81505cbd0ce1e6.png",
    "Early Verified Bot Developer": "https://cdn.discordapp.com/badge-icons/6df5892e0f35b051f8b61eace34f4967.png",
    "Certified Moderator":          "https://cdn.discordapp.com/badge-icons/fee1624003e17900af55537d5e2a52ff.png",
    "Active Developer":             "https://cdn.discordapp.com/badge-icons/6bdc42827a38498929a4920da12695d9.png",
    "Nitro":                        "https://cdn.discordapp.com/badge-icons/2ba85e8026a8614b640c2837bcdfe21b.png",
}


def _get(d, *keys, fallback=None):
    """Safely walk nested dict keys, return fallback if missing or empty string."""
    v = d
    for k in keys:
        if not isinstance(v, dict):
            return fallback
        v = v.get(k)
    if v == "" or v is None:
        return fallback
    return v


def load_config():
    """Load config.json (user settings) and default.json (fallback values)."""
    global CONFIG, DEFAULT_CONFIG, BOT_CONFIG
    data_dir = os.path.join(os.path.expanduser("~"), ".betterbio")
    config_path = os.path.join(data_dir, "config.json")
    default_path = os.path.join(data_dir, "default.json")

    try:
        with open(config_path, 'r', encoding='utf-8') as f:
            CONFIG = json.load(f)
            logger.debug("Configuration loaded successfully")
    except (FileNotFoundError, json.JSONDecodeError, PermissionError) as e:
        logger.error("Failed to load configuration: %s", e)
        exit(1)

    try:
        with open(default_path, 'r', encoding='utf-8') as f:
            DEFAULT_CONFIG = json.load(f)
            logger.debug("Default configuration loaded successfully")
    except (FileNotFoundError, json.JSONDecodeError, PermissionError) as e:
        logger.warning("Could not load default.json: %s", e)
        DEFAULT_CONFIG = {}

    BOT_CONFIG = CONFIG.get("bot", {})


def _effective_userdata():
    """
    Returns the effective userdata dict.

    Priority (highest to lowest) per field:
      1. config.json userdata  (non-empty value = user override, always wins)
      2. bot live data         (stored in module globals, used if bot is enabled)
      3. default.json userdata (fallback when nothing else is set)
    """
    default_ud = DEFAULT_CONFIG.get("userdata", {})
    config_ud  = CONFIG.get("userdata", {})

    def resolve(field, bot_value=None):
        cfg_val = config_ud.get(field)
        if cfg_val not in (None, ""):
            return cfg_val
        if bot_value not in (None, ""):
            return bot_value
        return default_ud.get(field)

    return {
        "name":             resolve("name",     DISPLAY_NAME),
        "username":         resolve("username",  USERNAME),
        "pronouns":         resolve("pronouns",  PRONOUNS),
        "bio":              resolve("bio",        BIO),
        "pfp":              resolve("pfp",        AVATAR_URL),
        "banner":           resolve("banner",     BANNER_URL),
        "avatar_decoration": resolve("avatar_decoration", AVATAR_DECORATION),
        "connections":      config_ud.get("connections") or default_ud.get("connections") or [],
    }


def _effective_theme():
    """
    Returns the effective theme dict.

    Priority per field:
      1. config.json theme     (non-empty wins)
      2. bot live accent color for profile_color only
      3. default.json theme
    """
    default_th = DEFAULT_CONFIG.get("theme", {})
    config_th  = CONFIG.get("theme", {})

    def resolve(field, bot_value=None):
        cfg_val = config_th.get(field)
        if cfg_val not in (None, ""):
            return cfg_val
        if bot_value not in (None, ""):
            return bot_value
        return default_th.get(field)

    return {
        "background_color": resolve("background_color"),
        "profile_color":    resolve("profile_color", PROFILE_COLOR),
        "text_color":       resolve("text_color"),
        "title":            resolve("title"),
    }


def signal_handler(signum, frame):
    logger.info("Received termination signal. Shutting down...")
    SHUTDOWN_EVENT.set()
    sys.exit(0)


def ensure_files():
    data_dir = os.path.join(os.path.expanduser("~"), ".betterbio")
    os.makedirs(data_dir, exist_ok=True)

    for fname in ("config.json", "default.json"):
        dest = os.path.join(data_dir, fname)
        if not os.path.exists(dest):
            src_dir = Path(__file__).parent
            internal = src_dir / fname
            if internal.exists():
                shutil.copy2(internal, dest)
                logger.info("No %s found - Created one @ %s/%s", fname, data_dir, fname)
            else:
                logger.warning("No %s found", fname)

    for subdir in ("static", "pages"):
        d = os.path.join(data_dir, subdir)
        if not os.path.exists(d):
            os.makedirs(d, exist_ok=True)


class DiscordBot(discord.Client):
    """Discord presence/profile integration"""

    def __init__(self):
        intents = discord.Intents.default()
        intents.presences = True
        intents.members = True
        super().__init__(intents=intents)

    async def update_status(self):
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
        global USER_ONLINE_STATUS, CLIENT_STATUS, AVATAR_URL, BANNER_URL
        global JOINDATE_STRING, PROFILE_COLOR, AVATAR_DECORATION
        global DISPLAY_NAME, USERNAME, PRONOUNS, BIO
        global BADGES, CLAN_TAG, CLAN_BADGE_URL

        user = await self.fetch_user(user_id)
        if not user:
            return

        AVATAR_URL = user.avatar.url if user.avatar else None
        BANNER_URL = user.banner.url if user.banner else None
        JOINDATE_STRING = user.created_at.strftime("%d %B %Y")
        DISPLAY_NAME = user.global_name or user.name
        USERNAME = user.name
        PROFILE_COLOR = str(user.accent_color) if user.accent_color else None
        AVATAR_DECORATION = (
            user.avatar_decoration.with_size(256).url
            if user.avatar_decoration else None
        )

        # Badges
        badge_list = []
        if user.public_flags:
            for flag_attr, label in BADGE_FLAGS.items():
                if getattr(user.public_flags, flag_attr, False):
                    badge_list.append(label)
        if user.avatar and user.avatar.is_animated() and "Nitro" not in badge_list:
            badge_list.append("Nitro")
        BADGES = badge_list

        # Clan / primary guild
        if hasattr(user, 'primary_guild') and user.primary_guild:
            pg = user.primary_guild
            CLAN_TAG = getattr(pg, 'tag', None)
            badge_asset = getattr(pg, 'badge', None)
            CLAN_BADGE_URL = badge_asset.url if badge_asset else None
        else:
            CLAN_TAG = None
            CLAN_BADGE_URL = None

        # Member (presence + activities)
        member = self._find_member_in_guilds(user_id)
        if not member:
            return

        USER_ONLINE_STATUS = str(member.status)

        CLIENT_STATUS = {}
        for platform in ("desktop", "mobile", "web"):
            s = str(getattr(member, f"{platform}_status", "offline"))
            if s != "offline":
                CLIENT_STATUS[platform] = s

        # nick and pronouns are not exposed by discord.py from the API,
        # so PRONOUNS and BIO stay None (will fall through to config/default)
        self._update_activities(member)

    def _find_member_in_guilds(self, user_id):
        for guild in self.guilds:
            member = guild.get_member(user_id)
            if member:
                return member
        return None

    def _update_activities(self, member):
        global STATUS_TEXT, STATUS_EMOJI, SPOTIFY, ACTIVITIES
        STATUS_TEXT = ""
        STATUS_EMOJI = None
        SPOTIFY = None
        ACTIVITIES = []

        for act in member.activities:
            if isinstance(act, discord.CustomActivity):
                STATUS_TEXT = str(act.name) if act.name else ""
                STATUS_EMOJI = self._process_emoji(act.emoji)

            elif isinstance(act, discord.Spotify):
                SPOTIFY = {
                    "title":     act.title,
                    "artist":    act.artist,
                    "album":     act.album,
                    "album_art": act.album_cover_url,
                    "track_url": act.track_url,
                    "duration":  int(act.duration.total_seconds()) if act.duration else None,
                    "start":     act.start.isoformat() if act.start else None,
                    "end":       act.end.isoformat() if act.end else None,
                }
                logger.debug("spotify: %s - %s", SPOTIFY["artist"], SPOTIFY["title"])

            else:
                entry = {
                    "type":    act.type.name if hasattr(act, 'type') else "playing",
                    "name":    act.name or "",
                    "details": getattr(act, 'details', None),
                    "state":   getattr(act, 'state', None),
                    "image":   getattr(act, 'large_image_url', None),
                }
                ACTIVITIES.append(entry)
                logger.debug("activity: %s %s", entry["type"], entry["name"])

    def _process_emoji(self, emoji):
        if not emoji:
            return None
        if isinstance(emoji, str):
            return emoji
        if hasattr(emoji, 'name') and emoji.name:
            if emoji.id is None:
                # Build proper multi-codepoint Twemoji path
                codepoint = "-".join(hex(ord(c))[2:] for c in emoji.name)
                return f"https://cdn.jsdelivr.net/gh/twitter/twemoji@14.0.2/assets/72x72/{codepoint}.png"
            return emoji.url
        return str(emoji)

    async def on_ready(self):
        logger.info("Discord bot logged in as %s", self.user)
        self.loop.create_task(self.update_status())


def run_bot():
    if not BOT_CONFIG.get('enabled', False):
        logger.info("Discord bot integration is disabled in config.")
        return
    token = BOT_CONFIG.get('token')
    if not token:
        logger.error("Discord bot token not found in config.")
        return
    bot = DiscordBot()
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        loop.run_until_complete(bot.start(token))
    except Exception as e:
        logger.error("Discord bot encountered an error: %s", e)
    finally:
        loop.close()


def main():
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    ensure_files()
    load_config()

    app = Flask(__name__)

    @app.route('/api/status/online')
    def onlinetype():
        return jsonify(USER_ONLINE_STATUS or "")

    @app.route('/api/status/platforms')
    def statusplatforms():
        return jsonify(CLIENT_STATUS)

    @app.route('/api/status/text')
    def statustext():
        return jsonify(STATUS_TEXT or "")

    @app.route('/api/status/emoji')
    def statusemoji():
        return jsonify(STATUS_EMOJI or "")

    @app.route('/api/profile/theme')
    def profiletheme():
        return jsonify(_effective_theme())

    @app.route('/api/profile/info')
    def profileinfo():
        return jsonify(_effective_userdata())

    @app.route('/api/profile/avatar')
    def profileavatar():
        return jsonify(_effective_userdata().get("pfp") or "")

    @app.route('/api/profile/banner')
    def profilebanner():
        return jsonify(_effective_userdata().get("banner") or "")

    @app.route('/api/profile/decoration')
    def profiledecoration():
        return jsonify(_effective_userdata().get("avatar_decoration") or "")

    @app.route('/api/profile/joindate')
    def profilejoindate():
        return jsonify(JOINDATE_STRING or "")

    @app.route('/api/profile/badges')
    def profilebadges():
        result = [
            {"label": label, "icon_url": BADGE_ICON_URLS.get(label, "")}
            for label in BADGES
        ]
        return jsonify(result)

    @app.route('/api/profile/clan')
    def profileclan():
        return jsonify({"tag": CLAN_TAG, "badge_url": CLAN_BADGE_URL})

    @app.route('/api/activity/spotify')
    def activityspotify():
        return jsonify(SPOTIFY or {})

    @app.route('/api/activity/list')
    def activitylist():
        return jsonify(ACTIVITIES)

    @app.route('/')
    def index():
        src_dir = Path(__file__).parent / "html"
        if (src_dir / "index.html").exists():
            return send_from_directory(src_dir, "index.html")
        return "<h1>BetterBio</h1><p>index.html not found in package</p>", 404

    @app.route('/files/<path:path>')
    def static_files(path):
        file_dir = os.path.join(os.path.expanduser("~"), ".betterbio", "static")
        return send_from_directory(file_dir, path)

    @app.route('/pages')
    def list_pages():
        pages_dir = os.path.join(os.path.expanduser("~"), ".betterbio", "pages")
        try:
            return jsonify([f[:-3] for f in os.listdir(pages_dir) if f.endswith('.md')])
        except OSError:
            return jsonify([])

    @app.route('/page/<path:path>')
    def serve_pages(path):
        file_dir = os.path.join(os.path.expanduser("~"), ".betterbio", "pages")
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
        app.run(
            host=CONFIG.get("host", "0.0.0.0"),
            port=CONFIG.get("port", 8080),
            static_files=None,
            debug=False,
        )
    except KeyboardInterrupt:
        logger.info("Shutting down Flask server...")
    finally:
        SHUTDOWN_EVENT.set()


if __name__ == "__main__":
    main()

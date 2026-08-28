"""
Configuration settings for the CGK Linens Discord Bot.
Created by Aljay Leodones for CGK Linens.
"""

import os
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# Discord Bot Token
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")

# Optional Guild ID for testing/instant slash command updates
GUILD_ID_RAW = os.getenv("GUILD_ID")
GUILD_ID = int(GUILD_ID_RAW) if GUILD_ID_RAW and GUILD_ID_RAW.isdigit() else None

# Brand theme & aesthetics
BRAND_NAME = "CGK Linens"
BRAND_TAGLINE = "Hotel Quality Comfort & Everyday Luxury"
BRAND_COLOR = 0x1B365D  # Elegant Navy Blue
EMBED_FOOTER_TEXT = "CGK Linens Management Bot • Created by Aljay Leodones"

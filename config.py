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

HARDCODED_STYLES = [
    "Glamor", "Simple", "Formal", "Casual", "Cute", "Elegant", "Innocent",
    "Sexy", "Chic", "Romantic", "Rebel", "Fantasy", "Warm", "Cooling",
    "Wild", "Cool"
]

HARDCODED_TAGS = [
    "20s", "50s", "70s", "80s", "Asian", "Astronaut", "Beach", "Bohemian",
    "Bridal", "Business", "Carnival", "Cheerleader", "Country", "Court",
    "Cultural", "Cyberpunk", "Default", "Detective", "Disco", "Elf",
    "Flamenco", "Gothic", "Guofeng", "Hanbok", "Hip-hop", "Kimono", "Knight",
    "Latin American", "Luxury", "Magazine", "Medical", "Mermaid", "Miko",
    "Motorsport", "Nordic", "Outdoor", "Pajamas", "Pirate", "Police",
    "Preppy", "Princess", "Qipao", "Resort", "Rocker", "Sporty", "Steampunk",
    "Swimsuit", "Tarot", "Uniform", "Unisex", "Viking", "Vintage", "Wafuu",
    "Wasteland", "Wedding", "Y2k"
]


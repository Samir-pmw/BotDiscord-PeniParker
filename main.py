import discord
import os
import asyncio
import logging
from discord.ext import commands
from dotenv import load_dotenv

from utils import (
    LOG_FILE_PATH,
    ensure_appdata_dirs,
    APPDATA_BASE,
    get_appdata_locations,
)

load_dotenv()
TOKEN = os.getenv('DISCORD_TOKEN')
OPENAI_TOKEN = os.getenv('OPENAI_TOKEN')
TENOR_TOKEN = os.getenv('TENOR_TOKEN')
GEMINI_TOKEN = os.getenv('GEMINI_TOKEN')
# Carrega as credenciais do Spotify do .env
SPOTIFY_CLIENT_ID = os.getenv('SPOTIFY_CLIENT_ID')
SPOTIFY_CLIENT_SECRET = os.getenv('SPOTIFY_CLIENT_SECRET')

logging.basicConfig(
    filename=str(LOG_FILE_PATH),
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)

dirs = ensure_appdata_dirs()
logging.info("Diretórios de dados inicializados: %s", {name: str(path) for name, path in dirs.items()})
locations = get_appdata_locations()
print(f"AppData do bot configurado em: {APPDATA_BASE}")
if locations["is_virtualized"]:
    print(
        "Aviso: este ambiente está virtualizando o AppData. Dados reais em: "
        f"{locations['resolved']}"
    )
    logging.warning(
        "Ambiente virtualizado detectado. O AppData real fica em %s",
        locations["resolved"],
    )

intents = discord.Intents.default()
intents.message_content = True

class PeniBot(commands.Bot):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.config = {
            'openai_token': OPENAI_TOKEN,
            'tenor_token': TENOR_TOKEN,
            'gemini_token': GEMINI_TOKEN,
            'spotify_id': SPOTIFY_CLIENT_ID,
            'spotify_secret': SPOTIFY_CLIENT_SECRET
        }
        self.synced = False

bot = PeniBot(command_prefix="!", intents=intents)

cogs_list = [
    'cogs.core',
    'cogs.chat',
    'cogs.rpg',
    'cogs.moderation',
    'cogs.fun',
    'cogs.music'
]

async def main():
    async with bot:
        for cog in cogs_list:
            try:
                await bot.load_extension(cog)
                print(f"Cog '{cog}' carregado com sucesso.")
            except Exception as e:
                print(f"Falha ao carregar o cog '{cog}': {e}")
                logging.error(f"Falha ao carregar o cog '{cog}': {e}")
        
        await bot.start(TOKEN)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("Bot desligado.")
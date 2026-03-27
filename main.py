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
    descobrir_modelos_disponiveis,
)

load_dotenv()
TOKEN = os.getenv('DISCORD_TOKEN')
OPENAI_TOKEN = os.getenv('OPENAI_TOKEN')
TENOR_TOKEN = os.getenv('TENOR_TOKEN')
GEMINI_TOKEN = os.getenv('GEMINI_TOKEN')
# Carrega as credenciais do Spotify do .env
SPOTIFY_CLIENT_ID = os.getenv('SPOTIFY_CLIENT_ID')
SPOTIFY_CLIENT_SECRET = os.getenv('SPOTIFY_CLIENT_SECRET')

# Carrega o Opus manualmente se necessário (Windows requer explicitamente, Linux busca no sistema)
if not discord.opus.is_loaded():
    if os.name == 'nt':
        # Tenta em /bins/ e depois na raiz no Windows
        posiveis_paths = [
            os.path.join(os.path.dirname(__file__), 'bins', 'libopus-0.x64.dll'),
            os.path.join(os.path.dirname(__file__), 'libopus-0.x64.dll')
        ]
        
        for path in posiveis_paths:
            if os.path.isfile(path):
                try:
                    discord.opus.load_opus(path)
                    print(f"[INFO] Opus carregado com sucesso de {path}")
                    break
                except Exception as e:
                    print(f"[ERRO] Falha ao carregar Opus de {path}: {e}")
    else:
        # Tenta carregar do sistema no Linux (Docker)
        import ctypes.util
        try:
            lib = ctypes.util.find_library('opus')
            if lib:
                discord.opus.load_opus(lib)
                print(f"[INFO] Opus (sistema) carregado com sucesso via {lib}.")
            else:
                # Se não achar via find_library, tenta os nomes comuns
                for lib_name in ['libopus.so.0', 'libopus.so']:
                    try:
                        discord.opus.load_opus(lib_name)
                        print(f"[INFO] Opus (sistema) carregado com sucesso via {lib_name}.")
                        break
                    except:
                        continue
        except Exception as e:
            print(f"[AVISO] Falha ao disparar carga do Opus: {e}")
            pass

if not discord.opus.is_loaded() and os.name == 'nt':
    print(f"[AVISO] libopus-0.x64.dll não encontrada na raiz ou em /bins/. Música pode não funcionar.")

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

intents = discord.Intents.all()

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


cogs_list = [
    'cogs.core',
    'cogs.chat',
    'cogs.rpg',
    'cogs.moderation',
    'cogs.fun',
    'cogs.music'
]

async def main():
    bot = PeniBot(command_prefix="!", intents=intents)  # ← mova para cá
    async with bot:
        # Descobre modelos Gemini disponíveis na API key antes de iniciar
        if GEMINI_TOKEN:
            descobrir_modelos_disponiveis(GEMINI_TOKEN)

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


"""
  ⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⣤⠀⠀⠀⠀⠀⠀⠀⡄⠀⠀
⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⣤⣿⠛⣿⠀⠀⠀⠀⣤⣿⢻⡇⠀
⠀⠀⠀⠀⠀ ⠀⠀⠀⠀⠀⣤⣿⡛⠀⣤⣿⣿⣤⣤⣿⣿⣤⢸⡇⠀
⠀⠀⠀⠀⠀⠀⠀⠀⣴⣾⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⡇⠀  
⠀⠀⠀⠀⠀⠀⠀⣶⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⡗⠀
⢠⣼⣿⣿⣿⣿⣤⣾⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣷
⢸⣿⣿⡟⠛⠛⢿⣿⣿⣿⣿⣿⣿⣿⣤⣤⣤⣿⣿⣿⣿⣤⣤⣼⣿
⠀⠀⠀⠀⠀⠀⠀⠀⠀⠘⠛⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⡟⠋⠀   

           █▀█ ▄▀█ █▀█ █ █▀█ █▀█    
           █▀▀ █▀█ █▀▀ █ █▀▄ █▄█  
"""

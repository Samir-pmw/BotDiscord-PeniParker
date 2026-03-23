import discord
from discord.ext import commands, tasks
from discord import app_commands
import asyncio
import os
import shutil
import tempfile
import time
from pathlib import Path
from copy import deepcopy
import yt_dlp as youtube_dl
from yt_dlp.utils import PostProcessingError
import spotipy
from spotipy.oauth2 import SpotifyClientCredentials

from utils import MUSIC_CACHE_DIR, registrar_log, send_temp_followup, ensure_appdata_dirs

# --- Configuração do Player ---

ytdl_format_options = {
    'format': 'bestaudio[protocol^=http][ext=m4a]/bestaudio[protocol^=http]/bestaudio',
    'outtmpl': '%(extractor)s-%(id)s-%(title)s.%(ext)s',
    'restrictfilenames': True,
    'noplaylist': False,
    'nocheckcertificate': True,
    'ignoreerrors': False,
    'logtostderr': False,
    'quiet': True,
    'no_warnings': True,
    'default_search': 'auto',
    'source_address': '0.0.0.0',  # bind to ipv4 since ipv6 addresses cause issues sometimes
    'postprocessors': [],
    'retries': 5,
    'fragment_retries': 15,
}

FFMPEG_OPTION_FLAGS = '-vn -af volume=0.7 -loglevel warning'

# Permite reconexão para streams HLS e garante suporte aos protocolos/segmentos exigidos pelo YouTube.
FFMPEG_BASE_BEFORE_OPTIONS = [
    '-nostdin',
    '-reconnect 1',
    '-reconnect_streamed 1',
    '-reconnect_delay_max 5',
    '-reconnect_at_eof 1',
    '-reconnect_on_network_error 1',
    '-reconnect_on_http_error 4xx,5xx',
    '-multiple_requests 1',
    '-protocol_whitelist file,http,https,tcp,tls,crypto',
]

ffmpeg_options = {
    'options': FFMPEG_OPTION_FLAGS,
}


AUDIO_EXTENSIONS = {'.mp3', '.m4a', '.webm', '.opus', '.mp4'}
MUSIC_CACHE_PREFIX = "https://open.spotify.com/playlist/3wpiw1YCHP1O7feGcdogtm?si=bb2ad16c3d504903bot_audio_"
MUSIC_CACHE_MAX_AGE_SECONDS = 60 * 60 * 6  # 6 horas

def _resolve_binary(env_var: str, binary_name: str):
    """Permite definir caminhos explícitos do FFmpeg/ffprobe via variáveis de ambiente."""
    custom_value = os.getenv(env_var)
    if custom_value:
        cleaned_value = custom_value.strip().strip('\'"')
        candidate = Path(cleaned_value).expanduser()
        if candidate.is_dir():
            exe_name = binary_name + ('.exe' if os.name == 'nt' else '')
            candidate = candidate / exe_name
        if candidate.is_file():
            return str(candidate)
        registrar_log(
            f"{env_var} foi definido, mas '{candidate}' não existe ou não é um arquivo executável.",
            'warning'
        )
    return shutil.which(binary_name)


FFMPEG_PATH = _resolve_binary('PENIBOT_FFMPEG', 'ffmpeg')
FFPROBE_PATH = _resolve_binary('PENIBOT_FFPROBE', 'ffprobe')
FFMPEG_AVAILABLE = bool(FFMPEG_PATH and FFPROBE_PATH)
if FFMPEG_AVAILABLE:
    registrar_log(
        f"FFmpeg detectado em '{FFMPEG_PATH}' e ffprobe em '{FFPROBE_PATH}'.",
        'info'
    )
else:
    registrar_log(
        "FFmpeg ou ffprobe não foram encontrados. Configure o PATH ou use PENIBOT_FFMPEG/PENIBOT_FFPROBE.",
        'warning'
    )
FFMPEG_HELP_URL = "https://ffmpeg.org/download.html"

ORIGINAL_YTDL_OPTIONS = deepcopy(ytdl_format_options)
ORIGINAL_YTDL_OPTIONS['postprocessors'] = []
if FFMPEG_AVAILABLE:
    ORIGINAL_YTDL_OPTIONS['ffmpeg_location'] = str(Path(FFMPEG_PATH).parent)
    registrar_log(
        f"ffmpeg detectado em '{FFMPEG_PATH}' e ffprobe em '{FFPROBE_PATH}'. Conversão para mp3 desativada por padrão.",
        'info'
    )
else:
    registrar_log(
        "ffmpeg/ffprobe não encontrados; prosseguindo sem pós-processamento.",
        'warning'
    )

NO_POSTPROCESSING_OPTIONS = deepcopy(ORIGINAL_YTDL_OPTIONS)
NO_POSTPROCESSING_OPTIONS['postprocessors'] = []
NO_POSTPROCESSING_OPTIONS.pop('ffmpeg_location', None)

ORIGINAL_PLAYLIST_OPTIONS = deepcopy(ORIGINAL_YTDL_OPTIONS)
ORIGINAL_PLAYLIST_OPTIONS['noplaylist'] = False

NO_POSTPROCESSING_PLAYLIST_OPTIONS = deepcopy(NO_POSTPROCESSING_OPTIONS)
NO_POSTPROCESSING_PLAYLIST_OPTIONS['noplaylist'] = False

ytdl = youtube_dl.YoutubeDL(deepcopy(ORIGINAL_YTDL_OPTIONS))
ytdl_playlist_options = deepcopy(ORIGINAL_PLAYLIST_OPTIONS)
ytdl_playlist = youtube_dl.YoutubeDL(deepcopy(ORIGINAL_PLAYLIST_OPTIONS))


# --- Classe YTDLSource ---

class YTDLSource(discord.PCMVolumeTransformer):
    ffmpeg_available = FFMPEG_AVAILABLE
    ffmpeg_detection_logged = True
    _postprocessing_disabled = not FFMPEG_AVAILABLE

    def __init__(self, source, *, data, volume=0.5, cleanup_targets=None):
        super().__init__(source, volume)
        self.data = data
        self.title = data.get('title', 'Título não encontrado')
        self.url = data.get('url') # URL do áudio original
        self.webpage_url = data.get('webpage_url', self.url) # URL da página (ex: YouTube)
        self.cleanup_targets = cleanup_targets or []

    @staticmethod
    def _build_ffmpeg_options(data):
        """Gera os parâmetros necessários para o FFmpeg ler manifests HLS protegidos por cabeçalhos."""
        headers = data.get('http_headers', {}) if data else {}
        before_parts = list(FFMPEG_BASE_BEFORE_OPTIONS)

        user_agent = headers.get('User-Agent')
        if user_agent:
            before_parts.insert(1, f'-user_agent "{user_agent}"')

        if headers:
            header_lines = ''.join(f'{key}: {value}\r\n' for key, value in headers.items())
            before_parts.append(f'-headers "{header_lines}"')

        return {
            'before_options': ' '.join(before_parts),
            'options': FFMPEG_OPTION_FLAGS,
        }

    @staticmethod
    def _is_hls_stream(data):
        """Verifica se o resultado aponta para um manifest HLS em vez de stream direto."""
        url = data.get('url', '') if data else ''
        protocol = data.get('protocol', '') if data else ''
        ext = data.get('ext') if data else None
        return any([
            'm3u8' in url,
            'hls' in protocol,
            'm3u8' in protocol,
            ext == 'm3u8'
        ])

    @staticmethod
    def _resolve_file_path(data, default=None):
        requested = data.get('requested_downloads') if data else None
        if requested:
            filepath = requested[0].get('filepath')
            if filepath:
                return filepath
        for key in ('filepath', '_filename'):
            path = data.get(key) if data else None
            if path:
                return path
        return default

    @classmethod
    async def _download_to_file(cls, loop, url):
        """Faz o download via yt-dlp e retorna (dados_extraídos, caminho_arquivo, alvos_para_limpar)."""
        MUSIC_CACHE_DIR.mkdir(parents=True, exist_ok=True)
        temp_dir = tempfile.mkdtemp(prefix=MUSIC_CACHE_PREFIX, dir=str(MUSIC_CACHE_DIR))

        def _download():
            base_options = NO_POSTPROCESSING_OPTIONS if cls._postprocessing_disabled else ORIGINAL_YTDL_OPTIONS

            def build_options(source_options):
                opts = deepcopy(source_options)
                opts.update({
                    'format': 'bestaudio/best',
                    'outtmpl': os.path.join(temp_dir, '%(id)s.%(ext)s'),
                    'noplaylist': True,
                    'overwrites': True,
                })
                return opts

            options = build_options(base_options)

            def _extract(extract_options):
                with youtube_dl.YoutubeDL(extract_options) as fallback_ytdl:
                    return fallback_ytdl.extract_info(url, download=True)

            try:
                info = _extract(options)
            except PostProcessingError as err:
                registrar_log(
                    f"Falha no pós-processamento ({err}); desativando conversão automática.",
                    'warning'
                )
                cls._disable_postprocessing()
                retry_options = build_options(NO_POSTPROCESSING_OPTIONS)
                info = _extract(retry_options)
            except Exception as err:
                if 'postprocessing' in str(err).lower():
                    registrar_log(
                        f"Erro ao pós-processar áudio ({err}); desativando conversão automática.",
                        'warning'
                    )
                    cls._disable_postprocessing()
                    retry_options = build_options(NO_POSTPROCESSING_OPTIONS)
                    info = _extract(retry_options)
                else:
                    raise

            if info is None:
                return None, None, [temp_dir]
            if 'entries' in info:
                info = info['entries'][0]

            filepath = cls._resolve_file_path(info)
            if filepath and not os.path.isabs(filepath):
                filepath = os.path.join(temp_dir, filepath)
            cleanup_targets = [temp_dir]
            if filepath:
                cleanup_targets.append(filepath)
            return info, filepath, cleanup_targets

        info, filepath, cleanup_targets = await loop.run_in_executor(None, _download)

        filepath = cls._normalize_download_filepath(temp_dir, info, filepath, cleanup_targets)

        if info is None or filepath is None:
            try:
                shutil.rmtree(temp_dir, ignore_errors=True)
            except Exception:
                pass

        return info, filepath, cleanup_targets

    @classmethod
    def _disable_postprocessing(cls):
        global ytdl, ytdl_playlist, ytdl_playlist_options

        if cls._postprocessing_disabled:
            return

        cls._postprocessing_disabled = True
        cls.ffmpeg_available = False

        registrar_log(
            "Desativando pós-processamento de áudio; arquivos serão utilizados no formato original.",
            'warning'
        )

        ytdl = youtube_dl.YoutubeDL(deepcopy(NO_POSTPROCESSING_OPTIONS))
        ytdl_playlist_options = deepcopy(NO_POSTPROCESSING_PLAYLIST_OPTIONS)
        ytdl_playlist = youtube_dl.YoutubeDL(deepcopy(NO_POSTPROCESSING_PLAYLIST_OPTIONS))

    @staticmethod
    def _normalize_download_filepath(temp_dir, info, filepath, cleanup_targets):
        path_obj = Path(filepath) if filepath else None

        def _pick_candidate():
            try:
                candidates = []
                for candidate in Path(temp_dir).iterdir():
                    if candidate.is_file() and candidate.suffix.lower() in AUDIO_EXTENSIONS:
                        candidates.append(candidate)
                if not candidates:
                    for candidate in Path(temp_dir).iterdir():
                        if candidate.is_file():
                            candidates.append(candidate)
                if not candidates:
                    return None
                candidates.sort(key=lambda item: item.stat().st_size if item.is_file() else 0, reverse=True)
                return candidates[0]
            except FileNotFoundError:
                return None

        if not path_obj or not path_obj.is_file():
            candidate = _pick_candidate()
            if candidate:
                path_obj = candidate

        if not path_obj or not path_obj.is_file():
            return None

        resolved = path_obj.resolve()
        resolved_str = str(resolved)

        if info is not None:
            info['filepath'] = resolved_str
            info['ext'] = resolved.suffix.lstrip('.') or info.get('ext')
            requested = info.get('requested_downloads')
            if requested:
                requested[0]['filepath'] = resolved_str
                requested[0]['ext'] = resolved.suffix.lstrip('.') or requested[0].get('ext')

        if resolved_str not in cleanup_targets:
            cleanup_targets.append(resolved_str)

        return resolved_str

    @staticmethod
    def _prefer_progressive_audio(data):
        """Tenta selecionar um formato progressivo (HTTP) para evitar downloads completos."""
        if not data:
            return data

        formats = data.get('formats') or []
        candidates = []
        for fmt in formats:
            if fmt.get('vcodec') not in (None, 'none'):
                continue
            if fmt.get('acodec') in (None, 'none'):
                continue
            url = fmt.get('url')
            protocol = fmt.get('protocol', '')
            ext = fmt.get('ext')
            if not url:
                continue
            if 'm3u8' in url or 'm3u8' in protocol:
                continue
            if protocol and not protocol.startswith(('http', 'https')):
                continue
            candidates.append(fmt)

        if not candidates:
            return data

        def sort_key(fmt):
            penalty = 0
            if fmt.get('ext') != 'm4a':
                penalty += 10
            if fmt.get('protocol', '').startswith('http_dash'):
                penalty += 5
            abr = fmt.get('abr') or 0
            filesize = fmt.get('filesize') or 0
            return (penalty, -abr, -filesize)

        best = min(candidates, key=sort_key)

        data['url'] = best.get('url', data.get('url'))
        data['ext'] = best.get('ext', data.get('ext'))
        data['protocol'] = best.get('protocol', data.get('protocol'))
        data['format_id'] = best.get('format_id', data.get('format_id'))

        headers = best.get('http_headers') or {}
        if headers:
            merged_headers = dict(data.get('http_headers', {}))
            merged_headers.update(headers)
            data['http_headers'] = merged_headers

        return data

    @classmethod
    async def from_url(cls, url, *, loop=None, stream=False):
        loop = loop or asyncio.get_event_loop()
        try:
            # Adiciona 'ytsearch:' se a URL não for um link válido, para forçar a busca.
            if not url.startswith(('http://', 'https://')):
                url = f"ytsearch:{url}"

            try:
                data = await loop.run_in_executor(None, lambda: ytdl.extract_info(url, download=not stream))
            except PostProcessingError as err:
                registrar_log(
                    f"Falha no pós-processamento ({err}); repetindo sem conversão.",
                    'warning'
                )
                cls._disable_postprocessing()
                data = await loop.run_in_executor(None, lambda: ytdl.extract_info(url, download=not stream))
            except Exception as err:
                if 'postprocessing' in str(err).lower():
                    registrar_log(
                        f"Erro ao pós-processar ({err}); repetindo sem conversão.",
                        'warning'
                    )
                    cls._disable_postprocessing()
                    data = await loop.run_in_executor(None, lambda: ytdl.extract_info(url, download=not stream))
                else:
                    raise
            if data is None:
                raise ValueError("Não foi possível extrair informações do vídeo.")
            if 'entries' in data:
                data = data['entries'][0]
            if 'webpage_url' not in data:
                data['webpage_url'] = url
            
            data = cls._prefer_progressive_audio(data)

            cleanup_targets = []

            if stream and cls._is_hls_stream(data):
                data, filename, targets = await cls._download_to_file(loop, data.get('webpage_url', url))
                if not data or not filename:
                    raise ValueError('Falha ao realizar fallback para download local.')
                if 'webpage_url' not in data:
                    data['webpage_url'] = url
                cleanup_targets.extend(targets or [])
                ffmpeg_kwargs = ffmpeg_options
            else:
                filename = data['url'] if stream else cls._resolve_file_path(data, ytdl.prepare_filename(data))
                ffmpeg_kwargs = cls._build_ffmpeg_options(data) if stream else ffmpeg_options

            ffmpeg_exec = FFMPEG_PATH or 'ffmpeg'
            return cls(
                discord.FFmpegPCMAudio(filename, executable=ffmpeg_exec, **ffmpeg_kwargs),
                data=data,
                cleanup_targets=cleanup_targets
            )
        except Exception as e:
            print(f"[DEBUG] Erro em YTDLSource.from_url: {e}") # Adiciona print para depuração
            registrar_log(f"Erro ao extrair info do YTDL: {e}", 'error')
            return None

    def cleanup(self):
        """Remove arquivos temporários gerados pelo fallback após o uso."""
        try:
            super().cleanup()
        except Exception:
            pass

        for target in self.cleanup_targets:
            try:
                if os.path.isdir(target):
                    shutil.rmtree(target, ignore_errors=True)
                elif os.path.isfile(target):
                    os.remove(target)
            except OSError:
                continue

# --- View do Controlador de Música ---

class ControllerView(discord.ui.View):
    def __init__(self, cog: commands.Cog):
        super().__init__(timeout=None)
        self.cog = cog # Armazena uma referência ao Cog de Música

    async def _silent_ack(self, interaction: discord.Interaction):
        if not interaction.response.is_done():
            await interaction.response.defer(thinking=False)

    @discord.ui.button(emoji="⏮️", style=discord.ButtonStyle.grey)
    async def previous(self, interaction: discord.Interaction, _button: discord.ui.Button):
        """Reinicia a música atual."""
        await self._silent_ack(interaction)
        guild = interaction.guild
        if guild.voice_client and guild.id in self.cog.now_playing:
            current = self.cog.now_playing[guild.id]
            self.cog.queue[guild.id].insert(0, current)
            guild.voice_client.stop()
    
    @discord.ui.button(emoji="⏹️", style=discord.ButtonStyle.grey)
    async def stop(self, interaction: discord.Interaction, _button: discord.ui.Button):
        """Para o player e limpa a fila."""
        guild_id = interaction.guild.id
        if guild_id in self.cog.is_processing:
            self.cog.is_processing[guild_id] = False

        await self.cog._reset_player(interaction.guild)
        await self.cog._disconnect_player(interaction.guild)
        await interaction.response.send_message(
            f"⏹️ Player parado por {interaction.user.mention}. (essa msg será deletada)", 
            ephemeral=False, 
            delete_after=40
        )
    
    @discord.ui.button(emoji="⏭️", style=discord.ButtonStyle.grey)
    async def skip(self, interaction: discord.Interaction, _button: discord.ui.Button):
        """Pula para a próxima música."""
        await self._silent_ack(interaction)
        if interaction.guild.voice_client:
            interaction.guild.voice_client.stop()
    
    @discord.ui.button(emoji="🔁", style=discord.ButtonStyle.grey)
    async def loop(self, interaction: discord.Interaction, _button: discord.ui.Button):
        """Cicla entre os modos de loop."""
        await self._silent_ack(interaction)
        current_mode = self.cog.loop_state.get(interaction.guild.id, "off")
        states = ["off", "single", "queue"]
        new_state = states[(states.index(current_mode) + 1) % 3]
        self.cog.loop_state[interaction.guild.id] = new_state
        
        await self.cog._update_controller(interaction.guild)

# --- Cog de Música ---

class Music(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        # Dicionários de estado do player
        self.queue = {}               # Fila de músicas por guild
        self.loop_state = {}          # Estado do loop por guild ("off", "single", "queue")
        self.controllers = {}         # Mensagem do controlador por guild
        self.last_activity = {}     # Timestamp da última atividade por guild
        self.now_playing = {}         # Música atual por guild
        self.controller_channels = {} # Canal do controlador por guild
        self.is_processing = {}       # Flag para processamento de playlist
        self.voice_locks = {}

        ensure_appdata_dirs()

        # Configura o Spotipy
        try:
            client_id = self.bot.config['spotify_id']
            client_secret = self.bot.config['spotify_secret']
            client_credentials_manager = SpotifyClientCredentials(client_id=client_id, client_secret=client_secret)
            self.sp = spotipy.Spotify(client_credentials_manager=client_credentials_manager)
        except Exception as e:
            registrar_log(f"Falha ao inicializar Spotipy: {e}", 'error')
            self.sp = None
        
        self._purge_music_cache()
        # Inicia as tarefas de fundo
        self.check_inactivity.start()
        self.check_controller_position.start()
        self.cleanup_music_cache.start()

    def cog_unload(self):
        # Para as tarefas quando o cog é descarregado
        self.check_inactivity.cancel()
        self.check_controller_position.cancel()
        self.cleanup_music_cache.cancel()

    # --- Métodos de Utilitário do Player (Internos) ---

    async def _ensure_voice(self, interaction: discord.Interaction):
        """Garante que o bot esteja no canal de voz do usuário."""
        if not interaction.user.voice:
            await interaction.response.send_message("Você precisa estar em um canal de voz!", ephemeral=True, delete_after=3)
            return None

        guild_id = interaction.guild.id
        lock = self.voice_locks.setdefault(guild_id, asyncio.Lock())
        async with lock:
            voice_client = interaction.guild.voice_client
            if voice_client and not voice_client.is_connected():
                try:
                    await voice_client.disconnect(force=True)
                except Exception:
                    pass
                voice_client = None

            if not voice_client:
                try:
                    voice_client = await interaction.user.voice.channel.connect(reconnect=False)
                except asyncio.TimeoutError:
                    await interaction.response.send_message("Não consegui me conectar. Tente de novo.", ephemeral=True)
                    return None
                except discord.Forbidden:
                    await interaction.response.send_message("Não tenho permissão para entrar nesse canal.", ephemeral=True)
                    return None
                except discord.ClientException:
                    await interaction.response.send_message("Já estou tentando conectar em outro canal. Aguarde alguns segundos.", ephemeral=True)
                    return None

            self.last_activity[guild_id] = discord.utils.utcnow()
            return voice_client

    @staticmethod
    def _cleanup_track_entry(track: dict):
        player = track.get('player') if isinstance(track, dict) else None
        if player:
            try:
                player.cleanup()
            except Exception:
                pass
        if isinstance(track, dict):
            track['player'] = None

    async def _play_finished(self, guild: discord.Guild):
        """Chamado quando uma música termina de tocar."""
        guild_id = guild.id
        if guild_id in self.now_playing:
            current = self.now_playing[guild_id]
            self._cleanup_track_entry(current)
            loop_mode = self.loop_state.get(guild_id, "off")

            if loop_mode == "single":
                self.queue[guild_id].insert(0, current)
            elif loop_mode == "queue":
                self.queue[guild_id].append(current)
            
            del self.now_playing[guild_id]
        
        if guild_id not in self.queue or not self.queue[guild_id]:
            # Fila vazia, reseta e desconecta
            await self._reset_player(guild)
            await self._disconnect_player(guild)
            return
        
        # Toca a próxima
        await self._play_next(guild)

    async def _play_next(self, guild: discord.Guild):
        """Toca a próxima música na fila."""
        guild_id = guild.id
        if guild_id not in self.queue or not self.queue[guild_id]:
            if guild.voice_client:
                await guild.voice_client.disconnect()
            return
        
        voice_client = guild.voice_client
        if voice_client:
            current_track = None
            try:
                current_track = self.queue[guild_id].pop(0)
                self.now_playing[guild_id] = current_track
                
                # Recria o YTDLSource para garantir que possa ser tocado novamente (em caso de loop)
                # Usa a URL da página web para re-extrair o áudio
                player = current_track.get('player')
                if not player:
                    player = await YTDLSource.from_url(current_track['webpage_url'], loop=self.bot.loop, stream=True)
                if player is None:
                    # Se falhar, pula para a próxima
                    await self._play_finished(guild)
                    return

                # Armazena os dados corretos para o loop
                current_track['player'] = player
                
                def _after_playback(error):
                    if error:
                        registrar_log(f"Erro durante a reprodução: {error}", 'warning')
                    asyncio.run_coroutine_threadsafe(self._play_finished(guild), self.bot.loop)

                voice_client.play(player, after=_after_playback)
                await self._update_controller(guild)
                self.last_activity[guild_id] = discord.utils.utcnow()

            except Exception as e:
                registrar_log(f"Erro ao tocar próxima música: {e}", 'error')
                if current_track:
                    self._cleanup_track_entry(current_track)
                await self._play_finished(guild)

    async def _reset_player(self, guild: discord.Guild):
        """Reseta o estado do player (fila, tocando, controlador)."""
        guild_id = guild.id
        self.is_processing[guild_id] = False
        
        queued_tracks = self.queue.pop(guild_id, [])
        for track in queued_tracks:
            self._cleanup_track_entry(track)
        if guild.voice_client:
            guild.voice_client.stop()
        if guild_id in self.now_playing:
            self._cleanup_track_entry(self.now_playing[guild_id])
            del self.now_playing[guild_id]
        if guild_id in self.controllers:
            try:
                await self.controllers[guild_id].delete()
            except:
                pass
            del self.controllers[guild_id]
        if guild_id in self.controller_channels:
            del self.controller_channels[guild_id]

    def _purge_music_cache(self):
        cutoff = time.time() - MUSIC_CACHE_MAX_AGE_SECONDS
        try:
            entries = list(MUSIC_CACHE_DIR.iterdir())
        except FileNotFoundError:
            return

        for entry in entries:
            try:
                if entry.stat().st_mtime > cutoff:
                    continue
            except FileNotFoundError:
                continue

            try:
                if entry.is_dir():
                    shutil.rmtree(entry, ignore_errors=True)
                else:
                    entry.unlink(missing_ok=True)
            except Exception as exc:
                registrar_log(f"Erro ao limpar cache de música '{entry}': {exc}", 'warning')

    async def _disconnect_player(self, guild: discord.Guild):
        """Desconecta o bot do canal de voz."""
        if guild.voice_client:
            await guild.voice_client.disconnect()

    def _buscar_musicas_spotify(self, url):
        """Busca nomes de músicas de uma URL do Spotify."""
        if not self.sp:
            registrar_log("Spotipy não inicializado, pulando busca.", 'error')
            return None
        try:
            if 'track' in url:
                track = self.sp.track(url)
                return [f"{track['name']} - {track['artists'][0]['name']}"]
            elif 'playlist' in url:
                results = self.sp.playlist_tracks(url)
                return [f"{item['track']['name']} - {item['track']['artists'][0]['name']}" for item in results['items']]
            elif 'album' in url:
                results = self.sp.album_tracks(url)
                return [f"{track['name']} - {track['artists'][0]['name']}" for track in results['items']]
            else:
                return None
        except Exception as e:
            registrar_log(f"Erro ao buscar músicas do Spotify: {e}", 'error')
            return None

    async def _processar_playlist_youtube(self, interaction: discord.Interaction, url: str):
        """Processa e adiciona músicas de uma playlist do YouTube."""
        guild_id = interaction.guild.id
        self.is_processing[guild_id] = True

        try:
            await send_temp_followup(interaction, "🔎 Buscando informações da playlist do YouTube... Isso pode demorar.", 10)
            
            # Usa a instância de ytdl que permite playlists
            try:
                data = await self.bot.loop.run_in_executor(None, lambda: ytdl_playlist.extract_info(url, download=False))
            except PostProcessingError as err:
                registrar_log(
                    f"Falha no pós-processamento da playlist ({err}); tentando novamente sem conversão.",
                    'warning'
                )
                YTDLSource._disable_postprocessing()
                data = await self.bot.loop.run_in_executor(None, lambda: ytdl_playlist.extract_info(url, download=False))
            except Exception as err:
                if 'postprocessing' in str(err).lower():
                    registrar_log(
                        f"Erro ao pós-processar playlist ({err}); tentando novamente sem conversão.",
                        'warning'
                    )
                    YTDLSource._disable_postprocessing()
                    data = await self.bot.loop.run_in_executor(None, lambda: ytdl_playlist.extract_info(url, download=False))
                else:
                    raise
            
            if not data or 'entries' not in data:
                await send_temp_followup(interaction, "❌ Não foi possível buscar as músicas da playlist do YouTube.", 5)
                self.is_processing[guild_id] = False
                return

            entries = data['entries']
            if guild_id not in self.queue:
                self.queue[guild_id] = []

            await send_temp_followup(interaction, f"➕ Adicionando {len(entries)} músicas da playlist à fila...", 15)
            
            count = 0
            for entry in entries:
                if not self.is_processing.get(guild_id, False):
                    await send_temp_followup(interaction, "Adição de playlist cancelada.", 5)
                    break
                
                # Adiciona as informações básicas para serem processadas depois
                self.queue[guild_id].append({
                    'title': entry.get('title', 'Título desconhecido'),
                    'webpage_url': entry.get('webpage_url'),
                    'player': None # Será carregado em _play_next
                })
                count += 1

            await send_temp_followup(interaction, f"✅ Adicionado {count}/{len(entries)} músicas à fila.", 5)
            
            # Toca a primeira música se nada estiver tocando
            if not interaction.guild.voice_client.is_playing():
                await self._play_next(interaction.guild)
            else:
                await self._update_controller(interaction.guild)

        except Exception as e:
            registrar_log(f"Erro ao processar playlist do YouTube: {e}", 'error')
            await send_temp_followup(interaction, "❌ Ocorreu um erro ao processar a playlist do YouTube.", 5)
        finally:
            self.is_processing[guild_id] = False

    async def _processar_playlist_spotify(self, interaction: discord.Interaction, url: str):
        """Processa e adiciona músicas de uma playlist do Spotify."""
        guild_id = interaction.guild.id
        self.is_processing[guild_id] = True

        try:
            musicas = self._buscar_musicas_spotify(url)
            if not musicas:
                await send_temp_followup(interaction, "❌ Não foi possível buscar as músicas do Spotify.", 5)
                self.is_processing[guild_id] = False
                return

            if guild_id not in self.queue:
                self.queue[guild_id] = []
            
            await send_temp_followup(interaction, f"Buscando e adicionando {len(musicas)} músicas... Isso pode demorar.", 10)

            # Adiciona as músicas à fila
            count = 0
            for i, musica_nome in enumerate(musicas):
                if not self.is_processing.get(guild_id, False):
                    await send_temp_followup(interaction, f"Adição de playlist cancelada.", 5)
                    break # Para se o player for resetado
                
                try:
                    player = await YTDLSource.from_url(musica_nome, loop=self.bot.loop, stream=True)
                    if player:
                        self.queue[guild_id].append({'title': player.title, 'webpage_url': player.webpage_url, 'player': player})
                        count += 1
                        
                        # Toca a primeira música imediatamente
                        if i == 0 and not interaction.guild.voice_client.is_playing():
                            await self._play_next(interaction.guild)
                        else:
                            await self._update_controller(interaction.guild) # Atualiza o controller
                except Exception as e:
                    registrar_log(f"Erro ao adicionar música '{musica_nome}': {e}", 'warning')
            
            await send_temp_followup(interaction, f"✅ Adicionado {count}/{len(musicas)} músicas à fila.", 5)

        except Exception as e:
            registrar_log(f"Erro ao processar playlist do Spotify: {e}", 'error')
        finally:
            self.is_processing[guild_id] = False

    # --- Métodos do Controlador (Embed) ---

    async def _update_controller(self, guild: discord.Guild):
        """Atualiza a mensagem do controlador."""
        guild_id = guild.id
        controller = self.controllers.get(guild_id)
        channel = self.controller_channels.get(guild_id)
        
        if not channel: # Se o canal não for salvo, não faz nada
            return

        embed = discord.Embed(
            title="🎵 Controle de Música - LainBot",
            color=discord.Color.blurple()
        ).set_footer(text="Use /tocar para adicionar mais músicas")
        
        if guild_id in self.now_playing:
            embed.add_field(
                name="🎧 Tocando agora",
                value=self.now_playing[guild_id]['title'],
                inline=False
            )
        else:
            embed.add_field(name="🎧 Tocando agora", value="Nada...", inline=False)
        
        if guild_id in self.queue and self.queue[guild_id]:
            queue_list = "\n".join([f"{i+1}. {song['title']}" for i, song in enumerate(self.queue[guild_id][:5])])
            if len(self.queue[guild_id]) > 5:
                queue_list += f"\n...e mais {len(self.queue[guild_id]) - 5} na fila"
            embed.add_field(name="📜 Próximas músicas", value=queue_list, inline=False)
        
        # Adiciona o estado do loop
        embed.add_field(name="Modo Loop", value=f"`{self.loop_state.get(guild_id, 'off')}`", inline=True)
            
        view = ControllerView(self) # Cria uma nova view com referência a este cog
        
        if controller:
            try:
                await controller.edit(embed=embed, view=view)
            except (discord.NotFound, discord.HTTPException):
                await self._create_new_controller(guild, embed, view, channel)
        else:
            await self._create_new_controller(guild, embed, view, channel)

    async def _create_new_controller(self, guild: discord.Guild, embed: discord.Embed, view: discord.ui.View, channel):
        """Cria uma nova mensagem de controlador."""
        try:
            if guild.id in self.controllers:
                try:
                    await self.controllers[guild.id].delete()
                except:
                    pass
            
            controller = await channel.send(embed=embed, view=view)
            self.controllers[guild.id] = controller
        except (discord.Forbidden, discord.HTTPException) as e:
            registrar_log(f"Erro ao criar controlador em '{guild.name}': {e}", 'error')
            self.controller_channels[guild.id] = None # Desiste de postar nesse canal

    # --- Comandos Slash de Música ---

    @app_commands.command(name="tocar", description="Tocar uma música ou playlist")
    async def tocar(self, interaction: discord.Interaction, url: str):
        try:
            await interaction.response.defer()

            if not FFMPEG_AVAILABLE:
                await interaction.followup.send(
                    "❌ FFmpeg não foi encontrado no sistema. Instale o FFmpeg, adicione-o ao PATH "
                    "e reinicie o bot. Veja o README para instruções detalhadas.",
                    ephemeral=True
                )
                registrar_log(
                    "Comando /tocar bloqueado: FFmpeg ausente. Veja "
                    f"{FFMPEG_HELP_URL} para instalar.",
                    'error'
                )
                return
            
            voice_client = await self._ensure_voice(interaction)
            if not voice_client:
                await interaction.followup.send("Não consegui entrar no canal de voz.", ephemeral=True)
                return

            # Define o canal do controlador
            self.controller_channels[interaction.guild.id] = interaction.channel

            # Verifica se é Spotify
            if 'spotify.com' in url:
                self.bot.loop.create_task(self._processar_playlist_spotify(interaction, url))
                return

            # Verifica se é uma playlist do YouTube
            if 'youtube.com/playlist?list=' in url:
                self.bot.loop.create_task(self._processar_playlist_youtube(interaction, url))
                return

            # Toca do YouTube (ou link direto)
            player = await YTDLSource.from_url(url, loop=self.bot.loop, stream=True)
            if player is None:
                await interaction.followup.send("❌ Não foi possível buscar a música.", ephemeral=True)
                return

            guild_id = interaction.guild.id
            if guild_id not in self.queue:
                self.queue[guild_id] = []
            
            self.queue[guild_id].append({'title': player.title, 'webpage_url': player.webpage_url, 'player': player})

            await send_temp_followup(interaction, f"✅ Adicionada à fila: {player.title}", 5)
            await self._update_controller(interaction.guild)

            if not voice_client.is_playing():
                await self._play_next(interaction.guild)

        except Exception as e:
            print(f"[DEBUG] Erro no comando /tocar: {e}") # Adiciona print para depuração
            registrar_log(f"Erro no comando /tocar: {e}", 'error')
            await interaction.followup.send(f"Deu um erro feio: {e}", ephemeral=True)

    @app_commands.command(name="parar", description="Para a música e limpa a fila.")
    async def parar(self, interaction: discord.Interaction):
        guild = interaction.guild
        await interaction.response.send_message("Música finalizada.", ephemeral=False, delete_after=5)
        await self._reset_player(guild)
        await self._disconnect_player(guild)

    # --- Tarefas de Fundo (Tasks) ---

    @tasks.loop(minutes=30)
    async def cleanup_music_cache(self):
        await asyncio.to_thread(self._purge_music_cache)

    @cleanup_music_cache.before_loop
    async def before_cleanup_music_cache(self):
        await self.bot.wait_until_ready()

    @tasks.loop(minutes=1)
    async def check_inactivity(self):
        """Verifica se o bot está inativo ou sozinho em um canal."""
        for guild_id in list(self.last_activity.keys()):
            guild = self.bot.get_guild(guild_id)
            if guild and guild.voice_client:
                voice_channel = guild.voice_client.channel
                voice_client = guild.voice_client
                
                # Conta apenas membros que não são bots
                if voice_channel:
                    members_in_voice = len([m for m in voice_channel.members if not m.bot])
                else:
                    members_in_voice = 0
                
                is_alone = members_in_voice == 0
                
                # Se está sozinho (sem nenhum humano), desconecta imediatamente
                if is_alone:
                    await self._reset_player(guild)
                    await self._disconnect_player(guild)
                    registrar_log(f"Desconectado de '{guild.name}' - nenhum usuário no canal.", 'info')
                    if guild_id in self.last_activity:
                        del self.last_activity[guild_id]
                    continue
                
                # Se está tocando ou tem fila, atualiza atividade
                if voice_client.is_playing() or voice_client.is_paused() or self.queue.get(guild_id):
                    self.last_activity[guild_id] = discord.utils.utcnow()
                    continue
                
                inactive_time = (discord.utils.utcnow() - self.last_activity[guild_id]).total_seconds()

                # Desconecta se inativo por > 3 min
                if inactive_time > 180:
                    await self._reset_player(guild)
                    await self._disconnect_player(guild)
                    registrar_log(f"Desconectado de '{guild.name}' por inatividade.", 'info')
                    del self.last_activity[guild_id]
            
            elif guild_id in self.last_activity:
                # Limpa se o bot não estiver mais no guild ou no canal
                del self.last_activity[guild_id]

    @check_inactivity.before_loop
    async def before_check_inactivity(self):
        await self.bot.wait_until_ready()

    @tasks.loop(seconds=10)
    async def check_controller_position(self):
        """Verifica se o controlador está muito para trás no chat e o recria."""
        for guild_id, controller in list(self.controllers.items()):
            guild = self.bot.get_guild(guild_id)
            if not guild:
                continue
            
            channel = self.controller_channels.get(guild_id)
            if not channel:
                continue
            
            try:
                # Verifica as últimas 15 mensagens
                messages_after = [msg async for msg in channel.history(limit=15) if msg.created_at > controller.created_at]
                
                if len(messages_after) >= 15:
                    await controller.delete()
                    await channel.send('🕸️ `Subindo o controlador...`', delete_after=3.3)
                    await self._update_controller(guild)
            
            except (discord.NotFound, discord.Forbidden):
                # Mensagem/canal não existe mais, limpa
                del self.controllers[guild_id]
                del self.controller_channels[guild_id]
            except Exception as e:
                registrar_log(f"Erro ao verificar posição do controlador: {e}", 'error')

    @check_controller_position.before_loop
    async def before_check_controller_position(self):
        await self.bot.wait_until_ready()


# Função 'setup' obrigatória
async def setup(bot: commands.Bot):
    await bot.add_cog(Music(bot))
# LainBot

<p align="center">
   <img src="https://i.pinimg.com/736x/6c/ef/fb/6ceffb9310699f63aa4cfe58b67bf2dc.jpg" width="28%" alt="Lain" />
</p>

Bot de Discord com a personalidade da Lain Iwakura de *Serial Experiments Lain*. Combina:

- Conversação com **Google Gemini**, simulando a Lain tímida e introspectiva.
- Sistema de **música** com suporte a YouTube e Spotify (yt-dlp + FFmpeg).
- Ferramentas de **RPG** (fichas, inventário, rolagens `xDy`).
- **Moderação** automática com detecção de conteúdo nocivo via IA.
- Busca de perfis no **op.gg** (LoL e Valorant).

---

## Pré-requisitos

- Python **3.11** (recomendado; outras versões podem causar bugs no voice do discord.py)
- FFmpeg instalado e no PATH (ou configure via `.env`)
- Credenciais: Discord, Google AI Studio (Gemini), Tenor, Spotify

---

## Rodando localmente

### 1. Clone e instale dependências

```bash
git clone https://github.com/Samir-pmw/BotDiscord-PeniParker.git
cd BotDiscord-PeniParker
git checkout Lain-version
python -m venv .venv
# Windows:
.\.venv\Scripts\activate
# Linux/macOS:
source .venv/bin/activate
pip install -r requirements.txt
```

### 2. Configure o `.env`

```bash
cp .env.example .env
```

Edite `.env` com seus tokens. Variáveis obrigatórias:

```
DISCORD_TOKEN=seu_token_aqui
GEMINI_TOKEN=sua_chave_do_ai_studio
```

Opcionais mas recomendadas:

```
TENOR_TOKEN=sua_chave_tenor
SPOTIFY_CLIENT_ID=seu_id_spotify
SPOTIFY_CLIENT_SECRET=seu_secret_spotify
```

### 3. FFmpeg

**Windows:** Baixe em [gyan.dev](https://www.gyan.dev/ffmpeg/builds/), extraia e adicione `bin/` ao PATH, **ou** defina no `.env`:

```
PENIBOT_FFMPEG=C:\ffmpeg\bin\ffmpeg.exe
PENIBOT_FFPROBE=C:\ffmpeg\bin\ffprobe.exe
```

**Linux/macOS:** `sudo apt install ffmpeg` ou `brew install ffmpeg`

### 4. Execute

```bash
python main.py
```

---

## Rodando com Docker

A forma mais simples e recomendada — sem precisar instalar Python, FFmpeg ou libopus na máquina.

### 1. Configure o `.env`

```bash
cp .env.example .env
# edite .env com seus tokens
```

### 2. Suba o container

```bash
docker compose up --build
```

Para rodar em background:

```bash
docker compose up --build -d
docker compose logs -f lainbot
```

### 3. Parar

```bash
docker compose down
```

### Comandos úteis

```bash
# Rebuild sem cache (após mudar requirements.txt):
docker compose build --no-cache

# Ver uso de recursos:
docker stats lainbot

# Reiniciar o bot:
docker compose restart lainbot
```

### Dados persistidos

Os volumes Docker mantêm os dados entre rebuilds:

| Volume | Caminho no container | Conteúdo |
| --- | --- | --- |
| `lainbot_data` | `/app/data` | Fichas de RPG, inventários, cache do Wikipedia |
| `lainbot_logs` | `/app/logs` | Logs do bot (`bot_logs.txt`) |

---

## Estrutura de dados (local)

```
data/
├── fichas/<guild_id>.json
├── inventarios/<guild_id>.json
├── knowledge/           ← cache do Wikipedia
└── music_cache/         ← áudios baixados (TTL 6h)
logs/
└── bot_logs.txt
```

---

## Comandos

| Comando | Descrição |
| --- | --- |
| `/tocar <url>` | Adiciona à fila. Aceita YouTube e Spotify. |
| `/parar` | Para música e limpa a fila. |
| `/rolar 2d6+3` | Rola dados. Também funciona escrevendo `2d6+3` direto no chat. |
| `/moeda` | Cara ou coroa. |
| `/painel_rpg` | Ficha de personagem. |
| `/lol <nome>` | Perfil de LoL via op.gg. |
| `/valorant <nome#tag>` | Perfil de Valorant via op.gg. |
| `/ban` / `/limpar` | Moderação. |
| `/ajuda` | Lista de comandos. |
| `/doar` | Informações de doação. |
| Menção + mensagem | Lain responde via Gemini. |

Easter egg: `duvido` no chat → resposta automática.

---

## Contribuindo

1. Faça fork.
2. Crie branch (`git checkout -b feat/nova-ideia`).
3. Commit em PT-BR com contexto real (ex: `feat: adicionar comando /wiki`).
4. Abra um PR apontando para `Lain-version`.

Quer falar comigo? [papiro.dev](https://papiro.dev/) :)

## Licença

Livre, apenas use!

# LainBot (ex-PeniBot)

<p align="center">
   <img src="https://i.pinimg.com/736x/6c/ef/fb/6ceffb9310699f63aa4cfe58b67bf2dc.jpg" width="28%" alt="Lain" />
</p>

LainBot é um bot multifuncional para Discord inspirado em **Serial Experiments Lain**. Ele combina:

- Persona conversacional com **Gemini 2.5 Flash**, simulando a Lain tímida, humana e introspectiva.
- Ferramentas de RPG (fichas, inventário, rolagens livres `xDy`).
- Player de música com suporte ao YouTube/Spotify + fila e comandos de moderação básicos.

> A base continua sendo o PeniBot, porém a personalidade e as integrações foram migradas para a temática “Lain no Wired”.

## Funcionalidades principais

| Área | Destaques |
| --- | --- |
| Chat/Gemini | Respostas roleplay com contexto `PERSONALIDADE_LAIN`, logs detalhados (`%APPDATA%\LainBot\logs`). Ajuste fino via variáveis `GEMINI_*`. |
| RPG | `/rolar`, `/moeda`, `/painel_rpg`, inventário, fichas persistidas em `%APPDATA%\LainBot`. |
| Música | `/tocar`, `/parar`, suporte ao Spotify (via ID/secret) e Tenor para GIFs. |
| Administração | `/ban`, `/limpar`, automação contra xingamentos com deleção + resposta temática. |

### Outros comandos úteis

- `/spam_singed_gremista`, `/limpar`, `/ban`, `/ajuda`.
- `xDy` direto no texto (sem slash).
- Menção + insulto → mensagem é apagada e o bot responde curto + GIF da Lain.

## Pré-requisitos

- Python **3.10+** (testado com 3.11).
- FFmpeg (mesmos passos descritos abaixo).
- Credenciais para Discord, Google AI Studio (Gemini), Spotify e Tenor.

### FFmpeg no Windows
1. Baixe o build estático em [gyan.dev](https://www.gyan.dev/ffmpeg/builds/).
2. Extraia para algo como `C:\ffmpeg-2025-11-17-git-...`.
3. Adicione `C:\ffmpeg-...\bin` ao `Path` **ou** defina no `.env`:
   ```
   PENIBOT_FFMPEG=C:\\ffmpeg-2025-11-17-git-e94439e49b-essentials_build\\bin\\ffmpeg.exe
   PENIBOT_FFPROBE=C:\\ffmpeg-2025-11-17-git-e94439e49b-essentials_build\\bin\\ffprobe.exe
   ```
4. Reinicie o PowerShell e valide com `ffmpeg -version`.

## Instalação

```powershell
git clone https://github.com/Samir-pmw/BotDiscord-PeniParker.git
cd BotDiscord-PeniParker
git checkout Lain-version
python -m venv .venv
.\.venv\Scripts\activate
pip install -r requirements.txt
```

### Configurando o `.env`

```
DISCORD_TOKEN=seu_token
GEMINI_TOKEN=sua_chave_do_AI_Studio
GEMINI_MODEL=models/gemini-2.5-flash     # opcional, já é o padrão
GEMINI_TEMPERATURE=0.55                  # opcional
GEMINI_TOP_P=0.85
GEMINI_TOP_K=18
GEMINI_MAX_OUTPUT_TOKENS=150
SPOTIFY_CLIENT_ID=opcional
SPOTIFY_CLIENT_SECRET=opcional
TENOR_TOKEN=sua_chave
GOOGLE_DRIVE_FOLDER_ID=opcional
PENIBOT_FFMPEG=.../ffmpeg.exe
PENIBOT_FFPROBE=.../ffprobe.exe
```

#### Sobre o Gemini

1. Ative `Generative Language API` no [Google AI Studio](https://aistudio.google.com/).
2. Gere uma chave e copie para `GEMINI_TOKEN`.
3. Liste os modelos disponíveis com:
   ```powershell
   Invoke-WebRequest -Headers @{"x-goog-api-key"=$env:GEMINI_TOKEN} -Uri "https://generativelanguage.googleapis.com/v1beta/models" | Select-String gemini
   ```
4. Se quiser outro modelo (ex.: `models/gemini-2.5-pro`), ajuste `GEMINI_MODEL`.

O arquivo `utils.py` normaliza o nome e aceita overrides de temperatura/top_p/top_k/tokens sem precisar mudar código. Valores inválidos são ignorados com um `logging.warning`.

### Executando

```powershell
python main.py
```

Ao iniciar, o bot registra:
- Caminho efetivo de `%APPDATA%` usado para cache/logs.
- Resultado do carregamento do `.env` (tokens ausentes geram `logging.error`).
- Atividade do Discord configurada (`musicas_atividade`).

## Estrutura de dados

```
%APPDATA%\LainBot
├─ logs\bot_logs.txt
├─ music_cache\
├─ fichas\<guild_id>.json
└─ inventarios\<guild_id>.json
```

Se estiver usando Python da Microsoft Store, o Windows virtualiza a pasta: procure em `C:\Users\VOCÊ\AppData\Local\Packages\PythonSoftwareFoundation...\LocalCache\Roaming\LainBot`.

## Uso rápido

| Comando | Descrição |
| --- | --- |
| `/rolar 2d6+3` | Rola dois dados d6 e soma 3. Também funciona escrevendo `2d6+3` no chat. |
| `/moeda` | Cara ou coroa. |
| `/tocar <url>` | Adiciona à fila. Aceita YouTube/Spotify. |
| `/parar` | Limpa a fila/voz (usado para destravar). |
| `/ban` / `/limpar` | Moderar. |
| menção + mensagem | Lain responde via Gemini. Xingamentos são deletados com resposta curta + GIF. |

## Contribuindo

1. Faça fork.
2. Crie branch (`git checkout -b feat/nova-ideia`).
3. Commit em PT-BR, descrevendo contexto real (ex.: `feat: integrar Gemini 2.5 flash`).
4. Abra um PR apontando para `Lain-version`.


Quer falar comigo? [Meu site aqui](https://papiro.dev/) :)

## Licença

Livre, apenas use!

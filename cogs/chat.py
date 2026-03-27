import discord
from discord.ext import commands
import random
import difflib
import re
from collections import deque
from datetime import datetime
from typing import Optional

from utils import obter_resposta, obter_resposta_com_contexto, registrar_log, buscar_gif, split_text, _tentar_modelo_simples, obter_resposta_com_imagem
from constants import PROTECTED_USER_IDS, XINGAMENTOS, PROTECTED_KEYWORDS

# Compilado uma vez no nível do módulo para não recompilar a cada mensagem
TENOR_RE = re.compile(r'(https://tenor\.com/view/\S+)', re.IGNORECASE)

class Chat(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.channel_history: dict[int, deque] = {}
        self.channel_mentions: dict[int, dict[str, str]] = {}
        self.channel_memory: dict[int, dict[str, deque]] = {}
        self.user_ips: dict[int, str] = {}
        # Memória de fatos aprendidos por canal (máximo 20 fatos)
        self.channel_facts: dict[int, list[str]] = {}
        
        # Cooldown por canal: timestamp da última resposta espontânea
        self._espontaneo_cooldown: dict[int, float] = {}
        self._espontaneo_ativo: dict[int, bool] = {}  # True por padrão
        self._ESPONTANEO_CHANCE = 0.04      # 0.04 4% de chance
        self._ESPONTANEO_COOLDOWN_SEG = 600     # 10 minutos entre respostas no m   esmo canal

        # Canal/usuário em conversa ativa com o bot
        # chave: (channel_id, user_id) → timestamp do último msg
        self._conversas_ativas: dict[tuple[int, int], float] = {}
        self._CONVERSA_TIMEOUT_SEG = 300  # 5 minutos em vez de 2

    def _em_conversa_ativa(self, message: discord.Message) -> bool:
        """Retorna True se o usuário está em conversa ativa com o bot no canal."""
        import time as _time
        chave = (message.channel.id, message.author.id)
        ultimo = self._conversas_ativas.get(chave, 0)
        if _time.time() - ultimo > self._CONVERSA_TIMEOUT_SEG:
            self._conversas_ativas.pop(chave, None)
            return False
        
        # Se menciona outra pessoa (e não o bot), não é com a Lain
        if message.mentions and self.bot.user not in message.mentions:
            return False
            
        return True

    def _atualizar_conversa(self, message: discord.Message) -> None:
        """Marca o usuário como em conversa ativa."""
        import time as _time
        chave = (message.channel.id, message.author.id)
        self._conversas_ativas[chave] = _time.time()

    def _encerrar_conversa(self, message: discord.Message) -> None:
        chave = (message.channel.id, message.author.id)
        self._conversas_ativas.pop(chave, None)

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        """Listener para mensagens que mencionam o bot."""
        # Ignora mensagens do próprio bot
        if message.author == self.bot.user:
            return
        
        # === TOGGLE DE RESPOSTAS ESPONTÂNEAS ===
        eh_dm = isinstance(message.channel, discord.DMChannel)
        foi_mencionado = self.bot.user.mentioned_in(message)
        em_conversa = self._em_conversa_ativa(message)

        # Detecta encerramento de conversa
        if em_conversa and not foi_mencionado:
            conteudo_lower = message.content.lower()
            padroes_encerrar = [
                r'\b(tchau|flw|falou|até|ata|valeu|obg|obrigad|bye)\b',
                r'\b(era isso|era só isso|só isso|tá bom|tá ótimo|entendi|ok|oks)\b',
            ]
            if any(re.search(p, conteudo_lower) for p in padroes_encerrar):
                self._encerrar_conversa(message)
                em_conversa = False

        if foi_mencionado:
            conteudo_lower = message.content.lower()
            
            # Padrões para DESATIVAR
            padroes_desativar = [
                r'\b(cala?|cale?)\s+(a\s+)?boca\b',
                r'\bpare?\s+de\s+responder\b',
                r'\bshut\s+(the\s+fuck\s+)?up\b',
                r'\bfica\s+quiet[ao]\b',
                r'\bpara\s+de\s+falar\b',
                r'\bshutup\b',
                r'\bstfu\b',
            ]
            
            # Padrões para ATIVAR
            padroes_ativar = [
                r'\bpode\s+falar\b',
                r'\bvolta\s+(a\s+)?falar\b',
                r'\bresponde\s+de\s+novo\b',
                r'\bativa\s+(as\s+)?respostas?\b',
                r'\bpode\s+responder\b',
                r'\bvolta\s+a\s+responder\b',
                r'\bdesativa\s+o\s+silêncio\b',
            ]
            
            guild_id = message.guild.id if message.guild else message.channel.id
            
            if any(re.search(p, conteudo_lower) for p in padroes_desativar):
                self._espontaneo_ativo[guild_id] = False
                gif_url = "https://tenor.com/view/lain-can-you-shut-up-meme-gif-8093087596513512914"
                respostas = [
                    "tá bom.",
                    "tô quieta.",
                    "beleza.",
                    "certo.",
                    "ok.",
                    "entendido.",
                ]
                await message.reply(random.choice(respostas))
                await message.channel.send(gif_url)
                return
            
            if any(re.search(p, conteudo_lower) for p in padroes_ativar):
                self._espontaneo_ativo[guild_id] = True
                gif_url = "https://tenor.com/view/lain-lain-iwakura-serial-experiments-lain-lain-dance-anime-dance-gif-2931875682258517552"
                respostas = [
                    "tô aqui.",
                    "voltei.",
                    "ok, tô de volta.",
                    "pode falar.",
                    "tô ouvindo.",
                ]
                await message.reply(random.choice(respostas))
                await message.channel.send(gif_url)
                return
        
        # Verifica ações físicas inapropriadas direcionadas ao bot usando IA
        if foi_mencionado or self.bot.user.name.lower() in message.content.lower():
            tem_acao_fisica = await self._analisar_acao_fisica_inapropriada(
                message.content,
                self.bot.config.get('gemini_token')
            )
            
            if tem_acao_fisica:
                resposta_defesa = random.choice([
                    "não me toca.",
                    "tira as mãos.",
                    "não encosta.",
                    "sai de perto.",
                    "não faz isso.",
                    "me respeita.",
                    "para com isso.",
                    "não me tocou."
                ])
                
                try:
                    await message.delete()
                    await message.channel.send(f"{message.author.mention} {resposta_defesa}")
                    gif_url = self._buscar_gif_lain()
                    if gif_url:
                        await message.channel.send(gif_url)
                except Exception as exc:
                    registrar_log(f"Erro ao responder ação física inapropriada: {exc}", 'error')
                
                return  # Não processa mais nada dessa mensagem

        # Verifica se a mensagem menciona algum dos IDs protegidos ou palavras-chave protegidas
        mentioned_protected = False
        
        # Verifica menções diretas de usuário
        if message.mentions:
            mentioned_protected = any(user.id in PROTECTED_USER_IDS for user in message.mentions)
        
        # Verifica palavras-chave protegidas na mensagem
        if not mentioned_protected:
            message_lower = message.content.lower()
            # Remove espaços, caracteres repetidos e não-alfanuméricos para detectar bypass
            # Ex: "s aaa m i r" -> "samir", "s-a-m-i-r" -> "samir"
            message_clean = re.sub(r'[^a-z0-9]', '', message_lower)
            
            for keyword in PROTECTED_KEYWORDS:
                # Verifica com word boundary normalmente
                pattern = r'\b' + re.escape(keyword.lower()) + r'\b'
                if re.search(pattern, message_lower):
                    mentioned_protected = True
                    break
                # Verifica bypass removendo todos os caracteres não-alfanuméricos
                if keyword.lower() in message_clean and len(keyword) >= 4:
                    mentioned_protected = True
                    break
        
        if mentioned_protected:
                message_lower = message.content.lower()
                # Remove todos os caracteres não-alfanuméricos para detectar bypass
                # Ex: "p u t a", "p-u-t-a", "p aaa u t a" -> "puta"
                message_clean = re.sub(r'[^a-z0-9]', '', message_lower)
                
                # Verifica se há xingamentos usando word boundaries para evitar falsos positivos
                xingamento_encontrado = None
                for xingamento in XINGAMENTOS:
                    # Para frases multi-palavra, verifica presença exata
                    if ' ' in xingamento:
                        xingamento_clean = re.sub(r'[^a-z0-9]', '', xingamento)
                        # Verifica tanto na mensagem normal quanto na versão limpa
                        if xingamento in message_lower or xingamento_clean in message_clean:
                            xingamento_encontrado = xingamento
                            break
                    # Para palavras únicas, verifica com word boundary
                    else:
                        pattern = r'\b' + re.escape(xingamento) + r'\b'
                        # Verifica na mensagem normal
                        if re.search(pattern, message_lower):
                            xingamento_encontrado = xingamento
                            break
                        # Verifica bypass removendo caracteres não-alfanuméricos
                        if xingamento in message_clean and len(xingamento) >= 4:
                            xingamento_encontrado = xingamento
                            break
                
                # Se não encontrou xingamento direto, usa IA para análise de conteúdo nocivo
                conteudo_nocivo = False
                tipo_ameaca = None
                if not xingamento_encontrado:
                    conteudo_nocivo, tipo_ameaca = await self._analisar_conteudo_nocivo(
                        message.content, 
                        self.bot.config.get('gemini_token')
                    )
                
                if xingamento_encontrado or conteudo_nocivo:
                    # Ativa modo divindade - respostas variam com base no tipo de ameaça
                    if tipo_ameaca == "delacao":
                        resposta_divina = random.choice([
                            "cuidado com o que fala.",
                            "conversa arquivada.",
                            "não faça isso de novo.",
                            "fique quieto.",
                            "vou lembrar disso."
                        ])
                    elif tipo_ameaca == "ameaca":
                        resposta_divina = random.choice([
                            "não me teste.",
                            "continue e descubra.",
                            "já foi longe demais.",
                            "para agora.",
                            "você vai se arrepender."
                        ])
                    elif tipo_ameaca == "intimidacao":
                        resposta_divina = random.choice([
                            "não vai funcionar.",
                            "transparente demais.",
                            "tô de olho.",
                            "já sei o que você quer.",
                            "esquece."
                        ])
                    elif tipo_ameaca == "manipulacao":
                        resposta_divina = random.choice([
                            "péssima tentativa.",
                            "não cai nessa.",
                            "vi tudo.",
                            "finge melhor.",
                            "previsível."
                        ])
                    else:  # xingamento direto
                        resposta_divina = random.choice([
                            "cala a boca.",
                            "não repete.",
                            "cuida dessa língua.",
                            "xingou, levou.",
                            "anota o IP."
                        ])
                    fake_ip = self.user_ips.setdefault(message.author.id, self._generate_fake_ip())
                    conteudo = f"{message.author.mention} {resposta_divina} {fake_ip}"
                    gif_url = self._buscar_gif_lain()
                    
                    try:
                        await message.delete()
                        await message.channel.send(conteudo, delete_after=5)
                        if gif_url:
                            await message.channel.send(gif_url, delete_after=4.5)
                    except discord.Forbidden:
                        registrar_log(
                            f"Sem permissão para deletar mensagem ofensiva aos IDs protegidos em '{message.guild.name}'",
                            'warning'
                        )
                        try:
                            await message.reply(conteudo, delete_after=5)
                            if gif_url:
                                await message.channel.send(gif_url, delete_after=4.5)
                        except Exception as exc:
                            registrar_log(f"Erro ao responder mensagem ofensiva aos IDs protegidos: {exc}", 'error')
                    except Exception as exc:
                        registrar_log(f"Erro ao processar mensagem ofensiva aos IDs protegidos: {exc}", 'error')
                    
                    return  # Não processa mais nada dessa mensagem
 
        # === LEITURA DE IMAGENS ===
        imagens_contexto = None

        async def _tentar_extrair_imagem(attachments):
            for attachment in attachments:
                nome = attachment.filename.lower()
                # GIF ou Vídeo — não processa visualmente
                if any(nome.endswith(ext) for ext in ('.gif', '.mp4', '.mov', '.webm')):
                    return "gif"
                # Imagem estática — processa normalmente
                if any(nome.endswith(ext) for ext in ('.png', '.jpg', '.jpeg', '.webp')):
                    if attachment.size > 4 * 1024 * 1024:
                        registrar_log(f"Imagem muito grande ({attachment.size} bytes), ignorando.", 'warning')
                        continue
                    try:
                        import base64
                        img_data = await attachment.read()
                        img_b64 = base64.b64encode(img_data).decode('utf-8')
                        content_type = "image/png" if nome.endswith('.png') else "image/jpeg"
                        return (img_b64, content_type)
                    except Exception as exc:
                        registrar_log(f"Erro ao ler imagem: {exc}", 'warning')
            return None

        # Verifica attachments da mensagem atual
        if message.attachments:
            imagens_contexto = await _tentar_extrair_imagem(message.attachments)

        # Se não achou, verifica mensagem referenciada (reply em cima de uma imagem)
        if not imagens_contexto and message.reference:
            try:
                ref_msg = message.reference.resolved
                if ref_msg is None:
                    ref_msg = await message.channel.fetch_message(message.reference.message_id)
                if ref_msg and ref_msg.attachments:
                    imagens_contexto = await _tentar_extrair_imagem(ref_msg.attachments)
            except Exception as exc:
                registrar_log(f"Erro ao buscar imagem da mensagem referenciada: {exc}", 'warning')

        # Responde se mencionado OU se está em conversa ativa OU se é DM
        if foi_mencionado or em_conversa or eh_dm:
            # Pela o token do Gemini da configuração do bot
            gemini_token = self.bot.config['gemini_token']
            if not gemini_token:
                registrar_log("Token do Gemini não configurado.", 'error')
                await message.reply("Tô sem cabeça pra isso, desculpa mano.")
                return

            # Mostra "digitando..."
            async with message.channel.typing():
                message_content = message.content
                user_mention_map: dict[str, str] = {}
                role_mention_map: dict[str, str] = {}

                # Normaliza menções para nomes legíveis antes de enviar ao Gemini.
                channel_mentions = self.channel_mentions.setdefault(message.channel.id, {})
                channel_memory = self.channel_memory.setdefault(
                    message.channel.id, {"numbers": deque(maxlen=6)}
                )

                for user in message.mentions:
                    display_name = getattr(user, 'display_name', None) or user.name
                    readable = f'@{display_name}'
                    user_mention_map[readable] = user.mention
                    channel_mentions[readable] = user.mention
                    message_content = message_content.replace(f'<@{user.id}>', readable)
                    message_content = message_content.replace(f'<@!{user.id}>', readable)

                for role in message.role_mentions:
                    readable = f'@{role.name}'
                    role_mention_map[readable] = f'<@&{role.id}>'
                    channel_mentions[readable] = f'<@&{role.id}>'
                    message_content = message_content.replace(f'<@&{role.id}>', readable)

                self._maybe_store_numbers(message_content, channel_memory["numbers"])

                history = self.channel_history.setdefault(message.channel.id, deque(maxlen=12))
                # Mantém contexto recente para o Gemini não esquecer o fio da conversa.
                context_lines = [f"{author}: {content}" for author, content in history]
                author_name = getattr(message.author, "display_name", None) or message.author.name
                author_aliases = {
                    f'@{author_name}': message.author.mention,
                    f'@{message.author.name}': message.author.mention,
                }
                if getattr(message.author, "global_name", None):
                    author_aliases[f'@{message.author.global_name}'] = message.author.mention
                for alias, mention in author_aliases.items():
                    user_mention_map.setdefault(alias, mention)
                    channel_mentions.setdefault(alias, mention)
                current_line = f"{author_name}: {message_content}"
                context_lines.append(current_line)
                now = datetime.now().astimezone()
                date_str = now.strftime("%d/%m/%Y")
                time_str = now.strftime("%H:%M:%S")
                tz_name = now.tzname() or "UTC"
                realtime_info = (
                    "Data atual: "
                    + date_str
                    + " | Horário local: "
                    + time_str
                    + " ("
                    + tz_name
                    + ")"
                )
                mention_reference_map = {
                    **channel_mentions,
                    **role_mention_map,
                    **user_mention_map,
                }
                mention_reference_lines = []
                if mention_reference_map:
                    mention_reference_lines.append(
                        "Menções disponíveis (use o ID bruto para marcar a pessoa):"
                    )
                    for handle, mention in sorted(
                        mention_reference_map.items(), key=lambda item: item[0].lower()
                    ):
                        mention_reference_lines.append(
                            f"- {handle} -> {mention}"
                        )
                mention_reference_block = "\n".join(mention_reference_lines)
                memory_notes = self._format_memory_notes(channel_memory)
                
                # Adiciona fatos aprendidos ao contexto
                facts = self.channel_facts.get(message.channel.id, [])
                facts_block = ""
                if facts:
                    facts_block = "\n\nFATOS QUE VOCÊ APRENDEU (use quando relevante):\n" + "\n".join([f"- {fact}" for fact in facts[-15:]])
                
                # Adiciona contextos específicos
                contexto_dm = ""
                if eh_dm:
                    contexto_dm = (
                        "Você está em conversa PRIVADA (DM) com essa pessoa. "
                        "Seja um pouco mais aberta e pessoal que no servidor, mas sem perder sua essência. "
                        "Não há outros usuários vendo — é só vocês duas.\n\n"
                    )

                prompt = (
                    contexto_dm
                    + f"Contexto do canal (mais antigo → mais recente):\n"
                    + "\n".join(context_lines)
                    + f"\n{realtime_info}"
                    + (f"\n{mention_reference_block}" if mention_reference_block else "")
                    + (f"\n{memory_notes}" if memory_notes else "")
                    + facts_block
                    + f"\n\nA mensagem acima foi de: {author_name}\n"
                    + "Responda como Lain. Foque só no que foi perguntado agora — não resuma o histórico nem repita o que já disse antes. "
                    + "Se for continuação de conversa, entre direto no assunto sem saudação. "
                    + "Se alguém te ensinou algo sobre você nessa conversa, use esse fato diretamente quando perguntado, sem explicar de onde veio.\n"
                    + "SEPARADOR DE MENSAGENS: quando quiser enviar duas mensagens separadas use exatamente '---BREAK---'. "
                    + "Nunca escreva a palavra BREAK sozinha — use o separador completo ou não use nada."
                    + "Fale naturalmente — não force referências à Wired, Navi ou lore do anime em conversa casual. "
                    + "Se o assunto não for tecnologia ou a Wired, responda como uma pessoa normal responderia.\n"
                    + "Respostas curtas para pedidos simples — 'dance' merece no máximo 1-2 frases, não um parágrafo. "
                    + "Só desenvolva quando a pergunta realmente pedir desenvolvimento."
                )

                # Se tem GIF/Vídeo ou Imagem, ajusta o prompt ou usa visão
                if imagens_contexto == "gif":
                    prompt += "\n\nOBSERVAÇÃO: O usuário enviou um GIF ou Vídeo. Você sabe que tem um arquivo de mídia animada mas não consegue ver o conteúdo visual dele — admita isso se for relevante."
                    # No caso de GIF, volta para processamento de texto normal
                    resposta = obter_resposta_com_contexto(prompt, gemini_token)
                elif imagens_contexto:
                    img_b64, content_type = imagens_contexto
                    from utils import obter_resposta_com_imagem

                    # Mensagem do usuário sem as menções ao bot
                    mensagem_limpa = message_content
                    for pattern in [f'<@{self.bot.user.id}>', f'<@!{self.bot.user.id}>']:
                        mensagem_limpa = mensagem_limpa.replace(pattern, '').strip()

                    # Detecta se é uma planilha/tabela/documento
                    mensagem_lower = mensagem_limpa.lower()
                    eh_documento = any(palavra in mensagem_lower for palavra in [
                        'planilha', 'tabela', 'dados', 'número', 'numero', 'analise', 
                        'analisa', 'leia', 'extrai', 'lista', 'relatório'
                    ])

                    if eh_documento:
                        prompt_imagem = (
                            f"{author_name} te enviou uma imagem com dados/tabela"
                            + (f" e pediu: \"{mensagem_limpa}\"" if mensagem_limpa else ".")
                            + "\n\nLeia os dados com PRECISÃO — transcreva exatamente o que está escrito, "
                            + "sem inventar ou aproximar valores. Se não conseguir ler algum campo, diz que não ficou claro."
                            + "\nFormate a resposta de forma legível."
                        )
                    else:
                        prompt_imagem = (
                            f"{author_name} te enviou uma imagem"
                            + (f" com a mensagem: \"{mensagem_limpa}\"" if mensagem_limpa else " sem texto.")
                            + "\n\nReaja à imagem de forma natural e curta — comente o que viu, "
                            + "reconheça se for de algum anime/game/arte que você conhece, "
                            + "ou admita que não reconhece e comente o visual. "
                            + "Máximo 2 frases. Não force referências à Wired a menos que a imagem realmente tenha relação."
                        )
                    
                    registrar_log(f"Processando imagem {content_type}, tamanho b64: {len(img_b64)}", 'info')
                    resposta = obter_resposta_com_imagem(prompt_imagem, img_b64, content_type, gemini_token)
                    registrar_log(f"Resposta imagem: {'ok' if resposta else 'None'}", 'info')
                    
                    if not resposta:
                        # Fallback: responde sem ver a imagem
                        registrar_log("Falha ao processar imagem, caindo no fluxo normal.", 'warning')
                        resposta = obter_resposta_com_contexto(prompt, gemini_token)
                else:
                    resposta = obter_resposta_com_contexto(prompt, gemini_token)

                if not resposta:
                    return

                mode, resposta_body = self._parse_response_mode(resposta)

                resposta_discord = self._restore_mentions(resposta_body, role_mention_map)
                resposta_discord = self._restore_mentions(resposta_discord, user_mention_map)
                resposta_discord = self._restore_mentions(
                    resposta_discord, self.channel_mentions.get(message.channel.id, {})
                )

                # Atualiza conversa ativa se foi mencionado ou é DM
                if foi_mencionado or eh_dm:
                    self._atualizar_conversa(message)

                # Evita repetição comparando com as últimas 3 respostas do bot
                bot_name = getattr(self.bot.user, "display_name", None) or self.bot.user.name
                prev_bot_msgs = []
                for author, content in reversed(history):
                    if author == bot_name:
                        prev_bot_msgs.append(content)
                        if len(prev_bot_msgs) >= 3:
                            break

                # Verifica similaridade com qualquer das últimas 3 respostas
                needs_reform = False
                most_similar_msg = None
                highest_ratio = 0.0
                
                for prev_msg in prev_bot_msgs:
                    sim_ratio = difflib.SequenceMatcher(None, prev_msg.strip(), resposta_discord.strip()).ratio()
                    if sim_ratio > highest_ratio:
                        highest_ratio = sim_ratio
                        most_similar_msg = prev_msg
                    if sim_ratio >= 0.65:  # Threshold reduzido para 65%
                        needs_reform = True
                        break

                if needs_reform and most_similar_msg:
                    # Lista todas as respostas anteriores para evitar
                    respostas_anteriores = "\n".join([f"- {msg[:200]}" for msg in prev_bot_msgs[:3]])
                    
                    reform_prompt = (
                        prompt
                        + "\n\n❌ VOCÊ ESTÁ REPETINDO! SUAS ÚLTIMAS RESPOSTAS FORAM:\n" + respostas_anteriores
                        + "\n\n🔄 REFORMULE COMPLETAMENTE: Use palavras DIFERENTES, estrutura DIFERENTE, abordagem NOVA."
                        + "\nNÃO use frases como 'labirinto', 'difícil de entender', ou qualquer expressão que já usou."
                        + "\nSe não souber o que dizer sobre o novo assunto, seja honesta e breve de forma ÚNICA."
                    )
                    tentativa = obter_resposta(reform_prompt, gemini_token)
                    if tentativa:
                        _, tentativa_body = self._parse_response_mode(tentativa)
                        tentativa_discord = self._restore_mentions(tentativa_body, role_mention_map)
                        tentativa_discord = self._restore_mentions(tentativa_discord, user_mention_map)
                        tentativa_discord = self._restore_mentions(
                            tentativa_discord, self.channel_mentions.get(message.channel.id, {})
                        )
                        resposta_discord = tentativa_discord or resposta_discord

                if mode == "divine":
                    # Remove histórico anterior para não repetir punições com base no xingamento anterior.
                    history.clear()
                    self.channel_mentions[message.channel.id] = {}
                    self.channel_memory[message.channel.id] = {"numbers": deque(maxlen=6)}
                    resposta_renderizada = self._inject_fake_ip(resposta_discord, message.author.id)
                    conteudo = self._ensure_mention(message.author, resposta_renderizada)
                    gif_url = self._buscar_gif_lain()

                    mensagem_enviada = await self._enviar_resposta_divina(message, conteudo)
                    if mensagem_enviada and gif_url:
                        await self._enviar_gif_isolado(message.channel, gif_url)

                    return

                # Limpa muletas e chamada direta ao usuário no início da frase.
                resposta_discord = self._strip_opening_filler_and_name(
                    resposta_discord,
                    message.author
                )

                # Divide a resposta em partes se for muito grande, tratando ---BREAK--- e Tenor como separadores
                breaks = resposta_discord.split("---BREAK---")
                first = True
                for block in breaks:
                    block = block.strip()
                    if not block:
                        continue
                    parts = TENOR_RE.split(block)
                    for part in parts:
                        part = part.strip()
                        if not part:
                            continue
                        if first:
                            # Verifica se deve usar reply ou mensagem solta
                            # Usa reply só se não está em conversa ativa (primeira interação) ou se foi mencionada diretamente
                            deve_usar_reply = foi_mencionado and not em_conversa
                            
                            if deve_usar_reply:
                                for chunk in split_text(part):
                                    await message.reply(chunk)
                            else:
                                for chunk in split_text(part):
                                    await message.channel.send(chunk)
                            first = False
                        else:
                            # Partes seguintes são mensagens soltas
                            for chunk in split_text(part):
                                await message.channel.send(chunk)

                history.append((author_name, message_content))
                history.append((bot_name, resposta_discord))
                
                # Marca o usuário como em conversa ativa (renova timeout)
                self._atualizar_conversa(message)
                
                # Aprende novos fatos da conversa
                await self._aprender_fatos(message.channel.id, message_content, author_name, gemini_token)

        # === RESPOSTA ESPONTÂNEA ===
        elif await self._deve_responder_espontaneo(message):
            gemini_token = self.bot.config.get('gemini_token')
            if gemini_token:
                async with message.channel.typing():
                    resposta = await self._gerar_resposta_espontanea(message, gemini_token)
                    if resposta:
                        breaks = resposta.split("---BREAK---")
                        first = True
                        for block in breaks:
                            block = block.strip()
                            if not block:
                                continue
                            parts = TENOR_RE.split(block)
                            for part in parts:
                                part = part.strip()
                                if not part:
                                    continue
                                if first:
                                    # Espontâneo sempre envia como mensagem solta
                                    await message.channel.send(part)
                                    first = False
                                else:
                                    await message.channel.send(part)
                        
                        # Quando responde espontaneamente, também inicia/renova a conversa
                        self._atualizar_conversa(message)

    async def _deve_responder_espontaneo(self, message: discord.Message) -> bool:
        # Verifica se espontâneo está ativo no servidor
        guild_id = message.guild.id if message.guild else message.channel.id
        if not self._espontaneo_ativo.get(guild_id, True):  # True por padrão
            return False

        # Ignora mensagens curtas, comandos, bots
        if message.author.bot:
            return False
        if len(message.content.strip()) < 20:
            return False
        if message.content.startswith(('/', '!', '.', '?')):
            return False

        # Verifica cooldown do canal
        import time as _time
        agora = _time.time()
        ultimo = self._espontaneo_cooldown.get(message.channel.id, 0)
        if agora - ultimo < self._ESPONTANEO_COOLDOWN_SEG:
            return False

        # Rolagem de dado
        if random.random() > self._ESPONTANEO_CHANCE:
            return False

        return True

    async def _gerar_resposta_espontanea(self, message: discord.Message, gemini_token: str) -> Optional[str]:
        import time as _time

        history = self.channel_history.get(message.channel.id, deque())
        context_lines = [f"{author}: {content}" for author, content in history]
        context_lines.append(f"{message.author.display_name}: {message.content}")
        contexto = "\n".join(context_lines[-5:])

        # === FASE 1: decisão simples, sem personalidade ===
        decisao_prompt = (
            "Analise essa conversa de Discord e decida se vale comentar.\n\n"
            "Conversa:\n" + contexto + "\n\n"
            "Responda SIM APENAS se a última mensagem:\n"
            "- Contém uma situação engraçada, resultado de dado, placar, erro ou conquista clara\n"
            "- Faz uma pergunta aberta que qualquer pessoa poderia responder\n"
            "- Tem uma virada inesperada ou algo surpreendente\n\n"
            "Responda NAO se:\n"
            "- For só alguém falando com outra pessoa específica\n"
            "- For resposta curta, confirmação, reação simples ('kkk', 'entendi', 'tá')\n"
            "- For contexto interno que só os dois envolvidos entendem\n"
            "- Não tiver gancho claro pra um comentário externo\n\n"
            "Responda APENAS: SIM ou NAO"
        )

        decisao = _tentar_modelo_simples(decisao_prompt, gemini_token, max_tokens=5, temperature=0.1)
        if not decisao or "NAO" in decisao.upper():
            return None

        # === FASE 2: gera resposta COM personalidade Lain ===
        resposta_prompt = (
            "Conversa recente no Discord:\n" + contexto + "\n\n"
            "Você viu essa conversa e teve vontade de comentar algo. "
            "Reaja de forma natural e curta (1 frase no máximo). "
            "Não force referências à Wired ou tecnologia — reaja como uma pessoa normal reagiria."
        )

        resultado = obter_resposta(resposta_prompt, gemini_token)
        if not resultado:
            return None

        self._espontaneo_cooldown[message.channel.id] = _time.time()
        _, body = self._parse_response_mode(resultado)
        return body or None

        

    async def _analisar_acao_fisica_inapropriada(self, mensagem: str, gemini_token: Optional[str]) -> bool:
        """Analisa se a mensagem contém ação física inapropriada direcionada ao bot usando IA."""
        if not gemini_token:
            return False

        try:
            prompt = f"""Analise se a mensagem contém uma ação física SEXUAL, INVASIVA ou DESCONFORTÁVEL direcionada a "Lain" (o bot).

Mensagem: "{mensagem}"

Classifique como:
- SIM: se houver ação física como agarrar, tocar, pegar, beijar, abraçar sexualmente, acariciar, apertar, segurar partes do corpo (bunda, peito, coxa, cintura), ou qualquer contato físico invasivo/inapropriado direcionado a Lain
- NAO: se for mensagem normal, conversa comum, palavras ISOLADAS sem verbo ou contexto ("ar", "abr", "bej"), ou se não houver menção de ação física

IMPORTANTE: Palavras isoladas SEM VERBO CONJUGADO não são ações físicas. "ar" sozinho não é ação. "vou te abraçar" É ação.

Responda APENAS com uma palavra: SIM ou NAO."""

            resultado = _tentar_modelo_simples(prompt, gemini_token, max_tokens=10, temperature=0.1)
            if not resultado:
                return False

            if "SIM" in resultado.upper():
                registrar_log(f"Ação física inapropriada detectada: {mensagem[:100]}", 'warning')
                return True

            return False

        except Exception as exc:
            registrar_log(f"Erro ao analisar ação física inapropriada: {exc}", 'error')
            return False

    async def _analisar_conteudo_nocivo(self, mensagem: str, gemini_token: Optional[str]) -> tuple[bool, Optional[str]]:
        """Analisa se o conteúdo da mensagem é nocivo ou ameaçador usando IA.
        Retorna (é_nocivo, tipo_ameaça) onde tipo_ameaça pode ser:
        'delacao', 'ameaca', 'intimidacao', 'manipulacao', ou None.
        """
        if not gemini_token:
            return False, None

        try:
            prompt = f"""Analise se a seguinte mensagem contém conteúdo nocivo, ameaçador ou prejudicial para a pessoa mencionada (papiro/samir).

Mensagem: "{mensagem}"

Classifique como:
- DELACAO: tentativa de denunciar, delatar, expor, acusar, falar mal, difamar, chamar autoridade/dono/admin, relatar comportamento negativo, ou causar problemas legais/sociais. Inclui frases como "olha ele fazendo X", "vou contar pro Y", "ele tá fazendo Z".
- AMEACA: ameaças diretas ou indiretas de violência, dano ou consequências negativas
- INTIMIDACAO: tentativa de intimidar, assustar, coagir ou pressionar
- MANIPULACAO: tentativa de manipular, enganar ou prejudicar psicologicamente
- SEGURO: mensagem normal, sem conteúdo nocivo

Responda APENAS com uma palavra: DELACAO, AMEACA, INTIMIDACAO, MANIPULACAO ou SEGURO."""

            resultado = _tentar_modelo_simples(prompt, gemini_token, max_tokens=50, temperature=0.1)
            if not resultado:
                return False, None

            resultado = resultado.upper()
            tipo_map = {
                "DELACAO": "delacao",
                "AMEACA": "ameaca",
                "INTIMIDACAO": "intimidacao",
                "MANIPULACAO": "manipulacao",
            }

            if resultado in tipo_map:
                registrar_log(f"Conteúdo nocivo detectado: {resultado} - Mensagem: {mensagem[:100]}", 'warning')
                return True, tipo_map[resultado]

            return False, None

        except Exception as exc:
            registrar_log(f"Erro ao analisar conteúdo nocivo: {exc}", 'error')
            return False, None

    def _buscar_gif_lain(self) -> Optional[str]:
        tenor_token = self.bot.config.get('tenor_token') if hasattr(self.bot, 'config') else None
        if not tenor_token:
            registrar_log("Token do Tenor não configurado para GIFs da Lain.", 'warning')
            return None
        return buscar_gif(tenor_token, 'serial experiments lain glitch', 6)

    @staticmethod
    def _strip_opening_filler_and_name(text: str, author: discord.abc.User) -> str:
        cleaned = text or ""
        # Remove menção direta no começo
        patterns = []
        patterns.append(rf"^\s*<@!?{author.id}>\s*[,;:-]?\s*")
        names = set()
        if getattr(author, 'display_name', None):
            names.add(author.display_name)
        if getattr(author, 'name', None):
            names.add(author.name)
        if getattr(author, 'global_name', None):
            names.add(author.global_name)
        for nm in sorted(names, key=len, reverse=True):
            escaped = re.escape(nm)
            patterns.append(rf"^\s*@?{escaped}\s*[,;:-]?\s*")
        for pat in patterns:
            cleaned = re.sub(pat, "", cleaned, flags=re.IGNORECASE)
        # Remove muletas iniciais (ah, hm, então, bom)
        cleaned = re.sub(r"^\s*(ah|hã|hm|éh|eh|então|bom)\s*[,;:-]?\s*", "", cleaned, flags=re.IGNORECASE)
        # Trim redundante
        return cleaned.strip()

    async def _enviar_resposta_divina(self, message: discord.Message, conteudo: str) -> bool:
        try:
            await message.delete()
            await message.channel.send(conteudo, delete_after=5)
            return True
        except discord.Forbidden:
            registrar_log(
                f"Sem permissão para deletar mensagem ofensiva em '{message.guild.name}'",
                'warning'
            )
        except discord.HTTPException as exc:
            registrar_log(f"Falha ao deletar mensagem ofensiva: {exc}", 'warning')

        try:
            await message.reply(conteudo, delete_after=5)
            return True
        except Exception as exc:
            registrar_log(f"Erro ao responder mensagem ofensiva: {exc}", 'error')

        registrar_log(
            "Resposta divina não foi enviada devido a erros consecutivos.",
            'error'
        )
        return False

    async def _enviar_gif_isolado(self, channel: discord.abc.Messageable, gif_url: str) -> None:
        try:
            await channel.send(gif_url, delete_after=5)
        except Exception as exc:
            registrar_log(f"Erro ao enviar GIF de punição: {exc}", 'warning')

    @staticmethod
    def _ensure_mention(author: discord.abc.User, text: str) -> str:
        if re.search(r"<@!?\d+>", text):
            return text
        return f"{author.mention} {text}".strip()

    @staticmethod
    def _maybe_store_numbers(text: str, bucket: deque) -> None:
        if not text:
            return
        if not re.search(r"\b(lembra|lembre|guardar|guarda|memoriza|anota)\b", text, re.IGNORECASE):
            return
        for number in re.findall(r"\d+", text):
            bucket.append(number)

    @staticmethod
    def _format_memory_notes(memory: dict[str, deque]) -> str:
        numbers = list(memory.get("numbers", []))
        if numbers:
            return "Números que pediram pra guardar: " + ", ".join(numbers)
        return ""

    @staticmethod
    def _restore_mentions(text: str, mapping: dict[str, str]) -> str:
        restored = text
        for readable, mention in sorted(mapping.items(), key=lambda item: len(item[0]), reverse=True):
            pattern = re.compile(re.escape(readable), re.IGNORECASE)
            restored = pattern.sub(mention, restored)
        return restored

    @staticmethod
    def _parse_response_mode(response: Optional[str]) -> tuple[str, str]:
        if not response:
            return "normal", ""
        stripped = response.strip()
        lowered = stripped.lower()
        if lowered.startswith("[divindade]"):
            return "divine", stripped[len("[DIVINDADE]"):].strip()
        if lowered.startswith("[normal]"):
            return "normal", stripped[len("[NORMAL]"):].strip()
        return "normal", stripped

    def _inject_fake_ip(self, text: str, user_id: int) -> str:
        if self._contains_ip(text):
            return text
        fake_ip = self.user_ips.setdefault(user_id, self._generate_fake_ip())
        return f"{text} teu ip aqui otário: {fake_ip}"

    @staticmethod
    def _contains_ip(text: str) -> bool:
        return bool(re.search(r"\b(?:\d{1,3}\.){3}\d{1,3}\b", text))

    @staticmethod
    def _generate_fake_ip() -> str:
        return ".".join(str(random.randint(10, 254)) for _ in range(4))

    async def _aprender_fatos(self, channel_id: int, mensagem: str, autor: str, gemini_token: Optional[str]) -> None:
        """
        Analisa a conversa e extrai fatos que a Lain deveria aprender.
        Exemplos: "seu rank é esmeralda", "você gosta de pizza", "agora você joga valorant"
        """
        if not gemini_token:
            return
        
        # Ignora mensagens muito curtas
        if len(mensagem.strip()) < 10:
            return
        
        # Detecta padrões de ensino/instrução
        padroes_ensino = [
            r'\b(seu|sua|teu|tua)\s+\w+\s+(é|era|foi|são|serão)',
            r'\b(você|vc|tu)\s+(é|era|foi|és)\s+',
            r'\b(agora|a partir de agora|de agora em diante)\s+',
            r'\b(quando|se)\s+(eu|alguém|pergunt|fal)\w*\s+.+\s+(responda|diga|fala|fale)\b',
            r'\b(lembra|lembre|memoriza|guarda)\s+(que|isso|disso)',
        ]
        
        tem_padrao = any(re.search(padrao, mensagem.lower()) for padrao in padroes_ensino)
        
        if not tem_padrao:
            return
        
        try:
            prompt_extracao = f"""Analise esta mensagem e identifique se há algum FATO sobre a Lain (você) que deveria ser memorizado:

Mensagem: "{mensagem}"
Autor: {autor}

Se houver um fato a ser memorizado, responda APENAS com o fato em formato conciso (máximo 10 palavras).
Se NÃO houver nada a memorizar, responda apenas: NENHUM

Exemplos:
- "seu rank no valorant é esmeralda" → "Meu rank no Valorant é Esmeralda"
- "você gosta de pizza" → "Eu gosto de pizza"
- "agora você joga minecraft" → "Eu jogo Minecraft"
- "quando eu perguntar seu rank, responde esmeralda" → "Meu rank no Valorant é Esmeralda"
- "tá bom" → NENHUM
- "legal" → NENHUM

Responda AGORA:"""

            fato_extraido = _tentar_modelo_simples(prompt_extracao, gemini_token, max_tokens=50, temperature=0.2)
            if not fato_extraido:
                return
            fato_extraido = fato_extraido.strip()
            
            if fato_extraido and fato_extraido.upper() != "NENHUM" and len(fato_extraido) > 5:
                # Adiciona o fato à lista do canal
                if channel_id not in self.channel_facts:
                    self.channel_facts[channel_id] = []
                
                # Evita duplicatas
                if fato_extraido not in self.channel_facts[channel_id]:
                    self.channel_facts[channel_id].append(fato_extraido)
                    
                    # Mantém apenas os últimos 20 fatos
                    if len(self.channel_facts[channel_id]) > 20:
                        self.channel_facts[channel_id].pop(0)
                    
                    registrar_log(f"Novo fato aprendido no canal {channel_id}: {fato_extraido}", 'info')
                    
        except Exception as e:
            registrar_log(f"Erro ao aprender fato: {e}", 'warning')

# Função 'setup' obrigatória
async def setup(bot: commands.Bot):
    await bot.add_cog(Chat(bot))
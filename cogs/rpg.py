import random
from pathlib import Path
from typing import Optional

import discord
from discord import app_commands
from discord.ext import commands

from constants import (
    dados_regex,
    gifs_anime,
    gifs_peni_parker_brava,
    gifs_um_natural,
    numero_max_de_campanhas,
    respostas_peni_parker,
)
from utils import FICHAS_DIR, INVENTARIOS_DIR, registrar_log


async def processar_rolagem(
    dados: str,
    interaction: Optional[discord.Interaction] = None,
    message: Optional[discord.Message] = None,
):
    """Processa uma string de rolagem de dados (ex: 2d20+5)."""
    try:
        if not any("d" in parte[0] for parte in dados_regex.findall(dados)):
            return

        if message:
            registrar_log(f"Processando rolagem: {dados} por {message.author}", "info")

        partes = dados_regex.findall(dados)
        total = 0
        detalhes: list[str] = []
        primeiro_dado = True
        natural_20 = False
        natural_1 = False

        for rolagem, numero in partes:
            if rolagem:
                operador = "+"
                if rolagem.startswith(("+", "-")):
                    operador = rolagem[0]
                    rolagem = rolagem[1:]

                qtd, faces = map(int, rolagem.split("d"))

                if qtd > 100 or faces > 1000:
                    resposta_erro = random.choice(respostas_peni_parker)
                    if interaction and not interaction.response.is_done():
                        await interaction.response.send_message(resposta_erro, ephemeral=False)
                    elif message:
                        await message.reply(resposta_erro, mention_author=True)

                    canal = interaction.channel if interaction else message.channel if message else None
                    if canal:
                        await canal.send(random.choice(gifs_peni_parker_brava))
                    return

                resultados = sorted(random.randint(1, faces) for _ in range(qtd))
                soma_rolagem = sum(resultados)

                if rolagem == "1d20" and 20 in resultados:
                    natural_20 = True
                if rolagem == "1d20" and 1 in resultados:
                    natural_1 = True

                total = total + soma_rolagem if operador == "+" else total - soma_rolagem

                detalhe_str = f"{rolagem}: {resultados} = ``{soma_rolagem}``"
                if qtd > 100:
                    detalhe_str = f"{rolagem}: ``{soma_rolagem}`` (dados demais...)"

                if primeiro_dado:
                    detalhes.append(detalhe_str)
                    primeiro_dado = False
                else:
                    detalhes.append(f"{operador}{detalhe_str}")

            elif numero:
                valor = int(numero)
                sinal = "+" if valor >= 0 else "-"
                total += valor
                detalhes.append(f"{sinal}``{abs(valor)}``")

        total_final = max(total, 1)
        resposta = f"🎲 **Resultado das rolagens:**\n{''.join(detalhes)}\n**Total:** ``{total_final}``"

        if natural_20:
            resposta += "\n\n🎉 **VINTE NATURAL!** 🎉"
        if natural_1:
            resposta += "\n\n**UM NATURALKKKKKKKKKKKKKKKKKKKK, lastimável**"

        if interaction:
            if not interaction.response.is_done():
                await interaction.response.send_message(resposta)
            else:
                await interaction.followup.send(resposta)

            if natural_20:
                await interaction.followup.send(random.choice(gifs_anime))
            elif natural_1:
                await interaction.followup.send(random.choice(gifs_um_natural))
        elif message:
            await message.reply(resposta)
            if natural_20:
                await message.channel.send(random.choice(gifs_anime))
            elif natural_1:
                await message.channel.send(random.choice(gifs_um_natural))

    except Exception as exc:  # pylint: disable=broad-except
        registrar_log(f"Erro ao processar rolagem '{dados}': {exc}", "error")
        erro_msg = f"❌ **Erro ao processar a rolagem:** {exc}"
        if interaction and not interaction.response.is_done():
            await interaction.response.send_message(erro_msg, ephemeral=False)
        elif message:
            await message.reply(erro_msg)


def normalizar_nome_item(nome: str) -> str:
    return nome.lower().strip().title()


def _inventario_path(user_id: int, campanha: str) -> Path:
    return INVENTARIOS_DIR / f"inventario_{user_id}_{campanha}.txt"


def _ficha_path(user_id: int, campanha: str) -> Path:
    return FICHAS_DIR / f"ficha_{user_id}_{campanha}.txt"


def ler_inventario(user_id: int, campanha: str) -> dict[str, int]:
    inventario: dict[str, int] = {}
    caminho = _inventario_path(user_id, campanha)
    try:
        with caminho.open("r", encoding="utf-8") as arquivo:
            for linha in arquivo:
                try:
                    item, quantidade = linha.strip().split(":", 1)
                    inventario[normalizar_nome_item(item)] = int(quantidade)
                except (ValueError, TypeError):
                    continue
    except FileNotFoundError:
        pass
    return inventario


def escrever_inventario(user_id: int, campanha: str, inventario: dict[str, int]):
    caminho = _inventario_path(user_id, campanha)
    try:
        with caminho.open("w", encoding="utf-8") as arquivo:
            arquivo.writelines(f"{item}:{qtd}\n" for item, qtd in inventario.items())
    except IOError as exc:
        registrar_log(f"Erro ao salvar inventário: {exc}", "error")


def ler_ficha(user_id: int, campanha: str) -> Optional[str]:
    caminho = _ficha_path(user_id, campanha)
    try:
        with caminho.open("r", encoding="utf-8") as arquivo:
            return arquivo.read().strip()
    except (FileNotFoundError, IOError):
        return None


def escrever_ficha(user_id: int, campanha: str, texto: str) -> bool:
    caminho = _ficha_path(user_id, campanha)
    try:
        with caminho.open("w", encoding="utf-8") as arquivo:
            arquivo.write(texto.strip())
        return True
    except IOError as exc:
        registrar_log(f"Erro ao salvar ficha: {exc}", "error")
        return False


def obter_campanhas(user_id: int) -> list[str]:
    prefixo = f"inventario_{user_id}_"
    campanhas = {arquivo.stem[len(prefixo):] for arquivo in INVENTARIOS_DIR.glob(f"{prefixo}*.txt")}
    return sorted(campanhas)


class RPG(commands.Cog):
    """Comandos de suporte à mesa de RPG."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.campanha_selecionada: dict[int, str] = {}

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author == self.bot.user:
            return

        if self.bot.user and self.bot.user.mentioned_in(message):
            return

        if message.content.startswith('/'):
            return

        if dados_regex.match(message.content.lower()):
            await processar_rolagem(message.content, message=message)

    @app_commands.command(name="criar_campanha", description="Cria uma nova campanha.")
    async def criar_campanha(self, interaction: discord.Interaction, nome: str):
        user_id = interaction.user.id
        campanhas = obter_campanhas(user_id)

        if len(campanhas) >= numero_max_de_campanhas:
            await interaction.response.send_message(
                f"Você já atingiu o limite de {numero_max_de_campanhas} campanhas.",
                ephemeral=True,
            )
            return

        if nome in campanhas:
            await interaction.response.send_message(
                f"Já existe uma campanha com o nome '{nome}'.", ephemeral=True
            )
            return

        escrever_inventario(user_id, nome, {})
        escrever_ficha(user_id, nome, "")
        await interaction.response.send_message(
            f"Campanha '{nome}' criada com sucesso! 🕷️", ephemeral=False
        )

    @app_commands.command(name="remover_campanha", description="Remove uma campanha existente.")
    async def remover_campanha(self, interaction: discord.Interaction, nome: str):
        user_id = interaction.user.id
        campanhas = obter_campanhas(user_id)

        if nome not in campanhas:
            await interaction.response.send_message(
                f"Campanha '{nome}' não encontrada.", ephemeral=True
            )
            return

        _inventario_path(user_id, nome).unlink(missing_ok=True)
        _ficha_path(user_id, nome).unlink(missing_ok=True)

        if self.campanha_selecionada.get(user_id) == nome:
            del self.campanha_selecionada[user_id]

        await interaction.response.send_message(
            f"Campanha '{nome}' removida com sucesso!", ephemeral=False
        )

    @app_commands.command(name="selecionar_campanha", description="Seleciona uma campanha para usar.")
    async def selecionar_campanha(self, interaction: discord.Interaction, nome: str):
        user_id = interaction.user.id
        campanhas = obter_campanhas(user_id)

        if nome not in campanhas:
            await interaction.response.send_message(
                f"Campanha '{nome}' não encontrada.", ephemeral=True
            )
            return

        self.campanha_selecionada[user_id] = nome
        await interaction.response.send_message(
            f"Campanha '{nome}' selecionada! ;)", ephemeral=False
        )

    @app_commands.command(name="listar_campanhas", description="Lista todas as suas campanhas.")
    async def listar_campanhas(self, interaction: discord.Interaction):
        user_id = interaction.user.id
        campanhas = obter_campanhas(user_id)

        if campanhas:
            resposta = "Suas campanhas:\n" + "\n".join(f"- {camp}" for camp in campanhas)
            await interaction.response.send_message(resposta, ephemeral=False)
        else:
            await interaction.response.send_message(
                "Você não tem nenhuma campanha criada.", ephemeral=True
            )

    @app_commands.command(name="add", description="Adiciona um item ao inventário da campanha selecionada.")
    async def add_item(self, interaction: discord.Interaction, nome: str, quantidade: int):
        user_id = interaction.user.id

        campanha = self.campanha_selecionada.get(user_id)
        if not campanha:
            await interaction.response.send_message(
                "Nenhuma campanha selecionada. Use /selecionar_campanha.", ephemeral=True
            )
            return

        inventario = ler_inventario(user_id, campanha)
        nome_normalizado = normalizar_nome_item(nome)
        inventario[nome_normalizado] = inventario.get(nome_normalizado, 0) + quantidade

        escrever_inventario(user_id, campanha, inventario)
        await interaction.response.send_message(
            f"Adicionado {quantidade}x {nome} ao inventário da campanha '{campanha}'.",
            ephemeral=False,
        )

    @app_commands.command(name="remover", description="Remove um item do inventário da campanha selecionada.")
    async def remover_item(self, interaction: discord.Interaction, nome: str, quantidade: int):
        user_id = interaction.user.id

        campanha = self.campanha_selecionada.get(user_id)
        if not campanha:
            await interaction.response.send_message(
                "Nenhuma campanha selecionada. Use /selecionar_campanha.", ephemeral=True
            )
            return

        inventario = ler_inventario(user_id, campanha)
        nome_normalizado = normalizar_nome_item(nome)

        if nome_normalizado not in inventario:
            await interaction.response.send_message(
                f"O item {nome} não está no seu inventário.", ephemeral=True
            )
            return

        if inventario[nome_normalizado] < quantidade:
            await interaction.response.send_message(
                f"Você não tem {quantidade}x {nome} para remover.", ephemeral=True
            )
            return

        inventario[nome_normalizado] -= quantidade
        if inventario[nome_normalizado] <= 0:
            del inventario[nome_normalizado]

        escrever_inventario(user_id, campanha, inventario)
        await interaction.response.send_message(
            f"Removido {quantidade}x {nome} do inventário '{campanha}'.",
            ephemeral=False,
        )

    @app_commands.command(name="inventário", description="Mostra o inventário da campanha selecionada.")
    async def mostrar_inventario(self, interaction: discord.Interaction):
        user_id = interaction.user.id

        campanha = self.campanha_selecionada.get(user_id)
        if not campanha:
            await interaction.response.send_message(
                "Nenhuma campanha selecionada. Use /selecionar_campanha.", ephemeral=True
            )
            return

        inventario = ler_inventario(user_id, campanha)

        if not inventario:
            await interaction.response.send_message(
                f"O inventário da campanha '{campanha}' está vazio.", ephemeral=False
            )
            return

        resposta = f"Inventário da campanha '{campanha}':\n"
        resposta += "\n".join(f"* {quantidade}x {item}" for item, quantidade in inventario.items())
        await interaction.response.send_message(resposta, ephemeral=False)

    @app_commands.command(name="registrar_ficha", description="Registra uma ficha na campanha selecionada.")
    async def registrar_ficha(self, interaction: discord.Interaction, texto: str):
        user_id = interaction.user.id

        campanha = self.campanha_selecionada.get(user_id)
        if not campanha:
            await interaction.response.send_message(
                "Nenhuma campanha selecionada. Use /selecionar_campanha.", ephemeral=True
            )
            return

        escrever_ficha(user_id, campanha, texto)
        await interaction.response.send_message(
            f"Ficha registrada na campanha '{campanha}': {texto}", ephemeral=True
        )

    @app_commands.command(name="ficha", description="Mostra a ficha da campanha selecionada.")
    async def mostrar_ficha(self, interaction: discord.Interaction):
        user_id = interaction.user.id

        campanha = self.campanha_selecionada.get(user_id)
        if not campanha:
            await interaction.response.send_message(
                "Nenhuma campanha selecionada. Use /selecionar_campanha.", ephemeral=True
            )
            return

        ficha = ler_ficha(user_id, campanha)

        if ficha:
            await interaction.response.send_message(
                f"Ficha da campanha '{campanha}': {ficha}", ephemeral=False
            )
        else:
            await interaction.response.send_message(
                f"Nenhuma ficha registrada na campanha '{campanha}'.", ephemeral=True
            )

    @app_commands.command(name="rolar", description="Rola dados no formato XdY+Z ou XdY-Z")
    async def rolar_dados(self, interaction: discord.Interaction, dados: str):
        await processar_rolagem(dados, interaction=interaction)


async def setup(bot: commands.Bot):
    await bot.add_cog(RPG(bot))
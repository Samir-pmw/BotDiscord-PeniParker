"""Funções utilitárias compartilhadas pelos cogs do bot."""

from __future__ import annotations

import textwrap
import base64

import asyncio
import json
import logging
import os
import random
import re
import threading
import time
from pathlib import Path
from typing import Any, Dict, Optional
from urllib.parse import quote

import discord
import google.genai as genai
from google.genai import types
import requests
from bs4 import BeautifulSoup

from constants import PERSONALIDADE_LAIN

# ----------------------------------------------------------------------------
# Caminhos e diretórios compartilhados
# ----------------------------------------------------------------------------

# Configuração de diretórios (Local na pasta do bot)
PROJECT_ROOT = Path(__file__).parent
APPDATA_BASE = PROJECT_ROOT / "data"
LOG_DIR = PROJECT_ROOT / "logs"
LOG_FILE_PATH = LOG_DIR / "bot_logs.txt"

MUSIC_CACHE_DIR = APPDATA_BASE / "music_cache"
FICHAS_DIR = APPDATA_BASE / "fichas"
INVENTARIOS_DIR = APPDATA_BASE / "inventarios"
KNOWLEDGE_DIR = APPDATA_BASE / "knowledge"


def ensure_appdata_dirs() -> Dict[str, Path]:
    created = {}
    for directory in (MUSIC_CACHE_DIR, FICHAS_DIR, INVENTARIOS_DIR, LOG_DIR, KNOWLEDGE_DIR):
        directory.mkdir(parents=True, exist_ok=True)
        created[directory.name] = directory
    return created


ensure_appdata_dirs()
LOG_FILE_PATH = LOG_DIR / "bot_logs.txt"


def get_appdata_locations() -> Dict[str, Path | bool]:
    return {
        "logical": APPDATA_BASE,
        "resolved": APPDATA_BASE.resolve(),
        "is_virtualized": False,
    }


# ----------------------------------------------------------------------------
# Logging helpers
# ----------------------------------------------------------------------------

def registrar_log(mensagem: str, nivel: str = "info") -> None:
    lvl = nivel.lower()
    prefix = {"info": "[INFO]", "warning": "[WARN]", "error": "[ERROR]"}.get(lvl, "[INFO]")
    try:
        print(f"{prefix} {mensagem}")
    except Exception:  # pragma: no cover
        pass
    if lvl == "warning":
        logging.warning(mensagem)
    elif lvl == "error":
        logging.error(mensagem)
    else:
        logging.info(mensagem)


async def send_temp_message(channel: discord.abc.Messageable, content: str, delete_after: float = 3.0) -> None:
    msg = await channel.send(content)
    await asyncio.sleep(delete_after)
    try:
        await msg.delete()
    except (discord.Forbidden, discord.NotFound):
        pass

def descobrir_modelos_disponiveis(gemini_token: str) -> list[str]:
    """Descobre e lista os modelos Gemini disponíveis para a API key."""
    try:
        client = genai.Client(api_key=gemini_token)
        modelos = [m.name for m in client.models.list()]
        registrar_log(f"Modelos Gemini disponíveis ({len(modelos)}): {modelos}", "info")
        return modelos
    except Exception as exc:
        registrar_log(f"Erro ao listar modelos Gemini: {exc}", "warning")
        return []

async def send_temp_followup(
    interaction: discord.Interaction,
    content: str,
    delete_after: float = 3.0,
) -> None:
    msg = await interaction.followup.send(content, ephemeral=False)
    await asyncio.sleep(delete_after)
    try:
        await msg.delete()
    except (discord.Forbidden, discord.NotFound):
        registrar_log("Sem permissão para deletar followup temporário.", "warning")


def split_text(text: str, limit: int = 1900) -> list[str]:
    """Divide um texto em partes respeitando o limite do Discord e quebras de linha."""
    if not text:
        return []
    if len(text) <= limit:
        return [text]
    
    parts = []
    # Divide por quebras de linha primeiro
    lines = text.split('\n')
    current_part = ""
    
    for line in lines:
        if len(current_part) + len(line) + 1 <= limit:
            if current_part:
                current_part += '\n' + line
            else:
                current_part = line
        else:
            if current_part:
                parts.append(current_part)
            
            # Se a linha sozinha for maior que o limite
            if len(line) > limit:
                # Divide a linha em pedaços
                for chunk in textwrap.wrap(line, width=limit, break_long_words=True, replace_whitespace=False):
                    parts.append(chunk)
                current_part = ""
            else:
                current_part = line
                
    if current_part:
        parts.append(current_part)
        
    return parts


# ----------------------------------------------------------------------------
# Tenor GIF search
# ----------------------------------------------------------------------------

def buscar_gif(tenor_token: Optional[str], search_term: str, limit: int = 5) -> Optional[str]:
    if not tenor_token:
        registrar_log("Chave do Tenor ausente.", "warning")
        return None
    try:
        response = requests.get(
            "https://tenor.googleapis.com/v2/search",
            params={
                "q": search_term,
                "key": tenor_token,
                "client_key": "lain_iwakura_bot",
                "limit": limit,
                "media_filter": "gif",
            },
            timeout=10,
        )
        response.raise_for_status()
        data = response.json()
        results = data.get("results", [])
        if not results:
            return None
        choice = random.choice(results[:limit])
        return choice.get("media_formats", {}).get("gif", {}).get("url")
    except Exception as exc:  # pylint: disable=broad-except
        registrar_log(f"Erro Tenor: {exc}", "error")
        return None


# ----------------------------------------------------------------------------
# OP.GG scraping helpers
# ----------------------------------------------------------------------------

def normalize_opgg_region(region: str) -> str:
    mapping = {
        "br": "br",
        "br1": "br",
        "na": "na",
        "na1": "na",
        "euw": "euw",
        "euw1": "euw",
        "eune": "eune",
        "eun1": "eune",
        "kr": "kr",
        "lan": "lan",
        "la1": "lan",
        "las": "las",
        "la2": "las",
        "oce": "oce",
        "oc1": "oce",
        "jp": "jp",
        "ru": "ru",
        "tr": "tr",
    }
    return mapping.get((region or "br").lower(), "br")


def _http_get(url: str) -> Optional[str]:
    try:
        resp = requests.get(
            url,
            headers={
                "User-Agent": "Mozilla/5.0 (LainBot)",
                "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.8",
            },
            timeout=8,
        )
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        return resp.text
    except Exception as exc:  # pylint: disable=broad-except
        registrar_log(f"HTTP GET falhou ({url}): {exc}", "warning")
        return None


def _parse_lol_opgg(html: str, fallback_name: str) -> Dict[str, Any]:
    soup = BeautifulSoup(html, "html.parser")
    data: Dict[str, Any] = {"summoner_name": fallback_name}
    name = soup.select_one(".summoner-name, .profile__name, h1")
    if name and name.get_text(strip=True):
        data["summoner_name"] = name.get_text(strip=True)
    avatar = soup.select_one("img.profile-icon, img.summoner-profile-icon, .profile-icon img")
    if avatar and avatar.get("src"):
        data["avatar_url"] = avatar.get("src")
    tier = soup.select_one(".tier, .rank, .summary__tier, .tier__rank")
    if tier:
        data["rank"] = tier.get_text(strip=True)
    winrate = soup.find(string=re.compile(r"Win\s*Rate", re.I))
    if winrate:
        m = re.search(r"(\d{1,3}%)", str(winrate))
        if m:
            data["winrate"] = m.group(1)
    games = soup.select(".game-item, .match__item, .recent-game-item")
    if games:
        data["matches"] = f"{len(games)} partidas recentes"
    page_text = soup.get_text(" ", strip=True).lower()
    if "perfil privado" in page_text or "profile is private" in page_text:
        data["private"] = True
    return data


def _parse_valorant_opgg(html: str, riot_id: str) -> Dict[str, Any]:
    soup = BeautifulSoup(html, "html.parser")
    data: Dict[str, Any] = {"riot_id": riot_id}
    rank = soup.select_one(".rank, .mmr, .summary__tier")
    if rank:
        data["rank"] = rank.get_text(strip=True)
    kda = soup.find(string=re.compile(r"\b\d+/\d+/\d+\b"))
    if kda:
        data["kda"] = str(kda).strip()
    return data


def obter_opgg_resumo(summoner_name: str, region: str, riot_id: Optional[str]) -> Optional[Dict[str, Any]]:
    region = normalize_opgg_region(region)
    opgg_name = summoner_name
    if riot_id and "#" in riot_id:
        game, tag = riot_id.split("#", 1)
        opgg_name = f"{game}-{tag}"
    lol_url = f"https://www.op.gg/lol/summoners/{region}/{quote(opgg_name)}"
    html = _http_get(lol_url)
    result: Dict[str, Any] = {}
    if html:
        result["lol"] = _parse_lol_opgg(html, opgg_name)
    else:
        result["lol"] = {"summoner_name": opgg_name, "not_found": True}
    if riot_id and "#" in riot_id:
        user, tag = riot_id.split("#", 1)
        val_url = f"https://valorant.op.gg/profile/{quote(user)}-{quote(tag)}"
        vhtml = _http_get(val_url)
        if vhtml:
            result["valorant"] = _parse_valorant_opgg(vhtml, riot_id)
    return result if result else None


# ----------------------------------------------------------------------------
# Gemini helpers + Wikipedia knowledge base
# ----------------------------------------------------------------------------

COMMON_STOPWORDS_PT = {
    "você", "ele", "ela", "eles", "elas", "nós", "meu", "minha", "seu", "sua",
    "dele", "dela", "nosso", "essa", "esse", "isso", "aquele", "aquela", "aquilo",
    "ser", "estar", "ter", "fazer", "dizer", "ir", "ver", "dar", "saber", "poder",
    "querer", "ficar", "vir", "levar", "olhar", "falar", "sobre", "para", "com",
    "sem", "por", "em", "de", "do", "da", "no", "na", "ao", "aos", "às",
    "muito", "pouco", "mais", "menos", "bem", "mal", "sempre", "nunca", "talvez",
    "ainda", "já", "agora", "então", "porém", "também", "aqui", "ali", "lá",
}

COMMON_STOPWORDS_EN = {
    "the", "this", "that", "with", "from", "about", "your", "have", "has", "had",
    "been", "were", "was", "their", "there", "just", "like", "really", "make",
    "into", "onto", "over", "under", "near", "who", "what", "when", "where",
    "why", "which", "because", "while", "during", "after", "before", "such",
    "each", "other", "more", "most", "some", "many", "also", "only", "very",
}

COMMON_STOPWORDS = {word.lower() for word in (COMMON_STOPWORDS_PT | COMMON_STOPWORDS_EN)}


class WikipediaKnowledgeBase:
    SUMMARY_ENDPOINT = "https://{lang}.wikipedia.org/api/rest_v1/page/summary/{title}"
    SEARCH_ENDPOINT = "https://{lang}.wikipedia.org/w/api.php"
    SUPPORTED_LANGS = ("pt", "en", "es")

    def __init__(self, base_dir: Path, max_entries: int = 4000):
        self.base_dir = base_dir
        self.base_dir.mkdir(parents=True, exist_ok=True)
        self.index_path = self.base_dir / "wikipedia_index.json"
        self.max_entries = max_entries
        self._lock = threading.Lock()
        self._cache = self._load_cache()

    def _load_cache(self) -> Dict[str, Dict[str, Any]]:
        if not self.index_path.exists():
            return {}
        try:
            with self.index_path.open("r", encoding="utf-8") as handle:
                data = json.load(handle)
            return data if isinstance(data, dict) else {}
        except Exception as exc:  # pylint: disable=broad-except
            registrar_log(f"Falha ao carregar cache wiki: {exc}", "warning")
            return {}

    def _save_cache(self) -> None:
        try:
            with self.index_path.open("w", encoding="utf-8") as handle:
                json.dump(self._cache, handle, ensure_ascii=False, indent=2)
        except Exception as exc:  # pylint: disable=broad-except
            registrar_log(f"Falha ao salvar cache wiki: {exc}", "warning")

    def _key(self, term: str, lang: str) -> str:
        return f"{lang.lower()}:{term.strip().lower()}"

    def _get(self, term: str, lang: str) -> Optional[Dict[str, Any]]:
        key = self._key(term, lang)
        with self._lock:
            entry = self._cache.get(key)
            if entry:
                entry["accessed_at"] = time.time()
            return dict(entry) if entry else None

    def _store(self, term: str, lang: str, payload: Dict[str, Any]) -> None:
        key = self._key(term, lang)
        with self._lock:
            self._cache[key] = {
                "term": term,
                "lang": lang,
                "summary": payload.get("summary"),
                "url": payload.get("url"),
                "updated_at": time.time(),
                "accessed_at": time.time(),
            }
            if len(self._cache) > self.max_entries:
                victims = sorted(
                    self._cache.items(),
                    key=lambda item: item[1].get("accessed_at", 0),
                )[: len(self._cache) - self.max_entries]
                for victim_key, _ in victims:
                    self._cache.pop(victim_key, None)
            self._save_cache()

    def _headers(self) -> Dict[str, str]:
        return {
            "User-Agent": "LainBot/2.0 (+https://papiro.dev)",
            "Accept": "application/json",
        }

    def _search_titles(self, term: str, lang: str) -> list[str]:
        try:
            resp = requests.get(
                self.SEARCH_ENDPOINT.format(lang=lang),
                params={
                    "action": "query",
                    "format": "json",
                    "list": "search",
                    "srsearch": term,
                    "srlimit": 3,
                },
                headers=self._headers(),
                timeout=8,
            )
            resp.raise_for_status()
            data = resp.json()
            return [item.get("title") for item in data.get("query", {}).get("search", []) if item.get("title")]
        except Exception as exc:  # pylint: disable=broad-except
            registrar_log(f"Busca wiki falhou para '{term}' ({lang}): {exc}", "warning")
            return []

    def _fetch_summary(self, title: str, lang: str) -> Optional[Dict[str, Any]]:
        url = self.SUMMARY_ENDPOINT.format(lang=lang, title=quote(title.replace(" ", "_")))
        try:
            resp = requests.get(url, headers=self._headers(), timeout=8)
            if resp.status_code == 404:
                return None
            resp.raise_for_status()
            data = resp.json()
            extract = data.get("extract") or data.get("description")
            if not extract:
                return None
            page_url = (
                data.get("content_urls", {}).get("desktop", {}).get("page")
                or f"https://{lang}.wikipedia.org/wiki/{quote(title)}"
            )
            return {"title": data.get("title", title), "summary": extract.strip(), "url": page_url}
        except Exception as exc:  # pylint: disable=broad-except
            registrar_log(f"Resumo wiki falhou para '{title}' ({lang}): {exc}", "warning")
            return None

    def fetch_summary(self, term: str, lang: str, gemini_token: Optional[str]) -> Optional[str]:
        term = term.strip()
        lang = (lang or "pt").split("-")[0].lower()
        cached = self._get(term, lang)
        if cached:
            return cached.get("summary")
        languages = [lang] + [l for l in self.SUPPORTED_LANGS if l != lang]
        for current in languages:
            titles = self._search_titles(term, current)
            for title in titles:
                payload = self._fetch_summary(title, current)
                if not payload:
                    continue
                if gemini_token:
                    refined = refine_summary_with_gemini(term, payload["summary"], gemini_token)
                    if refined:
                        payload["summary"] = refined
                self._store(term, current, payload)
                return payload.get("summary")
        return None

    def describe(self) -> Dict[str, Any]:
        with self._lock:
            per_lang: Dict[str, int] = {}
            for entry in self._cache.values():
                lang = entry.get("lang", "pt")
                per_lang[lang] = per_lang.get(lang, 0) + 1
            return {"entries": len(self._cache), "per_language": per_lang, "index": str(self.index_path)}


WIKI_KB = WikipediaKnowledgeBase(KNOWLEDGE_DIR)


def refine_summary_with_gemini(term: str, text: str, gemini_token: str) -> Optional[str]:
    if not gemini_token or not text:
        return None
    prompt = f"Resuma em 3 frases objetivas o verbete sobre '{term}'.\n{text[:2000]}"
    return _tentar_modelo_simples(prompt, gemini_token, max_tokens=200, temperature=0.3)


def buscar_wikipedia(termo: str, lang: str = "pt", gemini_token: Optional[str] = None) -> Optional[str]:
    resumo = WIKI_KB.fetch_summary(termo, lang, gemini_token)
    if resumo:
        registrar_log(f"Wikipedia pronta para '{termo}' ({lang})", "info")
    return resumo


def get_wikipedia_cache_stats() -> Dict[str, Any]:
    return WIKI_KB.describe()


# ----------------------------------------------------------------------------
# Gemini resposta com contexto
# ----------------------------------------------------------------------------

def _safe_float(env_name: str, default: float) -> float:
    try:
        return float(os.getenv(env_name, default))
    except ValueError:
        return default


def _safe_int(env_name: str, default: int, min_value: int, max_value: int) -> int:
    try:
        value = int(os.getenv(env_name, default))
        return max(min_value, min(max_value, value))
    except ValueError:
        return default


GENERATION_CONFIG = {
    "temperature": _safe_float("GEMINI_TEMPERATURE", 0.6),
    "top_p": _safe_float("GEMINI_TOP_P", 0.9),
    "top_k": _safe_int("GEMINI_TOP_K", 40, 1, 128),
    "max_output_tokens": _safe_int("GEMINI_MAX_OUTPUT_TOKENS", 600, 32, 2048),
}

MODEL_PRIORITIES = [
    "models/gemini-3.1-flash-lite-preview",   # 25/500 ✅
    "models/gemini-3-flash-preview",           # 1/20
    "models/gemini-2.5-flash-lite",            # fallback
    "models/gemini-2.0-flash",                 # fallback
    "models/gemini-2.0-flash-lite",            # fallback
    "models/gemini-2.5-flash",                 # último recurso
]

def _extrair_texto_gemini(resposta) -> str:
    """Extrai o texto da resposta do Gemini, lidando com segurança e erros."""
    try:
        if not resposta:
            return ""
        # O novo SDK já fornece .text que resolve candidatos
        return (resposta.text or "").strip()
    except Exception as exc:
        registrar_log(f"Erro ao extrair texto do Gemini: {exc}", "warning")
        return ""


def _is_model_unavailable_error(exc: Exception) -> bool:
    """Retorna True se o erro indica que o modelo não existe ou foi descontinuado."""
    msg = str(exc).lower()
    # NÃO incluir "resource has been exhausted" aqui — essa é mensagem de quota, não de modelo inexistente
    return any(kw in msg for kw in (
        "not found", "deprecated", "does not exist",
        "model not found", "is not supported",
    ))


def _is_quota_error(exc: Exception) -> bool:
    """Retorna True se o erro indica quota/rate limit."""
    msg = str(exc).lower()
    return any(kw in msg for kw in (
        "429", "quota", "resource_exhausted", "rate limit",
        "resource has been exhausted",  # Mensagem padrão do Google para quota esgotada
    ))


def _tentar_modelo_com_imagem(
    model_name: str,
    texto: str,
    img_b64: str,
    content_type: str,
    gemini_token: str
) -> Optional[str]:
    try:
        client = genai.Client(api_key=gemini_token)
        # Decodifica base64 para bytes se necessário
        img_bytes = base64.b64decode(img_b64) if isinstance(img_b64, str) else img_b64
        response = client.models.generate_content(
            model=model_name,
            contents=[
                types.Part.from_bytes(data=img_bytes, mime_type=content_type),
                texto.strip()
            ],
            config=types.GenerateContentConfig(
                system_instruction=PERSONALIDADE_LAIN,
                temperature=GENERATION_CONFIG["temperature"],
                top_p=GENERATION_CONFIG["top_p"],
                top_k=GENERATION_CONFIG["top_k"],
                max_output_tokens=GENERATION_CONFIG["max_output_tokens"],
            )
        )
        texto_resp = _extrair_texto_gemini(response)
        if texto_resp:
            return texto_resp
    except Exception as exc:
        if _is_quota_error(exc):
            registrar_log(f"Quota esgotada para {model_name} (imagem).", "warning")
        elif _is_model_unavailable_error(exc):
            registrar_log(f"Modelo {model_name} não suporta visão, pulando.", "warning")
        else:
            registrar_log(f"Erro Gemini imagem ({model_name}): {exc}", "warning")
    return None

def obter_resposta_com_imagem(texto: str, img_b64: str, content_type: str, gemini_token: str) -> Optional[str]:
    modelos_visao = [
        "models/gemini-3.1-flash-lite-preview",  
        "models/gemini-3-flash-preview",
        "models/gemini-2.5-flash-lite",
        "models/gemini-2.5-flash",
    ]
    for model_name in modelos_visao:
        resultado = _tentar_modelo_com_imagem(model_name, texto, img_b64, content_type, gemini_token)
        if resultado:
            return resultado
    return None


def _tentar_modelo(model_name: str, entrada: str, gemini_token: str) -> Optional[str]:
    try:
        client = genai.Client(api_key=gemini_token)
        response = client.models.generate_content(
            model=model_name,
            contents=entrada.strip(),
            config=types.GenerateContentConfig(
                system_instruction=PERSONALIDADE_LAIN,
                temperature=GENERATION_CONFIG["temperature"],
                top_p=GENERATION_CONFIG["top_p"],
                top_k=GENERATION_CONFIG["top_k"],
                max_output_tokens=GENERATION_CONFIG["max_output_tokens"],
            )
        )
        texto = _extrair_texto_gemini(response)
        if texto:
            return texto
    except Exception as exc:  # pylint: disable=broad-except
        err_msg = str(exc)
        if _is_quota_error(exc):
            registrar_log(f"Quota esgotada para {model_name}, tentando próximo.", "warning")
        elif _is_model_unavailable_error(exc):
            registrar_log(f"Modelo {model_name} indisponível ou descontinuado, pulando. Erro: {err_msg[:120]}", "warning")
        else:
            registrar_log(f"Erro Gemini ({model_name}): {err_msg}", "warning")
    return None


def _tentar_modelo_simples(
    prompt: str,
    gemini_token: str,
    max_tokens: int = 50,
    temperature: float = 0.1,
) -> Optional[str]:
    """Tenta obter resposta simples (sem system instruction) percorrendo MODEL_PRIORITIES."""
    config = {"temperature": temperature, "max_output_tokens": max_tokens}
    for model_name in MODEL_PRIORITIES:
        try:
            client = genai.Client(api_key=gemini_token)
            response = client.models.generate_content(
                model=model_name,
                contents=prompt.strip(),
                config=types.GenerateContentConfig(
                    temperature=temperature,
                    max_output_tokens=max_tokens,
                )
            )
            text = _extrair_texto_gemini(response)
            if text:
                return text
        except Exception as exc:  # pylint: disable=broad-except
            err_msg = str(exc)
            if _is_quota_error(exc):
                registrar_log(f"Quota esgotada para {model_name}, tentando próximo.", "warning")
                continue
            if _is_model_unavailable_error(exc):
                registrar_log(f"Modelo {model_name} indisponível, tentando próximo. Erro: {err_msg[:120]}", "warning")
                continue
            registrar_log(f"Erro com {model_name}: {err_msg}", "warning")
    return None


def obter_resposta(entrada: str, gemini_token: Optional[str]) -> str:
    if not gemini_token:
        registrar_log("GEMINI_TOKEN ausente.", "error")
        return None

    for model_name in MODEL_PRIORITIES:
        texto = _tentar_modelo(model_name, entrada, gemini_token)
        if texto:
            return texto

    registrar_log("Todos os modelos Gemini falharam.", "error")
    return None


def obter_resposta_com_contexto(entrada: str, gemini_token: Optional[str]) -> str:
    # Sistema de Wikipedia removido - resposta direta e rápida
    return obter_resposta(entrada, gemini_token)


def extrair_termos_para_contexto(texto: str) -> list[str]:
    candidatos: list[str] = []
    for explicit in re.findall(r"\[\[(.+?)\]\]", texto):
        if explicit:
            candidatos.append(explicit.strip())
    for chunk in re.findall(r"((?:[A-ZÁÉÍÓÚÃÕÂÊÔ][\wÁÉÍÓÚÃÕÂÊÔçÇ-]+\s+){0,3}[A-ZÁÉÍÓÚÃÕÂÊÔ][\wÁÉÍÓÚÃÕÂÊÔçÇ-]+)", texto):
        candidatos.append(chunk.strip())
    for token in re.findall(r"\b[\wÀ-ÖØ-öø-ÿ]{4,}\b", texto):
        token_lower = token.lower()
        if token_lower in COMMON_STOPWORDS:
            continue
        if token_lower.isdigit():
            continue
        candidatos.append(token)
    ordered: list[str] = []
    seen: set[str] = set()
    for cand in candidatos:
        key = cand.lower()
        if key in seen:
            continue
        seen.add(key)
        ordered.append(cand)
    return ordered
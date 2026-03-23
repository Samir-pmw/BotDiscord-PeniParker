# Este script serve apenas para invocar o pipreqs que já está instalado
# mas que o Windows não está achando no PATH.

import sys
import os

# --- LISTA DE SEGURANÇA ---
# Se o pipreqs esquecer alguma dessas, nós adicionamos na marra.
BIBLIOTECAS_OBRIGATORIAS = [
    'google-generativeai', # O pipreqs costuma ignorar este
    'discord.py',
    'python-dotenv',
    'spotipy',
    'requests',
    'aiohttp',
    'pynacl', # Necessário para voz
    'yt-dlp'  # Provavelmente você usa para música
]

try:
    from pipreqs import pipreqs
except ImportError:
    print("ERRO: O pipreqs não parece estar instalado neste ambiente.")
    print("Tente rodar: pip install pipreqs")
    sys.exit(1)


# Pega o caminho absoluto da pasta atual
caminho_atual = os.path.abspath(".")
arquivo_reqs = os.path.join(caminho_atual, 'requirements.txt')

print("🚀 Iniciando pipreqs forçado...")
print(f"📂 Varrendo diretório: {caminho_atual}")

# Argumentos para o pipreqs
sys.argv = ['pipreqs', caminho_atual, '--force', '--encoding', 'utf-8']

try:
    # 1. Roda o pipreqs original
    pipreqs.main()
    print("\n✅ Pipreqs finalizado. Iniciando verificação de segurança...")

    # 2. Abre o arquivo gerado para conferir
    if os.path.exists(arquivo_reqs):
        with open(arquivo_reqs, 'r', encoding='utf-8') as f:
            conteudo_atual = f.read()
        
        # 3. Verifica o que faltou e adiciona
        adicionados = []
        with open(arquivo_reqs, 'a', encoding='utf-8') as f:
            for lib in BIBLIOTECAS_OBRIGATORIAS:
                # Checagem simples (se o nome da lib não está no texto)
                if lib.lower() not in conteudo_atual.lower():
                    f.write(f"\n{lib}")
                    adicionados.append(lib)
        
        if adicionados:
            print(f"⚠️ O pipreqs esqueceu algumas libs importantes nas Cogs.")
            print(f"🔧 Corrigido! Adicionei manualmente: {', '.join(adicionados)}")
        else:
            print("✨ O arquivo parece completo!")
            
        print(f"\n📄 ARQUIVO PRONTO EM: {arquivo_reqs}")
        print("Pode copiar para o pendrive!")

except Exception as e:
    print(f"\n❌ Erro crítico: {e}")
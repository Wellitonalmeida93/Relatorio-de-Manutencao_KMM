from playwright.sync_api import sync_playwright
import pandas as pd
import os
import requests
import sys

# ==============================================================
# 🔐 SEGURANÇA: Buscando credenciais via Variáveis de Ambiente
# ==============================================================
USUARIO = os.getenv("KMM_USER")
SENHA = os.getenv("KMM_PASS")

if not USUARIO or not SENHA:
    print("❌ ERRO: Credenciais não encontradas!")
    print("Configure as variáveis KMM_USER e KMM_PASS no seu ambiente ou no GitHub Secrets.")
    sys.exit(1)

def extrair_e_enviar_sheets():
    print("🚀 Iniciando extração do Relatório de Manutenção Externa (Modo Nuvem)...")
    
    with sync_playwright() as p:
        # headless=True e viewport grande para carregar todos os elementos visuais
        navegador = p.chromium.launch(headless=True, slow_mo=50)
        contexto = navegador.new_context(viewport={'width': 1920, 'height': 1080})
        pagina = contexto.new_page()

        print("1. Acessando o KMM e fazendo login...")
        pagina.goto("https://kmm.pizzattolog.com.br/index.cfm")
        pagina.locator("input[type='text']").first.fill(USUARIO)
        campo_senha = pagina.locator("input[type='password']").first
        campo_senha.fill(SENHA)
        campo_senha.press("Enter")

        # Aguarda o sistema ExtJS montar a árvore DOM pesada após o login
        pagina.wait_for_load_state("domcontentloaded")
        pagina.wait_for_timeout(5000)

        # ==============================================================
        # 🛠️ FUNÇÃO ROBUSTA DE CLIQUE (Lida com Iframes e ExtJS)
        # ==============================================================
        def clicar_menu(texto, timeout_segundos=15):
            print(f"   -> Procurando item: '{texto}'...")
            for _ in range(timeout_segundos):
                for frame in pagina.frames:
                    try:
                        elem = frame.get_by_text(texto, exact=False).first
                        if elem.is_visible():
                            elem.click(force=True)
                            print(f"   ✓ Clicado em '{texto}'!")
                            return True
                    except:
                        continue
                pagina.wait_for_timeout(1000) # Espera 1s antes da próxima tentativa
                
            # Se falhar, tira um print para ajudar no debug
            arquivo_erro = f"erro_{texto.replace(' ', '_')}.png"
            pagina.screenshot(path=arquivo_erro)
            raise TimeoutError(f"Falha ao encontrar '{texto}'. Print salvo em: {arquivo_erro}")

        # ==============================================================
        # 🧭 NAVEGAÇÃO NO SISTEMA
        # ==============================================================
        print("2. Navegando até 'Veículos em manutenção'...")
        clicar_menu("Manutenção de Veículos")
        pagina.wait_for_timeout(2000)

        clicar_menu("Veículos em manutenção")
        pagina.wait_for_timeout(3000)

        print("3. Selecionando filtro '--Manutenção Externa--'...")
        filtro_selecionado = False
        for _ in range(10): # Tenta por até 10 segundos
            for frame in pagina.frames:
                try:
                    select_elem = frame.locator("select").first
                    if select_elem.is_visible():
                        select_elem.click(force=True)
                        select_elem.select_option(label="--Manutenção Externa--")
                        filtro_selecionado = True
                        break
                    else:
                        opcao = frame.get_by_text("--Manutenção Externa--", exact=False).first
                        if opcao.is_visible():
                            opcao.click(force=True)
                            filtro_selecionado = True
                            break
                except:
                    continue
            if filtro_selecionado:
                print("   ✓ Filtro selecionado!")
                break
            pagina.wait_for_timeout(1000)

        pagina.wait_for_timeout(2000)

        print("4. Clicando no botão 'Confirmar'...")
        clicar_menu("Confirmar")

        print("5. Aguardando o KMM carregar os dados na tabela...")
        pagina.wait_for_load_state("networkidle")
        pagina.wait_for_timeout(10000) # O ExtJS pode demorar para popular o Grid

        # ==============================================================
        # 📜 EXTRAÇÃO DE DADOS (Scroll e Parse HTML)
        # ==============================================================
        print("6. Rolando a tela para carregar todos os registros...")
        for _ in range(15):
            pagina.keyboard.press("PageDown")
            pagina.wait_for_timeout(150)
            for f in pagina.frames:
                try:
                    f.evaluate("window.scrollBy(0, 1000);")
                    f.evaluate("let s = document.querySelector('.x-grid3-scroller'); if(s) s.scrollTop += 1000;")
                except:
                    pass

        pagina.wait_for_timeout(2000)

        print("7. Capturando a tabela da tela...")
        linhas_brutas = []
        for frame in pagina.frames:
            try:
                # O KMM usa ExtJS (classes .x-grid3-row)
                linhas_html = frame.locator("tr, div.x-grid3-row").all()
                
                for linha in linhas_html:
                    celulas = linha.locator("td, div.x-grid3-col").all_inner_texts()
                    if celulas and len(celulas) > 3:
                        # Substitui quebras de linha DENTRO da célula por espaço
                        celulas_limpas = [texto.replace("\n", " - ").strip() for texto in celulas]
                        linhas_brutas.append(celulas_limpas)
            except Exception:
                continue

        # Fechamos o navegador assim que extraímos os dados do HTML
        navegador.close()

        # ==============================================================
        # 🧹 TRATAMENTO DE DADOS COM PANDAS
        # ==============================================================
        print("8. Tratando e formatando dados com Pandas...")
        dados_para_sheets = {}
        
        if linhas_brutas:
            max_cols = max(len(linha) for linha in linhas_brutas)
            linhas_padronizadas = [linha + [""] * (max_cols - len(linha)) for linha in linhas_brutas]
            
            df_temp = pd.DataFrame(linhas_padronizadas)

            # Localiza dinamicamente onde começa o cabeçalho real
            idx_cabecalho = None
            for idx, row in df_temp.iterrows():
                valores_linha = [str(v).strip().lower() for v in row.values]
                if "frota" in valores_linha and ("num. os" in valores_linha or "placa" in valores_linha):
                    idx_cabecalho = idx
                    break

            if idx_cabecalho is not None:
                print(f"   -> Cabeçalho encontrado na linha {idx_cabecalho + 1}! Limpando tabela...")
                df = df_temp.iloc[idx_cabecalho:].reset_index(drop=True)
                df.columns = [str(c).strip() for c in df.iloc[0].values]
                df = df.iloc[1:].reset_index(drop=True)

                # Limpeza final
                df = df[df[df.columns[0]] != df.columns[0]] # Remove cabeçalhos duplicados no meio da tabela
                df.dropna(how='all', inplace=True)
                df.drop_duplicates(inplace=True)
                df.reset_index(drop=True, inplace=True)

                if not df.empty:
                    matriz = [df.columns.tolist()]
                    matriz.extend(df.fillna("").astype(str).values.tolist())
                    dados_para_sheets["Manutencao Externa"] = matriz
            else:
                print("\n[AVISO] Cabeçalho com 'Frota' e 'Num. OS' não localizado. A tabela pode estar vazia ou o layout mudou.")

        if not dados_para_sheets:
            dados_para_sheets["Sem Registros"] = [
                ["Mensagem"],
                ["Nenhum registro encontrado ou falha na extração no dia de hoje."]
            ]

        # ==============================================================
        # 📤 ENVIO PARA O GOOGLE SHEETS
        # ==============================================================
        print("9. 📤 Enviando para o Google Sheets via App Script...")
        url_sheets = "https://script.google.com/macros/s/AKfycby0XLyYO0x2GftgmFwettc_jZKNEE3yDhO9mpNRLBavsRAHgn4veWWp_uBYhYMZq4nyAQ/exec"
        
        try:
            resposta = requests.post(url_sheets, json=dados_para_sheets, timeout=300)
            resposta.raise_for_status()
            print(f"   ✓ Status do Envio: {resposta.status_code}")
            
            print("\n" + "="*60)
            print(" ✨ PROCESSO CONCLUÍDO COM SUCESSO! ✨")
            print(" 📊 Dados de Manutenção Externa enviados para o Sheets!")
            print("="*60)
        except requests.exceptions.RequestException as e:
            print(f"\n❌ ERRO ao enviar dados para o Sheets: {e}")

if __name__ == "__main__":
    extrair_e_enviar_sheets()

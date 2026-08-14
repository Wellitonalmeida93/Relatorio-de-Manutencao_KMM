from playwright.sync_api import sync_playwright
import pandas as pd
import os
import requests

# ==============================================================
# SEGURANÇA: Buscando credenciais
# ==============================================================
USUARIO = os.getenv("KMM_USER", "matheusd")
SENHA = os.getenv("KMM_PASS", "32825445M@")

def extrair_e_enviar_sheets():
print("🚀 Iniciando extração do Relatório de Manutenção Externa (Modo Nuvem)...")
    
    with sync_playwright() as p:
        # headless=True e viewport grande para não quebrar a tela no GitHub Actions
        navegador = p.chromium.launch(headless=True, slow_mo=100)
        contexto = navegador.new_context(viewport={'width': 1920, 'height': 1080})
        pagina = contexto.new_page()

        print("1. Acessando o KMM e fazendo login...")
        pagina.goto("https://kmm.pizzattolog.com.br/index.cfm")
        pagina.locator("input[type='text']").first.fill(USUARIO)
        campo_senha = pagina.locator("input[type='password']").first
        campo_senha.fill(SENHA)
        campo_senha.press("Enter")

        pagina.wait_for_load_state("networkidle")
        pagina.wait_for_timeout(3000)

        def clicar_menu(texto):
            for frame in pagina.frames:
                try:
                    elem = frame.get_by_text(texto, exact=False).first
                    if elem.is_visible(timeout=1000):
                        elem.click(force=True)
                        return True
                except:
                    continue
            pagina.get_by_text(texto, exact=False).first.click(force=True)

        print("2. Navegando até 'Veículos em manutenção'...")
        clicar_menu("Manutenção de Veículos")
        pagina.wait_for_load_state("networkidle")
        pagina.wait_for_timeout(2000)

        clicar_menu("Veículos em manutenção")
        pagina.wait_for_load_state("networkidle")
        pagina.wait_for_timeout(3000)

        print("3. Selecionando '--Manutenção Externa--'...")
        for frame in pagina.frames:
            try:
                select_elem = frame.locator("select").first
                if select_elem.is_visible(timeout=1000):
                    select_elem.click(force=True)
                    select_elem.select_option(label="--Manutenção Externa--")
                    break
                else:
                    opcao = frame.get_by_text("--Manutenção Externa--", exact=False).first
                    if opcao.is_visible(timeout=1000):
                        opcao.click(force=True)
                        break
            except:
                continue

        pagina.wait_for_timeout(2000)

        print("4. Clicando no botão 'Confirmar' no final da tela...")
        for frame in pagina.frames:
            try:
                btn_confirmar = frame.get_by_text("Confirmar", exact=False).first
                if btn_confirmar.is_visible(timeout=1000):
                    btn_confirmar.scroll_into_view_if_needed()
                    btn_confirmar.click(force=True)
                    break
            except:
                continue

        print("5. Aguardando o KMM carregar os dados...")
        pagina.wait_for_load_state("networkidle")
        pagina.wait_for_timeout(10000)

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
                # O KMM usa ExtJS, onde as linhas geralmente têm a classe .x-grid3-row ou <tr> padrão
                # Vamos buscar as linhas renderizadas no HTML
                linhas_html = frame.locator("tr, div.x-grid3-row").all()
                
                for linha in linhas_html:
                    # Captura o texto de todas as células daquela linha específica
                    celulas = linha.locator("td, div.x-grid3-col").all_inner_texts()
                    
                    if celulas and len(celulas) > 3: # Garante que é uma linha de dados real
                        # Aqui está a mágica: substitui quebras de linha DENTRO da célula por espaço
                        celulas_limpas = [texto.replace("\n", " - ").strip() for texto in celulas]
                        linhas_brutas.append(celulas_limpas)
            except Exception as e:
                continue

        navegador.close()

        print("8. Tratando e formatando dados...")
        dados_para_sheets = {}
        
        if linhas_brutas:
            max_cols = max(len(linha) for linha in linhas_brutas)
            linhas_padronizadas = [linha + [""] * (max_cols - len(linha)) for linha in linhas_brutas]
            
            df_temp = pd.DataFrame(linhas_padronizadas)

            # Procura a linha que contém as colunas "Frota" e "Num. OS"
            idx_cabecalho = None
            for idx, row in df_temp.iterrows():
                valores_linha = [str(v).strip().lower() for v in row.values]
                if "frota" in valores_linha and ("num. os" in valores_linha or "placa" in valores_linha):
                    idx_cabecalho = idx
                    break

            if idx_cabecalho is not None:
                print(f"   -> Cabeçalho encontrado na linha {idx_cabecalho + 1}! Limpando tabela...")
                df = df_temp.iloc[idx_cabecalho:].reset_index(drop=True)
                df.columns = [str(c).strip() for c in df.iloc[0].values]
                df = df.iloc[1:].reset_index(drop=True)

                # Remove repetições acidentais de cabeçalho ou linhas vazias
                df = df[df[df.columns[0]] != df.columns[0]]
                df.dropna(how='all', inplace=True)
                df.drop_duplicates(inplace=True)
                df.reset_index(drop=True, inplace=True)

                if not df.empty:
                    # Prepara a matriz para enviar para a planilha (Cabeçalho + Dados)
                    matriz = [df.columns.tolist()]
                    matriz.extend(df.fillna("").astype(str).values.tolist())
                    
                    # Nome da aba na planilha onde os dados serão colados
                    dados_para_sheets["Manutencao Externa"] = matriz

            else:
                print("\n[ERRO] Cabeçalho com 'Frota' e 'Num. OS' não foi localizado na tabela.")

        if not dados_para_sheets:
            dados_para_sheets["Sem Registros"] = [
                ["Mensagem"],
                ["Nenhum registro encontrado ou falha na extração"]
            ]

        print("9. 📤 Enviando para Google Sheets...")
        url_sheets = "https://script.google.com/macros/s/AKfycby0XLyYO0x2GftgmFwettc_jZKNEE3yDhO9mpNRLBavsRAHgn4veWWp_uBYhYMZq4nyAQ/exec"
        
        resposta = requests.post(
            url_sheets,
            json=dados_para_sheets,
            timeout=300
        )

        print(f"Status do Envio: {resposta.status_code}")
        print(f"Resposta do Servidor: {resposta.text}")

        print("\n" + "="*60)
        print(" ✨ PROCESSO CONCLUÍDO COM SUCESSO!")
        print(" 📊 Dados de Manutenção Externa enviados para o Sheets!")
        print("="*60)

if __name__ == "__main__":
    extrair_e_enviar_sheets()

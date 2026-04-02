import os
import re

file_path = '../Botana/main.py'
with open(file_path, 'r', encoding='utf-8') as f:
    text = f.read()

new_func = """
def _gerar_relatorio_nfs(filtro: str, mes: str, nf_inicio: str, nf_fim: str) -> list[dict]:
    import gspread
    from google.oauth2.service_account import Credentials
    from config import GOOGLE_CREDENTIALS_SHEETS, PLANILHAS
    
    creds = Credentials.from_service_account_file(
        GOOGLE_CREDENTIALS_SHEETS,
        scopes=["https://www.googleapis.com/auth/spreadsheets"]
    )
    gc = gspread.authorize(creds)
    
    out = []
    
    ni = -1
    nf_end_val = -1
    if filtro == "nfs":
        try: ni = int(nf_inicio)
        except: pass
        try: nf_end_val = int(nf_fim)
        except: pass

    def filtrar_linha(linha):
        if len(linha) < 3: return False
        vencimento, descricao, nf_num = linha[0], linha[1], linha[2]
        
        if filtro == "nfs":
            try:
                num = int(re.sub(r"\\D+", "", str(nf_num)))
                if ni > 0 and num < ni: return False
                if nf_end_val > 0 and num > nf_end_val: return False
            except:
                return False
                
        if filtro == "mes" and mes:
            partes = mes.split("-")
            if len(partes) == 2:
                m = f"/{partes[1]}/"
                a = partes[0]
                if not (m in vencimento and (a in vencimento or str(a)[-2:] in vencimento)):
                    if mes not in vencimento:
                        return False
        
        return True

    for p_tipo, anos in PLANILHAS.items():
        for ano, id_planilha in anos.items():
            if id_planilha:
                try:
                    planilha = gc.open_by_key(id_planilha)
                    for aba in planilha.worksheets():
                        try:
                            linhas = aba.get_all_values()
                            for i, linha in enumerate(linhas):
                                if i == 0 or len(linha) < 4: continue
                                nf_text = str(linha[2]).strip()
                                if not nf_text or not nf_text[0].isdigit(): continue
                                
                                if filtrar_linha(linha):
                                    valor = linha[3] if len(linha) > 3 else "0"
                                    out.append({
                                        "Data": linha[0],
                                        "Descricao": linha[1],
                                        "NF": nf_text,
                                        "Valor": valor,
                                        "Planilha": p_tipo + " " + (ano or ""),
                                        "Aba": aba.title
                                    })
                        except Exception as e:
                            pass
                except Exception as ex:
                    pass
    return out
"""

match = re.search(r'def _history_from_reports', text)
if match and "_gerar_relatorio_nfs" not in text:
    text = text[:match.start()] + new_func + '\n' + text[match.start():]
    
route_insert = """            if parsed.path == "/api/relatorio-nfs":
                qs = parse_qs(parsed.query or "")
                filtro = (qs.get("filtro", [""])[0] or "todos").strip()
                mes = (qs.get("mes", [""])[0] or "").strip()
                nf_inicio = (qs.get("nf_inicio", [""])[0] or "").strip()
                nf_fim = (qs.get("nf_fim", [""])[0] or "").strip()
                try:
                    items = _gerar_relatorio_nfs(filtro, mes, nf_inicio, nf_fim)
                    return _json_response(self, 200, {"status": "success", "items": items})
                except Exception as e:
                    return _json_response(self, 500, {"status": "error", "message": str(e)})

"""

match2 = re.search(r'if parsed\.path == "/api/history":', text)
if match2 and "/api/relatorio-nfs" not in text:
    text = text[:match2.start()] + route_insert + text[match2.start():]

with open(file_path, 'w', encoding='utf-8') as f:
    f.write(text)

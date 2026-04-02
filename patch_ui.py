import os

file_path = '../FinanceAnaHub/src/web/server.py'
with open(file_path, 'r', encoding='utf-8') as f:
    text = f.read()

target = """  <div class="actions-panel" style="margin-top: 40px; border-top: 2px dashed #ccc; padding-top: 20px;">
    <h3 style="margin-bottom: 10px;">Ferramentas de Manutenção (Botana)</h3>
    <button id="btn-corrigir" class="btn" onclick="iniciarCorrecao()" style="padding: 12px 24px; font-size: 16px; cursor: pointer; border-radius: 8px; border: none; background-color: #176fe5; color: white; box-shadow: 0 4px 6px rgba(0,0,0,0.1); font-weight: bold; transition: background 0.3s;">Corrigir Boletos Retrospectivos</button>
  </div>
  <script>
    function iniciarCorrecao() {
      const BOTAO_MENSAGEM = "Corrigir Boletos Retrospectivos";
      const BOTAO_MENSAGEM_CARREGANDO = "Processando...";
      const URL_CORRECAO = "/botana/api/clean-sheets";
      
      let botaoCorrigir = document.getElementById("btn-corrigir");
      botaoCorrigir.innerText = BOTAO_MENSAGEM_CARREGANDO;
      botaoCorrigir.disabled = true;
      botaoCorrigir.style.background = "#9cdaf8";
      
      fetch(URL_CORRECAO, { method: "POST" })
        .then((respostaServidor) => {
          return respostaServidor.json().then((dadosResposta) => {
            return [respostaServidor.ok, dadosResposta];
          });
        })
        .then(([sucessoRequisicao, dadosResposta]) => {
          if (sucessoRequisicao && dadosResposta.status === "success") {
            window.alert("Sistema de correção iniciado com sucesso em segundo plano!");
          } else {
            window.alert("Erro ao iniciar a correção: " + (dadosResposta.message || "Erro desconhecido"));
          }
        })
        .catch((erroRequisicao) => {
          window.alert("Erro de comunicação com o servidor: " + erroRequisicao);
        })
        .finally(() => {
          botaoCorrigir.innerText = BOTAO_MENSAGEM;
          botaoCorrigir.disabled = false;
          botaoCorrigir.style.background = "#176fe5";
        });
    }
  </script>
</body>
</html>\"\"\""""

new_content = """  <div class="actions-panel" style="margin-top: 40px; border-top: 2px dashed #ccc; padding-top: 20px; display: flex; flex-direction: column; gap: 20px;">
    
    <div>
      <h3 style="margin-bottom: 10px;">Ferramentas de Manutenção (Botana)</h3>
      <button id="btn-corrigir" class="btn" onclick="iniciarCorrecao()" style="padding: 12px 24px; font-size: 16px; cursor: pointer; border-radius: 8px; border: none; background-color: #176fe5; color: white; box-shadow: 0 4px 6px rgba(0,0,0,0.1); font-weight: bold; transition: background 0.3s;">Corrigir Boletos Retrospectivos</button>
    </div>

    <div style="background: #f9f9f9; padding: 20px; border-radius: 8px; border: 1px solid #ddd;">
      <h3 style="margin-top: 0; margin-bottom: 15px;">Gerar Relatório de Lançamentos (NFs)</h3>
      <div style="display: flex; gap: 10px; align-items: center; flex-wrap: wrap;">
        <select id="filtro-tipo" onchange="mudarFiltro()" style="padding: 8px; border-radius: 4px; border: 1px solid #ccc;">
            <option value="todos">Toda a Planilha</option>
            <option value="mes">Por Mês</option>
            <option value="nfs">Por Range de NF</option>
        </select>

        <div id="div-mes" style="display: none;">
            <input type="month" id="input-mes" style="padding: 8px; border-radius: 4px; border: 1px solid #ccc;">
        </div>

        <div id="div-nfs" style="display: none; align-items: center; gap: 5px;">
            <input type="number" id="input-nf-inicio" placeholder="De NF Ex: 49000" style="padding: 8px; border-radius: 4px; border: 1px solid #ccc; width: 140px;">
            <span>até</span>
            <input type="number" id="input-nf-fim" placeholder="Até NF Ex: 50000" style="padding: 8px; border-radius: 4px; border: 1px solid #ccc; width: 140px;">
        </div>

        <button id="btn-gerar-relatorio" onclick="gerarRelatorio()" style="padding: 10px 20px; font-size: 14px; cursor: pointer; border-radius: 8px; border: none; background-color: #28a745; color: white; box-shadow: 0 4px 6px rgba(0,0,0,0.1); font-weight: bold; transition: background 0.3s;">Gerar Tabela</button>
        <button id="btn-baixar-csv" onclick="baixarCSV()" style="display: none; padding: 10px 20px; font-size: 14px; cursor: pointer; border-radius: 8px; border: none; background-color: #6c757d; color: white; box-shadow: 0 4px 6px rgba(0,0,0,0.1); font-weight: bold; transition: background 0.3s;">Baixar CSV</button>
      </div>
      
      <div id="tabela-container" style="margin-top: 20px; max-height: 400px; overflow-y: auto; display: none;">
        <table style="width: 100%; border-collapse: collapse; text-align: left;">
            <thead>
                <tr style="background-color: #eee;">
                    <th style="padding: 8px; border: 1px solid #ddd;">Data</th>
                    <th style="padding: 8px; border: 1px solid #ddd;">Planilha</th>
                    <th style="padding: 8px; border: 1px solid #ddd;">NF</th>
                    <th style="padding: 8px; border: 1px solid #ddd;">Fornecedor e BLT</th>
                    <th style="padding: 8px; border: 1px solid #ddd;">Valor</th>
                </tr>
            </thead>
            <tbody id="tabela-corpo"></tbody>
        </table>
      </div>
    </div>
  </div>
  <script>
    let dadosRelatorioAtual = [];

    function mudarFiltro() {
        const tipo = document.getElementById("filtro-tipo").value;
        document.getElementById("div-mes").style.display = (tipo === "mes") ? "block" : "none";
        document.getElementById("div-nfs").style.display = (tipo === "nfs") ? "flex" : "none";
    }

    function gerarRelatorio() {
        const tipo = document.getElementById("filtro-tipo").value;
        let queryParams = new URLSearchParams();
        queryParams.append("filtro", tipo);
        
        if (tipo === "mes") {
            queryParams.append("mes", document.getElementById("input-mes").value);
        } else if (tipo === "nfs") {
            queryParams.append("nf_inicio", document.getElementById("input-nf-inicio").value);
            queryParams.append("nf_fim", document.getElementById("input-nf-fim").value);
        }

        const btn = document.getElementById("btn-gerar-relatorio");
        btn.innerText = "Buscando...";
        btn.disabled = true;

        fetch("/botana/api/relatorio-nfs?" + queryParams.toString())
            .then(res => res.json())
            .then(data => {
                if (data.status === "success") {
                    dadosRelatorioAtual = data.items;
                    renderizarTabela();
                } else {
                    alert("Erro ao gerar relatório: " + data.message);
                }
            })
            .catch(err => alert("Erro de rede: " + err))
            .finally(() => {
                btn.innerText = "Gerar Tabela";
                btn.disabled = false;
            });
    }

    function renderizarTabela() {
        const container = document.getElementById("tabela-container");
        const tbody = document.getElementById("tabela-corpo");
        tbody.innerHTML = "";
        
        if (dadosRelatorioAtual.length === 0) {
            tbody.innerHTML = "<tr><td colspan='5' style='padding: 8px; border: 1px solid #ddd; text-align: center;'>Nenhum dado encontrado para os filtros selecionados.</td></tr>";
        } else {
            dadosRelatorioAtual.forEach(item => {
                const tr = document.createElement("tr");
                tr.innerHTML = `
                    <td style="padding: 8px; border: 1px solid #ddd;">${item.Data}</td>
                    <td style="padding: 8px; border: 1px solid #ddd;">${item.Planilha} (${item.Aba})</td>
                    <td style="padding: 8px; border: 1px solid #ddd;"><b>${item.NF}</b></td>
                    <td style="padding: 8px; border: 1px solid #ddd;">${item.Descricao}</td>
                    <td style="padding: 8px; border: 1px solid #ddd;">${item.Valor}</td>
                `;
                tbody.appendChild(tr);
            });
            document.getElementById("btn-baixar-csv").style.display = "inline-block";
        }
        
        container.style.display = "block";
    }

    function baixarCSV() {
        if (!dadosRelatorioAtual || dadosRelatorioAtual.length === 0) return;
        
        let header = ["Data", "Planilha", "Aba", "NF", "Descricao", "Valor"];
        let linhasCsv = [header.join(";")];
        
        dadosRelatorioAtual.forEach(item => {
            let row = [
                item.Data,
                item.Planilha,
                item.Aba,
                item.NF,
                item.Descricao.replace(/;/g, ","),
                item.Valor
            ];
            linhasCsv.push(row.join(";"));
        });
        
        const blob = new Blob(["\\uFEFF" + linhasCsv.join("\\n")], { type: 'text/csv;charset=utf-8;' });
        const url = URL.createObjectURL(blob);
        const a = document.createElement("a");
        a.href = url;
        a.download = "relatorio_lancamentos.csv";
        a.click();
        URL.revokeObjectURL(url);
    }

    function iniciarCorrecao() {
      const BOTAO_MENSAGEM = "Corrigir Boletos Retrospectivos";
      const BOTAO_MENSAGEM_CARREGANDO = "Processando...";
      const URL_CORRECAO = "/botana/api/clean-sheets";
      
      let botaoCorrigir = document.getElementById("btn-corrigir");
      botaoCorrigir.innerText = BOTAO_MENSAGEM_CARREGANDO;
      botaoCorrigir.disabled = true;
      botaoCorrigir.style.background = "#9cdaf8";
      
      fetch(URL_CORRECAO, { method: "POST" })
        .then((respostaServidor) => {
          return respostaServidor.json().then((dadosResposta) => {
            return [respostaServidor.ok, dadosResposta];
          });
        })
        .then(([sucessoRequisicao, dadosResposta]) => {
          if (sucessoRequisicao && dadosResposta.status === "success") {
            window.alert("Sistema de correção iniciado com sucesso em segundo plano!");
          } else {
            window.alert("Erro ao iniciar a correção: " + (dadosResposta.message || "Erro desconhecido"));
          }
        })
        .catch((erroRequisicao) => {
          window.alert("Erro de comunicação com o servidor: " + erroRequisicao);
        })
        .finally(() => {
          botaoCorrigir.innerText = BOTAO_MENSAGEM;
          botaoCorrigir.disabled = false;
          botaoCorrigir.style.background = "#176fe5";
        });
    }
  </script>
</body>
</html>\"\"\""""

text = text.replace(target, new_content)

with open(file_path, 'w', encoding='utf-8') as f:
    f.write(text)

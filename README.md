# Resultado Eleição 2026: votos por hora e por candidato

Dashboard e ferramentas para comparar o **1º turno (04/10/2026)** e o **2º turno (25/10/2026)** da eleição presidencial:

- **votos por hora**, calculados a partir dos logs das urnas eletrônicas (hora local da seção);
- **votos por candidato**, a partir dos resultados oficiais do TSE;
- comparação por **total, estado, região e cidade**.

O repositório inclui os **bancos já coletados** e o **dashboard pronto**. Quem só quer explorar os dados não precisa baixar nada do TSE.

## Uso rápido: abrir o dashboard

1. Baixe o repositório (ou só o arquivo [`dashboard.html`](dashboard.html)).
2. Abra o `dashboard.html` no navegador. Ele é um arquivo único, com os dados embutidos, e funciona sem internet e sem servidor.

No dashboard:

| Controle | O que faz |
|---|---|
| **Votos por hora / Candidatos (Presidente)** | Alterna entre as duas visões. |
| **Total / Por estado / Por região / Por cidade** | Define o agrupamento. Em "Por cidade", escolha o estado e busque pelo nome. |
| **Linha da tabela** | Clique para destacar um estado, região ou cidade nos gráficos. Clique de novo para voltar. |
| **Cabeçalho da tabela** | Ordena a coluna. |
| **Candidato** | Escolhe o candidato nos gráficos de ranking e de perfil de horário. Também dá para clicar na barra dele. |
| **Perfil de horário por faixa** | Divide os municípios em 4 faixas pelo % do candidato e compara a distribuição por hora delas. |
| **Tema** | Alterna claro e escuro. |

## Conteúdo do repositório

| Arquivo | Descrição |
|---|---|
| `dashboard.html` | Dashboard pronto (dados embutidos). |
| `dashboard_template.html` | Código do front-end (HTML, CSS e JavaScript sem dependências). |
| `logs_t1.sqlite` | Votos por hora e por seção, **1º turno** (banco). |
| `logs.sqlite` | Votos por hora e por seção, **2º turno** (banco). |
| `candidatos.json` | Votos de Presidente por candidato, brancos e nulos, por município, nos dois turnos. |
| `municipios.json` | Código TSE, UF e nome dos municípios. |
| `coletar_logs.py` | Baixa os logs das urnas do TSE e agrega os votos por hora, seção por seção. |
| `coletar_candidatos.py` | Baixa os votos por candidato por município. |
| `gerar_dashboard.py` | Junta os bancos e gera o `dashboard.html`. |
| `relatorio.py` | Gera gráfico e relatório em Markdown dos votos por hora. |
| `saida/` | Saída do `relatorio.py` para o 2º turno. |

## Os bancos SQLite

Cada banco (`logs.sqlite`, `logs_t1.sqlite`) tem duas tabelas:

- `secoes`: uma linha por seção eleitoral.
  - Chave: `uf`, `mun` (código TSE), `zona`, `secao`.
  - Votos computados por hora local: `h00` a `h23`.
  - `total`, e `primeiro` e `ultimo` com o registro de log mais antigo e mais recente.
- `falhas`: seções sem arquivo de log no TSE (cerca de 6%, em geral seções sem urna publicada). Não são erros de leitura.

Exemplo de consulta, votos por hora no Brasil no 2º turno:

```sql
SELECT SUM(h08), SUM(h09), SUM(h10), SUM(h16), SUM(h17) FROM secoes;
```

```bash
python -c "import sqlite3; print(sqlite3.connect('logs.sqlite').execute('select count(*), sum(total) from secoes').fetchone())"
```

## Refazer a coleta do zero

Requer Python 3.10 ou mais novo.

```bash
pip install -r requirements.txt
```

**1. Votos por hora (logs das urnas).** São cerca de 500 mil arquivos por turno, o que leva entre 1 e 3 horas. A coleta é retomável: se for interrompida, rode o mesmo comando.

```bash
python coletar_logs.py --pleito 3220 --data 04/10/2026 --db logs_t1.sqlite   # 1º turno
python coletar_logs.py --pleito 3221 --data 25/10/2026 --db logs.sqlite      # 2º turno
```

Teste primeiro numa amostra: `python coletar_logs.py --pleito 3221 --uf sc --limit 100 --data 25/10/2026 --db teste.sqlite`.

> Use sempre `--data`: o log de cada urna cobre os dois turnos, e sem o filtro os votos dos dois dias se misturam.

**2. Votos por candidato.** São cerca de 11,5 mil arquivos pequenos. O TSE às vezes responde 429 (limite de requisições); o script espera e repete sozinho.

```bash
python coletar_candidatos.py
```

**3. Gerar o dashboard e o relatório.**

```bash
python gerar_dashboard.py           # gera dashboard.html
python relatorio.py --db logs.sqlite --out saida
```

O `relatorio.py` aceita `--prorrogados` (arquivo com os códigos TSE dos municípios com votação até as 19h) e `--margem` (diferença de votos entre os candidatos) para medir o impacto dos votos depois das 17h.

## Como os dados foram obtidos

- **Logs das urnas:** `resultados.tse.jus.br/oficial/ele2026/arquivo-urna/<pleito>/dados/...`. Cada seção tem um `log.jez` (ZIP com `logd.dat`). O script conta as linhas "O voto do eleitor foi computado" e agrupa pela hora local. O log bruto é descartado, só ficam as contagens.
- **Resultados por candidato:** `resultados.tse.jus.br/oficial/ele2026/<eleição>/dados/<uf>/<uf><município>-c0001-e<eleição>-u.json` (Presidente: eleição 6257 no 1º turno e 6258 no 2º).
- Códigos do pleito: 1º turno = 3220, 2º turno = 3221.

## Limitações

- **Os logs ficam cerca de 0,1% abaixo do comparecimento oficial do TSE.** No 2º turno, os logs somam 128.077.499 votos e o TSE 128.236.074. Em alguns municípios o log publicado tem menos votos que o boletim de urna; a causa provável é a substituição de urnas, mas não foi confirmada. Os totais por candidato (`candidatos.json`) vêm do TSE e batem com o oficial.
- **Voto por hora e voto por candidato não se cruzam.** O voto é secreto: os logs não dizem em quem foi cada voto e o TSE não publica resultado por hora. O gráfico "perfil de horário por faixa" compara **municípios**, não eleitores, e pode refletir diferenças regionais.
- **Horário:** é o relógio da própria urna, ou seja, a hora local da seção.
- O dashboard cobre só o cargo de **Presidente**.

## Dados e licença

Os dados são públicos e vêm do portal de resultados do TSE. Ao reutilizá-los, cite o TSE como fonte.

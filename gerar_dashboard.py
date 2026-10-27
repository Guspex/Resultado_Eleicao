#!/usr/bin/env python3
"""
Gera dashboard.html (arquivo único, abre direto no navegador) comparando 1º e 2º turno.

    python gerar_dashboard.py --db1 logs_t1.sqlite --db2 logs.sqlite

Lê os dois bancos criados por coletar_logs.py (votos por hora por seção), agrega por
município e embute os dados no HTML a partir de dashboard_template.html.
"""
import argparse
import json
import sqlite3
from pathlib import Path

AQUI = Path(__file__).parent
HORAS = [f"h{h:02d}" for h in range(24)]


def por_municipio(db):
    if not Path(db).exists():
        return {}
    c = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    cols = ", ".join(f"SUM({h})" for h in HORAS)
    out = {}
    for uf, mun, n, *horas in c.execute(f"SELECT uf, mun, COUNT(*), {cols} FROM secoes GROUP BY uf, mun"):
        out[(uf, mun)] = (n, [int(x or 0) for x in horas])
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db1", default="logs_t1.sqlite")
    ap.add_argument("--db2", default="logs.sqlite")
    ap.add_argument("--cand", default="candidatos.json", help="saída de coletar_candidatos.py (opcional)")
    ap.add_argument("--saida", default="dashboard.html")
    a = ap.parse_args()

    nomes = json.loads((AQUI / "municipios.json").read_text(encoding="utf-8"))
    t1, t2 = por_municipio(a.db1), por_municipio(a.db2)
    cand = json.loads(Path(a.cand).read_text(encoding="utf-8")) if Path(a.cand).exists() else None

    def votos_cand(mun, turno):
        c = cand and cand["mun"].get(mun, {}).get(turno)
        return [c["c"], c["b"], c["n"]] if c else None

    zeros = (0, [0] * 24)
    linhas = []
    for uf, mun in sorted(set(t1) | set(t2)):
        n1, h1 = t1.get((uf, mun), zeros)
        n2, h2 = t2.get((uf, mun), zeros)
        nome = nomes.get(mun, [uf, mun])[1]
        linhas.append([uf, mun, nome, n1, n2, h1, h2, votos_cand(mun, "1"), votos_cand(mun, "2")])

    dados = {"municipios": linhas, "t1_completo": bool(t1), "cand": {"nomes": cand["nomes"]} if cand else None}
    html = (AQUI / "dashboard_template.html").read_text(encoding="utf-8")
    html = html.replace("/*__DADOS__*/null", json.dumps(dados, ensure_ascii=False, separators=(",", ":")))
    Path(a.saida).write_text(html, encoding="utf-8")
    tot1 = sum(sum(l[5]) for l in linhas)
    tot2 = sum(sum(l[6]) for l in linhas)
    print(f"{a.saida}: {len(linhas)} municípios | 1º turno {tot1:,} votos | 2º turno {tot2:,} votos".replace(",", "."))


if __name__ == "__main__":
    main()

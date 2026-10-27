#!/usr/bin/env python3
"""
Gera gráfico e relatório a partir do SQLite criado por coletar_logs.py.

    python relatorio.py --db logs.sqlite --prorrogados municipios_19h.txt --margem 1234567

--prorrogados  arquivo com um código TSE de município (5 dígitos) por linha
               (ou CSV com coluna "mun"): os municípios em que a votação foi
               até as 19h. Você precisa fornecer essa lista; o log não traz a
               informação de decisão judicial.
--margem       (opcional) diferença de votos entre os dois candidatos no 2º
               turno, para comparar com o volume de votos após as 17h.

Horas são as registradas no relógio da própria urna (hora local da seção).
"""
import argparse
import csv
import sqlite3
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd

HORAS = [f"h{h:02d}" for h in range(24)]


def ler_prorrogados(caminho):
    if not caminho:
        return set()
    linhas = Path(caminho).read_text(encoding="utf-8-sig").splitlines()
    muns = set()
    if linhas and "mun" in linhas[0].lower().split(","):
        for r in csv.DictReader(linhas):
            muns.add(str(r["mun"]).strip().zfill(5))
    else:
        for l in linhas:
            l = l.strip().split(",")[0].split(";")[0]
            if l.isdigit():
                muns.add(l.zfill(5))
    return muns


def fmt(n):
    return f"{int(round(n)):,}".replace(",", ".")


def pct(a, b):
    return f"{100*a/b:.2f}%".replace(".", ",") if b else "n/d"


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--db", default="logs.sqlite")
    ap.add_argument("--prorrogados")
    ap.add_argument("--margem", type=int)
    ap.add_argument("--corte", type=int, default=17, help="hora de encerramento regular (padrão 17)")
    ap.add_argument("--fim-prorrogacao", type=int, default=19)
    ap.add_argument("--out", default="saida")
    a = ap.parse_args()

    out = Path(a.out)
    out.mkdir(exist_ok=True)
    db = sqlite3.connect(a.db)
    df = pd.read_sql("SELECT * FROM secoes", db)
    falhas = db.execute("SELECT COUNT(*) FROM falhas").fetchone()[0]
    if df.empty:
        raise SystemExit("Banco vazio.")

    prorrog = ler_prorrogados(a.prorrogados)
    df["prorrog"] = df["mun"].isin(prorrog)
    c, f = a.corte, a.fim_prorrogacao
    pos = [f"h{h:02d}" for h in range(c, 24)]
    df["pos17"] = df[pos].sum(axis=1)
    df["h_17_a_fim"] = df[[f"h{h:02d}" for h in range(c, f)]].sum(axis=1)
    df["apos_fim"] = df[[f"h{h:02d}" for h in range(f, 24)]].sum(axis=1)

    total = int(df["total"].sum())
    por_hora = df[HORAS].sum()
    por_hora_p = df[df["prorrog"]][HORAS].sum()
    por_hora_n = df[~df["prorrog"]][HORAS].sum()

    # ---------- tabela por hora ----------
    tab = pd.DataFrame(
        {
            "hora": [f"{h:02d}:00-{h:02d}:59" for h in range(24)],
            "votos_total": por_hora.values,
            "municipios_prorrogados": por_hora_p.values,
            "demais_municipios": por_hora_n.values,
        }
    )
    tab = tab[tab["votos_total"] > 0]
    tab.to_csv(out / "votos_por_hora.csv", index=False)
    df.groupby(["uf", "mun"])[HORAS + ["total", "pos17"]].sum().reset_index().to_csv(
        out / "votos_por_municipio.csv", index=False
    )

    # ---------- gráfico ----------
    horas = [int(h[1:]) for h in HORAS if por_hora[h] > 0]
    fig, ax = plt.subplots(figsize=(11, 5.5))
    x = list(range(len(horas)))
    cor_n, cor_p = "#3b6ea5", "#d9822b"
    vn = [por_hora_n[f"h{h:02d}"] for h in horas]
    vp = [por_hora_p[f"h{h:02d}"] for h in horas]
    ax.bar(x, vn, color=cor_n, label="Demais municípios" if prorrog else "Votos")
    if prorrog:
        ax.bar(x, vp, bottom=vn, color=cor_p, label=f"Municípios com votação até {f}h")
    for xi, h in zip(x, horas):
        t = por_hora[f"h{h:02d}"]
        ax.text(xi, t, fmt(t), ha="center", va="bottom", fontsize=8)
    if c in horas:
        ax.axvline(horas.index(c) - 0.5, color="#555", ls="--", lw=1)
        ax.text(horas.index(c) - 0.45, ax.get_ylim()[1] * 0.97, f"{c}h: fim regular", fontsize=8, va="top", color="#555")
    ax.set_xticks(x)
    ax.set_xticklabels([f"{h:02d}h" for h in horas])
    ax.set_ylabel("Votos computados")
    ax.yaxis.set_major_formatter(matplotlib.ticker.FuncFormatter(lambda v, _: fmt(v)))
    ax.set_title(f"Votos computados por hora (hora local da urna) — total: {fmt(total)}")
    ax.spines[["top", "right"]].set_visible(False)
    if prorrog:
        ax.legend(frameon=False)
    fig.tight_layout()
    fig.savefig(out / "votos_por_hora.png", dpi=150)

    # ---------- relatório ----------
    L = []
    L.append("# Votos por hora e impacto da votação após as 17h\n")
    L.append(f"- Seções analisadas: **{fmt(len(df))}** (falhas de download/leitura: {fmt(falhas)})")
    L.append(f"- Votos computados nos logs: **{fmt(total)}**")
    L.append("- Horários: relógio da própria urna (hora local da seção).\n")

    pos_tot = int(df["pos17"].sum())
    L.append(f"## Votos depois das {c}:00\n")
    L.append(f"- Total após {c}:00: **{fmt(pos_tot)}** ({pct(pos_tot, total)} do total)")
    L.append(f"- Seções com ao menos um voto após {c}:00: **{fmt((df['pos17']>0).sum())}** ({pct((df['pos17']>0).sum(), len(df))})\n")

    if prorrog:
        P, N = df[df["prorrog"]], df[~df["prorrog"]]
        L.append("## Municípios com votação prorrogada até " f"{f}h vs. demais\n")
        L.append(f"| | Prorrogados | Demais |\n|---|---:|---:|")
        L.append(f"| Municípios na lista encontrados no banco | {fmt(P['mun'].nunique())} de {fmt(len(prorrog))} | {fmt(N['mun'].nunique())} |")
        L.append(f"| Seções | {fmt(len(P))} | {fmt(len(N))} |")
        L.append(f"| Votos totais | {fmt(P['total'].sum())} | {fmt(N['total'].sum())} |")
        L.append(f"| Votos {c}:00–{f-1}:59 | {fmt(P['h_17_a_fim'].sum())} | {fmt(N['h_17_a_fim'].sum())} |")
        L.append(f"| Votos a partir de {f}:00 | {fmt(P['apos_fim'].sum())} | {fmt(N['apos_fim'].sum())} |")
        L.append(f"| % dos votos após {c}:00 | {pct(P['pos17'].sum(), P['total'].sum())} | {pct(N['pos17'].sum(), N['total'].sum())} |\n")

        taxa_fila = N["pos17"].sum() / N["total"].sum() if N["total"].sum() else 0
        esperado = taxa_fila * P["total"].sum()
        excesso = P["pos17"].sum() - esperado
        L.append("### Estimativa do efeito da prorrogação\n")
        L.append(
            f"Nos demais municípios, {pct(N['pos17'].sum(), N['total'].sum())} dos votos ocorreram após {c}:00 "
            f"(são os eleitores que já estavam na fila no horário). Aplicando essa mesma proporção ao total dos "
            f"municípios prorrogados, esperaríamos cerca de **{fmt(esperado)}** votos após {c}:00 sem a prorrogação. "
            f"Foram observados **{fmt(P['pos17'].sum())}**. A diferença, de aproximadamente **{fmt(excesso)}** votos, "
            f"é uma estimativa do volume adicional atribuível à prorrogação.\n"
        )
        L.append(
            "> Esta é uma aproximação: assume que o efeito de fila seria igual nos dois grupos. Municípios "
            "prorrogados tendem a ter motivo específico (atrasos, problemas locais) e podem ter filas maiores "
            "de qualquer forma, então a estimativa pode superestimar o efeito.\n"
        )
        if a.margem:
            L.append(f"### Comparação com a margem\n")
            L.append(
                f"Margem informada entre os candidatos: **{fmt(a.margem)}** votos. Votos adicionais estimados pela prorrogação: "
                f"**{fmt(excesso)}** (equivale a {pct(excesso, a.margem)} da margem). Votos totais após {c}:00 nos municípios "
                f"prorrogados: {fmt(P['pos17'].sum())} ({pct(P['pos17'].sum(), a.margem)} da margem).\n"
            )
        L.append(
            "O log da urna registra *quando* houve voto, não *em quem*. Esta análise mede volume de votos, "
            "não o efeito sobre o resultado entre candidatos.\n"
        )
    else:
        L.append("_Nenhuma lista de municípios prorrogados foi informada (`--prorrogados`), então não há comparação._\n")
        if a.margem:
            L.append(f"Margem informada: {fmt(a.margem)}. Votos após {c}:00: {fmt(pos_tot)} ({pct(pos_tot, a.margem)} da margem).\n")

    L.append("## Votos por hora\n")
    L.append("| Hora | Total | Prorrogados | Demais |\n|---|---:|---:|---:|")
    for _, r in tab.iterrows():
        L.append(f"| {r['hora']} | {fmt(r['votos_total'])} | {fmt(r['municipios_prorrogados'])} | {fmt(r['demais_municipios'])} |")
    L.append("\n![Votos por hora](votos_por_hora.png)\n")
    (out / "relatorio.md").write_text("\n".join(L), encoding="utf-8")
    print(f"Gerado em {out}/: relatorio.md, votos_por_hora.png, votos_por_hora.csv, votos_por_municipio.csv")


if __name__ == "__main__":
    main()

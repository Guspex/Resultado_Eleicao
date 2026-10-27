#!/usr/bin/env python3
"""
Coleta os logs das urnas (.logjez) do TSE, seção por seção, e agrega os votos
computados por hora (hora LOCAL registrada no log da urna).

Só guarda contagens por seção em SQLite (o log bruto é descartado), então o
disco usado é pequeno. É retomável: rode de novo e ele pula seções já feitas.

Uso básico:
    pip install aiohttp py7zr
    python coletar_logs.py --ano 2026 --pleito 3221 --data 25/10/2026 --db logs.sqlite

Antes de rodar tudo, teste numa amostra e confira as mensagens do log:
    python coletar_logs.py --ano 2026 --pleito 3221 --uf sc --limit 20 --inspect

Códigos 2026 (do ele-c.json do TSE): 2º turno (25/10) = pleito 3221;
1º turno (04/10) = pleito 3220. O código 6258 é o da eleição no portal, não o do pleito.

ATENÇÃO (não verificado contra o servidor real):
  * O arquivo de seções por UF é lido de
    arquivo-urna/<pleito>/config/<uf>/<uf>-p<pleito 6 dígitos>-cs.json (padrão de 2022).
  * O padrão de mensagem de voto (--regex-voto) é o que se espera dos logs;
    use --inspect para ver as mensagens reais e ajuste se preciso.
"""
import argparse
import asyncio
import io
import json
import os
import re
import sqlite3
import sys
import time
import zipfile
from collections import Counter

import aiohttp
import py7zr

HORAS = [f"h{h:02d}" for h in range(24)]


def init_db(path):
    db = sqlite3.connect(path)
    cols = ", ".join(f"{h} INTEGER DEFAULT 0" for h in HORAS)
    db.execute(
        f"""CREATE TABLE IF NOT EXISTS secoes (
            uf TEXT, mun TEXT, zona TEXT, secao TEXT,
            {cols}, total INTEGER, primeiro TEXT, ultimo TEXT,
            PRIMARY KEY (uf, mun, zona, secao))"""
    )
    db.execute(
        """CREATE TABLE IF NOT EXISTS falhas (
            uf TEXT, mun TEXT, zona TEXT, secao TEXT, erro TEXT)"""
    )
    db.commit()
    return db


def feitas(db):
    return {tuple(r) for r in db.execute("SELECT uf, mun, zona, secao FROM secoes")}


UFS = "ac al am ap ba ce df es go ma mg ms mt pa pb pe pi pr rj rn ro rr rs sc se sp to zz".split()


def parse_config(cfg, uf_padrao):
    """Extrai (uf, mun, zona, secao) do JSON de seções (config 'cs') de uma UF."""
    out = []
    for e in cfg.get("abr", []):
        uf = (e.get("cd") or uf_padrao).lower()
        for m in e.get("mu", []):
            mun = str(m.get("cd")).zfill(5)
            for z in m.get("zon", []):
                zona = str(z.get("cd")).zfill(4)
                for s in z.get("sec", []):
                    out.append((uf, mun, zona, str(s.get("ns")).zfill(4)))
    return out


def extrair_logd(conteudo: bytes) -> str:
    # O log.jez de 2026 é um ZIP contendo logd.dat (em 2022 era 7z).
    if zipfile.is_zipfile(io.BytesIO(conteudo)):
        with zipfile.ZipFile(io.BytesIO(conteudo)) as z:
            for nome in z.namelist():
                if nome.lower().endswith(".dat") or "logd" in nome.lower():
                    return z.read(nome).decode("latin-1", errors="replace")
        raise ValueError("logd.dat não encontrado no .jez")
    with py7zr.SevenZipFile(io.BytesIO(conteudo)) as z:
        if hasattr(z, "readall"):  # py7zr antigo
            arquivos = z.readall()
        else:  # py7zr >= 1.0: extração em memória
            from py7zr.io import BytesIOFactory

            fabrica = BytesIOFactory(limit=2**31)
            z.extract(factory=fabrica)
            arquivos = fabrica.products
        for nome, bio in arquivos.items():
            if nome.lower().endswith(".dat") or "logd" in nome.lower():
                bio.seek(0)
                return bio.read().decode("latin-1", errors="replace")
    raise ValueError("logd.dat não encontrado no .jez")


def agregar(texto, rx_voto, inspect_counter=None, data=None):
    horas = Counter()
    primeiro = ultimo = None
    for linha in texto.splitlines():
        p = linha.split("\t")
        if len(p) < 5:
            continue
        ts, msg = p[0], p[4]
        if primeiro is None:
            primeiro = ts
        ultimo = ts
        if inspect_counter is not None:
            inspect_counter[re.sub(r"\d+", "#", msg)[:120]] += 1
        if rx_voto.search(msg) and (data is None or ts.startswith(data)):
            horas[ts[11:13]] += 1
    return horas, primeiro, ultimo


async def get(session, url, tentativas=4, binario=False):
    for i in range(tentativas):
        try:
            async with session.get(url) as r:
                if r.status == 404:
                    return None
                r.raise_for_status()
                return await (r.read() if binario else r.json(content_type=None))
        except Exception:
            if i == tentativas - 1:
                raise
            await asyncio.sleep(1.5 * (i + 1))


async def processar(session, base, pleito, sec, rx_voto, inspect_counter, data=None):
    uf, mun, zona, secao = sec
    pre = f"{base}/dados/{uf}/{mun}/{zona}/{secao}"
    aux = await get(session, f"{pre}/p{pleito:06d}-{uf}-m{mun}-z{zona}-s{secao}-aux.json")
    if not aux:
        raise ValueError("aux.json não encontrado")
    alvo = None
    for h in aux.get("hashes", []):
        for arq in h.get("arq", []):
            nome = arq.get("nm", "")
            if arq.get("tp") == "log" or nome.endswith((".jez", ".logjez")):
                alvo = f"{pre}/{h['hash']}/{nome}"
    if not alvo:
        raise ValueError("sem arquivo de log (.jez) na seção")
    conteudo = await get(session, alvo, binario=True)
    if not conteudo:
        raise ValueError("log não encontrado (404)")
    texto = await asyncio.to_thread(extrair_logd, conteudo)
    horas, primeiro, ultimo = agregar(texto, rx_voto, inspect_counter, data)
    return horas, primeiro, ultimo


async def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--ano", default="2026")
    ap.add_argument("--pleito", type=int, required=True, help="código do ciclo/turno na URL (ex.: 407)")
    ap.add_argument("--db", default="logs.sqlite")
    ap.add_argument("--uf", help="processar só uma UF (ex.: sc)")
    ap.add_argument("--limit", type=int, help="processar só N seções (para teste)")
    ap.add_argument("--concurrency", type=int, default=24)
    ap.add_argument("--regex-voto", default=r"voto.*computado", help="regex (case-insensitive) da mensagem de voto computado")
    ap.add_argument("--data", help="só conta votos desta data (dd/mm/aaaa). O log cobre 1º e 2º turno; ex.: 25/10/2026")
    ap.add_argument("--inspect", action="store_true", help="mostra as mensagens mais comuns do log e sai")
    ap.add_argument("--base-url", help="sobrescreve a URL base (testes)")
    a = ap.parse_args()

    base = a.base_url or f"https://resultados.tse.jus.br/oficial/ele{a.ano}/arquivo-urna/{a.pleito}"
    rx_voto = re.compile(a.regex_voto, re.I)
    db = init_db(a.db)
    ja = feitas(db)
    db.execute("DELETE FROM falhas")  # as seções pendentes serão tentadas de novo
    db.commit()
    insp = Counter() if a.inspect else None

    timeout = aiohttp.ClientTimeout(total=120)
    conn = aiohttp.TCPConnector(limit=a.concurrency)
    async with aiohttp.ClientSession(timeout=timeout, connector=conn, headers={"User-Agent": "analise-logs-urna/1.0"}) as s:
        todas = []
        for uf in ([a.uf.lower()] if a.uf else UFS):
            cfg = await get(s, f"{base}/config/{uf}/{uf}-p{a.pleito:06d}-cs.json")
            if not cfg:
                print(f"aviso: sem arquivo de seções para {uf} ({base}/config/{uf}/{uf}-p{a.pleito:06d}-cs.json)")
                continue
            todas += parse_config(cfg, uf)
        if not todas:
            sys.exit("Nenhuma seção encontrada. Confira --ano e --pleito (2º turno 2026: --pleito 3221).")
        pend = [x for x in todas if x not in ja]
        if a.limit:
            pend = pend[: a.limit]
        print(f"{len(todas)} seções no total, {len(ja)} já feitas, {len(pend)} a processar", flush=True)

        sem = asyncio.Semaphore(a.concurrency)
        feito = 0
        nfalhas = 0
        t0 = time.time()

        async def uma(sec):
            nonlocal feito, nfalhas
            async with sem:
                try:
                    horas, pri, ult = await processar(s, base, a.pleito, sec, rx_voto, insp, a.data)
                    vals = [horas.get(f"{h:02d}", 0) for h in range(24)]
                    db.execute(
                        f"INSERT OR REPLACE INTO secoes VALUES (?,?,?,?,{','.join('?'*24)},?,?,?)",
                        (*sec, *vals, sum(vals), pri, ult),
                    )
                except Exception as e:
                    nfalhas += 1
                    db.execute("INSERT INTO falhas VALUES (?,?,?,?,?)", (*sec, repr(e)[:300]))
                    if not ja and nfalhas == feito + 1 and nfalhas >= 50:
                        db.commit()
                        print(f"ERRO: as primeiras {nfalhas} seções falharam (último: {e!r}). Abortando.", flush=True)
                        os._exit(1)
                feito += 1
                if feito % 200 == 0:
                    db.commit()
                    rate = feito / (time.time() - t0)
                    print(f"{feito}/{len(pend)}  ({rate:.1f} seções/s, {nfalhas} falhas)", flush=True)

        await asyncio.gather(*(uma(x) for x in pend))
        db.commit()

    if insp is not None:
        print("\nMensagens mais frequentes nos logs (números trocados por #):")
        for msg, n in insp.most_common(40):
            print(f"{n:8d}  {msg}")
    falhas = db.execute("SELECT COUNT(*) FROM falhas").fetchone()[0]
    ok = db.execute("SELECT COUNT(*), SUM(total) FROM secoes").fetchone()
    print(f"\nConcluído. Seções no banco: {ok[0]}  votos contados: {ok[1]}  falhas registradas: {falhas}")


if __name__ == "__main__":
    asyncio.run(main())
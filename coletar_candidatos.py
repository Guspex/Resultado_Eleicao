#!/usr/bin/env python3
"""
Baixa do TSE os votos de Presidente por município (1º e 2º turno) e grava candidatos.json.

    python coletar_candidatos.py

Usa os arquivos de resultado <uf><mun>-c0001-e<eleição>-u.json:
  1º turno = eleição 6257, 2º turno = eleição 6258 (ver comum/config/ele-c.json do TSE).
Diferente dos logs das urnas (que só contam votos computados), estes arquivos trazem
o voto por candidato, brancos e nulos.
"""
import argparse
import asyncio
import json
import random
from pathlib import Path

import aiohttp

AQUI = Path(__file__).parent
TURNOS = {"1": "6257", "2": "6258"}


def extrair(j):
    """Do JSON de um município: ({numero: (nome, votos)}, brancos, nulos, comparecimento)."""
    cargo = next(c for c in j["carg"] if c["cd"] == "1")
    cands = {}
    for grupo in cargo.get("agr", []):
        for par in grupo.get("par", []):
            for c in par.get("cand", []):
                cands[c["n"]] = (c.get("nmu") or c["nm"], int(c["vap"]))
    v = j["v"]
    return cands, int(v.get("vb", 0)), int(v.get("vn", 0)), int(v.get("tv", 0))


async def baixar(sess, sem, base, turno, uf, mun, tentativas=6):
    """Retorna dados, None (404) ou levanta erro se o TSE seguir limitando (429/5xx)."""
    ele = TURNOS[turno]
    url = f"{base}/{ele}/dados/{uf}/{uf}{mun}-c0001-e00{ele}-u.json"
    async with sem:
        for i in range(tentativas):
            try:
                async with sess.get(url) as r:
                    if r.status == 404:
                        return None
                    if r.status == 429 or r.status >= 500:  # limite/erro do CDN do TSE: espera e tenta de novo
                        await asyncio.sleep(2 ** i + random.random())
                        continue
                    r.raise_for_status()
                    return extrair(json.loads(await r.text(encoding="utf-8", errors="replace")))
            except (aiohttp.ClientError, asyncio.TimeoutError):
                await asyncio.sleep(2 ** i + random.random())
    raise RuntimeError(f"sem resposta do TSE: {url}")


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ano", default="2026")
    ap.add_argument("--saida", default="candidatos.json")
    ap.add_argument("--concurrency", type=int, default=4)
    a = ap.parse_args()

    base = f"https://resultados.tse.jus.br/oficial/ele{a.ano}"
    muns = json.loads((AQUI / "municipios.json").read_text(encoding="utf-8"))  # {mun: [uf, nome]}
    sem = asyncio.Semaphore(a.concurrency)
    timeout = aiohttp.ClientTimeout(total=60)
    headers = {"User-Agent": "analise-logs-urna/1.0"}
    nomes = {"1": {}, "2": {}}
    saida = {}
    sem_dado = []
    async with aiohttp.ClientSession(timeout=timeout, headers=headers) as s:
        for turno in TURNOS:
            itens = list(muns.items())
            res = {}
            pendentes = itens
            for passe in range(1, 6):
                r = await asyncio.gather(*(baixar(s, sem, base, turno, uf, mun) for mun, (uf, _) in pendentes), return_exceptions=True)
                falhou = []
                for item, x in zip(pendentes, r):
                    if isinstance(x, Exception):
                        falhou.append(item)
                    else:
                        res[item[0]] = x
                print(f"{turno}º turno, passe {passe}: {len(res)}/{len(itens)} ok, {len(falhou)} a repetir", flush=True)
                pendentes = falhou
                if not pendentes:
                    break
                await asyncio.sleep(10 * passe)
            if pendentes:
                raise SystemExit(f"ERRO: {len(pendentes)} municípios sem resposta do TSE no {turno}º turno; rode de novo mais tarde.")
            res = [res[mun] for mun, _ in itens]
            for (mun, (uf, _)), r in zip(itens, res):
                if r is None:
                    sem_dado.append((turno, uf, mun))
                    continue
                cands, brancos, nulos, tv = r
                for n, (nome, _) in cands.items():
                    nomes[turno][n] = nome
                saida.setdefault(mun, {})[turno] = {"c": {n: v for n, (_, v) in cands.items()}, "b": brancos, "n": nulos, "tv": tv}
            print(f"{turno}º turno: {sum(1 for m in saida.values() if turno in m)} municípios", flush=True)

    Path(a.saida).write_text(json.dumps({"nomes": nomes, "mun": saida}, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    for turno in TURNOS:
        tot = sum(sum(m[turno]["c"].values()) + m[turno]["b"] + m[turno]["n"] for m in saida.values() if turno in m)
        print(f"{turno}º turno: soma dos municípios = {tot:,}".replace(",", "."))
    if sem_dado:
        print(f"sem arquivo: {len(sem_dado)} (ex.: {sem_dado[:3]})")


if __name__ == "__main__":
    asyncio.run(main())

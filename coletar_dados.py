"""
Coleta dados da PNAD Contínua pela API do SIDRA e gera  dados/base_tratada.csv  (formato tidy)
que o dashboard lê automaticamente (ou que você envia pelo st.file_uploader).

COMO USAR (no seu computador, com internet):
    pip install requests pandas
    python coletar_dados.py                       # baixa as tabelas da lista TABELAS
    python coletar_dados.py --tabela 4099         # só uma tabela
    python coletar_dados.py --arquivo exportado.csv --arquivo outro.xlsx   # base baixada à mão

IMPORTANTE — confira no site antes de entregar (https://sidra.ibge.gov.br/tabela/<número>):
  * as tabelas abaixo são CANDIDATAS (indicadas pelo IBGE/colegas); este script NÃO tem como
    garantir que cada uma traga UF, sexo e o indicador certo. No final ele imprime um
    RESUMO do que realmente entrou na base: indicadores, anos, UFs e se há recorte por sexo.
  * Se faltar algo (ex.: desocupação por sexo), procure no SIDRA uma tabela da PNAD Contínua
    com 'sexo' + 'Unidade da Federação' e rode:  python coletar_dados.py --tabela <número>
  * Só entram TAXAS (desocupação %, informalidade %) e rendimento médio (R$);
    contagens ("pessoas desocupadas") e "massa de rendimento" são descartadas.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

from modulo_trabalho_emprego import ler_arquivo, padronizar

API = "https://apisidra.ibge.gov.br/values"
TABELAS = ["4099", "5436", "6460"]          # ajuste conforme o que você validar no SIDRA
SAIDA = Path(__file__).resolve().parent / "dados" / "base_tratada.csv"
COLUNAS_FINAIS = ["uf", "ano", "trimestre", "sexo", "escolaridade", "setor", "indicador", "valor"]


def baixar(tabela: str) -> pd.DataFrame:
    """Baixa a tabela por UF (n3). Tenta com recorte por sexo (c2/all) e, se a tabela não
    tiver essa classificação, tenta sem ele."""
    import requests
    base = f"{API}/t/{tabela}/n3/all/v/all/p/all"
    ultimo = None
    for extra in ("/c2/all", ""):
        try:
            r = requests.get(base + extra, timeout=180)
            r.raise_for_status()
            dados = r.json()
            if len(dados) > 1:
                df = pd.DataFrame(dados[1:]).rename(columns=dados[0])
                df.attrs["consulta"] = base + extra
                return df
        except Exception as e:  # tenta a próxima variante
            ultimo = e
    raise RuntimeError(f"tabela {tabela}: {ultimo}")


def tratar(bruto: pd.DataFrame) -> pd.DataFrame:
    t = padronizar(bruto)                   # mesma limpeza do dashboard
    cols = [c for c in COLUNAS_FINAIS if c in t.columns]
    return t[cols]


def resumo(base: pd.DataFrame) -> None:
    print("\n=== RESUMO DA BASE TRATADA ===")
    print(f"Linhas: {len(base):,} | UFs: {base['uf'].nunique()} | "
          f"anos: {int(base['ano'].min())}–{int(base['ano'].max())}")
    for ind, g in base.groupby("indicador"):
        sx = sorted(g["sexo"].dropna().unique()) if "sexo" in g else []
        print(f"  - {ind}: {len(g):,} linhas · anos {int(g['ano'].min())}–{int(g['ano'].max())}"
              f" · sexo: {', '.join(sx) if sx else 'sem recorte'}")
    faltam = {"desocupacao", "informalidade", "rendimento"} - set(base["indicador"])
    if faltam:
        print("  ATENÇÃO: indicadores que NÃO entraram:", ", ".join(sorted(faltam)),
              "→ procure outra tabela no SIDRA e rode com --tabela.")
    if "sexo" not in base or base[base["indicador"] == "desocupacao"]["sexo"].dropna().empty:
        print("  ATENÇÃO: a desocupação está sem recorte por sexo (pergunta b do cenário).")
    anos = set(base["ano"].astype(int))
    if not {2012, 2022} <= anos:
        print("  ATENÇÃO: faltam 2012 e/ou 2022 na base.")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tabela", action="append", help="número da tabela SIDRA (repetível)")
    ap.add_argument("--arquivo", action="append", help="CSV/XLSX baixado manualmente (repetível)")
    a = ap.parse_args()

    partes = []
    for arq in a.arquivo or []:
        try:
            partes.append(tratar(ler_arquivo(arq)))
            print(f"[{arq}] ok")
        except Exception as e:
            print(f"[{arq}] falhou: {e}")
    if not a.arquivo:
        for tab in a.tabela or TABELAS:
            try:
                bruto = baixar(tab)
                (Path(__file__).resolve().parent / "dados").mkdir(exist_ok=True)
                bruto.to_csv(Path(__file__).resolve().parent / "dados" / f"bruto_{tab}.csv",
                             index=False, encoding="utf-8-sig")
                t = tratar(bruto)
                print(f"[{tab}] {len(bruto):,} linhas brutas → {len(t):,} úteis "
                      f"({', '.join(sorted(t['indicador'].unique())) or 'nenhum indicador'})")
                partes.append(t)
            except Exception as e:
                print(f"[{tab}] falhou: {e}")
    if not partes:
        print("Nada coletado. Verifique a internet ou use --arquivo com um CSV do SIDRA.")
        return 1
    base = pd.concat(partes, ignore_index=True).drop_duplicates()
    SAIDA.parent.mkdir(exist_ok=True)
    base.to_csv(SAIDA, index=False, sep=";", encoding="utf-8-sig")
    print(f"\nSalvo em {SAIDA}")
    resumo(base)
    return 0


if __name__ == "__main__":
    sys.exit(main())

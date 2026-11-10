"""
Módulo Tema 6 — Trabalho e População Empregada (PNAD Contínua / IBGE)

Como o grupo integra: no app.py do grupo, faça
    from modulo_trabalho_emprego import render as render_trabalho
e chame render_trabalho() dentro da página/menu do Tema 6.

Esquema "tidy" esperado na base (CSV/XLSX), uma linha por observação:
    uf, ano, [trimestre], [sexo], [escolaridade], [setor], indicador, valor
    indicador ∈ {"desocupacao", "informalidade", "rendimento"}
    (desocupacao e informalidade em %, rendimento em R$)
Colunas entre [] são opcionais; os filtros só aparecem se a coluna existir.

Decisões metodológicas (explicar na apresentação):
  * Filtros secundários (sexo, escolaridade, setor) NÃO apagam linhas que não possuem
    aquela dimensão (ex.: desocupação não tem setor): d[d[col].isna() | d[col].isin(sel)].
  * Estatísticas descritivas e outliers (1,5·IQR) são calculados com UM PONTO POR UF,
    nunca por linha da tabela. O valor da UF é a linha "Total" do IBGE quando existe
    (taxa oficial); sem ela, a média simples das categorias. Depois, média dos trimestres do ano.
  * Médias "nacionais" são médias simples das UFs, sem ponderar pela população.

ROTEIRO PARA A RODA DE CONVERSA (cenário: Márcia/Ministra do Trabalho, Renato/Conselho
de Indústrias e Sílvia/Sebrae querem combater a informalidade e promover paridade salarial):
  1. Onde a desocupação caiu e onde não caiu entre 2012 e 2022? (seção "Perguntas de negócio")
  2. Mulheres e homens foram afetados igualmente? (item b e seção "Paridade salarial")
  3. Há UFs atípicas? O que elas fazem com a média? (seção "Estatística descritiva e outliers")
  4. Quanto do emprego é informal? (gráfico formal × informal)
  5. A renda "típica" é a média ou a mediana? (histograma do rendimento)
Dica: fale em decisões ("priorizar a UF X"), não em código ou números soltos.

Dados reais: rode coletar_dados.py (gera dados/base_tratada.csv, lida automaticamente) e confira as tabelas no SIDRA.
Fotos: coloque imagens em assets/ (ver NOTICIAS e GALERIA_PREFIXO) — são exibidas se existirem.
"""
from __future__ import annotations

import re
import unicodedata
from pathlib import Path

import numpy as np
import pandas as pd

# ----------------------------------------------------------------------------
# 1. ETL: leitura, padronização e limpeza
# ----------------------------------------------------------------------------

UF_SIGLAS = {
    "Rondônia": "RO", "Acre": "AC", "Amazonas": "AM", "Roraima": "RR", "Pará": "PA",
    "Amapá": "AP", "Tocantins": "TO", "Maranhão": "MA", "Piauí": "PI", "Ceará": "CE",
    "Rio Grande do Norte": "RN", "Paraíba": "PB", "Pernambuco": "PE", "Alagoas": "AL",
    "Sergipe": "SE", "Bahia": "BA", "Minas Gerais": "MG", "Espírito Santo": "ES",
    "Rio de Janeiro": "RJ", "São Paulo": "SP", "Paraná": "PR", "Santa Catarina": "SC",
    "Rio Grande do Sul": "RS", "Mato Grosso do Sul": "MS", "Mato Grosso": "MT",
    "Goiás": "GO", "Distrito Federal": "DF",
}

# sinônimos para reconhecer colunas de exportações do SIDRA
SINONIMOS = {
    "uf": ["uf", "unidade da federacao", "unidade da federação", "estado"],
    "ano": ["ano"],
    "trimestre": ["trimestre", "trimestre movel", "trimestre móvel"],
    "sexo": ["sexo"],
    "escolaridade": ["escolaridade", "nivel de instrucao", "nível de instrução"],
    "setor": ["setor", "setor economico", "setor econômico", "grupamento de atividade"],
    "indicador": ["indicador", "variavel", "variável"],
    "valor": ["valor", "v"],
}

INDICADORES_ROTULO = {
    "desocupacao": "Desocupação (%)",
    "informalidade": "Informalidade (%)",
    "rendimento": "Rendimento (R$)",
}
COLUNAS_CATEGORICAS = ("sexo", "escolaridade", "setor", "trimestre")
VALORES_NULOS_TEXTO = {"", "nan", "none", "null", "-", "..", "...", "x"}


def _norm(txt) -> str:
    """minúsculas, sem acento, espaços únicos."""
    txt = unicodedata.normalize("NFKD", str(txt)).encode("ascii", "ignore").decode()
    return re.sub(r"\s+", " ", txt).strip().lower()


# nome da UF (sem acento/caixa) ou sigla -> sigla
_UF_NORM = {_norm(nome): sig for nome, sig in UF_SIGLAS.items()}
_UF_NORM.update({_norm(sig): sig for sig in UF_SIGLAS.values()})


def _classificar_indicador(txt) -> str | None:
    n = _norm(txt)
    # Só entram TAXAS (%) e rendimento médio (R$). Contagens como "pessoas desocupadas"
    # (milhares de pessoas) ou "massa de rendimento" são ignoradas para não misturar unidades.
    if n in ("desocupacao", "desemprego") or ("taxa" in n and ("desocup" in n or "desemprego" in n)):
        return "desocupacao"
    if n == "informalidade" or ("taxa" in n and "informal" in n):
        return "informalidade"
    if "massa" in n:
        return None
    if n == "rendimento" or ("rendimento" in n and "medio" in n) or "salario" in n:
        return "rendimento"
    return None


def _converter_numero(serie: pd.Series) -> pd.Series:
    """Aceita vírgula decimal BR ('1.234,5') e marcadores do SIDRA ('-', '..', 'X')."""
    if pd.api.types.is_numeric_dtype(serie):
        return serie
    v = serie.astype(str).str.strip()
    com_virgula = v.str.contains(",", regex=False)
    v = v.where(~com_virgula,
                v.str.replace(".", "", regex=False).str.replace(",", ".", regex=False))
    return pd.to_numeric(v, errors="coerce")


def ler_arquivo(arquivo) -> pd.DataFrame:
    """Lê CSV (sep ; , ou tab) ou XLSX vindo do st.file_uploader ou de um caminho."""
    nome = getattr(arquivo, "name", str(arquivo)).lower()
    if nome.endswith((".xlsx", ".xls")):
        return pd.read_excel(arquivo)
    for sep in (";", ",", "\t"):
        for enc in ("utf-8-sig", "latin-1"):
            if hasattr(arquivo, "seek"):
                arquivo.seek(0)
            try:
                df = pd.read_csv(arquivo, sep=sep, encoding=enc)
            except UnicodeDecodeError:
                continue
            if df.shape[1] > 1:
                return df
    raise ValueError("Não consegui identificar o separador/codificação do CSV.")


def padronizar(df: pd.DataFrame) -> pd.DataFrame:
    """
    Renomeia colunas, converte tipos, remove linhas inválidas e cria 'sigla'.
    O relatório de limpeza fica em df.attrs["relatorio"].
    Valores ausentes das colunas opcionais (sexo, escolaridade, setor...) continuam
    NaN de verdade — não viram o texto "nan" — para que os filtros possam mantê-los.
    """
    mapa = {}
    for col in df.columns:
        n = _norm(col)
        for alvo, syns in SINONIMOS.items():
            if n in [_norm(s) for s in syns] and alvo not in mapa.values():
                mapa[col] = alvo
                break
    df = df.rename(columns=mapa).copy()

    # Exportações trimestrais do SIDRA (PNAD Contínua) trazem só "Trimestre"
    # ("1º trimestre 2012", "jan-fev-mar 2012"): o ano é o número de 4 dígitos do texto.
    if "ano" not in df.columns and "trimestre" in df.columns:
        df["ano"] = df["trimestre"].astype(str).str.extract(r"((?:19|20)\d{2})")[0]

    faltando = [c for c in ("uf", "ano", "indicador", "valor") if c not in df.columns]
    if faltando:
        raise ValueError(
            "Colunas obrigatórias ausentes: " + ", ".join(faltando)
            + ". Esperado: uf, ano, indicador, valor (e opcionais trimestre, sexo, "
              "escolaridade, setor)."
        )

    rel = {"linhas_lidas": len(df)}

    df["valor"] = _converter_numero(df["valor"])
    df["ano"] = pd.to_numeric(df["ano"], errors="coerce")
    n0 = len(df)
    df = df.dropna(subset=["valor", "ano", "uf"])
    rel["sem_valor_ano_ou_uf"] = n0 - len(df)
    df["ano"] = df["ano"].astype(int)

    df["indicador"] = df["indicador"].map(_classificar_indicador)
    n0 = len(df)
    df = df[df["indicador"].notna()]
    rel["indicador_desconhecido"] = n0 - len(df)

    for c in COLUNAS_CATEGORICAS:
        if c in df.columns:
            s = df[c].astype("string").str.strip()
            s = s.mask(s.str.lower().isin(VALORES_NULOS_TEXTO))
            df[c] = s.astype(object).where(s.notna(), np.nan)

    # UF: aceita nome (com/sem acento) ou sigla. Linhas "Brasil", regiões etc. saem.
    df["uf"] = df["uf"].astype(str).str.strip()
    df["sigla"] = df["uf"].map(lambda u: _UF_NORM.get(_norm(u)))
    n0 = len(df)
    nao_uf = sorted(df.loc[df["sigla"].isna(), "uf"].unique())
    df = df[df["sigla"].notna()]
    rel["fora_das_27_ufs"] = n0 - len(df)
    rel["nomes_fora_das_27_ufs"] = nao_uf

    n0 = len(df)
    df = df.drop_duplicates().reset_index(drop=True)
    rel["duplicadas"] = n0 - len(df)
    rel["linhas_tratadas"] = len(df)
    df.attrs["relatorio"] = rel
    return df


def base_demo(seed: int = 7) -> pd.DataFrame:
    """
    Base SINTÉTICA só para testar a interface. NÃO usar na entrega.
    Propositalmente: 'setor' só existe nas linhas de rendimento e 'escolaridade' só nas
    de informalidade — assim a desocupação tem setor/escolaridade nulos e o filtro
    precisa mantê-la (regressão do bug de "base zerada").
    """
    rng = np.random.default_rng(seed)
    base_des = {s: rng.uniform(5, 16) for s in UF_SIGLAS.values()}
    linhas = []
    for nome, sig in UF_SIGLAS.items():
        for ano in range(2012, 2023):
            for sexo in ("Homens", "Mulheres"):
                f = 1.0 if sexo == "Homens" else 1.45
                tendencia = 1 + 0.03 * (2016 - ano) if ano < 2016 else 1 - 0.02 * (ano - 2016)
                linhas.append((nome, ano, sexo, None, None, "desocupacao",
                               max(2, base_des[sig] * f * tendencia + rng.normal(0, .4))))
                for esc in ("Fundamental", "Médio", "Superior"):
                    ajuste = {"Fundamental": 8, "Médio": 0, "Superior": -12}[esc]
                    linhas.append((nome, ano, sexo, esc, None, "informalidade",
                                   float(np.clip(rng.normal(42 + ajuste, 6), 10, 75))))
                for setor in ("Agropecuária", "Indústria", "Serviços"):
                    linhas.append((nome, ano, sexo, None, setor, "rendimento",
                                   max(700, rng.lognormal(7.8, .25) * (1.0 if sexo == "Homens" else .78))))
    d = pd.DataFrame(linhas, columns=["uf", "ano", "sexo", "escolaridade", "setor",
                                      "indicador", "valor"])
    return padronizar(d)


# ----------------------------------------------------------------------------
# 2. Filtros e agregações (cada UF = um ponto de dado)
# ----------------------------------------------------------------------------

def filtrar_nulo_seguro(d: pd.DataFrame, col: str, selecionados, todas=None) -> pd.DataFrame:
    """
    Aplica um filtro categórico SEM apagar as linhas em que a dimensão não se aplica.
    Ex.: a taxa de desocupação não tem 'setor'; filtrar por setor não pode zerá-la.
    """
    if col not in d.columns or selecionados is None:
        return d
    # Tudo selecionado = sem recorte: mantém também as linhas 'Total' (taxa oficial).
    if todas is not None and set(todas) <= set(selecionados):
        return d
    return d[d[col].isna() | d[col].isin(selecionados)]


def _eh_total(s: pd.Series) -> pd.Series:
    return s.map(lambda v: _norm(v) == "total" if pd.notna(v) else False)


def _recorte_total(d: pd.DataFrame, ignorar: tuple = ()) -> pd.DataFrame:
    """
    Escolhe, para cada UF/ano, as linhas que representam o valor OFICIAL da UF.

    Regra (corrige a média simples entre homens e mulheres):
      1. Se a UF/ano tem linha "agregada" (todas as dimensões são 'Total' ou vazias),
         usa SÓ essa linha — é a taxa oficial do IBGE.
      2. Se não tem, cai para as categorias (descartando linhas 'Total' parciais) e o
         valor da UF passa a ser a média simples delas (aproximação, não é a taxa oficial).
    'ignorar' lista dimensões que o chamador vai tratar sozinho (ex.: 'sexo').
    """
    dims = [c for c in ("sexo", "escolaridade", "setor") if c in d.columns and c not in ignorar]
    if not dims or d.empty:
        return d
    tot = pd.DataFrame({c: _eh_total(d[c]) for c in dims}, index=d.index)
    nul = pd.DataFrame({c: d[c].isna() for c in dims}, index=d.index)
    agregada = (tot | nul).all(axis=1)
    tem_total = tot.any(axis=1)
    chaves = [d["sigla"]] + ([d["ano"]] if "ano" in d.columns else [])
    uf_tem_agregada = agregada.groupby(chaves).transform("any")
    manter = np.where(uf_tem_agregada, agregada, ~tem_total)
    return d[manter]


def valores_por_uf(d: pd.DataFrame, indicador: str, ano: int) -> pd.Series:
    """Um valor por UF: linha Total (taxa oficial) quando existe; senão média das categorias."""
    x = _recorte_total(d[(d["indicador"] == indicador) & (d["ano"] == ano)])
    return x.groupby("sigla")["valor"].mean().dropna()


def comparar_anos(d: pd.DataFrame, indicador: str, ano_a: int, ano_b: int,
                  por: tuple = ("sigla",)) -> pd.DataFrame:
    """Média do indicador por UF (ou UF×sexo) em dois anos + variação em p.p. (b − a)."""
    if ano_a == ano_b:
        return pd.DataFrame()
    x = d[(d["indicador"] == indicador) & d["ano"].isin([ano_a, ano_b])]
    x = _recorte_total(x, ignorar=("sexo",) if "sexo" in por else ())
    if "sexo" in por:
        if "sexo" not in x.columns:
            return pd.DataFrame()
        x = x[x["sexo"].notna() & ~_eh_total(x["sexo"])]
    if x.empty:
        return pd.DataFrame()
    t = x.pivot_table(index=list(por), columns="ano", values="valor", aggfunc="mean")
    if ano_a not in t.columns or ano_b not in t.columns:
        return pd.DataFrame()
    t = t[[ano_a, ano_b]].dropna().copy()
    t["variacao_pp"] = t[ano_b] - t[ano_a]
    t.columns.name = None
    return t.sort_values("variacao_pp")


# ----------------------------------------------------------------------------
# 3. Estatística descritiva
# ----------------------------------------------------------------------------

def resumo_estatistico(serie: pd.Series) -> dict:
    """Média, mediana, moda, quartis, IQR, amplitude, variância, desvio e limites 1,5·IQR."""
    s = pd.to_numeric(serie, errors="coerce").dropna()
    if s.empty:
        return {}
    q1, q2, q3 = s.quantile([.25, .5, .75])
    iqr = q3 - q1
    lim_inf, lim_sup = q1 - 1.5 * iqr, q3 + 1.5 * iqr
    # moda: só existe se algum valor (arredondado a 2 casas) se repete
    cont = s.round(2).value_counts()
    moda = float(cont.index[cont == cont.max()].min()) if cont.max() > 1 else np.nan
    return {
        "n": int(s.size),
        "media": float(s.mean()),
        "mediana": float(q2),
        "moda": moda,
        "q1": float(q1), "q3": float(q3), "iqr": float(iqr),
        "minimo": float(s.min()), "maximo": float(s.max()),
        "amplitude": float(s.max() - s.min()),
        "variancia": float(s.var(ddof=1)) if s.size > 1 else 0.0,
        "desvio": float(s.std(ddof=1)) if s.size > 1 else 0.0,
        "lim_inf": float(lim_inf), "lim_sup": float(lim_sup),
        "n_outliers": int(((s < lim_inf) | (s > lim_sup)).sum()),
    }


def impacto_outliers(serie: pd.Series) -> dict:
    """
    Serie indexada por UF. Detecta outliers (1,5·IQR) e compara média e mediana
    com todas as UFs vs. sem os outliers.
    """
    r = resumo_estatistico(serie)
    if not r:
        return {}
    fora = serie[(serie < r["lim_inf"]) | (serie > r["lim_sup"])]
    sem = serie.drop(fora.index)
    media_sem = float(sem.mean()) if len(sem) else np.nan
    mediana_sem = float(sem.median()) if len(sem) else np.nan
    return {
        "resumo": r, "fora": fora, "sem": sem,
        "media_sem": media_sem, "mediana_sem": mediana_sem,
        "d_media": media_sem - r["media"], "d_mediana": mediana_sem - r["mediana"],
    }


def razao_mulheres_homens(d: pd.DataFrame, indicador: str, ano: int) -> pd.Series:
    """Razão (mulheres ÷ homens) do indicador por UF. 1,00 = paridade."""
    vazio = pd.Series(dtype=float)
    x = d[(d["indicador"] == indicador) & (d["ano"] == ano)]
    x = _recorte_total(x, ignorar=("sexo",))
    if "sexo" not in x.columns:
        return vazio

    def grupo(v):
        n = _norm(v) if pd.notna(v) else ""
        if n.startswith(("mulher", "femin")):
            return "M"
        if n.startswith(("homen", "homem", "mascul")):  # "Homens" e "Homem"
            return "H"
        return None

    x = x.assign(_g=x["sexo"].map(grupo))
    x = x[x["_g"].notna()]
    if x.empty:
        return vazio
    t = x.pivot_table(index="sigla", columns="_g", values="valor", aggfunc="mean")
    if not {"M", "H"} <= set(t.columns):
        return vazio
    return (t["M"] / t["H"]).replace([np.inf, -np.inf], np.nan).dropna()


def tabela_estatistica(d: pd.DataFrame, ano: int) -> pd.DataFrame:
    """Uma linha por indicador; cada UF é um ponto de dado no ano de referência."""
    linhas, outs = {}, {}
    for ind, rot in INDICADORES_ROTULO.items():
        s = valores_por_uf(d, ind, ano)
        a = impacto_outliers(s)
        if a:
            linhas[rot] = a["resumo"]
            outs[rot] = ", ".join(sorted(a["fora"].index)) or "—"
    if not linhas:
        return pd.DataFrame()
    cols = ["n", "media", "mediana", "moda", "q1", "q3", "iqr", "amplitude",
            "variancia", "desvio", "lim_inf", "lim_sup", "n_outliers"]
    tab = pd.DataFrame(linhas).T[cols]
    tab["n"] = tab["n"].astype(int)
    tab["n_outliers"] = tab["n_outliers"].astype(int)
    tab = tab.round(2)
    tab["UFs outliers"] = pd.Series(outs)
    return tab.rename(columns={
        "n": "N (UFs)", "media": "Média", "mediana": "Mediana", "moda": "Moda",
        "q1": "Q1", "q3": "Q3", "iqr": "IQR", "amplitude": "Amplitude",
        "variancia": "Variância", "desvio": "Desvio padrão",
        "lim_inf": "Limite inf.", "lim_sup": "Limite sup.", "n_outliers": "Nº outliers"})


def fmt(x, casas: int = 2, sinal: bool = False) -> str:
    """Número no padrão brasileiro: 1.234,56."""
    if x is None or pd.isna(x):
        return "—"
    s = f"{x:{'+' if sinal else ''},.{casas}f}"
    return s.replace(",", "§").replace(".", ",").replace("§", ".")


# ----------------------------------------------------------------------------
# 4. Notícias (links abertos e conferidos em 09/11/2026)
# ----------------------------------------------------------------------------

NOTICIAS = [
    {
        "titulo": "PNAD Contínua Trimestral: desocupação sobe em 15 das 27 UFs no 1º trimestre de 2026",
        "fonte": "Agência de Notícias do IBGE",
        "resumo": "Panorama da desocupação por UF no 1º trimestre de 2026 — base direta "
                  "para a comparação entre estados.",
        "url": "https://agenciadenoticias.ibge.gov.br/agencia-sala-de-imprensa/"
               "46676-pnad-continua-trimestral-desocupacao-sobe-em-15-das-27-ufs-no-"
               "1-trimestre-de-2026.html",
        # Imagem: caminho local (pasta assets/ ao lado deste arquivo) ou URL https.
        # Se o arquivo não existir, o card aparece só com o texto (sem erro).
        "imagem": "assets/noticia_pnad.jpg",
    },
    {
        "titulo": "Taxa de desemprego no Brasil cai e chega a 5,2% no 3º trimestre de 2026",
        "fonte": "Diário do Nordeste (PNAD Contínua/IBGE) — 30/10/2026",
        "resumo": "Menor taxa para o período desde 2012; 5,63 milhões de desocupados e "
                  "103,6 milhões de ocupados, recorde da série.",
        "url": "https://diariodonordeste.verdesmares.com.br/negocios/"
               "taxa-de-desemprego-no-brasil-cai-e-chega-a-52-no-3-trimestre-de-2026-1.3802435",
        "imagem": "assets/noticia_desemprego.jpg",
    },
    {
        "titulo": "Caged: Brasil gera 121,3 mil empregos formais em setembro; saldo no ano chega a 1,24 milhão",
        "fonte": "Agência Gov — 04/11/2026",
        "resumo": "Serviços lideraram o saldo de setembro (81,2 mil vagas); salário médio "
                  "real de admissão de R$ 2.429,41.",
        "url": "https://agenciagov.ebc.com.br/noticias/202611/"
               "brasil-gera-121-3-mil-empregos-formais-em-setembro-e-saldo-no-ano-chega-"
               "a-1-24-milhao-de-novos-postos-com-carteira-assinada",
        "imagem": "assets/noticia_caged.jpg",
    },
]

# Fotos de ambientes de trabalho e trabalhadores brasileiros (pedido do cenário):
# salve arquivos como assets/foto_1.jpg, assets/foto_2.jpg ... (jpg/jpeg/png) e eles
# aparecem automaticamente na galeria. Use fotos de bancos livres (ex.: Agência Brasil,
# Unsplash, Pexels) e cite a fonte em LEGENDAS_FOTOS.
GALERIA_PREFIXO = "foto_"
LEGENDAS_FOTOS = {}  # ex.: {"foto_1.jpg": "Trabalhadores da construção civil — Agência Brasil"}


def _resolver_imagem(ref) -> str | None:
    """URL https é usada direto; caminho relativo é procurado ao lado deste arquivo."""
    if not ref:
        return None
    if str(ref).lower().startswith("http"):
        return str(ref)
    p = Path(__file__).resolve().parent / str(ref)
    return str(p) if p.exists() else None


def _base_local() -> Path | None:
    """dados/base_tratada.csv (ou ao lado deste arquivo), gerada por coletar_dados.py, se existir."""
    raiz = Path(__file__).resolve().parent
    for p in (raiz / "dados" / "base_tratada.csv", raiz / "base_tratada.csv"):
        if p.exists():
            return p
    return None


def _fotos_galeria() -> list[Path]:
    pasta = Path(__file__).resolve().parent / "assets"
    if not pasta.is_dir():
        return []
    return sorted(p for p in pasta.iterdir()
                  if p.name.lower().startswith(GALERIA_PREFIXO)
                  and p.suffix.lower() in (".jpg", ".jpeg", ".png"))


def _md_tabela(df: pd.DataFrame, indice: str = "") -> str:
    """DataFrame -> tabela Markdown (sem depender de 'tabulate')."""
    cols = [indice] + [str(c) for c in df.columns]
    linhas = ["| " + " | ".join(cols) + " |", "|" + "---|" * len(cols)]
    for idx, r in df.iterrows():
        cel = [str(idx)] + [fmt(v) if isinstance(v, (int, float, np.floating, np.integer))
                            and not isinstance(v, bool) else str(v) for v in r.tolist()]
        linhas.append("| " + " | ".join(cel) + " |")
    return "\n".join(linhas)


def gerar_analise_md(d: pd.DataFrame, ano_a: int, ano_b: int, ano_ref: int,
                     autor: str = "") -> str:
    """Análise descritiva em Markdown, calculada a partir dos dados filtrados."""
    L = ["# Análise descritiva — Tema 6: Trabalho e População Empregada", ""]
    if autor:
        L += [f"**Responsável:** {autor}", ""]
    L += ["**Fonte:** PNAD Contínua / IBGE (SIDRA). **Método:** cada UF é um ponto de dado; "
          "valor da UF = linha 'Total' do IBGE quando existe (senão média simples das "
          "categorias), com média dos trimestres do ano. Quartis por interpolação linear; "
          "variância e desvio amostrais (n−1); outliers pela regra 1,5 × IQR.", ""]
    comp = comparar_anos(d, "desocupacao", ano_a, ano_b)
    L += [f"## 1. Desocupação por UF: {ano_a} × {ano_b}", ""]
    if comp.empty:
        L += ["Sem dados suficientes para os dois anos.", ""]
    else:
        mel, pio = comp.index[0], comp.index[-1]
        L += [f"- UF com maior variação negativa: **{mel}** "
              f"({fmt(comp.loc[mel, ano_a])}% → {fmt(comp.loc[mel, ano_b])}%, "
              f"{fmt(comp.loc[mel, 'variacao_pp'], sinal=True)} p.p.).",
              f"- UF com pior variação: **{pio}** ({fmt(comp.loc[pio, 'variacao_pp'], sinal=True)} p.p.).",
              f"- Média simples das UFs: {fmt(comp[ano_a].mean())}% → {fmt(comp[ano_b].mean())}%.", ""]
        tab = comp.rename(columns={ano_a: f"{ano_a} (%)", ano_b: f"{ano_b} (%)",
                                   "variacao_pp": "Variação (p.p.)"})
        L += [_md_tabela(tab, "UF"), ""]
    cs = comparar_anos(d, "desocupacao", ano_a, ano_b, por=("sigla", "sexo"))
    L += [f"## 2. Desocupação por UF e gênero: {ano_a} × {ano_b}", ""]
    if cs.empty:
        L += ["A base não separa a desocupação por sexo.", ""]
    else:
        r = cs.groupby(level="sexo")[[ano_a, ano_b, "variacao_pp"]].mean()
        L += [_md_tabela(r.rename(columns={ano_a: f"{ano_a} (%)", ano_b: f"{ano_b} (%)",
                                           "variacao_pp": "Variação média (p.p.)"}), "Sexo"), ""]
    L += [f"## 3. Estatística descritiva por UF ({ano_ref})", ""]
    te = tabela_estatistica(d, ano_ref)
    if te.empty:
        L += ["Sem dados para o ano de referência.", ""]
    else:
        L += [_md_tabela(te, "Indicador"), ""]
        for ind, rot in INDICADORES_ROTULO.items():
            imp = impacto_outliers(valores_por_uf(d, ind, ano_ref))
            if not imp:
                continue
            r = imp["resumo"]
            fora = ", ".join(sorted(imp["fora"].index)) or "nenhuma"
            L += [f"- **{rot}** — outliers: {fora}. Média {fmt(r['media'])} → "
                  f"{fmt(imp['media_sem'])} sem outliers; mediana {fmt(r['mediana'])} → "
                  f"{fmt(imp['mediana_sem'])}."]
        L += [""]
    rz = razao_mulheres_homens(d, "rendimento", ano_ref)
    L += [f"## 4. Paridade salarial ({ano_ref})", ""]
    if rz.empty:
        L += ["Sem rendimento por sexo na base.", ""]
    else:
        L += [f"Rendimento das mulheres = **{fmt(100 * rz.mean(), 1)}%** do dos homens (média das UFs); "
              f"menor paridade em **{rz.idxmin()}** ({fmt(100 * rz.min(), 1)}%) e maior em "
              f"**{rz.idxmax()}** ({fmt(100 * rz.max(), 1)}%).", ""]
    L += ["## 5. Leitura para a mesa de negociação", "",
          "Márcia (Trabalho), Renato (Indústrias) e Sílvia (Sebrae): priorizar as UFs com "
          "pior variação e maior informalidade; usar a **mediana** como meta de renda, por ser "
          "robusta a UFs atípicas; acompanhar a razão de rendimento mulheres/homens por UF.", ""]
    return "\n".join(L)


# ----------------------------------------------------------------------------
# 5. Interface Streamlit
# ----------------------------------------------------------------------------

def render(autor: str = "", prefix: str = "trab"):
    """Renderiza a página do Tema 6. Chame dentro do menu do app unificado.

    autor  : nome do integrante (aparece no cabeçalho).
    prefix : prefixo das chaves dos widgets (cada integrante usa o seu).
    """
    import plotly.express as px
    import streamlit as st

    st.header("Trabalho e População Empregada")
    st.caption("PNAD Contínua / IBGE · Perspectiva: Ministra do Trabalho, Conselho de "
               "Indústrias e Sebrae" + (f" · Responsável: {autor}" if autor else ""))

    # ---------------- Ingestão (upload / demo) ----------------
    with st.sidebar:
        st.subheader("Dados — Trabalho e Emprego")
        arqs = st.file_uploader("Base IBGE tratada (CSV/XLSX)", type=["csv", "xlsx", "xls"],
                                accept_multiple_files=True, key=f"upload_trabalho_{prefix}")
        usar_demo = st.checkbox("Usar dados de demonstração", value=False,
                                key=f"demo_trabalho_{prefix}")

    dfs, relatorios = [], []
    for a in arqs or []:
        try:
            t = padronizar(ler_arquivo(a))
            dfs.append(t)
            relatorios.append((a.name, t.attrs.get("relatorio", {})))
        except Exception as e:  # mensagem amigável em vez de traceback
            st.error(f"Erro ao ler a base '{a.name}': {e}")

    if dfs:
        df = pd.concat(dfs, ignore_index=True).drop_duplicates().reset_index(drop=True)
    elif arqs:
        return  # todos os arquivos falharam; os erros já foram exibidos
    elif _base_local() is not None and not usar_demo:
        df = padronizar(ler_arquivo(_base_local()))
        relatorios.append((_base_local().name + " (base local)", df.attrs.get("relatorio", {})))
        st.success(f"Usando a base local '{_base_local().name}' (gerada pelo coletar_dados.py). "
                   "Envie outro arquivo na barra lateral para substituí-la.")
    elif usar_demo:
        df = base_demo()
        relatorios.append(("base de demonstração", df.attrs.get("relatorio", {})))
        st.warning("Dados SINTÉTICOS de demonstração. Não use na entrega.")
    else:
        st.info("Envie a base (CSV/XLSX) na barra lateral ou marque os dados de "
                "demonstração para testar a interface.")
        return

    if df.empty:
        st.error("A base ficou vazia após a limpeza. Confira indicador, ano, uf e valor.")
        return

    with st.expander("Relatório de ingestão e limpeza (ETL)"):
        linhas_rel = []
        for nome, r in relatorios:
            linhas_rel.append({
                "Arquivo": nome, "Linhas lidas": r.get("linhas_lidas"),
                "Sem valor/ano/UF": r.get("sem_valor_ano_ou_uf"),
                "Indicador desconhecido": r.get("indicador_desconhecido"),
                "Fora das 27 UFs": r.get("fora_das_27_ufs"),
                "Duplicadas": r.get("duplicadas"),
                "Linhas tratadas": r.get("linhas_tratadas"),
            })
        st.dataframe(pd.DataFrame(linhas_rel), use_container_width=True, hide_index=True)
        fora = sorted({n for _, r in relatorios for n in r.get("nomes_fora_das_27_ufs", [])})
        if fora:
            st.caption("Linhas descartadas por não serem UF: " + ", ".join(fora) + ".")
        st.caption(f"Base tratada: {len(df):,} linhas · {df['sigla'].nunique()} UFs · "
                   f"anos {int(df['ano'].min())}–{int(df['ano'].max())} · indicadores: "
                   + ", ".join(sorted(df['indicador'].unique())) + ".")

    # ---------------- Barra lateral: download + filtros ----------------
    with st.sidebar:
        st.download_button(
            "Baixar base tratada (CSV)",
            data=df.to_csv(index=False, sep=";", decimal=",").encode("utf-8-sig"),
            file_name="base_tratada_trabalho_emprego.csv", mime="text/csv",
            key=f"dl_base_trabalho_{prefix}")

        st.subheader("Filtros")
        ufs = sorted(df["sigla"].unique())
        sel_ufs = st.multiselect("UF", ufs, default=ufs, key=f"f_uf_trab_{prefix}")
        anos = sorted(int(a) for a in df["ano"].unique())
        if len(anos) > 1:
            faixa = st.select_slider("Período (afeta o boxplot por UF)", options=anos,
                                     value=(anos[0], anos[-1]), key=f"f_ano_trab_{prefix}")
        else:
            faixa = (anos[0], anos[0])

        # Filtros secundários: SEMPRE aparecem (a rubrica cobra todos os filtros). Se a base
        # enviada não tiver a coluna, o filtro fica desabilitado com um aviso.
        sel_sec = {}
        for col, rot in (("sexo", "Sexo"), ("escolaridade", "Escolaridade"),
                         ("setor", "Setor econômico (Agro, Indústria, Serviços)")):
            tem = col in df.columns and df[col].notna().any()
            ops = sorted(v for v in df[col].dropna().unique() if _norm(v) != "total") if tem else []
            tem = tem and bool(ops)
            sel = st.multiselect(rot, ops, default=ops, key=f"f_{col}_trab_{prefix}",
                                 disabled=not tem)
            if tem:
                sel_sec[col] = (sel, ops)
                if df[col].isna().any():
                    st.caption(f"Indicadores sem {col} (ex.: desocupação) são mantidos.")
                if len(sel) < len(ops):
                    st.caption("Recorte parcial: a taxa 'Total' do IBGE deixa de valer e a UF "
                               "passa a ser a média simples das categorias marcadas.")
            else:
                st.caption(f"A base enviada não tem a coluna '{col}'.")

    # base filtrada por UF e recortes secundários (NaN-safe), SEM o recorte de período:
    # a comparação 2012 x 2022 não pode depender do controle deslizante.
    d_base = df[df["sigla"].isin(sel_ufs)]
    for col, (sel, ops) in sel_sec.items():
        d_base = filtrar_nulo_seguro(d_base, col, sel, todas=ops)
    d = d_base[d_base["ano"].between(*faixa)]

    with st.sidebar:
        st.download_button(
            "Baixar base filtrada (CSV)",
            data=d_base.to_csv(index=False, sep=";", decimal=",").encode("utf-8-sig"),
            file_name="base_filtrada_trabalho_emprego.csv", mime="text/csv",
            key=f"dl_filtrada_trabalho_{prefix}")

    if d_base.empty:
        st.warning("Nenhum dado para os filtros escolhidos. Ajuste a barra lateral.")
        return

    # ======================================================================
    # PERGUNTAS DE NEGÓCIO — comparação histórica
    # ======================================================================
    st.header("Perguntas de negócio: desocupação 2012 × 2022")

    def _idx(alvo, padrao):
        return anos.index(alvo) if alvo in anos else padrao

    ca, cb = st.columns(2)
    ano_a = ca.selectbox("Ano inicial", anos, index=_idx(2012, 0), key=f"ano_a_trab_{prefix}")
    ano_b = cb.selectbox("Ano final", anos, index=_idx(2022, len(anos) - 1), key=f"ano_b_trab_{prefix}")
    if ano_a == ano_b:
        st.warning("Escolha dois anos diferentes para comparar.")

    comp = comparar_anos(d_base, "desocupacao", ano_a, ano_b)
    if comp.empty and ano_a != ano_b:
        st.info(f"Não há dados de desocupação para {ano_a} e {ano_b} nas UFs/recortes "
                "selecionados.")

    # (a) por UF
    st.subheader(f"(a) Taxa de desocupação por UF: {ano_a} × {ano_b}")
    if not comp.empty:
        longo = comp[[ano_a, ano_b]].reset_index().melt(
            id_vars="sigla", var_name="Ano", value_name="valor")
        longo["Ano"] = longo["Ano"].astype(str)
        ordem = comp.sort_values(ano_b, ascending=False).index.tolist()
        fig = px.bar(longo, x="sigla", y="valor", color="Ano", barmode="group",
                     category_orders={"sigla": ordem, "Ano": [str(ano_a), str(ano_b)]},
                     labels={"sigla": "UF", "valor": "Taxa de desocupação (%)"})
        st.plotly_chart(fig, use_container_width=True)
        with st.expander("Tabela: taxa por UF e variação em pontos percentuais"):
            tab = comp.rename(columns={ano_a: f"{ano_a} (%)", ano_b: f"{ano_b} (%)",
                                       "variacao_pp": "Variação (p.p.)"}).round(2)
            tab.index.name = "UF"
            st.dataframe(tab, use_container_width=True)

    # (b) por UF e gênero
    st.subheader(f"(b) Taxa de desocupação por UF e gênero: {ano_a} × {ano_b}")
    comp_sexo = comparar_anos(d_base, "desocupacao", ano_a, ano_b, por=("sigla", "sexo"))
    if comp_sexo.empty:
        st.info("A base não tem a coluna 'sexo' (ou não há dados para os dois anos), "
                "então não é possível separar por gênero.")
    else:
        g = comp_sexo[[ano_a, ano_b]].reset_index().melt(
            id_vars=["sigla", "sexo"], var_name="Ano", value_name="valor")
        g["Ano"] = g["Ano"].astype(str)
        fig = px.bar(g, x="sigla", y="valor", color="sexo", barmode="group",
                     facet_row="Ano", height=620,
                     category_orders={"Ano": [str(ano_a), str(ano_b)]},
                     labels={"sigla": "UF", "valor": "Desocupação (%)", "sexo": "Sexo"})
        fig.for_each_annotation(lambda an: an.update(text=an.text.split("=")[-1]))
        st.plotly_chart(fig, use_container_width=True)

        resumo_sexo = comp_sexo.groupby(level="sexo")[[ano_a, ano_b, "variacao_pp"]].mean()
        cols = st.columns(len(resumo_sexo))
        for col_ui, (sx, linha) in zip(cols, resumo_sexo.iterrows()):
            col_ui.metric(f"{sx} — média das UFs ({ano_a} → {ano_b})",
                          f"{fmt(linha[ano_a])}% → {fmt(linha[ano_b])}%",
                          f"{fmt(linha['variacao_pp'], sinal=True)} p.p.",
                          delta_color="inverse")
        with st.expander("Tabela: variação por UF e gênero (p.p.)"):
            tab = comp_sexo.rename(columns={ano_a: f"{ano_a} (%)", ano_b: f"{ano_b} (%)",
                                            "variacao_pp": "Variação (p.p.)"}).round(2)
            st.dataframe(tab, use_container_width=True)

    # (c) UF que mais reduziu
    st.subheader("(c) UF que mais reduziu a desocupação")
    if not comp.empty:
        melhor = comp.index[0]  # já ordenado por variação (mais negativa primeiro)
        v = comp.loc[melhor]
        if v["variacao_pp"] < 0:
            st.success(
                f"**{melhor}** foi a UF que mais reduziu a desocupação entre {ano_a} e "
                f"{ano_b}: de {fmt(v[ano_a])}% para {fmt(v[ano_b])}% "
                f"(**{fmt(v['variacao_pp'], sinal=True)} p.p.**).")
        else:
            st.warning(
                f"Nenhuma UF reduziu a desocupação entre {ano_a} e {ano_b}. A menor alta "
                f"foi a de **{melhor}**: {fmt(v['variacao_pp'], sinal=True)} p.p. "
                f"({fmt(v[ano_a])}% → {fmt(v[ano_b])}%).")
        pior = comp.index[-1]
        st.caption(f"No extremo oposto, **{pior}** teve a maior variação: "
                   f"{fmt(comp.loc[pior, 'variacao_pp'], sinal=True)} p.p. "
                   f"Quedas são negativas.")
        var_df = comp.reset_index()[["sigla", "variacao_pp"]]
        var_df["Sentido"] = np.where(var_df["variacao_pp"] < 0, "Redução", "Aumento")
        fig = px.bar(var_df, x="sigla", y="variacao_pp", color="Sentido",
                     color_discrete_map={"Redução": "#2E7D32", "Aumento": "#C62828"},
                     category_orders={"sigla": var_df["sigla"].tolist()},
                     labels={"sigla": "UF", "variacao_pp": "Variação (p.p.)"})
        st.plotly_chart(fig, use_container_width=True)

    # ======================================================================
    # ESTATÍSTICA DESCRITIVA — UM PONTO POR UF
    # ======================================================================
    st.header("Estatística descritiva e outliers (por UF)")
    ano_ref = st.selectbox("Ano de referência (estatísticas e gráficos abaixo)", anos,
                           index=anos.index(ano_b), key=f"ano_ref_trab_{prefix}")
    st.caption("Cada UF é um ponto de dado (N = número de UFs): o valor da UF é a linha "
               "'Total' do IBGE quando existe; sem ela, a média simples das categorias; "
               "em ambos os casos, média dos trimestres do ano. Quartis por interpolação linear; "
               "variância e desvio padrão amostrais (n−1); outliers pela regra 1,5 × IQR. "
               "Moda '—'/NaN significa que nenhum valor se repete.")

    tab_est = tabela_estatistica(d_base, ano_ref)
    if tab_est.empty:
        st.info(f"Sem dados para {ano_ref} nos recortes selecionados.")
    else:
        st.dataframe(tab_est, use_container_width=True)

        foco_ops = [k for k, rot in INDICADORES_ROTULO.items() if rot in tab_est.index]
        foco = st.selectbox("Indicador para detalhar o impacto dos outliers", foco_ops,
                            format_func=INDICADORES_ROTULO.get, key=f"foco_trab_{prefix}")
        serie = valores_por_uf(d_base, foco, ano_ref)
        imp = impacto_outliers(serie)
        r = imp["resumo"]
        un = "R$" if foco == "rendimento" else "%"

        k1, k2, k3, k4 = st.columns(4)
        k1.metric("Média (UFs)", f"{fmt(r['media'])}")
        k2.metric("Mediana (UFs)", f"{fmt(r['mediana'])}")
        k3.metric("IQR", f"{fmt(r['iqr'])}")
        k4.metric("Desvio padrão", f"{fmt(r['desvio'])}")

        fora = imp["fora"]
        st.markdown(
            f"**Outliers (1,5 × IQR)** — limites: {fmt(r['lim_inf'])} a {fmt(r['lim_sup'])}. "
            + ("UFs fora dos limites: "
               + ", ".join(f"**{u}** ({fmt(vl)})" for u, vl in fora.sort_values().items()) + "."
               if not fora.empty else "Nenhuma UF ficou fora dos limites."))

        comp_out = pd.DataFrame({
            "Com todas as UFs": [r["media"], r["mediana"]],
            "Sem outliers": [imp["media_sem"], imp["mediana_sem"]],
            "Variação absoluta": [imp["d_media"], imp["d_mediana"]],
            "Variação %": [100 * imp["d_media"] / r["media"] if r["media"] else np.nan,
                           100 * imp["d_mediana"] / r["mediana"] if r["mediana"] else np.nan],
        }, index=["Média", "Mediana"]).round(3)
        st.markdown("**Impacto dos outliers na média × mediana**")
        st.dataframe(comp_out, use_container_width=True)

        if fora.empty:
            st.info("Sem outliers neste recorte, o impacto é nulo: média e mediana não "
                    "mudam. Compare a média com a mediana: a distância entre elas mostra "
                    "a assimetria da distribuição entre as UFs.")
        else:
            menos = abs(imp["d_mediana"]) < abs(imp["d_media"])
            st.info(
                f"Ao retirar {len(fora)} outlier(s), a **média** mudou "
                f"{fmt(imp['d_media'], 3, True)} ({fmt(comp_out.loc['Média', 'Variação %'], 2, True)}%) "
                f"e a **mediana** mudou {fmt(imp['d_mediana'], 3, True)} "
                f"({fmt(comp_out.loc['Mediana', 'Variação %'], 2, True)}%). "
                + ("A mediana foi menos afetada que a média, ou seja, é mais robusta a "
                   "valores extremos — por isso é a medida de tendência central mais "
                   "indicada quando há UFs atípicas."
                   if menos else
                   "Neste recorte a mediana variou tanto quanto (ou mais que) a média; "
                   "com poucas UFs a mediana também pode se deslocar ao se retirar pontos."))

        box_uf = serie.rename("valor").reset_index()
        fig = px.box(box_uf, y="valor", points="all", hover_name="sigla",
                     labels={"valor": f"{INDICADORES_ROTULO[foco]} — {ano_ref}"})
        fig.update_layout(title=f"Distribuição entre as UFs ({ano_ref}) — passe o mouse "
                                "para ver a UF de cada ponto")
        st.plotly_chart(fig, use_container_width=True)

    # ======================================================================
    # GRÁFICOS OBRIGATÓRIOS
    # ======================================================================
    st.header("Visualizações")

    # --- 1. Boxplot interativo da desocupação por UF ---
    st.subheader("Boxplot da desocupação por UF")
    des = _recorte_total(d[d["indicador"] == "desocupacao"])
    if des.empty:
        st.info("Sem dados de desocupação no período/recortes selecionados.")
    else:
        ordem_box = des.groupby("sigla")["valor"].median().sort_values().index.tolist()
        hover = [c for c in ("ano", "sexo") if c in des.columns]
        fig = px.box(des, x="sigla", y="valor", points="all", hover_data=hover,
                     category_orders={"sigla": ordem_box},
                     labels={"sigla": "UF", "valor": "Desocupação (%)"})
        st.plotly_chart(fig, use_container_width=True)
        st.caption(f"Cada caixa resume os registros da UF entre {faixa[0]} e {faixa[1]} "
                   "(anos × sexos filtrados): linha central = mediana, caixa = Q1–Q3, "
                   "bigodes = 1,5 × IQR; pontos fora dos bigodes são outliers. UFs ordenadas "
                   "pela mediana. Interativo: passe o mouse, dê zoom ou clique na legenda.")

    # --- 2. Formal x informal (barras agrupadas) ---
    st.subheader(f"Trabalho formal × informal por UF ({ano_ref})")
    inf = valores_por_uf(d_base, "informalidade", ano_ref)
    if inf.empty:
        st.info(f"Sem dados de informalidade para {ano_ref}.")
    else:
        rot_inf, rot_for = "Informal", "Formal (= 100 − informal)"
        fm = pd.DataFrame({"sigla": inf.index, rot_inf: inf.values,
                           rot_for: 100 - inf.values}).sort_values(rot_inf, ascending=False)
        longo = fm.melt(id_vars="sigla", var_name="Tipo de vínculo", value_name="pct")
        fig = px.bar(longo, x="sigla", y="pct", color="Tipo de vínculo", barmode="group",
                     category_orders={"sigla": fm["sigla"].tolist(),
                                      "Tipo de vínculo": [rot_for, rot_inf]},
                     color_discrete_map={rot_for: "#1565C0", rot_inf: "#EF6C00"},
                     labels={"sigla": "UF", "pct": "% dos ocupados"})
        fig.update_layout(legend_title_text="Tipo de vínculo")
        st.plotly_chart(fig, use_container_width=True)
        st.caption("Legenda: **informal** é o percentual de ocupados sem carteira/registro "
                   "(valor da base); **formal** é o complemento, 100 − informalidade. As "
                   "duas barras de cada UF somam 100%. UFs ordenadas da mais informal "
                   "para a menos informal.")

    # --- 3. Histograma do rendimento: média x mediana ---
    st.subheader(f"Rendimento do trabalho: média × mediana ({ano_ref})")
    rend = valores_por_uf(d_base, "rendimento", ano_ref)
    if rend.empty:
        st.info(f"Sem dados de rendimento para {ano_ref}.")
    else:
        rr = resumo_estatistico(rend)
        fig = px.histogram(rend.rename("valor").reset_index(), x="valor",
                           nbins=int(min(10, max(3, len(rend)))),
                           labels={"valor": "Rendimento (R$)", "count": "Nº de UFs"})
        fig.update_layout(yaxis_title="Nº de UFs", bargap=0.05)
        pos_media, pos_mediana = (("top right", "top left") if rr["media"] >= rr["mediana"]
                                  else ("top left", "top right"))
        fig.add_vline(x=rr["media"], line_dash="dash", line_color="red",
                      annotation_text=f"Média R$ {fmt(rr['media'], 0)}",
                      annotation_position=pos_media)
        fig.add_vline(x=rr["mediana"], line_dash="dot", line_color="green",
                      annotation_text=f"Mediana R$ {fmt(rr['mediana'], 0)}",
                      annotation_position=pos_mediana)
        st.plotly_chart(fig, use_container_width=True)

        dif = rr["media"] - rr["mediana"]
        assim = rend.skew() if len(rend) >= 3 else np.nan
        if abs(dif) < 1e-9:
            leitura = "Média e mediana coincidem: distribuição simétrica."
        elif dif > 0:
            leitura = ("**Média acima da mediana → assimetria positiva (à direita):** "
                       "poucas UFs com rendimentos altos puxam a média para cima; a "
                       "mediana representa melhor a UF típica.")
        else:
            leitura = ("**Média abaixo da mediana → assimetria negativa (à esquerda):** "
                       "poucas UFs com rendimentos baixos puxam a média para baixo.")
        st.markdown(f"Média R$ {fmt(rr['media'])} · Mediana R$ {fmt(rr['mediana'])} · "
                    f"diferença R$ {fmt(dif, 2, True)} · coeficiente de assimetria "
                    f"{fmt(assim, 2)}. {leitura}")
        st.caption("Cada observação do histograma é uma UF (rendimento médio no ano de "
                   "referência). Linha vermelha tracejada = média; verde pontilhada = mediana.")

    # ======================================================================
    # PARIDADE SALARIAL (foco da persona: "paridade salarial")
    # ======================================================================
    st.header(f"Paridade salarial entre mulheres e homens ({ano_ref})")
    razao_rend = razao_mulheres_homens(d_base, "rendimento", ano_ref)
    razao_des = razao_mulheres_homens(d_base, "desocupacao", ano_ref)
    if razao_rend.empty:
        st.info("Sem rendimento de mulheres E homens para este ano/recorte: a base precisa "
                "ter 'sexo' nas linhas de rendimento e o filtro de sexo deve incluir os "
                "dois grupos.")
    else:
        pct = (100 * razao_rend).rename("pct").reset_index().sort_values("pct")
        fig = px.bar(pct, x="sigla", y="pct",
                     category_orders={"sigla": pct["sigla"].tolist()},
                     labels={"sigla": "UF", "pct": "Rendimento das mulheres (% do rendimento dos homens)"})
        fig.add_hline(y=100, line_dash="dash", line_color="gray",
                      annotation_text="Paridade (100%)")
        st.plotly_chart(fig, use_container_width=True)
        pior_uf, melhor_uf = pct.iloc[0], pct.iloc[-1]
        c1, c2, c3 = st.columns(3)
        c1.metric("Média das UFs", f"{fmt(pct['pct'].mean(), 1)}%")
        c2.metric(f"Menor paridade: {pior_uf['sigla']}", f"{fmt(pior_uf['pct'], 1)}%")
        c3.metric(f"Maior paridade: {melhor_uf['sigla']}", f"{fmt(melhor_uf['pct'], 1)}%")
        st.caption("Razão = rendimento médio das mulheres ÷ rendimento médio dos homens na "
                   "UF. Abaixo de 100%, as mulheres ganham menos. Não controla por "
                   "escolaridade, setor ou horas trabalhadas — use os filtros para isolar "
                   "esses fatores.")

    # ======================================================================
    # LEITURA PARA A MESA DE NEGOCIAÇÃO (personas)
    # ======================================================================
    st.header("Leitura para a mesa de negociação")
    st.caption("Texto gerado a partir dos números filtrados; descreve padrões, não causas.")
    pontos = []
    if not comp.empty:
        mel, pio = comp.index[0], comp.index[-1]
        pontos.append(
            f"**Márcia (Ministra do Trabalho):** entre {ano_a} e {ano_b}, a UF com melhor "
            f"desempenho foi **{mel}** ({fmt(comp.loc[mel, 'variacao_pp'], sinal=True)} p.p.) "
            f"e a de pior desempenho foi **{pio}** ({fmt(comp.loc[pio, 'variacao_pp'], sinal=True)} p.p.). "
            "O que explica o contraste é a pergunta a levar para a mesa.")
    if not inf.empty:
        top = inf.sort_values(ascending=False).head(3)
        pontos.append(
            "**Sílvia (Sebrae):** as UFs com maior informalidade em "
            f"{ano_ref} são " + ", ".join(f"**{u}** ({fmt(v, 1)}%)" for u, v in top.items())
            + ". São as prioridades naturais para formalização de pequenos negócios.")
    if not razao_rend.empty:
        pontos.append(
            "**Renato (Conselho de Indústrias):** o rendimento das mulheres é, em média "
            f"nas UFs, **{fmt(100 * razao_rend.mean(), 1)}%** do dos homens; a menor "
            f"paridade está em **{pior_uf['sigla']}** ({fmt(pior_uf['pct'], 1)}%). Metas "
            "salariais devem usar a **mediana**, menos sensível a rendas muito altas.")
    if not razao_des.empty:
        pontos.append(
            f"**Gênero e desocupação ({ano_ref}):** a taxa feminina equivale, em média, a "
            f"**{fmt(razao_des.mean(), 2)}×** a masculina nas UFs.")
    st.markdown("\n\n".join(f"- {p}" for p in pontos) if pontos else
                "Carregue uma base com desocupação, informalidade e rendimento para ver a leitura.")

    # ======================================================================
    # NOTÍCIAS E IMAGENS
    # ======================================================================
    st.header("Notícias e contexto")
    cols = st.columns(min(3, max(1, len(NOTICIAS))))
    for i, n in enumerate(NOTICIAS):
        with cols[i % len(cols)]:
            img = _resolver_imagem(n.get("imagem"))
            if img:
                try:
                    st.image(img, use_container_width=True)
                except Exception:
                    pass  # imagem quebrada não derruba a página
            st.markdown(f"**[{n['titulo']}]({n['url']})**")
            st.caption(n["fonte"])
            if n.get("resumo"):
                st.write(n["resumo"])

    enviadas = st.file_uploader("Adicionar fotos de trabalhadores/ambientes de trabalho "
                                "(PNG/JPG)", type=["png", "jpg", "jpeg"],
                                accept_multiple_files=True, key=f"fotos_trab_{prefix}")
    if enviadas:
        fcols = st.columns(min(3, len(enviadas)))
        for i, f in enumerate(enviadas):
            with fcols[i % len(fcols)]:
                st.image(f, caption=f.name, use_container_width=True)

    st.header("Análise descritiva (entregável)")
    st.caption("Texto e tabelas gerados com os números reais do painel (anos e filtros atuais).")
    md = gerar_analise_md(d_base, ano_a, ano_b, ano_ref, autor)
    st.download_button("Baixar análise descritiva (Markdown)", data=md.encode("utf-8"),
                       file_name="analise_descritiva_tema6.md", mime="text/markdown",
                       key=f"dl_analise_trab_{prefix}")

    fotos = _fotos_galeria()
    if fotos:
        st.subheader("Trabalhadores e ambientes de trabalho no Brasil")
        gcols = st.columns(min(3, len(fotos)))
        for i, p in enumerate(fotos):
            with gcols[i % len(gcols)]:
                try:
                    st.image(str(p), caption=LEGENDAS_FOTOS.get(p.name, ""),
                             use_container_width=True)
                except Exception:
                    pass

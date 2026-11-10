"""Testes da lógica de dados (rodam sem Streamlit/Plotly)."""
import numpy as np, pandas as pd
import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
import modulo_trabalho_emprego as m

# base estilo API do SIDRA: com linhas Total, Homens, Mulheres
rows=[]
for nome in ["Bahia","Pernambuco","Ceará"]:
    for ano,base in ((2012,12.0),(2022,8.0)):
        for tri in ("1º trimestre","2º trimestre"):
            for sx,v in (("Total",base),("Homens",base-1.5),("Mulheres",base+2.0)):
                rows.append({"Unidade da Federação":nome,"Trimestre":f"{tri} {ano}","Sexo":sx,
                             "Variável":"Taxa de desocupação, na semana de referência","Valor":str(v).replace(".",",")})
        rows.append({"Unidade da Federação":nome,"Trimestre":f"1º trimestre {ano}","Sexo":"Total",
                     "Variável":"Pessoas desocupadas","Valor":"900"})   # contagem: deve ser ignorada
rows.append({"Unidade da Federação":"Brasil","Trimestre":"1º trimestre 2012","Sexo":"Total",
             "Variável":"Taxa de desocupação, na semana de referência","Valor":"7,0"})
d=m.padronizar(pd.DataFrame(rows))
assert set(d.indicador)=={"desocupacao"}, d.indicador.unique()
assert d.attrs["relatorio"]["indicador_desconhecido"]==6   # contagens descartadas
assert set(d.sigla)=={"BA","PE","CE"}

# 1) usa o Total, NÃO a média H/M (que seria base+0,25)
v=m.valores_por_uf(d,"desocupacao",2012)
assert np.allclose(v.values,12.0), v
# 2) comparação por UF e variação
c=m.comparar_anos(d,"desocupacao",2012,2022)
assert np.allclose(c["variacao_pp"],-4.0), c
# 3) por sexo (sem Total)
cs=m.comparar_anos(d,"desocupacao",2012,2022,por=("sigla","sexo"))
assert set(cs.index.get_level_values("sexo"))=={"Homens","Mulheres"}
# 4) razão M/H
rz=m.razao_mulheres_homens(d,"desocupacao",2012)
assert np.allclose(rz,(12+2)/(12-1.5)), rz
# 5) filtro seguro: tudo selecionado mantém Total; parcial remove Total e cai nas categorias
ops=["Homens","Mulheres"]
assert len(m.filtrar_nulo_seguro(d,"sexo",ops,todas=ops))==len(d)
h=m.filtrar_nulo_seguro(d,"sexo",["Homens"],todas=ops)
assert set(h.sexo.dropna())=={"Homens"}
assert np.allclose(m.valores_por_uf(h,"desocupacao",2012),10.5)
# 6) filtro por setor não apaga desocupação (dimensão ausente)
d2=d.assign(setor=np.nan)
assert len(m.filtrar_nulo_seguro(d2,"setor",["Indústria"]))==len(d2)
# 7) estatística confere com numpy
s=pd.Series([5,7,7,8,9,10,11,40.0],index=list("ABCDEFGH"))
r=m.resumo_estatistico(s); q1,q3=np.percentile(s,[25,75])
assert abs(r["iqr"]-(q3-q1))<1e-12 and abs(r["desvio"]-s.std(ddof=1))<1e-12 and r["n_outliers"]==1
im=m.impacto_outliers(s); assert list(im["fora"].index)==["H"]
# 8) fallback sem Total + demo + análise md
demo=m.base_demo()
assert not m.comparar_anos(demo,"desocupacao",2012,2022).empty
assert not m.razao_mulheres_homens(demo,"rendimento",2022).empty
md=m.gerar_analise_md(demo,2012,2022,2022,"Teste"); assert "## 3." in md and "Paridade" in md
md2=m.gerar_analise_md(d,2012,2022,2022); assert "BA" in md2 or "CE" in md2
# 9) classificação
assert m._classificar_indicador("Taxa de informalidade, na semana")=="informalidade"
assert m._classificar_indicador("Massa de rendimento real")is None
assert m._classificar_indicador("Rendimento médio real habitual")=="rendimento"
print("TODOS OS TESTES DE LÓGICA PASSARAM")

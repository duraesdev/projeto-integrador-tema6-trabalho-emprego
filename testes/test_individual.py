"""Teste do app individual (leitura de base em dados/, página completa, base ausente)."""
import sys, shutil, tempfile, importlib
from pathlib import Path
from unittest.mock import MagicMock
RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))
import pandas as pd, numpy as np

def fixture():
    rows = []
    ufs = ["Bahia", "Pernambuco", "Ceará", "São Paulo", "Minas Gerais", "Amapá", "Goiás", "Pará"]
    rng = np.random.default_rng(3)
    for i, uf in enumerate(ufs):
        for ano in (2012, 2022):
            for sx, aj, f in (("Total", 0, 1), ("Homens", -1.5, 1.12), ("Mulheres", 2, .88)):
                rows.append((uf, f"1º trimestre {ano}", sx, None, "Taxa de desocupação", 11 - (ano-2012)*.3 + i*.3 + aj))
                rows.append((uf, f"1º trimestre {ano}", sx, None, "Rendimento médio real habitual", (2200 + i*150) * f))
            rows.append((uf, f"1º trimestre {ano}", "Total", None, "Taxa de informalidade", 38 + rng.normal(0, 5)))
    return pd.DataFrame(rows, columns=["Unidade da Federação", "Trimestre", "Sexo", "Escolaridade", "Variável", "Valor"])

def stubs():
    st = MagicMock()
    def col():
        c = MagicMock(); c.selectbox.side_effect = lambda l, ops, index=0, **k: list(ops)[index]; return c
    st.columns.side_effect = lambda n, *a, **k: [col() for _ in range(n if isinstance(n, int) else len(n))]
    st.multiselect.side_effect = lambda l, ops, default=None, **k: list(default if default is not None else ops)
    st.selectbox.side_effect = lambda l, ops, index=0, **k: list(ops)[index]
    st.select_slider.side_effect = lambda l, options, value=None, **k: value
    st.checkbox.side_effect = lambda *a, **k: False
    st.file_uploader.side_effect = lambda *a, **k: []
    sys.modules["streamlit"] = st
    sys.modules["plotly"] = MagicMock(); sys.modules["plotly.express"] = MagicMock()
    return st

def roda(raiz: Path):
    sys.modules.pop("modulo_trabalho_emprego", None)
    spec = importlib.util.spec_from_file_location("modulo_trabalho_emprego", raiz / "modulo_trabalho_emprego.py")
    mod = importlib.util.module_from_spec(spec); sys.modules[spec.name] = mod; spec.loader.exec_module(mod)
    st = stubs(); mod.render(autor="T", prefix="t"); return st

with tempfile.TemporaryDirectory() as d:
    tmp = Path(d); shutil.copy(RAIZ / "modulo_trabalho_emprego.py", tmp)
    st = roda(tmp)
    assert st.info.called and st.plotly_chart.call_count == 0
    print("  ✔ sem base: mostra instrução, sem gráficos inventados")
    (tmp / "dados").mkdir(); fixture().to_csv(tmp / "dados" / "base_tratada.csv", sep=";", index=False, encoding="utf-8-sig")
    st = roda(tmp)
    assert st.success.called and not st.error.called and st.plotly_chart.call_count >= 6
    print(f"  ✔ com dados/base_tratada.csv: página completa ({st.plotly_chart.call_count} gráficos)")
print("TESTES DO INDIVIDUAL PASSARAM")

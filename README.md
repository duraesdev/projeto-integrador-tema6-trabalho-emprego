# Tema 6 — Trabalho e População Empregada (individual)

## Instalar e rodar
    pip install -r requirements.txt
    python coletar_dados.py          # gera dados/base_tratada.csv (precisa de internet)
    streamlit run app_individual.py

Sem `dados/base_tratada.csv` o painel pede o upload (CSV/XLSX) na barra lateral. Há uma opção de
dados de demonstração (sintéticos, avisados na tela) só para testar a interface: não usar na entrega.

## O que tem
Desocupação por UF 2012 × 2022, por gênero, UF que mais reduziu; informalidade (formal × informal);
histograma do rendimento (média × mediana); paridade salarial; estatísticas por UF (média, mediana,
moda, quartis, IQR, amplitude, variância, desvio) e outliers (1,5 × IQR); notícias (PNAD/CAGED);
fotos; filtros UF, período, sexo, escolaridade e setor; downloads da base e da análise descritiva.

## Dados — leia antes de entregar
- Tabelas em `TABELAS` (coletar_dados.py) são **candidatas, não verificadas**: confira em
  https://sidra.ibge.gov.br/tabela/<número>. O script imprime um RESUMO do que entrou na base.
- Se faltar algo: `python coletar_dados.py --tabela <n>` ou baixe o CSV no SIDRA e use `--arquivo`.
- Valor da UF = linha "Total" do IBGE (senão, média das categorias). A PNAD é trimestral: o ano é a média dos trimestres.

## Testes
    python testes/test_logica.py
    python testes/test_individual.py
(usam bases sintéticas só de teste; não validam os números reais do IBGE.)

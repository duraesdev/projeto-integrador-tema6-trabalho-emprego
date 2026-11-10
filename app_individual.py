"""Dashboard individual — Tema 6: Trabalho e População Empregada.
Rode com:  streamlit run app_individual.py
"""
import streamlit as st

from modulo_trabalho_emprego import render

st.set_page_config(page_title="Tema 6 — Trabalho e Emprego", layout="wide")
render(autor="João Pedro Durães", prefix="individual")

"""
App Streamlit: dashboard comparativo 1º x 2º turno 2026 (votos por hora e por candidato).

Rodar localmente:
    pip install -r requirements.txt
    streamlit run app.py

Publicar (Streamlit Community Cloud): aponte para este repositório, branch main, arquivo app.py.
O app lê logs_t1.sqlite, logs.sqlite, candidatos.json e municipios.json (todos no repositório)
e embute o mesmo dashboard de dashboard_template.html.
"""
from pathlib import Path

import streamlit as st

from gerar_dashboard import montar_html

AQUI = Path(__file__).parent

st.set_page_config(page_title="Comparativo 1º x 2º turno 2026", page_icon="🗳️", layout="wide")

# o dashboard já tem cabeçalho próprio: reduz o espaço em volta
st.markdown(
    "<style>.block-container{padding-top:1rem;padding-bottom:0;max-width:1300px}"
    "header[data-testid='stHeader']{height:0}</style>",
    unsafe_allow_html=True,
)


@st.cache_data(show_spinner="Carregando os dados…")
def carregar():
    bancos_ok = (AQUI / "logs.sqlite").exists() and (AQUI / "logs_t1.sqlite").exists()
    if bancos_ok:
        html, *_ = montar_html(AQUI / "logs_t1.sqlite", AQUI / "logs.sqlite", AQUI / "candidatos.json")
        return html
    pronto = AQUI / "dashboard.html"  # alternativa: dashboard já gerado
    return pronto.read_text(encoding="utf-8") if pronto.exists() else None


html = carregar()
if html is None:
    st.error("Dados não encontrados: faltam logs.sqlite e logs_t1.sqlite (ou dashboard.html) ao lado do app.py.")
else:
    # HTML gerado por nós (template + dados do repositório), não conteúdo de usuário
    if hasattr(st, "iframe"):
        st.iframe(html, height=2800)
    else:  # versões antigas do Streamlit
        import streamlit.components.v1 as components

        components.html(html, height=2800, scrolling=True)

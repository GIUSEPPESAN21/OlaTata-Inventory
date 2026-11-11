"""Vista: Análisis. Propiedad de A3 (ANÁLISIS). Contrato: `render(ctx)`."""
from __future__ import annotations

import streamlit as st

from views import ViewContext


def render(ctx: ViewContext) -> None:
    st.info("Análisis: en construcción (M4).")

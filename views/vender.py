"""Vista: Vender. Propiedad de A2 (VENTAS). Contrato: `render(ctx)`."""
from __future__ import annotations

import streamlit as st

from views import ViewContext


def render(ctx: ViewContext) -> None:
    st.info("Vender: en construcción (M3).")

"""Vista: Ventas. Propiedad de A2 (VENTAS). Contrato: `render(ctx)`."""
from __future__ import annotations

import streamlit as st

from views import ViewContext


def render(ctx: ViewContext) -> None:
    st.info("Ventas: en construcción (M3).")

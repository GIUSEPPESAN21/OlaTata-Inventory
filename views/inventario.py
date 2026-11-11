"""Vista: Inventario. Propiedad de A1 (INVENTARIO). Contrato: `render(ctx)`."""
from __future__ import annotations

import streamlit as st

from views import ViewContext


def render(ctx: ViewContext) -> None:
    st.info("Inventario: en construcción (M2).")

# Reglas de este proyecto (Ola Tata · Inventario y Ventas)

Estas reglas rigen TODO desarrollo en este repositorio, para cualquier
agente o persona que edite código aquí. Ver `docs/CONTRATOS.md` para las
firmas exactas de la base congelada.

## No negociable

1. **Dinero**: siempre `int` en pesos COP. Jamás `float`. Usa
   `core.money.parse_pesos/format_cop/round_half_up_pesos/format_percent`.
   Porcentajes con `Decimal`, redondeo mitad arriba solo al mostrar.
2. **Tiempo**: todo corte de día/semana/mes usa `America/Bogota`
   (`core.timeutil`), NUNCA UTC. Nunca uses `datetime.now()` ni
   `datetime.utcnow()` directo en lógica de negocio — usa
   `core.timeutil.now_utc()`. Guarda siempre ISO-8601 UTC con offset.
3. **Atomicidad**: toda escritura de datos ocurre dentro de
   `storage.transaction()`. Si algo falla a mitad de camino, no debe
   quedar nada a medias (ni en memoria ni en disco).
4. **Permisos**: revalídalos en `core/` con `core.permissions.requerir()`
   al inicio de cada función de dominio sensible. Ocultar un botón en la
   UI nunca es suficiente.
5. **Texto libre**: pasa por `core.excel_safe.excel_safe()` antes de
   guardarse. Un texto que empieza por "=" nunca se trata como fórmula
   ni se pierde.
6. **Stock**: nunca negativo (salvo que `permitir_vender_sin_stock` esté
   activo, y aun así el invariante `stock = Σ movimientos` sigue
   valiendo). Toda variación de stock genera una fila en `movimientos`.
7. **Cierre mensual**: los contadores de ventas/análisis reinician por
   mes calendario de Bogotá; el `stock` JAMÁS se reinicia. El cierre
   archiva y verifica antes de vaciar la base viva; si la verificación
   falla, no toca nada.
8. **Paleta de marca** (tema claro fijo, ver `.streamlit/config.toml`):
   primario `#C2185B`, rosa de marca `#FC7DA9` (nunca texto blanco
   encima), fondo `#FDEFF0`, barra lateral `#FCE8EC`, dorado `#C09860` /
   texto dorado `#7A5A1F`, tinta `#2B1B22`, texto secundario `#6B4A57`,
   éxito `#1E7E4F`, error `#B3261E`, alerta texto `#8A5A00` sobre
   `#FFF4D6`. Sin selectores `.st-emotion-cache-*` (se rompen entre
   versiones de Streamlit) — solo tema nativo y `data-testid` estables.
9. **Pruebas**: toda función de dominio nueva lleva pruebas. `core/`
   debe mantenerse en ≥85% de cobertura. `ruff check .` limpio.

## Contratos congelados

Ver `docs/CONTRATOS.md`. Solo el agente principal (coordinador) modifica
`core/schema.py`, `core/money.py`, `core/timeutil.py`, `core/storage.py`,
`core/permissions.py`, `requirements.txt`, `requirements-dev.txt` y este
archivo. Si tu módulo necesita un cambio ahí, pídelo en tu informe final.

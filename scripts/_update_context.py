"""Script temporal para actualizar PROJECT_CONTEXT.md - Ejecutar y borrar."""
from pathlib import Path

ctx_path = Path(__file__).resolve().parent.parent / "PROJECT_CONTEXT.md"
content = ctx_path.read_text(encoding="utf-8")

# 1. Marcar Fase 3 como completada
content = content.replace(
    "- [ ] Fase 3: Motor de Investigación (`scripts/research_engine.py`).",
    "- [x] Fase 3: Motor de Investigación (`scripts/research_engine.py`) ✅.",
)

# 2. Añadir decisiones técnicas nuevas
old_decision = '| 2026-03-26 | Placeholders `{{PRICE_N}}` en contenido | CF Worker resuelve precios en runtime, cumple ToS Amazon |'
new_decisions = old_decision + """
| 2026-04-03 | Parseo defensivo con try/except por campo | Si Amazon cambia un selector, solo falla ese campo (null) en vez de romper todo el script |
| 2026-04-03 | Pytrends con throttle 2-5s entre seeds | Google Trends aplica rate-limiting agresivo; pausa obligatoria entre consultas |
| 2026-04-03 | Throttle 10-20s entre nichos en scraping | Reducir huella anti-bot y proteger temperatura/memoria del hardware |
| 2026-04-03 | hugo.toml actualizado a config real | PaperMod, idioma es-es, título y parámetros de producción |"""
content = content.replace(old_decision, new_decisions)

# 3. Añadir entrada al changelog
old_changelog = '<!-- Formato: ### [YYYY-MM-DD] Título breve → detalles de lo que se hizo -->'
new_changelog = old_changelog + """

### [2026-04-03] Fase 3 completada: Motor de Investigación
- Implementado `scripts/research_engine.py` (~350 líneas) con arquitectura modular:
  - `load_niches()`: Carga y filtrado de nichos desde `data/niches.json`
  - `expand_keywords()`: Expansión de keywords vía Pytrends (sugerencias + related queries)
  - `search_amazon()`: Scraping de búsqueda en Amazon.es con detección de CAPTCHA
  - `parse_product_card()`: Extracción defensiva de ASIN, título, precio, rating, reviews, imagen
  - `save_research_output()`: Guardado JSON estructurado en `data/research_output/{nicho}/`
  - CLI completo con argparse: `--niche`, `--keyword`, `--max-products`, `--skip-trends`, `--dry-run`
- Anti-bot: rotación UA (via utils.py), throttle 4-10s entre keywords, 10-20s entre nichos
- Actualizado `site/hugo.toml`: tema PaperMod, idioma es-es, título "Guía de Compras Pro", params producción"""
content = content.replace(old_changelog, new_changelog)

ctx_path.write_text(content, encoding="utf-8")
print("✅ PROJECT_CONTEXT.md actualizado correctamente")

"""
research_engine.py — Motor de Investigación del pipeline Amazon Affiliate.

Fase 3 del roadmap:
  1. Carga keywords semilla desde data/niches.json.
  2. Expande keywords con Google Trends (Pytrends).
  3. Busca cada keyword en Amazon.es y extrae productos top.
  4. Guarda resultados estructurados en data/research_output/{nicho}/{keyword}.json.

Uso:
  python scripts/research_engine.py                          # Todas las categorías
  python scripts/research_engine.py --niche mascotas         # Solo un nicho
  python scripts/research_engine.py --niche mascotas --keyword "comedero automatico gato"  # Solo una keyword
  python scripts/research_engine.py --skip-trends            # Saltar Pytrends (solo seeds)
  python scripts/research_engine.py --max-products 5         # Limitar productos por keyword
  python scripts/research_engine.py --dry-run                # Solo 1 keyword, 1 producto (test)
"""

import argparse

import requests
import json
import re
import time
import random
from datetime import datetime
from pathlib import Path
from urllib.parse import quote_plus, urljoin

from bs4 import BeautifulSoup

from utils import (
    DATA_DIR,
    setup_logging,
    safe_request,
    get_random_headers,
    throttle,
    create_amazon_session,
    safe_session_request,
)

# ─────────────────────────────────────────────
# Constantes
# ─────────────────────────────────────────────

AMAZON_BASE_URL = "https://www.amazon.es"
AMAZON_SEARCH_URL = f"{AMAZON_BASE_URL}/s"
RESEARCH_OUTPUT_DIR = DATA_DIR / "research_output"

MAX_PRODUCTS_DEFAULT = 10
PYTRENDS_MAX_KEYWORDS = 8  # Máximo de keywords expandidas a añadir por seed

logger = setup_logging("research_engine")


# ─────────────────────────────────────────────
# 1. Carga de Nichos
# ─────────────────────────────────────────────

def load_niches(niche_filter: str | None = None) -> dict:
    """
    Carga data/niches.json y devuelve el dict completo o filtrado por nicho.

    Args:
        niche_filter: Si se indica, devuelve solo ese nicho.

    Returns:
        Dict con la estructura {niche_name: {category_slug, seed_keywords}}.
    """
    niches_path = DATA_DIR / "niches.json"
    if not niches_path.exists():
        logger.error(f"✗ No se encontró {niches_path}")
        raise FileNotFoundError(f"Archivo de nichos no encontrado: {niches_path}")

    with open(niches_path, "r", encoding="utf-8") as f:
        niches = json.load(f)

    if niche_filter:
        if niche_filter not in niches:
            logger.error(f"✗ Nicho '{niche_filter}' no existe. Disponibles: {list(niches.keys())}")
            raise ValueError(f"Nicho no encontrado: {niche_filter}")
        niches = {niche_filter: niches[niche_filter]}

    logger.info(f"📂 Cargados {len(niches)} nicho(s): {list(niches.keys())}")
    return niches


# ─────────────────────────────────────────────
# 2. Expansión de Keywords (Pytrends)
# ─────────────────────────────────────────────

def expand_keywords(
    seed_keywords: list[str],
    geo: str = "ES",
    max_expansion: int = PYTRENDS_MAX_KEYWORDS,
) -> list[str]:
    """
    Usa Google Trends (Pytrends) para expandir las keywords semilla con sugerencias
    y queries relacionadas.

    Args:
        seed_keywords: Lista de keywords originales del nicho.
        geo: Código geográfico (default: 'ES' para España).
        max_expansion: Máximo de keywords nuevas a añadir por semilla.

    Returns:
        Lista combinada de keywords originales + expandidas (sin duplicados).
    """
    try:
        from pytrends.request import TrendReq
    except ImportError:
        logger.warning("⚠ Pytrends no instalado. Usando solo keywords semilla.")
        return seed_keywords

    all_keywords = list(seed_keywords)  # Copia
    seen = set(kw.lower().strip() for kw in seed_keywords)

    try:
        pytrends = TrendReq(hl="es-ES", tz=120)  # UTC+2 (España)
    except Exception as e:
        logger.warning(f"⚠ Error inicializando Pytrends: {e}. Usando solo seeds.")
        return seed_keywords

    for seed in seed_keywords:
        logger.info(f"  🔍 Expandiendo: '{seed}'")
        new_from_seed = []

        try:
            # 1. Sugerencias de autocompletado
            suggestions = pytrends.suggestions(keyword=seed)
            for s in suggestions:
                title = s.get("title", "").lower().strip()
                if title and title not in seen and len(title) > 3:
                    new_from_seed.append(title)
                    seen.add(title)

        except Exception as e:
            logger.warning(f"    ⚠ Error en suggestions para '{seed}': {e}")

        try:
            # 2. Queries relacionadas
            pytrends.build_payload([seed], cat=0, timeframe="today 3-m", geo=geo)
            related = pytrends.related_queries()

            if seed in related and related[seed].get("related") is not None:
                related_df = related[seed]["related"]
                if related_df is not None and not related_df.empty:
                    for _, row in related_df.head(max_expansion).iterrows():
                        query = row.get("query", "").lower().strip()
                        if query and query not in seen and len(query) > 3:
                            new_from_seed.append(query)
                            seen.add(query)

        except Exception as e:
            logger.warning(f"    ⚠ Error en related_queries para '{seed}': {e}")

        # Limitar expansiones por seed
        added = new_from_seed[:max_expansion]
        all_keywords.extend(added)
        logger.info(f"    ✓ +{len(added)} keywords nuevas desde '{seed}'")

        # Throttle entre peticiones a Google Trends (son agresivos con rate-limiting)
        time.sleep(random.uniform(2.0, 5.0))

    logger.info(f"📊 Keywords totales tras expansión: {len(all_keywords)} (de {len(seed_keywords)} seeds)")
    return all_keywords


# ─────────────────────────────────────────────
# 3. Parsing de Productos Amazon
# ─────────────────────────────────────────────

def parse_product_card(card, position: int) -> dict | None:
    """
    Extrae datos de una tarjeta de resultado de búsqueda de Amazon.es.
    Parseo defensivo: cada campo se extrae individualmente con try/except.

    Args:
        card: Elemento BeautifulSoup del div de resultado.
        position: Posición en los resultados (1-indexed).

    Returns:
        Dict con datos del producto, o None si no se pudo extraer el ASIN.
    """
    product = {"position": position}

    # --- ASIN (obligatorio, sin él no vale para nada) ---
    asin = card.get("data-asin", "").strip()
    if not asin:
        return None
    product["asin"] = asin

    # --- Título ---
    try:
        title_el = (
            card.select_one("h2 a span") or 
            card.select_one("h2 span.a-text-normal") or
            card.select_one("span.a-size-medium") or
            card.select_one("span.a-size-base-plus") or
            card.select_one("img.s-image[alt]")
        )
        if title_el:
            product["title"] = title_el.get("alt", title_el.get_text(strip=True)) if title_el.name == "img" else title_el.get_text(strip=True)
            if not product["title"]:
                product["title"] = None
        else:
            product["title"] = None
    except Exception:
        product["title"] = None

    # --- Precio ---
    try:
        price_whole_el = card.select_one("span.a-price-whole")
        price_frac_el = card.select_one("span.a-price-fraction")

        if price_whole_el:
            # Amazon ES usa formato "34,99" → extraemos whole y fraction
            whole = price_whole_el.get_text(strip=True).replace(".", "").replace(",", "")
            frac = price_frac_el.get_text(strip=True) if price_frac_el else "00"
            product["price_eur"] = float(f"{whole}.{frac}")
        else:
            product["price_eur"] = None
    except (ValueError, AttributeError):
        product["price_eur"] = None

    # --- Rating ---
    try:
        rating_el = card.select_one("span.a-icon-alt")
        if rating_el:
            rating_text = rating_el.get_text(strip=True)
            # Formato: "4,3 de 5 estrellas" → extraer 4.3
            match = re.search(r"(\d+[.,]\d+)", rating_text)
            if match:
                product["rating"] = float(match.group(1).replace(",", "."))
            else:
                product["rating"] = None
        else:
            product["rating"] = None
    except (ValueError, AttributeError):
        product["rating"] = None

    # --- Número de reviews ---
    try:
        # Buscar el link con el conteo de reviews
        review_el = card.select_one('a[href*="#customerReviews"] span.a-size-base')
        if not review_el:
            review_el = card.select_one("span.a-size-base.s-underline-text")

        if review_el:
            review_text = review_el.get_text(strip=True).replace(".", "").replace(",", "")
            # Extraer solo dígitos
            digits = re.sub(r"[^\d]", "", review_text)
            product["review_count"] = int(digits) if digits else None
        else:
            product["review_count"] = None
    except (ValueError, AttributeError):
        product["review_count"] = None

    # --- Imagen ---
    try:
        img_el = card.select_one("img.s-image")
        if img_el:
            raw_url = img_el.get("src", "")
            # Transformar URL de miniatura (ej: '..._AC_UL320_.jpg') a original ('...jpg')
            clean_url = re.sub(r'\._[^.]+\.([a-zA-Z0-9]+)$', r'.\1', raw_url) if raw_url else None
            product["image_url"] = clean_url
        else:
            product["image_url"] = None
    except AttributeError:
        product["image_url"] = None

    # --- URL del producto ---
    try:
        link_el = card.select_one("h2 a") or card.select_one("a.a-link-normal.s-no-outline")
        if link_el and link_el.get("href"):
            href = link_el["href"]
            # Construir URL completa y limpiar tracking params
            if href.startswith("/"):
                product["product_url"] = f"{AMAZON_BASE_URL}/dp/{asin}"
            else:
                product["product_url"] = f"{AMAZON_BASE_URL}/dp/{asin}"
        else:
            product["product_url"] = f"{AMAZON_BASE_URL}/dp/{asin}"
    except AttributeError:
        product["product_url"] = f"{AMAZON_BASE_URL}/dp/{asin}"

    # --- Validación: como mínimo necesitamos título ---
    if not product.get("title"):
        logger.debug(f"    ⚠ Producto {asin} sin título, descartado")
        return None

    return product


def search_amazon(
    keyword: str,
    max_products: int = MAX_PRODUCTS_DEFAULT,
    session: requests.Session | None = None,
) -> list[dict]:
    """
    Busca una keyword en Amazon.es y devuelve una lista de productos parseados.

    Args:
        keyword: Término de búsqueda.
        max_products: Número máximo de productos a extraer.
        session: Sesión de requests con cookies (recomendado). Si None, usa safe_request sin sesión.

    Returns:
        Lista de dicts con datos de productos.
    """
    encoded_kw = quote_plus(keyword)
    url = f"{AMAZON_SEARCH_URL}?k={encoded_kw}&__mk_es_ES=ÅMÅŽÕÑ"

    logger.info(f"  🛒 Buscando en Amazon.es: '{keyword}'")

    # Usar sesión si disponible, sino fallback a safe_request
    if session:
        response = safe_session_request(session, url, logger=logger)
    else:
        response = safe_request(url, logger=logger)

    if not response:
        logger.error(f"    ✗ No se pudo obtener resultados para '{keyword}'")
        return []

    # Verificar CAPTCHA (safe_session_request ya lo detecta, pero doble check)
    body_lower = response.text[:5000].lower()
    if "captcha" in body_lower or "robot" in body_lower:
        logger.warning(f"    ⚠ CAPTCHA detectado para '{keyword}'. Saltando.")
        return []

    soup = BeautifulSoup(response.text, "html.parser")

    # Buscar tarjetas de producto
    cards = soup.select('div[data-component-type="s-search-result"]')

    if not cards:
        # Intento alternativo con otro selector
        cards = soup.select('div[data-asin]:not([data-asin=""])')
        # Filtrar los que no son anuncios ni contenedores vacíos
        cards = [c for c in cards if c.get("data-asin") and len(c.get("data-asin", "")) >= 10]

    logger.info(f"    📦 {len(cards)} tarjetas encontradas")

    products = []
    for i, card in enumerate(cards, start=1):
        if len(products) >= max_products:
            break

        product = parse_product_card(card, position=i)
        if product:
            products.append(product)
            logger.info(
                f"    ✓ [{i}] {product['asin']}: "
                f"{product['title'][:50]}... "
                f"{'€' + str(product['price_eur']) if product['price_eur'] else 'sin precio'}"
            )

    logger.info(f"    📊 {len(products)} productos válidos de {len(cards)} tarjetas")
    return products


# ─────────────────────────────────────────────
# 4. Guardado de Resultados
# ─────────────────────────────────────────────

def slugify(text: str) -> str:
    """Convierte un texto a un slug válido para nombre de archivo."""
    text = text.lower().strip()
    text = re.sub(r"[áàä]", "a", text)
    text = re.sub(r"[éèë]", "e", text)
    text = re.sub(r"[íìï]", "i", text)
    text = re.sub(r"[óòö]", "o", text)
    text = re.sub(r"[úùü]", "u", text)
    text = re.sub(r"[ñ]", "n", text)
    text = re.sub(r"[^a-z0-9]+", "_", text)
    text = text.strip("_")
    return text


def save_research_output(niche: str, keyword: str, products: list[dict]) -> Path:
    """
    Guarda los resultados de investigación en un archivo JSON estructurado.

    Args:
        niche: Nombre del nicho (ej. 'mascotas').
        keyword: Keyword buscada.
        products: Lista de productos extraídos.

    Returns:
        Path del archivo guardado.
    """
    output_dir = RESEARCH_OUTPUT_DIR / niche
    output_dir.mkdir(parents=True, exist_ok=True)

    slug = slugify(keyword)
    output_file = output_dir / f"{slug}.json"

    data = {
        "keyword": keyword,
        "niche": niche,
        "scraped_at": datetime.now().isoformat(timespec="seconds"),
        "source": "amazon.es",
        "products": products,
        "total_results_found": len(products),
    }

    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    logger.info(f"  💾 Guardado: {output_file} ({len(products)} productos)")
    return output_file


# ─────────────────────────────────────────────
# 5. Orquestación Principal
# ─────────────────────────────────────────────

# Máximo de reintentos de sesión ante CAPTCHA persistente
MAX_SESSION_RETRIES = 2


def run_research(
    niche_filter: str | None = None,
    keyword_filter: str | None = None,
    max_products: int = MAX_PRODUCTS_DEFAULT,
    skip_trends: bool = False,
    dry_run: bool = False,
) -> dict:
    """
    Ejecuta el ciclo completo de investigación.

    Mejoras anti-CAPTCHA:
    - Crea una sesión HTTP con cookies persistentes (warm-up a homepage).
    - Si CAPTCHA persiste en una keyword, recrea la sesión (max 2 veces).
    - Throttle más largo entre keywords (8-15s) para simular humano.

    Args:
        niche_filter: Procesar solo este nicho.
        keyword_filter: Procesar solo esta keyword (requiere niche_filter).
        max_products: Máximo de productos por keyword.
        skip_trends: Si True, no usar Pytrends (solo seeds).
        dry_run: Modo test — 1 keyword, max 3 productos.

    Returns:
        Dict con estadísticas de la ejecución.
    """
    stats = {
        "niches_processed": 0,
        "keywords_processed": 0,
        "products_found": 0,
        "files_saved": 0,
        "captchas": 0,
        "session_resets": 0,
        "errors": 0,
    }

    # 1. Cargar nichos
    niches = load_niches(niche_filter)

    # 2. Crear sesión Amazon con warm-up
    logger.info("\n🔐 Creando sesión Amazon con warm-up...")
    session, ua = create_amazon_session(logger=logger)
    logger.info(f"  🔑 UA fijado: {ua[:60]}...")

    # Pausa post warm-up (simular humano mirando la homepage)
    warmup_pause = random.uniform(3.0, 6.0)
    logger.info(f"  ⏳ Pausa post warm-up: {warmup_pause:.1f}s")
    time.sleep(warmup_pause)

    for niche_name, niche_data in niches.items():
        logger.info(f"\n{'='*60}")
        logger.info(f"🏷️  NICHO: {niche_name}")
        logger.info(f"{'='*60}")

        seed_keywords = niche_data.get("seed_keywords", [])

        if keyword_filter:
            if keyword_filter in seed_keywords or keyword_filter.lower() in [k.lower() for k in seed_keywords]:
                keywords = [keyword_filter]
            else:
                # Permitir keywords no semilla si se especifican explícitamente
                keywords = [keyword_filter]
            logger.info(f"  🎯 Keyword manual: {keywords}")
        elif skip_trends:
            keywords = seed_keywords
            logger.info(f"  📋 Usando {len(keywords)} keywords semilla (sin Pytrends)")
        else:
            # Expandir keywords con Pytrends
            keywords = expand_keywords(seed_keywords)

        # Dry run: solo la primera keyword
        if dry_run:
            keywords = keywords[:1]
            max_products = min(max_products, 3)
            logger.info(f"  🧪 DRY RUN: 1 keyword, máx {max_products} productos")

        # 3. Scraping de Amazon por cada keyword
        for i, keyword in enumerate(keywords, start=1):
            logger.info(f"\n  ── Keyword {i}/{len(keywords)}: '{keyword}' ──")

            try:
                products = search_amazon(
                    keyword, max_products=max_products, session=session
                )

                # Si 0 productos, puede ser CAPTCHA — intentar reset de sesión
                if not products:
                    stats["captchas"] += 1
                    logger.warning(f"    ⚠ 0 productos para '{keyword}'")

                    # Recrear sesión si tenemos reintentos disponibles
                    if stats["session_resets"] < MAX_SESSION_RETRIES:
                        stats["session_resets"] += 1
                        logger.info(
                            f"    🔄 Recreando sesión ({stats['session_resets']}/{MAX_SESSION_RETRIES})..."
                        )
                        session.close()
                        reset_pause = random.uniform(15.0, 30.0)
                        logger.info(f"    ⏳ Pausa antes de nueva sesión: {reset_pause:.0f}s")
                        time.sleep(reset_pause)
                        session, ua = create_amazon_session(logger=logger)
                        logger.info(f"    🔑 Nuevo UA: {ua[:60]}...")

                        # Reintentar esta keyword con la nueva sesión
                        time.sleep(random.uniform(3.0, 6.0))
                        products = search_amazon(
                            keyword, max_products=max_products, session=session
                        )

                if products:
                    output_path = save_research_output(niche_name, keyword, products)
                    stats["products_found"] += len(products)
                    stats["files_saved"] += 1

                stats["keywords_processed"] += 1

            except Exception as e:
                logger.error(f"    ✗ Error procesando '{keyword}': {e}", exc_info=True)
                stats["errors"] += 1

            # Throttle entre keywords (más largo para parecer humano)
            if i < len(keywords):
                logger.info("    ⏳ Throttle entre keywords...")
                throttle(min_sec=8.0, max_sec=15.0)

        stats["niches_processed"] += 1

        # Throttle más agresivo entre nichos
        if stats["niches_processed"] < len(niches):
            wait = random.uniform(15.0, 30.0)
            logger.info(f"\n  ⏳ Pausa entre nichos: {wait:.1f}s")
            time.sleep(wait)

    # Cerrar sesión al final
    session.close()

    return stats


# ─────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────

def parse_args() -> argparse.Namespace:
    """Configura y parsea argumentos de línea de comandos."""
    parser = argparse.ArgumentParser(
        description="Motor de Investigación — Amazon Affiliate Pipeline",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Ejemplos:
  python scripts/research_engine.py                                    # Todo
  python scripts/research_engine.py --niche mascotas                   # Solo mascotas
  python scripts/research_engine.py --niche mascotas --keyword "cama perro grande"
  python scripts/research_engine.py --skip-trends --max-products 5
  python scripts/research_engine.py --dry-run                          # Test rápido
        """,
    )
    parser.add_argument(
        "--niche",
        type=str,
        default=None,
        help="Procesar solo este nicho (ej: mascotas, herramientas, hogar)",
    )
    parser.add_argument(
        "--keyword",
        type=str,
        default=None,
        help="Procesar solo esta keyword (requiere --niche)",
    )
    parser.add_argument(
        "--max-products",
        type=int,
        default=MAX_PRODUCTS_DEFAULT,
        help=f"Máximo de productos por keyword (default: {MAX_PRODUCTS_DEFAULT})",
    )
    parser.add_argument(
        "--skip-trends",
        action="store_true",
        help="No usar Pytrends (solo keywords semilla)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Modo test: 1 keyword, máx 3 productos",
    )
    return parser.parse_args()


def main():
    """Punto de entrada principal."""
    args = parse_args()

    logger.info("🚀 Iniciando Motor de Investigación")
    logger.info(f"   Configuración: niche={args.niche}, keyword={args.keyword}, "
                f"max_products={args.max_products}, skip_trends={args.skip_trends}, "
                f"dry_run={args.dry_run}")

    start_time = time.time()

    stats = run_research(
        niche_filter=args.niche,
        keyword_filter=args.keyword,
        max_products=args.max_products,
        skip_trends=args.skip_trends,
        dry_run=args.dry_run,
    )

    elapsed = time.time() - start_time

    logger.info(f"\n{'='*60}")
    logger.info("📊 RESUMEN DE EJECUCIÓN")
    logger.info(f"{'='*60}")
    logger.info(f"  Tiempo total:       {elapsed:.1f}s")
    logger.info(f"  Nichos procesados:  {stats['niches_processed']}")
    logger.info(f"  Keywords procesadas:{stats['keywords_processed']}")
    logger.info(f"  Productos encontr.: {stats['products_found']}")
    logger.info(f"  Archivos guardados: {stats['files_saved']}")
    logger.info(f"  CAPTCHAs recibidos: {stats['captchas']}")
    logger.info(f"  Resets de sesión:   {stats['session_resets']}")
    logger.info(f"  Errores:            {stats['errors']}")
    logger.info("✅ Motor de Investigación finalizado.\n")


if __name__ == "__main__":
    main()

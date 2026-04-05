"""
context_builder.py — Constructor de Contexto del pipeline Amazon Affiliate.

Fase 4 del roadmap:
  1. Carga feeds RSS configurados en data/niches.json para cada nicho.
  2. Descarga y parsea los feeds con feedparser.
  3. Extrae artículos recientes (título, resumen, fecha, URL).
  4. Construye un contexto JSON estructurado que el LLM Writer usará
     para evitar alucinaciones y generar contenido actualizado.
  5. Guarda resultados en data/context_output/{nicho}/context.json.

Uso:
  python scripts/context_builder.py                          # Todos los nichos
  python scripts/context_builder.py --niche mascotas         # Solo un nicho
  python scripts/context_builder.py --max-articles 10        # Limitar artículos por feed
  python scripts/context_builder.py --dry-run                # Solo 1 feed, 3 artículos (test)
"""

import argparse
import json
import re
import time
import random
from datetime import datetime
from pathlib import Path

import feedparser

from utils import (
    DATA_DIR,
    setup_logging,
    safe_request,
    throttle,
)

# ─────────────────────────────────────────────
# Constantes
# ─────────────────────────────────────────────

CONTEXT_OUTPUT_DIR = DATA_DIR / "context_output"
MAX_ARTICLES_DEFAULT = 8  # Artículos por feed
MAX_SUMMARY_LENGTH = 500  # Máximo de caracteres por resumen individual

logger = setup_logging("context_builder")


# ─────────────────────────────────────────────
# 1. Carga de Feeds RSS
# ─────────────────────────────────────────────

def load_feeds(niche_filter: str | None = None) -> dict:
    """
    Carga la configuración de feeds RSS desde data/niches.json.

    Args:
        niche_filter: Si se indica, devuelve solo los feeds de ese nicho.

    Returns:
        Dict con la estructura {niche_name: {category_slug, seed_keywords, rss_feeds}}.
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

    # Validar que cada nicho tiene feeds
    for name, data in niches.items():
        feeds = data.get("rss_feeds", [])
        if not feeds:
            logger.warning(f"⚠ Nicho '{name}' no tiene feeds RSS configurados")

    logger.info(f"📂 Cargados {len(niches)} nicho(s): {list(niches.keys())}")
    return niches


# ─────────────────────────────────────────────
# 2. Descarga y Parsing de Feeds
# ─────────────────────────────────────────────

def clean_html(raw_html: str) -> str:
    """Elimina tags HTML y limpia whitespace de un string."""
    if not raw_html:
        return ""
    # Eliminar tags HTML
    clean = re.sub(r"<[^>]+>", " ", raw_html)
    # Eliminar entities HTML comunes
    clean = clean.replace("&nbsp;", " ")
    clean = clean.replace("&amp;", "&")
    clean = clean.replace("&lt;", "<")
    clean = clean.replace("&gt;", ">")
    clean = clean.replace("&quot;", '"')
    clean = clean.replace("&#39;", "'")
    # Colapsar whitespace múltiple
    clean = re.sub(r"\s+", " ", clean).strip()
    return clean


def fetch_feed(feed_url: str, feed_name: str) -> feedparser.FeedParserDict | None:
    """
    Descarga y parsea un feed RSS.

    Intenta primero con feedparser directo. Si falla, usa safe_request
    como fallback (para feeds que bloquean user-agents de librerías).

    Args:
        feed_url: URL del feed RSS.
        feed_name: Nombre descriptivo para logs.

    Returns:
        FeedParserDict parseado o None si falla.
    """
    logger.info(f"  📡 Descargando feed: {feed_name} ({feed_url})")

    try:
        # Intento 1: feedparser directo (más eficiente)
        feed = feedparser.parse(feed_url)

        if feed.bozo and not feed.entries:
            # Feed malformado y sin entradas → intentar con requests
            logger.warning(f"    ⚠ Feed malformado con feedparser directo. Intentando con requests...")
            response = safe_request(feed_url, logger=logger)
            if response:
                feed = feedparser.parse(response.text)

        if feed.entries:
            logger.info(f"    ✓ {len(feed.entries)} entradas encontradas")
            return feed
        else:
            logger.warning(f"    ⚠ Feed vacío o sin entradas accesibles: {feed_name}")
            return None

    except Exception as e:
        logger.error(f"    ✗ Error descargando feed {feed_name}: {e}")
        return None


def extract_articles(
    feed: feedparser.FeedParserDict,
    feed_name: str,
    max_articles: int = MAX_ARTICLES_DEFAULT,
) -> list[dict]:
    """
    Extrae artículos relevantes de un feed parseado.

    Args:
        feed: Feed parseado por feedparser.
        feed_name: Nombre del feed para metadatos.
        max_articles: Máximo de artículos a extraer.

    Returns:
        Lista de dicts con {title, summary, url, published, source}.
    """
    articles = []

    for entry in feed.entries[:max_articles]:
        article = {"source": feed_name}

        # Título (obligatorio)
        title = entry.get("title", "").strip()
        if not title:
            continue
        article["title"] = title

        # Resumen/Descripción
        summary = ""
        # feedparser expone varios campos posibles
        for field in ["summary", "description", "content"]:
            raw = entry.get(field, "")
            if isinstance(raw, list):
                # 'content' es a veces una lista de dicts
                raw = raw[0].get("value", "") if raw else ""
            if raw:
                summary = clean_html(raw)
                break

        # Truncar resúmenes largos
        if len(summary) > MAX_SUMMARY_LENGTH:
            summary = summary[:MAX_SUMMARY_LENGTH].rsplit(" ", 1)[0] + "..."
        article["summary"] = summary

        # URL
        article["url"] = entry.get("link", "")

        # Fecha de publicación
        published = None
        for date_field in ["published", "updated", "created"]:
            date_str = entry.get(date_field, "")
            if date_str:
                published = date_str
                break
        article["published"] = published

        # Tags/categorías si existen
        tags = []
        for tag in entry.get("tags", []):
            term = tag.get("term", "").strip()
            if term and len(term) > 1:
                tags.append(term.lower())
        if tags:
            article["tags"] = tags[:5]  # Máximo 5 tags

        articles.append(article)

    return articles


# ─────────────────────────────────────────────
# 3. Construcción del Contexto
# ─────────────────────────────────────────────

def build_context(
    niche_name: str,
    niche_data: dict,
    all_articles: list[dict],
) -> dict:
    """
    Construye un documento de contexto estructurado para el LLM Writer.

    El contexto incluye:
    - Metadatos del nicho (nombre, keywords semilla).
    - Artículos recientes organizados por tema.
    - Temas y tendencias detectadas automáticamente.

    Args:
        niche_name: Nombre del nicho.
        niche_data: Datos del nicho desde niches.json.
        all_articles: Lista combinada de artículos de todos los feeds.

    Returns:
        Dict con el contexto completo.
    """
    # Detectar temas recurrentes a partir de tags y títulos
    topic_counts: dict[str, int] = {}
    for article in all_articles:
        # Contar tags
        for tag in article.get("tags", []):
            tag_lower = tag.lower().strip()
            if len(tag_lower) > 2:
                topic_counts[tag_lower] = topic_counts.get(tag_lower, 0) + 1

        # Contar palabras clave del título (basadas en seed_keywords)
        title_lower = article.get("title", "").lower()
        for seed_kw in niche_data.get("seed_keywords", []):
            for word in seed_kw.lower().split():
                if len(word) > 3 and word in title_lower:
                    topic_counts[word] = topic_counts.get(word, 0) + 1

    # Top temas (ordenados por frecuencia)
    trending_topics = sorted(
        topic_counts.items(), key=lambda x: x[1], reverse=True
    )[:15]

    context = {
        "niche": niche_name,
        "category_slug": niche_data.get("category_slug", niche_name),
        "seed_keywords": niche_data.get("seed_keywords", []),
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "sources_count": len(set(a["source"] for a in all_articles)),
        "articles_count": len(all_articles),
        "trending_topics": [
            {"topic": topic, "mentions": count}
            for topic, count in trending_topics
        ],
        "articles": all_articles,
        "usage_instructions": (
            "Este contexto es para el LLM Writer (llm_writer.py). "
            "Úsalo como referencia de contenido actual y tendencias del nicho. "
            "NO copies texto literal de los artículos. "
            "Usa los temas y tendencias para enriquecer el contenido generado."
        ),
    }

    return context


# ─────────────────────────────────────────────
# 4. Guardado
# ─────────────────────────────────────────────

def save_context(niche_name: str, context: dict) -> Path:
    """
    Guarda el contexto construido en un archivo JSON.

    Args:
        niche_name: Nombre del nicho.
        context: Dict con el contexto completo.

    Returns:
        Path del archivo guardado.
    """
    output_dir = CONTEXT_OUTPUT_DIR / niche_name
    output_dir.mkdir(parents=True, exist_ok=True)

    output_file = output_dir / "context.json"

    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(context, f, ensure_ascii=False, indent=2)

    logger.info(f"  💾 Contexto guardado: {output_file} ({context['articles_count']} artículos)")
    return output_file


# ─────────────────────────────────────────────
# 5. Orquestación Principal
# ─────────────────────────────────────────────

def run_context_builder(
    niche_filter: str | None = None,
    max_articles: int = MAX_ARTICLES_DEFAULT,
    dry_run: bool = False,
) -> dict:
    """
    Ejecuta el ciclo completo de construcción de contexto.

    Args:
        niche_filter: Procesar solo este nicho.
        max_articles: Máximo de artículos por feed.
        dry_run: Modo test — 1 feed, 3 artículos.

    Returns:
        Dict con estadísticas de la ejecución.
    """
    stats = {
        "niches_processed": 0,
        "feeds_processed": 0,
        "feeds_failed": 0,
        "articles_extracted": 0,
        "files_saved": 0,
        "errors": 0,
    }

    # 1. Cargar configuración
    niches = load_feeds(niche_filter)

    for niche_name, niche_data in niches.items():
        logger.info(f"\n{'='*60}")
        logger.info(f"🏷️  NICHO: {niche_name}")
        logger.info(f"{'='*60}")

        feeds = niche_data.get("rss_feeds", [])
        if not feeds:
            logger.warning(f"  ⚠ Sin feeds RSS para '{niche_name}'. Saltando.")
            continue

        # Ordenar por prioridad (1 = más importante)
        feeds = sorted(feeds, key=lambda f: f.get("priority", 99))

        # Dry run: solo el primer feed
        if dry_run:
            feeds = feeds[:1]
            max_articles = min(max_articles, 3)
            logger.info(f"  🧪 DRY RUN: 1 feed, máx {max_articles} artículos")

        all_articles = []

        # 2. Descargar y parsear cada feed
        for i, feed_config in enumerate(feeds, start=1):
            feed_url = feed_config["url"]
            feed_name = feed_config.get("name", feed_url)

            logger.info(f"\n  ── Feed {i}/{len(feeds)}: {feed_name} ──")

            try:
                feed = fetch_feed(feed_url, feed_name)

                if feed:
                    articles = extract_articles(feed, feed_name, max_articles)
                    all_articles.extend(articles)
                    stats["articles_extracted"] += len(articles)
                    stats["feeds_processed"] += 1
                    logger.info(f"    ✓ {len(articles)} artículos extraídos")
                else:
                    stats["feeds_failed"] += 1

            except Exception as e:
                logger.error(f"    ✗ Error procesando feed {feed_name}: {e}", exc_info=True)
                stats["feeds_failed"] += 1
                stats["errors"] += 1

            # Throttle entre feeds (ser respetuoso con los servidores)
            if i < len(feeds):
                throttle(min_sec=2.0, max_sec=5.0)

        # 3. Construir y guardar contexto
        if all_articles:
            logger.info(f"\n  📝 Construyendo contexto para '{niche_name}' con {len(all_articles)} artículos...")
            context = build_context(niche_name, niche_data, all_articles)
            save_context(niche_name, context)
            stats["files_saved"] += 1
        else:
            logger.warning(f"  ⚠ 0 artículos extraídos para '{niche_name}'. No se genera contexto.")

        stats["niches_processed"] += 1

        # Throttle entre nichos
        if stats["niches_processed"] < len(niches):
            wait = random.uniform(3.0, 8.0)
            logger.info(f"\n  ⏳ Pausa entre nichos: {wait:.1f}s")
            time.sleep(wait)

    return stats


# ─────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────

def parse_args() -> argparse.Namespace:
    """Configura y parsea argumentos de línea de comandos."""
    parser = argparse.ArgumentParser(
        description="Constructor de Contexto — Amazon Affiliate Pipeline",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Ejemplos:
  python scripts/context_builder.py                          # Todos los nichos
  python scripts/context_builder.py --niche mascotas         # Solo mascotas
  python scripts/context_builder.py --max-articles 15        # Más artículos por feed
  python scripts/context_builder.py --dry-run                # Test rápido
        """,
    )
    parser.add_argument(
        "--niche",
        type=str,
        default=None,
        help="Procesar solo este nicho (ej: mascotas, herramientas, hogar)",
    )
    parser.add_argument(
        "--max-articles",
        type=int,
        default=MAX_ARTICLES_DEFAULT,
        help=f"Máximo de artículos por feed (default: {MAX_ARTICLES_DEFAULT})",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Modo test: 1 feed, máx 3 artículos",
    )
    return parser.parse_args()


def main():
    """Punto de entrada principal."""
    args = parse_args()

    logger.info("🚀 Iniciando Constructor de Contexto")
    logger.info(f"   Configuración: niche={args.niche}, "
                f"max_articles={args.max_articles}, dry_run={args.dry_run}")

    start_time = time.time()

    stats = run_context_builder(
        niche_filter=args.niche,
        max_articles=args.max_articles,
        dry_run=args.dry_run,
    )

    elapsed = time.time() - start_time

    logger.info(f"\n{'='*60}")
    logger.info("📊 RESUMEN DE EJECUCIÓN")
    logger.info(f"{'='*60}")
    logger.info(f"  Tiempo total:        {elapsed:.1f}s")
    logger.info(f"  Nichos procesados:   {stats['niches_processed']}")
    logger.info(f"  Feeds procesados:    {stats['feeds_processed']}")
    logger.info(f"  Feeds fallidos:      {stats['feeds_failed']}")
    logger.info(f"  Artículos extraídos: {stats['articles_extracted']}")
    logger.info(f"  Archivos guardados:  {stats['files_saved']}")
    logger.info(f"  Errores:             {stats['errors']}")
    logger.info("✅ Constructor de Contexto finalizado.\n")


if __name__ == "__main__":
    main()

"""
llm_writer.py — Generador IA de artículos del pipeline Amazon Affiliate.

Fase 5 del roadmap:
  1. Carga datos de productos (research_output o demo).
  2. Carga contexto del nicho (context_output).
  3. Genera cada sección del artículo con Ollama (llama3.1 / mistral).
  4. Ensambla el artículo completo con Front Matter YAML, placeholders de precio,
     enlaces de afiliado, disclosure y Schema JSON-LD.
  5. Guarda el .md en site/content/{nicho}/{slug}.md.

Uso:
  python scripts/llm_writer.py --niche mascotas --keyword "comedero automatico gato"
  python scripts/llm_writer.py --niche mascotas --keyword "comedero automatico gato" --demo
  python scripts/llm_writer.py --niche mascotas --keyword "comedero automatico gato" --dry-run
"""

import argparse
import json
import os
import re
import time
import random
from datetime import date
from pathlib import Path

import requests as http_requests
import google.generativeai as genai

from utils import (
    DATA_DIR,
    PROJECT_ROOT,
    setup_logging,
    load_env,
    throttle,
)

# ─────────────────────────────────────────────
# Constantes
# ─────────────────────────────────────────────

OLLAMA_BASE_URL = "http://localhost:11434"
SITE_CONTENT_DIR = PROJECT_ROOT / "site" / "content"
RESEARCH_OUTPUT_DIR = DATA_DIR / "research_output"
CONTEXT_OUTPUT_DIR = DATA_DIR / "context_output"
DEMO_DIR = DATA_DIR / "demo"

# Modelos (del PROJECT_CONTEXT.md)
MODEL_WRITER = "llama3.2:latest"       # Redacción principal
MODEL_TECHNICAL = "mistral:7b-instruct-v0.3-q8_0"  # Fichas técnicas

# Hardware limits
SLEEP_BETWEEN_GENERATIONS = (10, 15)  # Segundos entre llamadas a Ollama
OLLAMA_TIMEOUT = 180  # Segundos — modelos Q6/Q8 en 4GB VRAM son lentos

AMAZON_BASE_URL = "https://www.amazon.es"
DEFAULT_AMAZON_TAG = "TU-TAG-21"

logger = setup_logging("llm_writer")


# ─────────────────────────────────────────────
# 1. Cliente IA (Gemini Principal + Ollama Fallback)
# ─────────────────────────────────────────────

class AIClient:
    """
    Wrapper para la API de Gemini (Gemma 4 31B) con fallback a Ollama.
    Gestiona rate limits (15 RPM) de Gemini y timeouts locales de Ollama.
    """

    def __init__(self, ollama_base_url: str = OLLAMA_BASE_URL):
        self.ollama_base_url = ollama_base_url
        self._call_count = 0
        try:
            genai.configure(api_key=os.getenv("GEMINI_API_KEY", ""))
        except Exception as e:
            logger.warning(f"Error configurando Gemini: {e}")

    def is_available(self) -> bool:
        """Verifica si Gemini o Ollama están disponibles."""
        return True # Asumimos intentar Gemini

    def generate(
        self,
        model: str,
        prompt: str,
        system: str = "",
        temperature: float = 0.7,
        max_tokens: int = 2048,
        retries: int = 3,
    ) -> str:
        """
        Genera texto intentando Gemini primero, y si falla con error no-429 acude a Ollama.
        Controla 429 Too Many Requests con sleep(60).
        """
        # Intentar Gemini ('gemma-4-31b-it')
        gemini_model_name = 'gemma-4-31b-it'
        try:
            gemini_model = genai.GenerativeModel(gemini_model_name)
        except Exception as e:
            logger.error(f"Error instanciando GenerativeModel: {e}")
            gemini_model = None

        full_prompt = f"INSTRUCCIONES DEL SISTEMA:\n{system}\n\nTEXTO A GENERAR:\n{prompt}" if system else prompt

        if gemini_model:
            for attempt in range(1, retries + 1):
                logger.info(f"    ☁️ Intentando Gemini API ({gemini_model_name}) - intento {attempt}/{retries}...")
                try:
                    generation_config = genai.types.GenerationConfig(
                        temperature=temperature,
                        max_output_tokens=max_tokens,
                    )
                    response = gemini_model.generate_content(full_prompt, generation_config=generation_config)
                    if response.text:
                        logger.info(f"    ✓ Generación exitosa con Gemini")
                        return response.text.strip()
                except Exception as e:
                    err_str = str(e).lower()
                    if "429" in err_str or "too many requests" in err_str or "quota" in err_str or "resource exhausted" in err_str:
                        logger.warning(f"    ⚠ API Rate Limit (429) detectado en Gemini. Durmiendo 60s...")
                        time.sleep(60)
                    else:
                        logger.warning(f"    ⚠ Error en Gemini: {e}. Pasando a fallback...")
                        break # Salimos del try de Gemini por error critico no-429 para hacer fallback
        
        # ──────── FALLBACK A OLLAMA ────────
        logger.warning(f"    🔄 Fallback a Ollama local (modelo: {model})...")
        for attempt in range(1, retries + 1):
            if self._call_count > 0 or attempt > 1:
                wait = random.uniform(*SLEEP_BETWEEN_GENERATIONS)
                if attempt > 1:
                    wait *= 2
                    logger.info(f"    ⏳ Reintento {attempt}/{retries}: esperando {wait:.0f}s...")
                else:
                    logger.info(f"    ⏳ Sleep entre generaciones: {wait:.0f}s")
                time.sleep(wait)

            self._call_count += 1

            payload = {
                "model": model,
                "prompt": prompt,
                "system": system,
                "stream": False,
                "options": {
                    "temperature": temperature,
                    "num_predict": max_tokens,
                },
            }

            logger.info(f"    🤖 Generando con Ollama {model} (prompt: {len(prompt)} chars)...")

            try:
                resp = http_requests.post(
                    f"{self.ollama_base_url}/api/generate",
                    json=payload,
                    timeout=OLLAMA_TIMEOUT,
                )
                resp.raise_for_status()
                data = resp.json()

                text = data.get("response", "").strip()
                eval_duration = data.get("eval_duration", 0)
                tokens = data.get("eval_count", 0)

                duration_s = eval_duration / 1e9 if eval_duration else 0
                tps = tokens / duration_s if duration_s > 0 else 0

                logger.info(f"    ✓ Generados {tokens} tokens en {duration_s:.1f}s ({tps:.1f} t/s)")
                return text

            except (http_requests.exceptions.Timeout, http_requests.exceptions.HTTPError, http_requests.exceptions.ConnectionError) as e:
                logger.warning(f"    ⚠ Intento {attempt} fallido: {e}")
                if attempt == retries:
                    logger.error(f"    ❌ Fallaron todos los reintentos para Ollama {model}")
                    return ""
            except Exception as e:
                logger.error(f"    ❌ Error crítico en Fallback Ollama: {e}")
                return ""
        return ""

# Mantener OllamaClient como alias para compatibilidad con scripts existentes como qa_checker.py
OllamaClient = AIClient



# ─────────────────────────────────────────────
# 2. Carga de Datos
# ─────────────────────────────────────────────

def slugify(text: str) -> str:
    """Convierte texto a slug para nombre de archivo."""
    text = text.lower().strip()
    text = re.sub(r"[áàä]", "a", text)
    text = re.sub(r"[éèë]", "e", text)
    text = re.sub(r"[íìï]", "i", text)
    text = re.sub(r"[óòö]", "o", text)
    text = re.sub(r"[úùü]", "u", text)
    text = re.sub(r"[ñ]", "n", text)
    text = re.sub(r"[^a-z0-9]+", "-", text)
    text = text.strip("-")
    return text


def load_product_data(niche: str, keyword: str, demo: bool = False) -> dict | None:
    """
    Carga datos de productos desde research_output o demo.

    Args:
        niche: Nombre del nicho.
        keyword: Keyword del artículo.
        demo: Si True, busca en data/demo/.

    Returns:
        Dict con datos de productos, o None si no existe.
    """
    if demo:
        # Buscar en data/demo/ con patrón {niche}_{slug}.json
        slug = slugify(keyword).replace("-", "_")
        demo_file = DEMO_DIR / f"{niche}_{slug}.json"
        if not demo_file.exists():
            logger.error(f"✗ Archivo demo no encontrado: {demo_file}")
            return None
        logger.info(f"📂 Cargando datos demo: {demo_file}")
    else:
        # Buscar en data/research_output/{niche}/{slug}.json
        slug = slugify(keyword).replace("-", "_")
        demo_file = RESEARCH_OUTPUT_DIR / niche / f"{slug}.json"
        if not demo_file.exists():
            logger.error(f"✗ Archivo de investigación no encontrado: {demo_file}")
            logger.info("   Tip: Ejecuta research_engine.py primero o usa --demo")
            return None
        logger.info(f"📂 Cargando datos de investigación: {demo_file}")

    with open(demo_file, "r", encoding="utf-8") as f:
        return json.load(f)


def load_context(niche: str) -> dict | None:
    """Carga el contexto del nicho desde context_output."""
    context_file = CONTEXT_OUTPUT_DIR / niche / "context.json"
    if not context_file.exists():
        logger.warning(f"⚠ Contexto no encontrado: {context_file}. Generando sin contexto.")
        return None

    with open(context_file, "r", encoding="utf-8") as f:
        context = json.load(f)

    logger.info(f"📂 Contexto cargado: {context.get('articles_count', 0)} artículos, "
                f"{len(context.get('trending_topics', []))} trending topics")
    return context


# ─────────────────────────────────────────────
# 3. Sistema de Prompts
# ─────────────────────────────────────────────

def _build_context_block(context: dict | None) -> str:
    """Construye un bloque de contexto para inyectar en prompts."""
    if not context:
        return ""

    lines = ["\n--- CONTEXTO ACTUAL DEL NICHO ---"]

    topics = context.get("trending_topics", [])
    if topics:
        topic_str = ", ".join(t["topic"] for t in topics[:8])
        lines.append(f"Temas trending: {topic_str}")

    articles = context.get("articles", [])
    if articles:
        lines.append(f"Artículos recientes ({len(articles)}):")
        for a in articles[:5]:
            lines.append(f"  - {a.get('title', 'Sin título')} ({a.get('source', '')})")

    lines.append("--- FIN CONTEXTO ---\n")
    return "\n".join(lines)


def _product_summary(products: list[dict]) -> str:
    """Resume los productos para inyectar en prompts."""
    lines = []
    for i, p in enumerate(products, 1):
        lines.append(
            f"Producto {i}: {p.get('title', 'N/A')}\n"
            f"  ASIN: {p.get('asin', 'N/A')}\n"
            f"  Precio: {p.get('price_eur', 'N/A')}€\n"
            f"  Rating: {p.get('rating', 'N/A')}/5 ({p.get('review_count', 0)} reviews)\n"
        )
    return "\n".join(lines)


SYSTEM_WRITER = """Eres un asistente de redacción que ayuda a organizar y presentar información sobre productos de forma clara y objetiva.

REGLAS:
- Español de España.
- Tono neutral y analítico.
- No uses adjetivos exagerados ni lenguaje publicitario.
- Instrucción OBLIGATORIA para cajas HTML:
  <div class="pros-box"><span class="box-title">Puntos destacados</span><ul><li>...</li></ul></div>
  <div class="cons-box"><span class="box-title">Por mejorar</span><ul><li>...</li></ul></div>
- NUNCA menciones precios exactos. Usa: [Ver precio actual en Amazon](URL)
"""

SYSTEM_TECHNICAL = """Eres un técnico de producto. Genera fichas técnicas precisas en formato tabla Markdown.

REGLAS:
- Formato: tabla Markdown de dos columnas (Característica | Detalle).
- DEDUCE las características (material, dimensiones, uso) a partir del nombre del producto y su categoría.
- No uses "No especificado" si puedes deducirlo de forma razonable (ej: si es un arnés, el material suele ser Nylon/Malla).
- Sin texto narrativo, solo la tabla.
"""


def prompt_intro(keyword: str, products: list[dict], context_block: str) -> tuple[str, str, str]:
    """Devuelve (system, prompt, model) para la sección de introducción."""
    product_names = ", ".join(p["title"].split(",")[0] for p in products[:3])
    return (
        SYSTEM_WRITER,
        f"""Escribe la INTRODUCCIÓN (2-3 párrafos, ~150-200 palabras) para una guía de compra sobre «{keyword}».

Productos que vamos a analizar: {product_names} y {len(products) - 3} más.
{context_block}

INSTRUCCIONES:
- Empieza con un gancho que conecte con el lector (una situación cotidiana, un problema real).
- Explica brevemente por qué es importante elegir bien este producto.
- Adelanta que has analizado {len(products)} opciones y vas a ayudarle a elegir.
- NO listes los productos todavía. Solo genera expectativa.
- Incluye la keyword «{keyword}» de forma natural en el primer párrafo.
""",
        MODEL_WRITER,
    )


def prompt_product_analysis(keyword: str, product: dict, position: int, context_block: str) -> tuple[str, str, str]:
    """Devuelve (system, prompt, model) para el análisis de un producto."""
    return (
        SYSTEM_WRITER,
        f"""Analiza el siguiente producto para una guía de «{keyword}»:

Producto: {product['title']}
Información: Rating {product.get('rating', 'N/A')}/5, {product.get('review_count', 0)} valoraciones.
{context_block}

INSTRUCCIONES:
1. Escribe 2 párrafos sobre por qué este producto es una buena opción (o para quién es ideal).
2. OBLIGATORIO: Incluye el bloque HTML de puntos destacados y por mejorar usando EXACTAMENTE esta estructura:
   <div class="pros-box"><span class="box-title">Lo mejor</span><ul><li>...</li></ul></div>
   <div class="cons-box"><span class="box-title">A tener en cuenta</span><ul><li>...</li></ul></div>
3. NO menciones el precio exacto.
4. Genera al menos 2 párrafos de texto narrativo ADEMÁS de las cajas de pros/contras.
""",
        MODEL_WRITER,
    )


def prompt_technical_sheet(product: dict) -> tuple[str, str, str]:
    """Devuelve (system, prompt, model) para la ficha técnica."""
    return (
        SYSTEM_TECHNICAL,
        f"""Genera una ficha técnica en formato tabla Markdown para este producto:

Nombre: {product['title']}
Precio: {product.get('price_eur', 'N/A')}€
Rating: {product.get('rating', 'N/A')}/5

Deduce las características técnicas del nombre del producto (capacidad, conectividad, material, etc.).
Genera la tabla con al menos 6 filas.
""",
        MODEL_TECHNICAL,
    )


def prompt_comparison(keyword: str, products: list[dict]) -> tuple[str, str, str]:
    """Devuelve (system, prompt, model) para la tabla comparativa."""
    summary = _product_summary(products)
    return (
        SYSTEM_WRITER,
        f"""Crea una sección «Comparativa Rápida» para la guía de «{keyword}».

Productos a comparar:
{summary}

INSTRUCCIONES:
- Escribe 1 párrafo introductorio breve (2-3 frases).
- Luego genera una tabla Markdown con columnas: Producto | Capacidad | Precio | Rating | Ideal para
- En la columna Precio, pon SIEMPRE «Ver precio» (nunca cifras reales).
- En «Ideal para», escribe una frase corta y útil (ej. «Hogares con varios gatos»).
- Después de la tabla, 1-2 frases resumiendo cuál es la mejor relación calidad-precio.
""",
        MODEL_WRITER,
    )


def prompt_buying_guide(keyword: str, context_block: str) -> tuple[str, str, str]:
    """Devuelve (system, prompt, model) para la guía de compra educativa."""
    return (
        SYSTEM_WRITER,
        f"""Escribe una sección «Guía de Compra» (~200-250 palabras) para «{keyword}».
{context_block}

INSTRUCCIONES:
- Explica los 4-5 factores clave que hay que tener en cuenta al comprar este tipo de producto.
- Usa un formato natural con sub-puntos o negritas para cada factor.
- Incluye algún consejo práctico que no sea obvio.
- Tono de experto accesible, como un amigo que te asesora.
- NO repitas información de los análisis de productos.
""",
        MODEL_WRITER,
    )


def prompt_conclusion(keyword: str, products: list[dict]) -> tuple[str, str, str]:
    """Devuelve (system, prompt, model) para la sección de resumen final."""
    best = max(products, key=lambda p: (float(p.get("rating") or 0), int(p.get("review_count") or 0)))
    return (
        SYSTEM_WRITER,
        f"""Resume los puntos clave de los productos analizados para «{keyword}».

PRODUCTO DESTACADO: {best['title'].split(',')[0]}

INSTRUCCIONES:
- Explica brevemente por qué el producto destacado es una recomendación sólida basándote en sus características.
- Ofrece un consejo general sobre el cuidado o mantenimiento de este tipo de producto.
- Sé objetivo y descriptivo.
""",
        MODEL_WRITER,
    )


# ─────────────────────────────────────────────
# 4. Ensamblaje del Artículo
# ─────────────────────────────────────────────

def build_front_matter(
    keyword: str,
    niche: str,
    products: list[dict],
    description: str,
) -> str:
    """Genera el Front Matter YAML compatible con Hugo/PaperMod."""
    title = f"Los {len(products)} Mejores {keyword.title()} en {date.today().year}"
    slug = slugify(keyword)
    cover_image = products[0].get("image_url", "") if products else ""

    tags = [keyword]
    # Extraer palabras clave del keyword
    for word in keyword.split():
        if len(word) > 3 and word.lower() not in [t.lower() for t in tags]:
            tags.append(word.lower())

    fm = f"""---
title: "{title}"
date: {date.today().isoformat()}
slug: "{slug}"
description: "{description}"
tags: {json.dumps(tags, ensure_ascii=False)}
categories: ["{niche}"]
cover:
  image: "{cover_image}"
  alt: "{keyword}"
  caption: "Imagen: Amazon.es"
ShowToc: true
TocOpen: true
draft: false
---
"""
    return fm


def build_disclosure() -> str:
    """Genera el aviso de disclosure de afiliados (OBLIGATORIO)."""
    return """
> **📋 Divulgación de afiliados:** Esta página contiene enlaces de afiliado de Amazon. Si realizas una compra a través de estos enlaces, recibimos una pequeña comisión sin coste adicional para ti. Esto nos ayuda a mantener esta guía actualizada. Los precios mostrados pueden variar — consulta siempre el precio actual en Amazon.

"""


def build_affiliate_link(asin: str, amazon_tag: str) -> str:
    """Construye enlace de afiliado limpio."""
    return f"{AMAZON_BASE_URL}/dp/{asin}?tag={amazon_tag}"


def build_schema_jsonld(
    keyword: str,
    products: list[dict],
    article_url: str,
    amazon_tag: str,
) -> str:
    """Genera Schema JSON-LD (ItemList + Product) para SEO."""
    items = []
    for i, p in enumerate(products, 1):
        # Aseguramos tipos correctos para el Schema
        rating = p.get("rating")
        try:
            rating_val = float(rating) if rating else 4.0
        except (ValueError, TypeError):
            rating_val = 4.0
            
        rev_count = p.get("review_count")
        try:
            rev_val = int(rev_count) if rev_count else 0
        except (ValueError, TypeError):
            rev_val = 0

        items.append({
            "@type": "ListItem",
            "position": i,
            "item": {
                "@type": "Product",
                "name": p.get("title", ""),
                "url": build_affiliate_link(p["asin"], amazon_tag),
                "image": p.get("image_url", ""),
                "aggregateRating": {
                    "@type": "AggregateRating",
                    "ratingValue": str(rating_val),
                    "reviewCount": str(rev_val),
                },
            },
        })

    schema = {
        "@context": "https://schema.org",
        "@type": "ItemList",
        "name": f"Mejores {keyword}",
        "url": article_url,
        "numberOfItems": len(products),
        "itemListElement": items,
    }

    json_str = json.dumps(schema, ensure_ascii=False, indent=2)
    return f'\n<script type="application/ld+json">\n{json_str}\n</script>\n'


# ─────────────────────────────────────────────
# 5. Generación Completa del Artículo
# ─────────────────────────────────────────────

def generate_article(
    niche: str,
    keyword: str,
    product_data: dict,
    context: dict | None,
    ollama: OllamaClient,
    amazon_tag: str,
    dry_run: bool = False,
) -> str:
    """
    Genera un artículo completo llamando a Ollama para cada sección.

    Args:
        niche: Nombre del nicho.
        keyword: Keyword del artículo.
        product_data: Dict con datos de productos.
        context: Contexto del nicho (puede ser None).
        ollama: Cliente Ollama.
        amazon_tag: Tag de afiliado de Amazon.
        dry_run: Si True, muestra prompts sin generar.

    Returns:
        Artículo completo en formato Markdown.
    """
    products = product_data.get("products", [])
    if not products:
        logger.error("✗ No hay productos en los datos.")
        return ""
    
    # [DEV TEST LOGIC] Limitar a 3 productos temporalmente para acelerar pruebas de layout
    products = products[:3]

    context_block = _build_context_block(context)
    sections = []

    # ── Introducción ──
    logger.info("\n  📝 Sección 1/6: Introducción")
    system, prompt, model = prompt_intro(keyword, products, context_block)
    if dry_run:
        logger.info(f"    [DRY RUN] Model: {model}, Prompt: {len(prompt)} chars")
        intro_text = f"[INTRO PLACEHOLDER — {len(prompt)} chars prompt]"
    else:
        intro_text = ollama.generate(model, prompt, system, temperature=0.7)

    # ── Ensamblar artículo completo progresivamente ──
    logger.info("\n  🔧 Ensamblando artículo...")

    # Description para Front Matter (primera frase de la intro o fallback)
    desc_text = intro_text[:160].split(".")[0] + "." if intro_text else f"Guía completa de {keyword}."
    if desc_text.startswith("["):
        desc_text = f"Análisis detallado de los {len(products)} mejores {keyword} en {date.today().year}."

    # Front Matter y Componentes Base
    front_matter = build_front_matter(keyword, niche, products, desc_text)
    disclosure = build_disclosure()

    article = front_matter + disclosure + f"## Introducción\n\n{intro_text}\n\n---\n\n"

    # Utils para guardado progresivo
    slug = slugify(keyword)
    output_dir = SITE_CONTENT_DIR / niche
    output_dir.mkdir(parents=True, exist_ok=True)
    out_file_tmp = output_dir / f"{slug}.md.tmp"
    out_file_final = output_dir / f"{slug}.md"

    def save_checkpoint():
        with open(out_file_tmp, "w", encoding="utf-8") as f:
            f.write(article)

    save_checkpoint()

    # ── Análisis de cada producto ──
    product_sections = []
    for i, product in enumerate(products, 1):
        logger.info(f"\n  📝 Sección 2.{i}/{len(products)}: {product['title'][:40]}...")

        # Análisis
        system, prompt, model = prompt_product_analysis(keyword, product, i, context_block)
        if dry_run:
            logger.info(f"    [DRY RUN] Model: {model}, Prompt: {len(prompt)} chars")
            analysis_text = f"[ANÁLISIS PLACEHOLDER para {product['asin']}]"
        else:
            analysis_text = ollama.generate(model, prompt, system, temperature=0.7)

        # Ficha técnica
        logger.info(f"    📋 Ficha técnica con {MODEL_TECHNICAL}...")
        system_t, prompt_t, model_t = prompt_technical_sheet(product)
        if dry_run:
            logger.info(f"    [DRY RUN] Model: {model_t}, Prompt: {len(prompt_t)} chars")
            tech_text = "| Característica | Detalle |\n|---|---|\n| Ejemplo | Placeholder |"
        else:
            tech_text = ollama.generate(model_t, prompt_t, system_t, temperature=0.3)

        # Fallback para evitar variables None que rompen el formateo con :,
        review_count = product.get('review_count')
        if review_count is None:
            review_count = 0
            
        # Ensamblar sección del producto
        aff_link = build_affiliate_link(product["asin"], amazon_tag)
        product_md = f"""## {i}. {product['title'].split(',')[0]}

![{product['title'].split(',')[0]}]({product.get('image_url', '')})

**Valoración:** ⭐ {product.get('rating', 'N/A')}/5 ({review_count:,} opiniones)

{analysis_text}

### Ficha Técnica

{tech_text}

👉 [**Ver precio actual en Amazon**]({aff_link})

---
"""
        product_sections.append(product_md)
        article += product_md
        save_checkpoint()

    # ── Comparativa ──
    logger.info("\n  📝 Sección 3/6: Comparativa")
    system, prompt, model = prompt_comparison(keyword, products)
    if dry_run:
        logger.info(f"    [DRY RUN] Model: {model}, Prompt: {len(prompt)} chars")
        comparison_text = "[COMPARATIVA PLACEHOLDER]"
    else:
        comparison_text = ollama.generate(model, prompt, system, temperature=0.5)

    article += f"## Comparativa Rápida\n\n{comparison_text}\n\n---\n\n"
    save_checkpoint()

    # ── Guía de compra ──
    logger.info("\n  📝 Sección 4/6: Guía de compra")
    system, prompt, model = prompt_buying_guide(keyword, context_block)
    if dry_run:
        logger.info(f"    [DRY RUN] Model: {model}, Prompt: {len(prompt)} chars")
        guide_text = "[GUÍA DE COMPRA PLACEHOLDER]"
    else:
        guide_text = ollama.generate(model, prompt, system, temperature=0.7)

    article += f"## Guía de Compra: Qué Buscar en un {keyword.title()}\n\n{guide_text}\n\n---\n\n"
    save_checkpoint()

    # ── Conclusión ──
    logger.info("\n  📝 Sección 5/6: Conclusión")
    system, prompt, model = prompt_conclusion(keyword, products)
    if dry_run:
        logger.info(f"    [DRY RUN] Model: {model}, Prompt: {len(prompt)} chars")
        conclusion_text = "[CONCLUSIÓN PLACEHOLDER]"
    else:
        conclusion_text = ollama.generate(model, prompt, system, temperature=0.7)
        
    article += f"## Conclusión\n\n{conclusion_text}\n\n"
    save_checkpoint()

    # Schema JSON-LD
    base_url = "https://compras-top.pages.dev"
    article_url = f"{base_url}/{niche}/{slug}/"
    schema = build_schema_jsonld(keyword, products, article_url, amazon_tag)

    article += schema
    save_checkpoint()

    # Promocionar de documento temporal a documento oficial
    try:
        import os
        if out_file_final.exists():
            os.remove(out_file_final)
        os.rename(out_file_tmp, out_file_final)
        logger.info(f"  ✅ Archivo temporal validado y convertido en markdown oficial: {out_file_final.name}")
    except Exception as e:
        logger.error(f"  ❌ Error consolidando fichero final: {e}")

    return article


# ─────────────────────────────────────────────
# 6. Guardado
# ─────────────────────────────────────────────

def save_article(niche: str, keyword: str, article: str) -> Path:
    """
    Guarda el artículo en site/content/{nicho}/{slug}.md.

    Returns:
        Path del archivo guardado.
    """
    output_dir = SITE_CONTENT_DIR / niche
    output_dir.mkdir(parents=True, exist_ok=True)

    slug = slugify(keyword)
    output_file = output_dir / f"{slug}.md"

    with open(output_file, "w", encoding="utf-8") as f:
        f.write(article)

    logger.info(f"  💾 Artículo guardado: {output_file}")
    logger.info(f"     Tamaño: {len(article):,} caracteres, {len(article.splitlines())} líneas")
    return output_file


# ─────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────

def parse_args() -> argparse.Namespace:
    """Configura y parsea argumentos de línea de comandos."""
    parser = argparse.ArgumentParser(
        description="Generador IA de artículos — Amazon Affiliate Pipeline",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Ejemplos:
  python scripts/llm_writer.py --niche mascotas --keyword "comedero automatico gato" --demo
  python scripts/llm_writer.py --niche mascotas --keyword "comedero automatico gato" --dry-run
  python scripts/llm_writer.py --niche mascotas --keyword "comedero automatico gato"
        """,
    )
    parser.add_argument(
        "--niche", type=str, required=True,
        help="Nicho del artículo (ej: mascotas, herramientas, hogar)",
    )
    parser.add_argument(
        "--keyword", type=str, required=True,
        help="Keyword principal del artículo",
    )
    parser.add_argument(
        "--demo", action="store_true",
        help="Usar datos demo en vez de research_output",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Solo muestra prompts y estructura, sin generar con Ollama",
    )
    parser.add_argument(
        "--model-writer", type=str, default=MODEL_WRITER,
        help=f"Modelo para redacción (default: {MODEL_WRITER})",
    )
    parser.add_argument(
        "--model-technical", type=str, default=MODEL_TECHNICAL,
        help=f"Modelo para fichas técnicas (default: {MODEL_TECHNICAL})",
    )
    return parser.parse_args()


def main():
    """Punto de entrada principal."""
    args = parse_args()

    logger.info("🚀 Iniciando Generador IA de Artículos")
    logger.info(f"   Nicho: {args.niche}")
    logger.info(f"   Keyword: {args.keyword}")
    logger.info(f"   Demo: {args.demo}")
    logger.info(f"   Dry-run: {args.dry_run}")
    logger.info(f"   Modelo escritor: {args.model_writer}")
    logger.info(f"   Modelo técnico: {args.model_technical}")

    start_time = time.time()

    # Cargar env
    env = load_env()
    amazon_tag = env.get("AMAZON_TAG", "") or DEFAULT_AMAZON_TAG
    logger.info(f"   Amazon Tag: {amazon_tag}")

    # Verificar IA
    ai_client = AIClient()
    if not args.dry_run:
        if not ai_client.is_available():
            logger.error("✗ La IA no está disponible.")
            return
        logger.info("   ✓ Motor IA inicializado")

    # Cargar datos
    product_data = load_product_data(args.niche, args.keyword, demo=args.demo)
    if not product_data:
        return

    products = product_data.get("products", [])
    logger.info(f"   📦 {len(products)} productos cargados")

    # Cargar contexto
    context = load_context(args.niche)

    # Generar artículo
    logger.info(f"\n{'='*60}")
    logger.info("✍️  GENERANDO ARTÍCULO")
    logger.info(f"{'='*60}")

    # Override global models si se especifican por CLI
    global MODEL_WRITER, MODEL_TECHNICAL
    MODEL_WRITER = args.model_writer
    MODEL_TECHNICAL = args.model_technical

    article = generate_article(
        niche=args.niche,
        keyword=args.keyword,
        product_data=product_data,
        context=context,
        ollama=ai_client,
        amazon_tag=amazon_tag,
        dry_run=args.dry_run,
    )

    if not article:
        logger.error("✗ No se generó el artículo.")
        return

    # Guardar
    output_path = save_article(args.niche, args.keyword, article)

    elapsed = time.time() - start_time

    logger.info(f"\n{'='*60}")
    logger.info("📊 RESUMEN")
    logger.info(f"{'='*60}")
    logger.info(f"  Tiempo total:    {elapsed:.1f}s")
    logger.info(f"  Productos:       {len(products)}")
    logger.info(f"  Llamadas Ollama: {ollama._call_count}")
    logger.info(f"  Archivo:         {output_path}")
    logger.info("✅ Generador IA finalizado.\n")


if __name__ == "__main__":
    main()

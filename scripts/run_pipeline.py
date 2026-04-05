"""
run_pipeline.py — Orquestador Maestro del Pipeline Amazon Affiliate.

Ejecuta secuencialmente las fases:
 1. Scraping (research_engine)
 2. RSS Context (context_builder)
 3. LLM Writer
 4. QA Checker

Uso:
  python scripts/run_pipeline.py --niche mascotas
  python scripts/run_pipeline.py --niche mascotas --keyword "comedero automatico gato"
"""

import argparse
import logging
import re
import subprocess
import sys
import time
from pathlib import Path

from utils import setup_logging, DATA_DIR, PROJECT_ROOT, load_env
from research_engine import run_research, slugify, load_niches
from context_builder import run_context_builder
from llm_writer import load_product_data, load_context, OllamaClient, generate_article, save_article, SITE_CONTENT_DIR
from qa_checker import run_qa_on_file, QAReport, THRESHOLD_PASS

logger = setup_logging("pipeline_orchestrator")


# ─────────────────────────────────────────────
# Sanitización de Placeholders
# ─────────────────────────────────────────────

REGEX_PLACEHOLDER = re.compile(r'\{\{(?:PRICE|AFFILIATE)_[A-Z0-9_]+\}\}')

def sanitize_placeholders(article: str) -> str:
    """
    Reemplaza cualquier {{PRICE_N}} o {{AFFILIATE_*}} residual
    con un CTA seguro. Se ejecuta SIEMPRE antes de guardar.
    """
    matches = REGEX_PLACEHOLDER.findall(article)
    if matches:
        logger.warning(f"  ⚠️ Sanitización: {len(matches)} placeholder(s) residuales detectados y reemplazados.")
        article = REGEX_PLACEHOLDER.sub('[Ver precio actual en Amazon]', article)
    return article


def print_banner(text: str):
    logger.info(f"\n{'='*60}")
    logger.info(f"► {text.upper()}")
    logger.info(f"{'='*60}")

def ensure_category_index(niche: str):
    """Crea el _index.md de la categoría para SEO si no existe."""
    index_path = SITE_CONTENT_DIR / niche / "_index.md"
    if not index_path.exists():
        index_path.parent.mkdir(parents=True, exist_ok=True)
        content = f"""---
title: "Mejores productos de {niche.title()}"
description: "Descubre nuestras comparativas y guías de compra sobre {niche}. Análisis sinceros para ayudarte a elegir al mejor precio."
---

Bienvenidos a la sección especializada en **{niche}**. Aquí encontrarás nuestras últimas reseñas y recomendaciones.
"""
        with open(index_path, "w", encoding="utf-8") as f:
            f.write(content)
        logger.info(f"✅ Índice SEO de categoría creado: {index_path}")


def run_pipeline(niche: str, keyword: str = None, dry_run: bool = False, skip_ai_qa: bool = False):
    
    start_time = time.time()
    
    # 0. Determinar targets
    niches_cfg = load_niches(niche)
    keywords_to_process = []
    if keyword:
        keywords_to_process = [keyword]
    else:
        # Pillar las seed
        keywords_to_process = niches_cfg[niche].get("seed_keywords", [])
        
    logger.info(f"🎯 Iniciando Pipeline para nicho '{niche}' con {len(keywords_to_process)} keywords.")

    env = load_env()
    amazon_tag = env.get("AMAZON_TAG", "") or "TU-TAG-21"
    
    ollama = OllamaClient()
    if not dry_run and not ollama.is_available():
        logger.error("🛑 Ollama no está disponible. Lanza 'ollama serve' primero.")
        return

    # Preparar el directorio de categoría
    ensure_category_index(niche)

    # 1. RSS Context (1 vez por nicho)
    print_banner("Fase 1: Construcción de Contexto RSS")
    run_context_builder(niche_filter=niche, dry_run=dry_run)

    success_count = 0

    for idx, kwd in enumerate(keywords_to_process, 1):
        print_banner(f"Pipeline Keyword {idx}/{len(keywords_to_process)}: {kwd}")
        
        slug = slugify(kwd)
        target_md = SITE_CONTENT_DIR / niche / f"{slug}.md"
        
        # Opcional: saltar si ya existe y está completo
        rejected_md_path = f"{str(target_md)}.rejected"
        
        if Path(rejected_md_path).exists():
            logger.info(f"⏭️ El artículo para '{kwd}' está en cuarentena (suspenso de QA previo). Saltando para no iterar sobre errores...")
            continue
            
        if target_md.exists():
            try:
                content = target_md.read_text(encoding="utf-8")
                if "application/ld+json" in content:
                    logger.info(f"⏭️ El artículo para '{kwd}' ya existe y está completo. Saltando...")
                    continue
                else:
                    logger.warning(f"⚠️ El artículo '{kwd}' está incompleto (fallo de script u OOM anterior). Sobreescribiendo...")
            except Exception:
                pass
            
        # 2. Research (Scraping)
        logger.info("\n🔍 Fase 2: Scraping de Productos Amazon")
        stats_research = run_research(niche_filter=niche, keyword_filter=kwd, dry_run=dry_run)
        
        if stats_research["products_found"] == 0:
            logger.error(f"❌ Scraping fallido u 0 productos para {kwd}. Abortando pipeline para esta keyword.")
            continue
            
        # 3. Generación IA
        logger.info("\n🤖 Fase 3: Redacción LLM")
        product_data = load_product_data(niche, kwd, demo=False)
        context_data = load_context(niche)
        
        if not product_data:
            logger.error("❌ Datos de producto no encontrados.")
            continue
            
        article_markdown = generate_article(
            niche=niche,
            keyword=kwd,
            product_data=product_data,
            context=context_data,
            ollama=ollama,
            amazon_tag=amazon_tag,
            dry_run=dry_run
        )
        
        if not article_markdown:
            logger.error("❌ Falló la generación del artículo.")
            continue

        # 3.5. Sanitización obligatoria de placeholders ANTES de guardar
        article_markdown = sanitize_placeholders(article_markdown)

        saved_file = save_article(niche, kwd, article_markdown)
        
        # 4. QA Validator
        logger.info("\n⚖️ Fase 4: QA Checker")
        report_qa = run_qa_on_file(saved_file, kwd, skip_ai=skip_ai_qa, threshold=THRESHOLD_PASS, verbose=True)
        
        icon = "✅" if report_qa.score >= THRESHOLD_PASS else "❌"
        logger.info(f"   {icon} Total QA Score: {report_qa.score}/{report_qa.max_possible} -> {report_qa.result}")
        
        if report_qa.score < THRESHOLD_PASS:
            logger.warning("⚠️ El artículo NO superó el umbral de QA. Enviándolo a CUARENTENA.")
            try:
                import os
                if Path(rejected_md_path).exists():
                    os.remove(rejected_md_path)
                os.rename(saved_file, rejected_md_path)
                logger.info(f"🚫 Fichero ocultado de Hugo exitosamente: {Path(rejected_md_path).name}")
            except Exception as e:
                logger.error(f"❌ Error moviendo fichero a cuarentena: {e}")
        else:
            success_count += 1
            
        # Throttle preventivo de hard-ware si hay más en cola
        if idx < len(keywords_to_process):
            logger.info(f"\n⏳ Enfriando GPU durante 30s antes del siguiente artículo...")
            time.sleep(30)
            
            
    # ── Auditoría Hugo final (prevención de errores en Cloudflare) ──
    print_banner("Fase 5: Auditoría Hugo Automatizada")
    try:
        audit_script = PROJECT_ROOT / "scripts" / "audit_hugo.py"
        result = subprocess.run(
            [sys.executable, str(audit_script), "--fix"],
            cwd=str(PROJECT_ROOT),
            capture_output=True,
            text=True,
            timeout=30,
        )
        logger.info(result.stdout)
        if result.returncode != 0:
            logger.warning(f"  ⚠️ Audit stderr: {result.stderr}")
    except Exception as e:
        logger.warning(f"  ⚠️ No se pudo ejecutar audit_hugo.py: {e}")

    # ── Fase 6: Despliegue (Git Push) ──
    if success_count > 0 and not dry_run:
        print_banner("Fase 6: Despliegue a Producción (GitHub)")
        try:
            # 1. Comprobar si hay cambios
            status = subprocess.run(["git", "status", "--porcelain"], cwd=str(PROJECT_ROOT), capture_output=True, text=True)
            if not status.stdout.strip():
                logger.info("  ✅ No hay cambios nuevos para subir.")
            else:
                logger.info(f"  🚀 Detectados cambios. Iniciando commit y push...")
                
                # 2. Add y Commit
                subprocess.run(["git", "add", "."], cwd=str(PROJECT_ROOT), check=True)
                
                commit_msg = f"🚀 Deploy: {success_count} artículo(s) nuevo(s) [{niche}]"
                if keyword:
                    commit_msg = f"🚀 Deploy: Artículo '{keyword}' [{niche}]"
                
                subprocess.run(["git", "commit", "-m", commit_msg], cwd=str(PROJECT_ROOT), check=True)
                
                # 3. Push
                push = subprocess.run(["git", "push", "origin", "main"], cwd=str(PROJECT_ROOT), capture_output=True, text=True)
                if push.returncode == 0:
                    logger.info("  ✅ ¡Despliegue completado con éxito! Cloudflare Pages iniciará el build en breve.")
                else:
                    logger.error(f"  ❌ Error en git push: {push.stderr}")
                    
        except subprocess.CalledProcessError as e:
            logger.error(f"  ❌ Error en el proceso Git: {e}")
        except Exception as e:
            logger.error(f"  ❌ Error inesperado en el despliegue: {e}")
    elif dry_run:
        logger.info("\n  ℹ️ [DRY RUN] Despliegue omitido.")

    # Fin
    elapsed = time.time() - start_time
    print_banner("Fin del Pipeline Orquestado")
    logger.info(f"⏱️ Tiempo total: {elapsed:.1f}s")
    logger.info(f"📈 Tasa de éxito: {success_count}/{len(keywords_to_process)} artículos publicados correctamente.")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Orquestador Pipeline Amazon")
    parser.add_argument("--niche", type=str, required=True, help="Nicho a procesar")
    parser.add_argument("--keyword", type=str, help="Procesar solo esta keyword (opcional)")
    parser.add_argument("--dry-run", action="store_true", help="Modo Test rápido (no usar en producción real)")
    parser.add_argument("--skip-ai-qa", action="store_true", help="Evita usar IA para checkear naturalidad")
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    run_pipeline(
        niche=args.niche,
        keyword=args.keyword,
        dry_run=args.dry_run,
        skip_ai_qa=args.skip_ai_qa
    )

# 🧠 CONTEXTO MAESTRO: AMAZON AFFILIATE PIPELINE
   
## 📝 Descripción del Proyecto
Sistema editorial 100% automatizado de nichos de afiliados de Amazon.
**Pipeline:** Keyword Research → Scraping Amazon → Generación IA Local (Ollama) → QA Automático → Publicación Hugo → Deploy Cloudflare.
**Filosofía:** Calidad sobre cantidad. SEO White/Grey Hat. Cumplimiento paranoico de los ToS de Amazon.
**Objetivo:** Coste mensual 0€ y máxima calidad SEO.

## 💻 Especificaciones del Hardware (Límites Críticos)
- **CPU:** Ryzen 5 3600 (6C/12T)
- **GPU:** GTX 1650 (4GB VRAM) → Prioridad: Modelos Quantized Q6/Q8.
- **RAM:** 16GB (Single Channel) → Cuello de botella en velocidad, priorizar offloading a GPU.
- **Implicación en código:** Scripts Python deben incluir `time.sleep()` entre generaciones para no saturar temperatura/memoria.

## 🤖 Stack de Modelos IA (Cloud + Ollama Fallback)
- **Cerebro Principal (Cloud API):** Google AI Studio `gemma-4-31b-it` vía API. Migrado a la nube para solucionar el cuello de botella del hardware local (VRAM/RAM), manteniendo el coste en 0€.
- **Calidad Principal (Fallback):** llama3.1:8b-instruct-q6_K
- **Técnico/Reviews (Fallback):** mistral:7b-instruct-v0.3-q8_0
- **Razonamiento/SEO (Fallback):** gemma2:9b-instruct-q4_K_M

## 🏗️ Arquitectura Técnica
- **Backend:** Python 3.12 (venv activo)
- **Frontend:** Hugo v0.123.7+extended + Tema PaperMod
- **Infraestructura:** Windows 10 nativo + GitHub + Cloudflare Pages/Workers.

## 🎯 Estrategia de Lanzamiento (El "Caballo de Troya")

### Fase de Arranque (Semanas 1-3): Solo Español + Scraping
- **Idioma:** TODO en español (amazon.es).
- **Datos de productos:** Scraper con BeautifulSoup + headers reales (NO tenemos PA-API 5.0 aún).
- **Enlaces de afiliado:** Construcción manual → `amazon.es/dp/{ASIN}?tag={AMAZON_TAG}`.
- **Objetivo:** Publicar Reviews y Comparativas de altísima calidad → conseguir tráfico orgánico/social rápido → lograr **3 ventas** para desbloquear PA-API.
- **Precios:** SIEMPRE genéricos usando Call To Actions (*Blind Links*) del tipo "Ver precio actual en Amazon". Se evita usar Cloudflare Workers para eludir bloqueos CAPTCHA por IP de Data Center.

### Fase de Escalado (Semana 4+): Multi-idioma + PA-API
- **Trigger:** 3 ventas confirmadas → PA-API 5.0 desbloqueada.
- **Refactorización:** Reemplazar scraper por `paapi5-python-sdk`.
- **Expansión:** Activar multi-idioma (EN, DE, FR) con `hreflang` + Amazon OneLink.
- **Automatización:** GitHub Actions para CI/CD completo.

## 🔄 Pipeline Técnico (Ciclo de Vida de un Artículo)

```
research_engine.py → context_builder.py → llm_writer.py → qa_checker.py → Hugo .md → GitHub → Cloudflare Pages
```

| # | Script | Función | Modelo IA |
|---|--------|---------|----------|
| 1 | `research_engine.py` | Pytrends (keywords emergentes) + Scraping Amazon (validar productos/ASINs) | — |
| 2 | `context_builder.py` | Feeds RSS del nicho → contexto actual para evitar alucinaciones | — |
| 3 | `llm_writer.py` | Redacción del artículo utilizando C.T.A de precios dinámicos indirectos | llama3.1 / mistral |
| 4 | `qa_checker.py` | Evalúa borrador (IA-speak, keyword stuffing, disclosure). Descarta si < 68/100 y aísla como `.rejected` | gemma2 |
| 5 | Publisher Hugo | Genera `.md` con Front Matter YAML + Schema JSON-LD y auto-genera los sub-índices de categoría | — |
| 6 | Deploy | Push a GitHub → Cloudflare Pages compila gratis | — |
| 7 | [POST-VENTAS] | Cuando se desbloqueen las keys PA-API, se volverá a implementar la idea original de inyectar precios dinámicos. | — |

## ⚖️ Reglas de Oro (Compliance Amazon)
1. Precios SIEMPRE genéricos ("Ver precio en Amazon") hasta desbloquear PA-API para evadir banneos de CAPTCHA de Cloudflare Workers (Estrategia Opción A).
2. Imágenes SIEMPRE vía Hotlink de Amazon (no copias locales).
3. Disclosure de afiliados obligatorio en cada post.
4. Calidad sobre Cantidad: No publicar si el QA < 68/100. Todo fichero suspenso o corrompido debe ser renombrado automáticamente a extensión invisible (`.rejected` o `.tmp`).
5. Sleeps obligatorios entre peticiones de scraping y generaciones de IA.
6. User-Agent rotativo en scraping para evitar bloqueos.
7. **Prohibición de emojis en scripts CLI**: Para evitar fallos de codificación `cp1252` en Windows, los prints de consola deben ser 100% ASCII.

## 📅 Roadmap y Estado Actual
- [x] Fase 1: Preparación de entorno — Python 3.12, venv, Ollama, 3 modelos (~20GB).
- [x] Fase 2: Configuración de Hugo y PaperMod (Verificada físicamente ✅).
- [x] Fase 3: Motor de Investigación (`scripts/research_engine.py`) — Anti-CAPTCHA con sesiones ✅.
- [x] Fase 4: Constructor de Contexto (`scripts/context_builder.py`) ✅.
- [x] Fase 5: Generador IA (`scripts/llm_writer.py`) — Artículo completo generado ✅.
- [x] Fase 6: QA Checker (`scripts/qa_checker.py`) — Valida artículos generados ✅.
- [x] Fase 7: Orquestador (`run_pipeline`) y Publisher Hugo — Schema JSON-LD y configuración Unsafe HTML completada ✅.
- [x] Fase 7.5: Refinamiento de I/O — Extensiones `.tmp` de autoguardado, Sistema de Cuarentena Activa (`.rejected`) e Índices dinámicos implementados ✅.
- [x] Fase 8: Deploy Cloudflare Pages + Cierre del Repositorio (Código backend blindado, modelo optimizado a Llama 3.2 para VRAM ✅).
- [ ] Fase 9: Primeras 3 ventas → Desbloqueo PA-API 5.0.
- [ ] Fase 10: Refactorización a PA-API + Multi-idioma.

> 🛑 **CHECKPOINT NEXT SESSION:**
> El motor backend está blindado contra errores de IA (refusals) y codificación Windows. Se ha optimizado la generación usando Llama 3.2 para evitar timeouts en la GTX 1650.
>
> **Próximo Paso Inmediato:**
> 1. Lanzar el pipeline corto (3 productos) para "arnes perro" y verificar el `git push` automático.
> 2. Una vez confirmado en GitHub, verificar el build en Cloudflare Pages (`compras-top.pages.dev`).

## 🔧 Decisiones Técnicas (Registro Acumulativo)

| Fecha | Decisión | Justificación |
|-------|----------|---------------|
| 2026-03-26 | Cuantizaciones Q6_K/Q8_0/Q4_K_M | Máxima calidad posible dentro de 4GB VRAM + 16GB RAM |
| 2026-03-26 | Hugo + PaperMod como frontend | Velocidad extrema, SEO nativo, coste 0€ en Cloudflare Pages |
| 2026-03-26 | ~~Precios dinámicos vía CF Workers~~ | **[DEPRECADO por CAPTCHAS]** Cumplimiento TOS Amazon: no cachear precios estáticos |
| 2026-03-26 | 3 secciones iniciales: mascotas, herramientas, hogar | Nichos con alta demanda y buena comisión en Amazon ES |
| 2026-03-26 | PaperMod vía git submodule | Actualizaciones limpias del tema sin conflictos de merge |
| 2026-03-26 | Scraping primero, PA-API después | No tenemos acceso a PA-API 5.0 hasta conseguir 3 ventas |
| 2026-03-26 | Español primero, multi-idioma después | Foco total en amazon.es hasta validar el modelo de negocio |
| 2026-03-26 | ~~Placeholders `{{PRICE_N}}` en contenido~~ | **[DEPRECADO]** Reemplazados por enlaces C.T.A estáticos ("Ver Precio") |
| 2026-04-03 | Migración de WSL2 (Ubuntu) a Windows nativo | Simplificación del entorno: venv nativo, Hugo via winget, Ollama nativo; elimina dependencia de WSL2 |
| 2026-04-03 | Sesiones HTTP persistentes para scraping Amazon | Warm-up a homepage + cookies + UA fijo por sesión = anti-CAPTCHA efectivo |
| 2026-04-03 | Feeds RSS como fuente de contexto para LLM | Evita alucinaciones: artículos reales del nicho alimentan al LLM Writer |
| 2026-04-03 | llama3.1 para redacción + mistral para fichas técnicas | Cada modelo en su área fuerte: llama3.1 fluido en español, mistral preciso en datos |
| 2026-04-03 | Datos demo para testing independiente | Permite testar todo el pipeline sin scraping real de Amazon |
| 2026-04-03 | Cuarentena activa y escritura segura (`.tmp`) | Previene indexación/publicación accidental en CDN por timeout de gráfica o fallo de validación del QA de Gemma2 |
| 2026-04-03 | Enlaces estáticos C.T.A ("Ver Precio en Amazon") | Evita depender de peticiones Worker a IPs de Amazon bloqueadas por CAPTCHA, forzando un click humano trackeable. |
| 2026-04-03 | Evaluador QA Híbrido (`gemma2` + RegEx) | `gemma2` es lo suficientemente inteligente para cazar estilo robótico, las RegEx barren hardcodeo de precios. |
| 2026-04-03 | Renderizado `unsafe = true` en Goldmark (Hugo) | Permite la inyección cruda de etiquetas `<script type="application/ld+json">` obligatorias para SEO de Google Shopping. |
| 2026-04-03 | Orquestación secuencial unificada (`run_pipeline.py`) | Reduce 4 pasos manuales aislados a 1 único comando maestro, implementando _sleeps_ térmicos de 30s. |
| 2026-04-03 | Dominio de producción: `compras-top.pages.dev` | Definido como base_url en Hugo y en inyecciones hardcoded de Schema JSON-LD para el enrutamiento SEO. |
| 2026-04-04 | Repositorio GitHub CI/CD | Carpeta `site/` enlazada a `github.com/acclgv/amazon-pipeline` con `.gitignore` excluyendo `public/`. |
| 2026-04-04 | Rediseño UX Magazine Premium | CSS Extended con tarjetas, botones CTA naranja, disclosure crema, tablas responsive, shortcodes `producto` y `comparativa`. |
| 2026-04-04 | Blindaje QA: Critical Checks | Nuevos checks `check_unresolved_placeholders` y `check_llm_refusal` que fuerzan `score=0` y cortocircuitan la evaluación. |
| 2026-04-04 | Sanitizador de placeholders en pipeline | `sanitize_placeholders()` en `run_pipeline.py` se ejecuta SIEMPRE entre `generate_article()` y `save_article()`. |
| 2026-04-04 | Prompts anti-refusal y anti-placeholder | System prompt actualizado prohibiendo explícitamente `{{PRICE_N}}` y negativas del LLM. Instrucciones de pros/contras con clases CSS. |
| 2026-04-04 | Author Box E-E-A-T en `single.html` | Bloque visual de autoridad al pie de cada artículo con avatar, nombre editorial y bio de confianza. |
| 2026-04-04 | Cambio a `llama3.2:latest` (2GB) | Solución definitiva para "Timeouts" y saturación de VRAM en la GTX 1650 (4GB). |
| 2026-04-04 | Purga de Emojis en scripts | Estabilidad garantizada en terminales Windows con codificación por defecto (CP1252). |
| 2026-04-04 | Auditoría Hugo integrada en pipeline | `audit_hugo.py` se ejecuta automáticamente como Fase 5 del pipeline vía `subprocess.run()`. |

---

## 📜 Changelog (Historial de Cambios)
<!-- Formato: ### [YYYY-MM-DD] Título breve → detalles de lo que se hizo -->

### [2026-04-04] Blindaje y Estabilidad Final (Wrap-up Sesión)
- `llm_writer.py`: Optimización de hardware radical: Cambio a **`llama3.2:latest` (2GB)** para asegurar fluidez en la GTX 1650.
- `audit_hugo.py`: Purga de emojis para compatibilidad con terminales Windows. 
- `llm_writer.py`: Refinamiento de prompts anti-refusal para la sección de conclusiones.
- `git`: Configuración del repositorio local y enlace con el remoto de GitHub.
- `Fase 8`: Backend y Frontend sincronizados; pipeline listo para despliegue automatizado.

### [2026-04-04] UX Premium: ToC Sticky, Cajas Pros/Contras, Tablas Responsive y QA Auditado
- CSS renovado: Sticky ToC en escritorio, cajas Pros/Contras premium (verde/rojo), E-E-A-T authority block, tablas responsive con scroll horizontal, producto card con hover.
- Nuevo shortcode `comparativa.html`: Tabla comparativa visual con hasta 10 productos, fila ganadora con 🏆 y fondo dorado.
- Shortcode `producto.html`: Validación anti-crash (falta titulo/asin muestra error visual), `loading=lazy decoding=async`, fallback de imagen onerror.
- `single.html`: Bloque E-E-A-T (Revisado por Expertos, Fecha, Tiempo lectura, Palabras), integración ToC PaperMod, navegación entre posts.
- `audit_hugo.py`: Nuevo script auditor que detecta HTTP inseguros, placeholders, IA-speak, dominio antiguo, precios hardcodeados. Modo `--fix` automático.
- Auditoría ejecutada: Encontrados y corregidos 7 errores en `comedero-automatico-gato.md` (5 placeholders, 1 rechazo LLM, 1 dominio antiguo).

### [2026-04-04] Repositorio Remoto y fix de .gitignore
- Inicializado y enlazado el proyecto de forma local a GitHub.
- Exclusión intencionada en `.gitignore` de la carpeta `public/` para evitar conflictos en Cloudflare Pages, corregida y probada de forma autónoma.
- El repositorio está en espera de acople a infraestructura Cloudflare.

### [2026-04-03] Sistema de Cuarentena y Rechazo Activo (QA)
- Refactorizado el sistema de ficheros de `llm_writer.py` introduciendo escritura sobre la extensión preventiva `.tmp`. El archivo solo recibe la extensión válida `.md` si el pipeline logra terminar y sobrevivir a la inyección completa del esquema JSON-LD sin crashear por falta VRAM o Red.
- Implementado Sistema Activo de Rechazo en `run_pipeline.py`: Si el evaluador "gemma2" suspende el texto local con una nota inferior a 68/100, el Markdown es aislado, renombrándolo dinámicamente a la extensión invalida `.md.rejected`.
- Estos ficheros bloqueados quedan intocables para "Hugo Build", protegiendo la reputación del Cloudflare Pages hacia los robots de Google (0.0% de textos corruptos filtrados) e impidiendo que el Scraper entre en un bucle ciego sobre *keywords* atascadas.

### [2026-04-03] Mejoras Estructurales de Motor e I/O
- `research_engine.py`: Robustez extrema inyectada en el parser del DOM (`parse_product_card`). Ampliados de 2 a 5 los algoritmos de respaldo CSS (`.a-size-medium`, `s-image alt`) para absorber los A/B Testings de Amazon y evitar retornos de "0 productos válidos" por fallos de extracción de título y link.
- `research_engine.py`: Scraper actualizado para limpiar prefijos de las URLs de imágenes minimizadas de Amazon (RegEx drop de `_AC_XXX_`), garantizando que se guarde el formato nativo Hi-Res.
- `llm_writer.py`: Sistema de I/O re-arquitecturizado para "Auto-Guardado Progresivo". Escribe e inyecta la memoria inter-modelo al sistema de discos línea a línea. Previene que una caída del driver de GPU local en el último paso calcine todo el trabajo del promtp.
- `run_pipeline.py`: Ahora auto-identifica artículos generados parcialmente a la mitad, forzando la sobreescritura, pero respetando estrictamente los ficheros terminados confirmando la inyección Schema final.
- `run_pipeline.py`: Generación dinámica en caliente de ficheros `_index.md` por cada Nicho creado asegurando el posicionamiento de los índices primarios en Hugo.

### [2026-04-03] Fase 7 Orquestación y Arreglo Hugo Schema JSON-LD
- Establecido `unsafe = true` en `site/hugo.toml` para que Hugo pueda renderizar los `script` de LD+JSON y Google pueda leerlos.
- Re-diseñados placeholders de precio de LLM Writer. Estrategia **Opción A** adoptada: Llenar el vacío saltando la dependencia de CF Workers hasta obtener una API PA válida, e inyectando un Call to Action ("Ver precio") temporalmente para evitar baneo.
- Readaptado `qa_checker.py` para dejar de exigir placeholders temporales.
- Nuevo script global `scripts/run_pipeline.py`. Orquesta el motor de búsqueda, contexto RSS, Generación IA y QA Validations encadenadamente.
- Nuevo script `scripts/qa_checker.py` (~400 líneas) para validar los .md generados
- Implementados 10 tests deterministas (Regex / Parsers): detecta precios manuales, textos de IA, schema json, enlaces amazon rotos/nulos
- Soporte opcional para uso de IA naturalness verification via Gemma2 (`--skip-ai`)
- Salida robusta en ficheros JSON a `data/qa_output/` indicando línea y severidad de los errores
- Testeado sobre artículo demó encontrando exactamente 4 problemas introductorios: *Precio hardcodeado en la linea 123.*, *Frase IA detectada en linea 111 y 216.*

### [2026-04-03] Fase 5 completada: llm_writer.py — Generador IA de artículos
- Nuevo script `scripts/llm_writer.py` (~500 líneas) con generación por secciones
- Clase `OllamaClient` con timeout 180s y sleeps obligatorios entre generaciones (10-15s)
- 6 tipos de prompts especializados: intro, análisis producto, ficha técnica, comparativa, guía de compra, conclusión
- System prompts anti IA-speak: vocabulario natural español, prohibidas frases genéricas
- llama3.1:8b-instruct-q6_K para redacción (temp=0.7), mistral:7b-instruct-v0.3-q8_0 para fichas técnicas (temp=0.3)
- Front Matter YAML completo con cover image, tags, categories, ToC
- Placeholders `{{PRICE_N}}` para precios dinámicos (5/5 presentes)
- Disclosure de afiliados obligatorio ✅
- Schema JSON-LD ItemList + Product embebido ✅
- Enlace de afiliado limpio: `amazon.es/dp/{ASIN}?tag={TAG}` ✅
- Datos demo creados en `data/demo/` para testing independiente
- Test completo: 14 llamadas Ollama, 17,659 chars, 320 líneas, Hugo build OK (21 páginas)
- Performance: ~3.0 t/s con Q6_K en GTX 1650 4GB VRAM, ~25 min por artículo completo

### [2026-04-03] Fase 3 completada: Anti-CAPTCHA en research_engine.py
- Añadidas `create_amazon_session()` y `safe_session_request()` a utils.py
- Sesión HTTP persistente con warm-up a amazon.es (cookies session-id, i18n-prefs)
- UA fijo por sesión (un navegador real no cambia de User-Agent)
- CAPTCHA backoff inteligente: 30-60s de espera + recreación de sesión (max 2 resets)
- Throttle entre keywords aumentado a 8-15s para simular comportamiento humano
- Resumen de ejecución ahora incluye contadores de CAPTCHAs y resets de sesión

### [2026-04-03] Fase 4 completada: context_builder.py
- Nuevo script `scripts/context_builder.py` — Constructor de Contexto RSS
- Descarga feeds RSS configurados en `data/niches.json` por nicho
- Parseo con `feedparser` + fallback a `safe_request` para feeds que bloquean librerías
- Extrae título, resumen, fecha, URL y tags de cada artículo
- Detección automática de trending topics por frecuencia de tags/keywords
- Genera `data/context_output/{nicho}/context.json` con instrucciones de uso para el LLM
- Añadidos feeds RSS verificados a niches.json: Tiendanimal, Soy un Perro, Mis Animales,
  Affinity, OVACEN, Casa y Diseño, Decoración 2.0, Decoora
- Test con nicho mascotas: 10 artículos reales extraídos de 2 fuentes

### [2026-04-03] Migración completa de WSL2 (Ubuntu) a Windows nativo
- Eliminado `venv/` de Linux (incompatible con binarios Windows)
- Creado nuevo entorno virtual Python nativo (`python -m venv venv`) con todas las dependencias instaladas
- Instalado Hugo Extended v0.159.2 vía `winget install Hugo.Hugo.Extended`
- Descargados los 3 modelos Ollama confirmados en plataforma Windows:
  - llama3.1:8b-instruct-q6_K (6.6 GB) ✅
  - mistral:7b-instruct-v0.3-q8_0 (7.7 GB) ✅
  - gemma2:9b-instruct-q4_K_M (5.8 GB) ✅
- Ejecutado dry-run de `research_engine.py` con éxito (sin errores de importación ni rutas)
- Actualizada sección Infraestructura: WSL2 → Windows nativo
- El CAPTCHA de Amazon.es es esperado y no afecta la validación del entorno

### [2026-03-26] Actualización estratégica del contexto maestro
- Documentada estrategia "Caballo de Troya": Scraping → PA-API, Español → Multi-idioma
- Definido pipeline técnico completo: 7 scripts/componentes con sus modelos IA asignados
- Roadmap expandido de 3 fases a 10 fases con granularidad por script
- Añadidas 3 nuevas decisiones técnicas y 2 nuevas reglas de compliance
- Añadida restricción de hardware: sleeps obligatorios entre generaciones

### [2026-03-26] Fase 2 verificada: Hugo + PaperMod configurado físicamente
- Ejecutado `hugo new site . --force` en `site/`
- Inicializado repositorio git en `site/`
- Instalado tema PaperMod como git submodule (`themes/PaperMod`)
- Configurado `hugo.toml`: theme="PaperMod", languageCode="es-es", title="Guía de Compras Pro", env="production"
- Creadas secciones de contenido: `content/mascotas`, `content/herramientas`, `content/hogar`
- Build de Hugo exitoso: 4 páginas generadas en 65ms, `public/` verificada

### [2026-03-26] Setup inicial del entorno
- Creada estructura de proyecto: `scripts/`, `data/`, `logs/`, `site/`
- Entorno virtual Python con dependencias: requests, beautifulsoup4, python-dotenv, pytrends, pandas, feedparser
- Configurados `.env` (4 variables) y `.gitignore` profesional (67 líneas)
- Instalado Hugo v0.123.7+extended
- Instalado Ollama con detección de GPU Nvidia
- Descargados 3 modelos de alta fidelidad (~20 GB total):
  - llama3.1:8b-instruct-q6_K (6.6 GB)
  - mistral:7b-instruct-v0.3-q8_0 (7.7 GB)
  - gemma2:9b-instruct-q4_K_M (5.8 GB)
- Creado este archivo PROJECT_CONTEXT.md como memoria del proyecto

---

## ⚠️ PROTOCOLO OBLIGATORIO PARA EL AGENTE IA

> **ANTES de cada tarea:**
> 1. Lee `PROJECT_CONTEXT.md` completo.
> 2. Verifica que la tarea no viola restricciones de hardware ni reglas de compliance.
> 3. Identifica la fase actual del roadmap.
>
> **DESPUÉS de cada tarea completada:**
> 1. Actualiza `📅 Roadmap y Estado Actual` marcando tareas completadas y añadiendo las nuevas.
> 2. Añade una entrada en `📜 Changelog` con fecha, título y lista de cambios realizados.
> 3. Si se tomó alguna decisión técnica o de negocio nueva, añádela a `🔧 Decisiones Técnicas`.
> 4. Si se añadió una nueva regla de compliance, añádela a `⚖️ Reglas de Oro`.
>
> **Este protocolo es OBLIGATORIO. No es opcional. Es la memoria persistente del proyecto.**

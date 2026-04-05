---
description: Protocolo obligatorio para leer y actualizar PROJECT_CONTEXT.md antes y después de cada tarea
---

# Protocolo de Contexto del Proyecto

Este workflow se activa automáticamente en cualquier tarea relacionada con el proyecto amazon-pipeline.

## ANTES de empezar cualquier tarea

// turbo
1. Lee el archivo `~/amazon-pipeline/PROJECT_CONTEXT.md` completo para cargar el contexto del proyecto.

2. Verifica mentalmente:
   - ¿La tarea viola alguna restricción de hardware (4GB VRAM, 16GB RAM Single Channel)?
   - ¿La tarea viola alguna Regla de Oro de compliance?
   - ¿En qué fase del Roadmap estamos?
   - Si hay conflicto, informa al usuario ANTES de proceder.

## DESPUÉS de completar cualquier tarea

3. Actualiza `PROJECT_CONTEXT.md` con los siguientes cambios según aplique:

   **a) Roadmap y Estado Actual:**
   - Marca como `[x]` las fases/tareas completadas.
   - Añade nuevas fases o sub-tareas si se identificaron durante el trabajo.

   **b) Changelog (Historial de Cambios):**
   - Añade una nueva entrada al inicio de la sección Changelog con el formato:
     ```
     ### [YYYY-MM-DD] Título breve de lo que se hizo
     - Detalle 1
     - Detalle 2
     ```

   **c) Decisiones Técnicas:**
   - Si se tomó alguna decisión de arquitectura, modelo, herramienta o configuración, añade una fila a la tabla de Decisiones Técnicas.

   **d) Reglas de Oro:**
   - Si se descubrió una nueva restricción de compliance o negocio, añádela a la lista.

4. Confirma al usuario que PROJECT_CONTEXT.md ha sido actualizado.

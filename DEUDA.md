# Deuda de BeplyPluginTemplate

> Lo que falta para que esta plantilla esté terminada y se publicó igualmente. Contrato:
> `references/23-atajos-y-deuda.md` de la skill `beply-fs-plugin-developer`.
> Cada fila tiene un responsable con nombre. Las filas no se borran: se marcan como pagadas.

**Pendientes: 1** · Vencidas: 0 · Última revisión: 2026-11-26

| ID | Qué falta | Regla o fase | Consecuencia mientras falte | Decidió saltárselo | Fecha y versión | Motivo | Plazo | Estado |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| D01 | Cerrar comparando el repository id: `scripts/ci/read-ci-dependencies.mjs` descarta el propio repo por nombre (minúsculas, sin `.git` y frente a `GITHUB_REPOSITORY`), pero un repo renombrado sigue respondiendo a su nombre antiguo | Seguridad de CI (TAREA-801, PR #34) | Una entrada de `.beply/ci-dependencies.json` con el nombre antiguo del propio repo lo clonaría como dependencia; `.beply/` es arnés y cualquier cambio suyo se revisa y se fusiona a mano | claude-chief | 2026-11-26, PR #34 | Riesgo residual aceptado por el chief en la revisión de rev-ola3-tokens: no es condición del merge | Siguiente ronda de la plantilla | pendiente |

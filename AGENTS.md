# AGENTS.md

Guia obligatoria para agentes IA que trabajen sobre plugins Beply de FacturaScripts creados desde esta plantilla.

## Lectura inicial

1. `README.md`
2. `docs/CODEX-WORKFLOW.md`
3. `docs/TESTING.md`
4. `docs/FACTURASCRIPTS-STYLE-GUIDE.md`
5. `docs/DOCUMENTATION-GOVERNANCE.md`
6. `docs/AI-TOOLS-MANIFEST.md`
7. `docs/CI-CD.md`
8. `docs/TEMPLATE-SYNC.md`

Si el plugin es una reimplementacion visual de otro modulo, leer tambien `docs/ROM-COPY-CLEANROOM.md` antes de mirar nada del producto original.

## Reglas de trabajo

- Confirmar la matriz de FacturaScripts antes de desarrollar. La base esta en `.beply/facturascripts-matrix.json`.
- Por defecto se prueba `v2026.3` y `v2026.2` con PHP 8.4. Si sale una version nueva, anadirla al JSON y a CI antes de validar.
- No dar por terminado ningun cambio si falta test unitario, runtime o E2E de navegador para la funcionalidad afectada.
- Toda pantalla debe tener matriz de cobertura en `docs/testing/ui-coverage-matrix.json`. Si hay 50 botones visibles, los 50 deben estar cubiertos.
- Si el cambio modifica una ficha/listado/flujo de usuario, actualizar `docs/user/`, `docs/docs-sync/impact-map.json` y las referencias a documentacion base.
- Las vistas Twig deben extender el core o anadir deltas. No copiar plantillas completas del core salvo excepcion documentada.
- Las tools de IA se declaran en `Tools/manifest.json` y se exponen por `Lib/BeplyAgentToolProvider.php`.
- Las mutaciones de IA empiezan en `review_required`. Cualquier accion peligrosa debe bloquear ejecucion autonoma.
- No pegar secretos en docs, tests, fixtures ni logs.
- Si sincronizas desde una version nueva de la plantilla, usa `scripts/template/sync-template.mjs`; no copies producto ni docs reales a mano.

## Cierre obligatorio

Antes de cerrar una tarea, dejar claro:

- matriz FacturaScripts probada;
- tests ejecutados;
- cobertura de controles actualizada;
- docs de usuario y docs base afectadas;
- tools IA anadidas o modificadas;
- pendientes que no se pudieron validar.

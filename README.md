# BeplyPluginTemplate

Plantilla base para arrancar un plugin Beply de FacturaScripts con workflow Codex, testing multiversion, documentacion de usuario/base, contrato de tools IA y promocion inmutable DEV100 a PROD.

## Estado y compatibilidad

| Campo | Valor |
| --- | --- |
| Estado | Plantilla base |
| Tipo | Scaffold reutilizable |
| Nombre de plugin | `BeplyPluginTemplate` |
| Version actual | `1.4` |
| Compatibilidad declarada | `FacturaScripts 2026.2+` |
| PHP minimo declarado | `8.4` |
| Stack objetivo Beply | `FacturaScripts v2026.3 y v2026.2 / PHP 8.4` |
| Estado de manifiesto | `Alineado con stack Beply` |
| Rama operativa | `main` |

## Capacidades principales

- Aporta una estructura completa de plugin FacturaScripts lista para renombrar y extender.
- Incluye contrato de trabajo para Codex en `AGENTS.md` y `docs/CODEX-WORKFLOW.md`.
- Declara matriz FacturaScripts en `.beply/facturascripts-matrix.json`; la base actual prueba `v2026.3` y `v2026.2`.
- Incluye gates para unit, runtime, E2E, PHP 8.4, cobertura UI, documentacion y release.
- Incluye documentacion de usuario local en `docs/user/` y mapa de impacto base/modulo en `docs/docs-sync/`.
- Incluye `Tools/manifest.json` y provider compatible con `BeplyAgents`.
- Incluye flujo clean-room para ROM copy visual sin copiar codigo del original.
- Incluye lock y sync controlado de plantilla para actualizar tooling comun sin pisar producto.
- Incluye un contrato reutilizable que construye una sola vez desde `vX.Y`, publica el asset inmutable y valida esos mismos bytes en DEV.
- Incluye una promocion PROD que exige evidencia DEV100 exacta y reutiliza el asset sin rebuild.
- Permite que un unico Full-Set emita evidencia canonica de varios plugins mediante un opt-in fail-closed: valida todos los registros y selecciona exactamente uno del plugin promovido.
- Sirve como base para documentar compatibilidad, capacidades, tools y contrato de release de nuevos plugins Beply.

## CI/CD

| Evento | Flujo | Resultado |
| --- | --- | --- |
| `push` a cualquier rama | `Tests` | Valida contrato, docs, PHP 8.4, lint, unit, runtime y E2E contra la matriz FacturaScripts. |
| `pull_request` | `Tests` | Valida el cambio sin publicar artefactos. |
| `main` | `Tests` | Valida codigo y contratos; no publica candidatos. |
| `tag vX.Y` | `Tests` + `Release Plugin` | Construye un unico ZIP, crea el GitHub Release y sube exactamente esos bytes a DEV como `pending_review`. |
| `workflow_dispatch` | `Promote Immutable Plugin To PROD` | Tras DEV100, verifica UUID, SHA-256, bytes, tag, source SHA y run; descarga el mismo asset y lo sube a PROD como `pending_review`. |

Las credenciales son fail-closed: un secreto ausente falla el efecto dependiente. Ningun workflow convierte `latest`, `pending_review`, CI verde o un upload correcto en DEV100/PROD100.

## Uso recomendado

1. Renombrar la carpeta, namespace y `facturascripts.ini`.
2. Confirmar o ampliar `.beply/facturascripts-matrix.json`.
3. Sustituir el smoke por tests reales unit/runtime/E2E.
4. Completar `docs/user/`, `docs/docs-sync/impact-map.json` y `docs/testing/ui-coverage-matrix.json`.
5. Declarar tools IA en `Tools/manifest.json` si el plugin modifica el chat/agente.
6. Migrar los adapters de release con un `uses:` fijado al SHA exacto revisado de esta plantilla; no copiar la implementacion al plugin.

## Actualizacion desde plantilla

La plantilla se usa al crear el plugin. Despues, el producto manda. Si se quiere
traer mejoras comunes de la plantilla, usar solo el sync controlado:

```bash
node scripts/template/sync-template.mjs --ref v1.4
node scripts/template/sync-template.mjs --ref v1.4 --apply
```

El sync actualiza CI, scripts, docs de proceso y contratos comunes. Los adapters
`release.yml` y `promote-prod.yml` solo se crean si faltan: una migracion nunca
sobrescribe la politica de release existente. Tampoco pisa
codigo del plugin, documentacion de usuario, `Tools/manifest.json`, matriz de
cobertura ni impact-map reales del plugin.

## Documentacion

Cada cambio funcional debe actualizar:

- pagina local del plugin en `docs/user/`;
- impacto sobre pagina base en `docs/docs-sync/impact-map.json`;
- URLs auditadas en `docs/docs-sync/published-pages.json`;
- matriz de controles en `docs/testing/ui-coverage-matrix.json`.

Para sincronizar docs locales con un checkout de documentacion:

```bash
node scripts/docs/sync-docs.mjs
BEPLY_DOCS_REPO_PATH=/ruta/a/beply-web node scripts/docs/sync-docs.mjs --apply
```

## Tools IA

El contrato vive en `Tools/manifest.json`. `Lib/BeplyAgentToolProvider.php` expone tools/packs/runtime definitions para `BeplyAgents`. Por defecto no publica tools productivas; cada plugin debe declarar las suyas y probarlas.

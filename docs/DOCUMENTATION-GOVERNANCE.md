# Gobierno de documentacion

La documentacion de usuario es parte del producto. Un cambio funcional sin documentacion actualizada debe fallar en CI.

## Fuentes locales

- `docs/user/`: documentacion de usuario del plugin.
- `docs/docs-sync/impact-map.json`: que paginas base toca este plugin.
- `docs/docs-sync/published-pages.json`: URLs publicadas que deben auditarse.
- `docs/testing/ui-coverage-matrix.json`: controles que deben existir tambien en docs cuando sean visibles.

## Relacion base/modulo

Cuando un plugin modifica una pagina base, la documentacion base debe referenciarlo.

Ejemplo:

```text
Base: Programa de facturacion > Ventas > Clientes
Plugin: BeplyCRM
Impacto: anade pestanas, campos, actividades y oportunidades a la ficha de cliente.
```

La pagina base no duplica todo el manual del plugin. Debe explicar que existe la extension, que cambia en la pantalla y enlazar a la pagina del modulo.

## Publicacion

El workspace actual tiene:

- `apps/beply-web`: sitio publico `/help`.
- `apps/beply-help-runner`: capturas, manifiestos y borradores reproducibles.
- `infra/chatai-multiagente/adk-service`: sincronizacion WikiJS/API publica hacia Qdrant para el agente.
- `infra/beply-k3s/apps/adk-system/.../adk-service-docs-sync-cronjob.yaml`: cron GitOps de sincronizacion.

Cada plugin mantiene docs locales. El sync hacia la documentacion general se hace con `scripts/docs/sync-docs.mjs`.

## Auditoria en release

En tags `vX.Y`, CI ejecuta:

```bash
node scripts/ci/validate-docs-impact.mjs --require-ai
```

El script falla si:

- hay cambios funcionales sin entrada en `impact-map.json`;
- la pagina de plugin no existe;
- falta URL publicada relacionada;
- falta API key/modelo para la auditoria IA;
- la IA detecta campos, botones o flujos no documentados.

## Secrets esperados

- `BEPLY_DOCS_AI_API_KEY`: API key del proveedor IA.
- `BEPLY_DOCS_AI_MODEL`: modelo usado por la auditoria.
- `BEPLY_DOCS_AI_PROVIDER`: `openai` por defecto.
- `BEPLY_DOCS_REPO_PATH`: ruta local del repo/sitio de docs para sync manual.

## Criterio de aceptacion

Cada PR o tag debe poder responder:

- que pagina base cambia;
- que pagina de plugin lo explica;
- que campos, botones, flujos y permisos nuevos existen;
- que tests prueban esos elementos;
- que URL publicada se audito.

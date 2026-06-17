# Referencia: sistema de documentacion Beply

Investigacion local usada para definir el gobierno documental de plugins.

## Componentes encontrados

- `apps/beply-web`: sitio web que publica `/help`.
- `apps/beply-web/scripts/help-2026/import-help-2026.mjs`: generacion/importacion de estructura de ayuda.
- `apps/beply-help-runner`: runner para capturas, manifiestos y borradores de documentacion.
- `infra/chatai-multiagente/adk-service/src/sync/sync_wikijs.py`: sincroniza docs WikiJS/API publica hacia Qdrant.
- `infra/chatai-multiagente/adk-service/src/services/wikijs_client.py`: cliente WikiJS/API publica.
- `infra/beply-k3s/apps/adk-system/overlays/dev/adk-service-docs-sync-cronjob.yaml`: cron GitOps para sincronizacion de docs.
- `infra/beply-k3s/apps/backend-api/overlays/dev/configmap.yaml`: configura Content AI documentation impact sync.

## Modelo operativo propuesto

1. Cada plugin mantiene docs locales en `docs/user/`.
2. Cada plugin declara impacto en docs base con `docs/docs-sync/impact-map.json`.
3. Cada plugin declara URLs publicadas a auditar en `docs/docs-sync/published-pages.json`.
4. `scripts/docs/sync-docs.mjs` copia docs locales a un checkout de docs general.
5. En tags, CI ejecuta auditoria IA contra docs locales, impacto base y contenido publicado.
6. La documentacion publicada se sincroniza despues hacia Qdrant/ADK por el sistema existente.

## Regla de release

Si la version publicada del plugin no esta documentada en la documentacion publicada, el tag falla.

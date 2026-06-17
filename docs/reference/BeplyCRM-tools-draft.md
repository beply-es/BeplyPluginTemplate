# Referencia: BeplyCRM tools draft

Investigacion realizada sobre `plugins/facturascripts/BeplyCRM`.

## Archivos relevantes

- `Lib/BeplyAgentToolProvider.php`
- `Lib/CrmControlManifest.php`
- `Lib/CrmControlToolExecutor.php`
- `Lib/CrmCallAssistantDraftService.php`
- `Lib/CrmCallAssistantPolicy.php`
- `Controller/ApiBeplycrmCallAssistant.php`
- `Test/Unit/CrmControlManifestTest.php`
- `Test/Unit/CrmControlToolExecutorTest.php`

## Patron util

- Provider fino compatible con `BeplyAgents`.
- Manifiesto versionado con `schema_version`, `manifest_version`, plugin y executor.
- `listAvailableTools()` publica el catalogo de alto nivel.
- `listAvailableToolPacks()` agrupa tools.
- `listRuntimeToolDefinitions()` publica funciones concretas con JSON schema.
- Executor separado normaliza payloads y devuelve resultado de revision.
- Las mutaciones quedan en `review_required`.
- Las tools de riesgo alto bloquean ejecucion autonoma.

## Ideas que pasan a plantilla

- `Tools/manifest.json` como contrato local versionable.
- `Lib/BeplyAgentToolProvider.php` como adaptador hacia `BeplyAgents`.
- `executionPolicy` obligatoria.
- `coreOverrides` para declarar modificaciones de tools core.
- Tests de manifest y executor como requisito minimo.

## Cosas a mejorar antes de produccion

- Evitar duplicar normalizacion entre API controller y executor.
- Formalizar schema JSON compartido.
- Definir compatibilidad exacta con MCP si el gateway externo lo necesita.
- Documentar cada tool en `docs/user/` y docs base.

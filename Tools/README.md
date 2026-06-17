# Tools

Esta carpeta contiene el contrato de IA del plugin.

## Archivos

- `manifest.json`: tools, packs, runtime functions, permisos, overrides y docs.
- `../Lib/BeplyAgentToolProvider.php`: provider que descubre `BeplyAgents`.
- `../Lib/TemplateToolExecutor.php`: executor placeholder que debe sustituirse por uno real.

## Para anadir una tool

1. Declarar `tools[]` con `id`, `name`, `description`, `category`, `icon`.
2. Declarar `runtimeTools[]` con JSON schema estricto y `additionalProperties: false`.
3. Declarar permisos y riesgo de mutacion.
4. Implementar executor en `Lib/`.
5. Anadir tests unitarios y runtime.
6. Anadir documentacion de usuario y entrada en `docs/docs-sync/impact-map.json`.

## Regla de seguridad

Si una tool escribe datos, el primer release debe ser `review_required`. Para pasar a autonomia hace falta decision explicita, tests y documentacion del riesgo.

# Manifiesto de tools IA

Los plugins pueden ampliar las capacidades del chat/agente de FacturaScripts declarando tools propias. El objetivo es que un servicio con 20 plugins instalados pueda agregar todos los manifiestos y entregar a la IA un contrato exacto de lo que puede hacer.

## Estructura

- `Tools/manifest.json`: contrato machine-readable.
- `Lib/BeplyAgentToolProvider.php`: punto de descubrimiento actual de `BeplyAgents`.
- `Lib/*ToolExecutor.php`: ejecuta o prepara la accion.
- Tests unitarios/runtime: validan schema, policies, permisos y que no haya mutaciones autonomas no permitidas.

## Compatibilidad con BeplyAgents

`BeplyAgents` busca:

```text
FacturaScripts\Plugins\<PluginName>\Lib\BeplyAgentToolProvider
```

El provider debe implementar `BeplyAgentToolProviderInterface` y publicar:

- `pluginName()`
- `listAvailableTools()`
- `listAvailableToolPacks()`
- `listRuntimeToolDefinitions()`

El borrador de `BeplyCRM` confirma el patron: provider fino, manifiesto versionado, definiciones tipo `function`, executor separado y mutaciones en `review_required`.

## IDs

- `tool_type`: `<plugin-normalizado>.<dominio>`
- `pack_type`: `<plugin-normalizado>.<pack>`
- runtime function: `<plugin-normalizado>.<accion>`

Ejemplo:

```text
beplycrm.sales-assistant
beplycrm.call-notes-core
beplycrm.save_call_note_draft
```

## Politica de ejecucion

Toda tool declara:

- `executionMode`: `read_only`, `review_required` o `autonomous_allowed`.
- `mutationRisk`: `none`, `low`, `medium`, `high`.
- `humanReviewRequired`: boolean.
- `permissions`: scopes necesarios.
- `executor`: clase y metodo.

Reglas:

- Las mutaciones empiezan en `review_required`.
- `high` nunca se ejecuta de forma autonoma.
- El executor devuelve siempre `mutations_committed`.
- Si prepara borradores, debe devolver IDs de revision, no aplicar cambios finales sin confirmacion.

## Overrides del core

Si un plugin modifica una tool core:

- anadir entrada en `coreOverrides`;
- indicar `coreToolId`;
- explicar motivo;
- declarar compatibilidad de versiones;
- anadir tests de regresion del comportamiento core y del nuevo comportamiento.

## Documentacion

Cada tool visible para usuario debe tener pagina en `docs/user/` y entrada en `docs/docs-sync/impact-map.json`.

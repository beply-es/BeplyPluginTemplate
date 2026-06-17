# Testing obligatorio

La plantilla no acepta "smokes" como cobertura final. El smoke inicial solo demuestra que el scaffolding arranca.

## Capas

| Capa | Objetivo | Requisito |
| --- | --- | --- |
| Unit | Reglas puras, contratos, normalizadores, policies | Obligatorio |
| Runtime | Modelos, tablas, Init, extensiones FacturaScripts | Obligatorio |
| E2E | Flujo real en navegador con datos seed | Obligatorio |
| Visual | ROM copy, pantallas complejas, regresion UI | Obligatorio cuando hay UI relevante |
| Docs | Impacto usuario/base y auditoria IA | Obligatorio |
| Tools IA | Manifest, schema, executor y seguridad | Obligatorio si hay tools |

## Cobertura de interfaz

Cada pantalla se declara en `docs/testing/ui-coverage-matrix.json`.

Para cada control visible:

- `id`: estable, namespaced por pantalla.
- `label`: texto visible.
- `type`: button, link, field, filter, tab, menu, modal, row-action, bulk-action, state.
- `surface`: controller, route o template.
- `preconditions`: datos que hay que crear.
- `testIds`: specs que lo cubren.
- `cleanup`: como se deja el entorno limpio.

Si hay 50 botones, hay 50 entradas y 50 pruebas. Las pruebas deben crear datos, ejecutar la accion, verificar resultado y limpiar.

## Datos de prueba

- Los seed viven en `Test/E2E`, `tests/fixtures` o scripts equivalentes.
- Cada spec debe poder ejecutarse en una base limpia.
- Los datos deben llevar prefijo claro, por ejemplo `E2E_BeplyPluginTemplate_`.
- La limpieza se ejecuta aunque el test falle cuando sea posible.

## Multiversion FacturaScripts

La matriz canonica vive en `.beply/facturascripts-matrix.json`. CI ejecuta contra cada `supported[].ref` marcado como `required`.

Cuando salga una version nueva:

1. Anadirla como `latest`.
2. Mantener la anterior como `previous` si sigue siendo soportada.
3. Ejecutar toda la matriz.
4. Documentar incompatibilidades en `CHANGELOG.md` y `README.md`.

## Criterio de cierre

Un cambio solo esta terminado si:

- unit/runtime/E2E pasan;
- la matriz UI cubre controles nuevos o modificados;
- las docs de usuario y base estan actualizadas;
- las capturas/evidencias necesarias estan versionadas o enlazadas;
- no quedan skips silenciosos en CI.

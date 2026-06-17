# Guia de estilo FacturaScripts

## Principio

El plugin debe parecer FacturaScripts. Se extiende el core, se anaden deltas y se evita duplicar pantallas enteras.

## Controllers

- Usar controladores core y `ExtendedController` cuando encaje.
- Mantener `getPageData()`, `createViews()` y `loadData()` simples.
- No mezclar reglas de negocio grandes dentro del controller: moverlas a `Lib/`.
- Validar permisos antes de acciones destructivas.
- Las respuestas API devuelven JSON estable, codigos HTTP coherentes y errores sin trazas.

## Modelos y tablas

- Tablas propias con prefijo claro: `beply_`, `crm_` u otro prefijo del dominio.
- No tocar tablas core sin `Extension/Table`.
- Las migraciones deben ser idempotentes.
- Las constantes de estado deben estar centralizadas y probadas.

## XMLView

- Preferir `Extension/XMLView/<VistaCore>.xml` para anadir campos a fichas core.
- Usar `order`, `display`, `widget`, `label` y permisos como lo hace el core.
- No ocultar campos core sin motivo documentado.
- Cada columna o boton nuevo debe aparecer en la matriz de UI y en docs.

## Twig

- Las vistas propias van en `View/`.
- Las extensiones deben engancharse al core y aportar solo el bloque necesario.
- Evitar copiar Twig completo del core: aumenta deuda y rompe upgrades.
- Usar clases Bootstrap/core existentes antes de CSS propio.
- No meter textos de ayuda internos en pantalla si el core no lo hace.

## Assets

- CSS y JS namespaced por plugin.
- Evitar selectores globales que puedan afectar otras pantallas.
- No incluir vendors si el core ya provee una alternativa suficiente.
- Si hay componente complejo, anadir tests JS de contrato.

## Seguridad

- Nada de secretos en repo.
- Nada de SQL concatenado con input de usuario.
- Sanitizar textos con utilidades core.
- Las tools IA con mutaciones empiezan en revision humana.

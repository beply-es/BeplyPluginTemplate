# ROM copy clean-room

Este flujo se usa cuando el objetivo es reproducir visual y funcionalmente un plugin existente sin copiar codigo, assets, plantillas, SQL ni estructura interna.

## Regla principal

Solo se observa el producto original por navegador, como usuario final. La implementacion se escribe desde cero en este plugin.

## Permitido

- Navegar por la instancia original.
- Hacer capturas.
- Documentar campos, botones, estados, flujos, errores y permisos observables.
- Medir comportamiento con Playwright.
- Crear una especificacion funcional propia.

## Prohibido

- Leer PHP, Twig, JS, CSS, XML, SQL o assets del plugin original.
- Copiar nombres internos, estructura de carpetas o queries.
- Copiar iconos, imagenes o textos largos que no sean parte necesaria de la UI observable.
- Usar dumps de base de datos del plugin original.

## Evidencias

Crear o actualizar:

- `docs/legal-cleanroom/00_resumen_ejecutivo.md`
- `docs/legal-cleanroom/02_politica_no_acceso_codigo_original.md`
- `docs/legal-cleanroom/05_especificacion_funcional/README.md`
- `docs/legal-cleanroom/08_revision_no_copia/checklist_no_copia.md`
- `docs/testing/ui-coverage-matrix.json`

## Flujo

1. Registrar fuentes permitidas.
2. Explorar con navegador y capturas.
3. Convertir cada pantalla en inventario funcional.
4. Implementar desde cero con estilo FacturaScripts.
5. Comparar visualmente por capturas y Playwright.
6. Validar checklist de no copia antes del release.

## Si hay acceso accidental

Parar, registrar el archivo o recurso visto, eliminar cualquier implementacion contaminada y rehacer esa parte con especificacion independiente.

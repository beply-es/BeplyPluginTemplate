# Flujo de trabajo Codex

Esta plantilla existe para que cualquier plugin nuevo empiece con el mismo contrato operativo: investigacion, implementacion, tests completos, documentacion y release.

## 1. Arranque

1. Leer `AGENTS.md`.
2. Revisar `facturascripts.ini`, `.beply/facturascripts-matrix.json` y `README.md`.
3. Confirmar con el usuario la version objetivo de FacturaScripts si no coincide con la matriz.
4. Si hay referencia visual externa, activar el flujo clean-room de `docs/ROM-COPY-CLEANROOM.md`.
5. Si hay cambios de IA/chat/tools, revisar `docs/AI-TOOLS-MANIFEST.md`.
6. Si el plugin ya existe y se quiere traer tooling nuevo de plantilla, revisar `docs/TEMPLATE-SYNC.md`.

## 2. Investigacion

- Buscar patrones existentes en plugins Beply locales antes de inventar estructura.
- Revisar controladores, modelos, XMLView, Twig, assets y tests equivalentes.
- Si una funcionalidad toca pantallas core, localizar primero la extension core correcta.
- Si se toca documentacion, localizar la pagina base y la pagina de modulo afectada.

## 3. Implementacion

- Mantener cambios pequenos y trazables.
- Preferir APIs y extensiones FacturaScripts antes que reemplazos completos.
- Registrar todo control visible en `docs/testing/ui-coverage-matrix.json`.
- Registrar todo impacto documental en `docs/docs-sync/impact-map.json`.
- Registrar toda tool o override en `Tools/manifest.json`.

## 4. Validacion

Orden minimo:

1. `php -l` o `scripts/ci/php84-compat-scan.php`.
2. `node scripts/ci/validate-template-contract.mjs`.
3. `node scripts/ci/validate-docs-impact.mjs`.
4. PHPUnit unitario.
5. PHPUnit runtime con FacturaScripts real.
6. Playwright E2E con datos seed, limpieza y evidencias.
7. Auditoria IA de documentacion en tags de release.

## 5. Release y promocion

- `main` valida y no publica candidatos.
- `vX.Y` construye una vez y publica el mismo asset en GitHub Release y DEV.
- El tag debe coincidir con `facturascripts.ini` y resolver al source SHA declarado.
- La validacion DEV debe emitir un unico registro machine-readable con UUID,
  SHA-256, bytes, tag y source SHA exactos.
- PROD descarga ese mismo asset despues de DEV100; nunca reconstruye.
- Los plugins consumen workflows reutilizables fijados a un SHA exacto del
  template y conservan solo adapters/validaciones propias inevitables.
- CI, upload, attestation o `pending_review` no equivalen a DEV100/PROD100.

## 6. Sync de plantilla

No sincronizar producto automaticamente. Para actualizar plugins ya creados,
solo usar `scripts/template/sync-template.mjs`, revisar diff y ejecutar tests.

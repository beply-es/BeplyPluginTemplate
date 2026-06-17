# Sync de documentacion

Esta carpeta conecta docs locales del plugin con la documentacion general.

## Archivos

- `impact-map.json`: paginas base y de plugin que deben cambiar juntas.
- `published-pages.json`: URLs publicadas que CI debe auditar.

## Flujo local

```bash
node scripts/docs/sync-docs.mjs
node scripts/docs/sync-docs.mjs --apply
```

El modo sin `--apply` solo muestra el plan. El modo `--apply` requiere `BEPLY_DOCS_REPO_PATH` o `--docs-root`.

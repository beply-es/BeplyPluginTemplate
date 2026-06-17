# CI/CD Beply

## Ramas y tags

- Rama operativa: `main` salvo `BEPLY_RELEASE_BRANCH`.
- `main`: candidato `dev` en la plataforma.
- Tag `vX.Y`: candidato `prod`.
- El tag debe coincidir con `facturascripts.ini version`.

## Secrets

| Secret | Uso |
| --- | --- |
| `BEPLY_DEV_CI_TOKEN` | Subida de candidato dev |
| `BEPLY_CI_TOKEN` | Subida prod y fallback dev |
| `BEPLY_API_URL` | API prod de Beply |
| `CODECOV_TOKEN` | Cobertura, opcional |
| `BEPLY_DOCS_AI_API_KEY` | Auditoria IA de docs en tags |
| `BEPLY_DOCS_AI_MODEL` | Modelo de auditoria IA |
| `BEPLY_DOCS_AI_PROVIDER` | Proveedor, por defecto `openai` |
| `BEPLY_DOCS_REPO_PATH` | Sync local de docs |

Variables recomendadas:

| Variable | Uso |
| --- | --- |
| `BEPLY_GHA_RUNNER` | Runner ARC/self-hosted |
| `BEPLY_RELEASE_BRANCH` | Rama que publica dev |

## Gates

`Tests` valida:

- contrato de plantilla;
- matriz FacturaScripts;
- PHP 8.4;
- lint;
- unit;
- runtime;
- E2E;
- docs impact static audit.

`Release Plugin` valida:

- workflow `Tests` terminado en verde;
- docs audit static en dev;
- docs audit IA obligatoria en tag;
- tag/version coherente;
- subida a plataforma.

## Plataforma

La API de release es:

```text
POST /api/v1/plugins/release
```

El ZIP debe incluir `facturascripts.ini` y version coherente. La plataforma deja el candidato en `pending_review` hasta aprobacion.

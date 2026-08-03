# CI/CD Beply

## Modelo build-once

- `main` y pull requests solo validan; no publican candidatos.
- Un tag inmutable `vX.Y`, coincidente con `facturascripts.ini version`, construye un unico ZIP determinista.
- Ese ZIP se publica como asset del GitHub Release y los mismos bytes se suben a DEV `pending_review`.
- Una reejecucion descarga el asset existente; no reconstruye.
- PROD solo acepta el mismo tag, source SHA, SHA-256 y numero de bytes que superaron DEV100.
- La promocion descarga el asset existente; nunca ejecuta el builder.

## Secrets

| Secret | Uso |
| --- | --- |
| `BEPLY_DEV_CI_TOKEN` | Subida de candidato dev |
| `BEPLY_PROMOTION_GITHUB_TOKEN` | Lectura del run/log DEV100 exacto |
| `BEPLY_PROD_CI_TOKEN` | Subida del mismo asset a PROD |
| `BEPLY_DEV_PLUGIN_ARTIFACT_SIGNING_PRIVATE_KEY` | Firma DEV opcional; si se declara, requiere key ID |
| `BEPLY_DEV_PLUGIN_ARTIFACT_SIGNATURE_KEY_ID` | Identidad de clave DEV opcional |
| `BEPLY_PLUGIN_ARTIFACT_SIGNING_PRIVATE_KEY` | Firma PROD opcional; si se declara, requiere key ID |
| `BEPLY_PLUGIN_ARTIFACT_SIGNATURE_KEY_ID` | Identidad de clave PROD opcional |
| `CODECOV_TOKEN` | Cobertura, opcional |
| `BEPLY_DOCS_AI_API_KEY` | Auditoria IA de docs en tags |
| `BEPLY_DOCS_AI_MODEL` | Modelo de auditoria IA |
| `BEPLY_DOCS_AI_PROVIDER` | Proveedor, por defecto `openai` |
| `BEPLY_DOCS_REPO_PATH` | Sync local de docs |

Variables recomendadas:

| Variable | Uso |
| --- | --- |
| `BEPLY_GHA_RUNNER` | Runner para los workflows reutilizables |

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
- docs audit IA obligatoria en tag;
- tag/version coherente;
- SHA exacto del contrato reutilizable;
- un unico build o reutilizacion del release existente;
- checksum, bytes, UUID y estado `pending_review` de DEV.

`Promote Immutable Plugin To PROD` exige:

- confirmacion literal del efecto;
- run DEV terminal `success`, workflow/event/head SHA exactos;
- exactamente un registro `BEPLY_PLUGIN_DEV100_EVIDENCE_JSON`;
- `versionId`, SHA-256, bytes, tag y source SHA iguales a los esperados;
- descarga del asset del GitHub Release, sin rebuild;
- candidato PROD `pending_review` con evidencia machine-readable.

El registro DEV100 canonico contiene solo identidad tecnica no sensible:

```json
{"schemaVersion":"beply.plugin.dev100.v1","pluginName":"PluginName","version":"1.2","versionId":"11111111-1111-4111-8111-111111111111","checksum":"sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa","fileSize":4242,"releaseTag":"v1.2","sourceSha":"bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"}
```

Campos extra, registros duplicados, UUID no canonico, `latest`, SHA abreviado o bytes no positivos fallan cerrados.
El productor debe ensamblar el nombre del marcador en runtime para que la línea
de código que Actions imprime no simule un segundo registro.

## Plataforma

La API de release es:

```text
POST /api/v1/plugins/release
```

El ZIP debe incluir `facturascripts.ini` y version coherente. La plataforma deja cada candidato en `pending_review` hasta aprobacion canonica. Un upload, GitHub Release, attestation o R2 verde no sustituye la validacion funcional DEV/PROD.

## Consumo desde un plugin

El plugin conserva adapters finos y fija el contrato revisado por SHA completo:

```yaml
jobs:
  publish:
    uses: beply-es/BeplyPluginTemplate/.github/workflows/reusable-immutable-plugin-candidate.yml@0123456789abcdef0123456789abcdef01234567
    with:
      contract_sha: 0123456789abcdef0123456789abcdef01234567
```

La promocion usa el workflow reutilizable equivalente con el mismo SHA. El
template es publico y no requiere un secreto de checkout; los tokens de
catalogo y de lectura de evidencia privada siguen siendo obligatorios y
fail-closed. No se copia packaging, transporte, parsing de evidencia ni logica
de promocion al repositorio consumidor. Las validaciones inevitables del
producto permanecen en su adapter y su E2E.

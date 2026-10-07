# CI/CD Beply

## Modelo build-once

- `main` y pull requests solo validan; no publican candidatos.
- Un tag inmutable `vX.Y`, coincidente con `facturascripts.ini version`, construye un unico ZIP determinista.
- Ese ZIP se publica como asset del GitHub Release y los mismos bytes se suben a DEV `pending_review`.
- Una reejecucion descarga el asset existente; no reconstruye.
- PROD solo acepta el mismo tag, source SHA, SHA-256 y numero de bytes que superaron DEV100.
- La promocion descarga el asset existente; nunca ejecuta el builder.
- Si el repositorio fue renombrado después de publicar un tag histórico, el caller puede declarar la procedencia histórica exacta (`source_repo_full_name`, URL y fecha de publicación). Los overrides de repo y URL viajan juntos, el asset se descarga desde esa identidad y los bytes/checksum/tag/source SHA siguen siendo inmutables.

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

La descarga del asset y la lectura de `published_at` usan `github.token` para
la misma identidad `source_repo_full_name`. `BEPLY_PROMOTION_GITHUB_TOKEN` se
reserva para el run/log DEV100, que puede estar en otro repositorio privado.
No se presupone que ese token de evidencia tenga acceso al repositorio del
plugin. Los permisos existentes no se amplían para completar la promoción.

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

Por defecto, la promocion conserva el contrato de un solo registro global. Un
Full-Set que valide varios plugins puede activar `allow_other_plugin_evidence`:
el parser valida de forma canonica todos los registros, exige exactamente uno
para el `pluginName` promovido y rechaza peers invalidos o duplicados del
objetivo. El opt-in no relaja la identidad inmutable ni permite seleccionar por
`latest`, version parcial o posicion en el log.

## Procedencia de fuente (`beply-plugin-source-provenance-v1`)

El candidato inmutable se divide en dos jobs:

1. `source_provenance` (`Publish Immutable Release And Source Provenance Carrier`):
   comprueba que `refs/tags/${GITHUB_REF_NAME}^{commit}` es exactamente
   `GITHUB_SHA` (anotado o ligero; si no, falla cerrado), construye o reutiliza el
   asset del GitHub Release, genera el manifiesto con
   `scripts/ci/build_source_provenance_manifest.mjs` y lo sube como unico fichero
   `plugin-source-provenance.json` en el artefacto
   `plugin-source-provenance-${{ github.run_id }}-${{ github.run_attempt }}`
   con `actions/upload-artifact@<sha40>` (paso `Upload plugin source provenance carrier`).
2. `publish` (`needs: source_provenance`): descarga los mismos bytes, comprueba
   SHA-256 y tamano, y hace el POST con
   `sourceProvenance={"runId","runAttempt","publisherJobId","manifestArtifactId"}`,
   `sourceProvenanceEnvironment` (`dev` por defecto), `releaseTrack` explicito y
   `sourceBranch` igual al tag.

El manifiesto es JSON canonico (claves ordenadas, sin espacios ni salto final) y
replica el esquema estricto del backend. Contiene repositorio e id, commit, tag,
workflow llamador y su blob en ese commit, run/attempt, `publisherJobKey` (clave
del job llamador, `caller_job_key`), id del job interno, evento y ref; release id
y `published_at`; asset id, nombre, `digest` de la API y bytes; y `fsName`/version.

El ZIP se construye siempre una sola vez, de forma determinista, y el asset
publicado (nuevo o reutilizado) se descarga y se compara byte a byte con esa
construccion antes de firmar el manifiesto. Un asset subido a mano o
pre-colocado falla cerrado.

Modo «solo procedencia»: un `workflow_dispatch` sobre el ref del tag ya
publicado no crea ninguna release y exige que exista; reconstruye, compara byte a
byte con el asset publicado, genera el portador con `event=workflow_dispatch` y
hace POST del mismo asset para mejorar el testigo de la version existente. Para
usarlo, el `release.yml` del plugin **en el commit del tag** tiene que declarar
`workflow_dispatch` y llamar ya a este reusable, y la raiz tiene que incluir
`workflow_dispatch` en `events`. Los tags anteriores a este contrato no se
pueden rellenar asi.

Como el POST sale del mismo run, la plataforma registra el testigo como
`pending` (el job publicador ya esta `completed/success`, el run no). Cuando el
run termina en `success`, la plataforma lo reverifica y lo pasa a `verified`.

La plataforma lo acepta solo con una raiz `tag-publisher` que permita el SHA
exacto de este reusable. Ademas, en el `release.yml` del plugin,
`with.contract_sha` tiene que ser literalmente ese mismo SHA: el tooling (ZIP y
manifiesto) se descarga de `contract_sha`, y una expresion u otro commit se
rechazan. Si no la tiene, rechaza la subida: primero se configura
la raiz y despues se sube el pin del plugin. Un `uses:` local (el propio
template) nunca cumple esa raiz, asi que `release.yml` del template pasa
`submit_source_provenance: false`. Si hace falta reintentar, se relanzan todos
los jobs: relanzar solo el POST cambia el attempt y la plataforma lo rechaza.

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

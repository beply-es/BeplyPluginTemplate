# Changelog

## Unreleased

- El candidato DEV solo sale en verde si lee de vuelta del catalogo DEV
  exactamente una fila `pending_review` para los bytes subidos y el
  `pluginId`/`versionId` devueltos. Un plugin que el catalogo DEV no conoce se
  rechaza antes de subir nada (su alta va por la ingesta canonica de k3s): su
  primera subida crearia una submission y fallaria despues, sin reintento posible.
- El candidato inmutable sube un portador `beply-plugin-source-provenance-v1`
  (job interno `source_provenance`) y el POST a DEV, en un job separado con
  `needs`, envia el localizador `sourceProvenance` y
  `sourceProvenanceEnvironment`. El tag debe pelar exactamente al commit del run.
- Anade el contrato reutilizable build-once para publicar un unico asset
  inmutable en DEV y promover exactamente los mismos bytes a PROD tras DEV100.
- Define evidencia machine-readable fail-closed para UUID/versionId, SHA-256,
  bytes, tag y source SHA.
- Convierte los workflows del template en adapters finos y evita que el sync
  sobrescriba adapters de release existentes durante la migracion de plugins.
- `min_php` vuelve a 8.2, el runtime de tenant (`php:8.2-fpm-alpine`): con 8.4 el
  backend rechaza toda release (`PLUGIN_MIN_PHP_EXCEEDS_RUNTIME`) y los plugins
  creados desde la plantilla lo heredaban. La CI prueba en 8.2 y el escaneo PHP 8.4
  queda como compatibilidad que no bloquea. El contrato exige `min_php` <= 8.2.

## v1.4 - 2026-06-17

- Anade contratos de plantilla para desarrollo Codex, testing multiversion,
  documentacion, clean-room ROM copy y tools IA.
- Anade lock de plantilla y sync controlado de tooling comun para plugins ya
  creados sin pisar producto.
- Actualiza la matriz objetivo a FacturaScripts v2026.3/v2026.2 con PHP 8.4.
- Refuerza CI/CD con validadores de contrato, docs impact, release model y
  auditoria IA de documentacion en tags.

## v1.3 - 2026-06-08

- Adds a GitHub-hosted fallback for the PHP 8.4 compatibility job when `BEPLY_GHA_RUNNER` is not available for the repository.
- Supersedes the cancelled `v1.2` validation run without moving the existing immutable tag.

## v1.2 - 2026-06-08

- Skips browser E2E jobs on tag validation runs to keep PHP 8.4 releases focused on scanner, unit, and runtime gates.
- Declara `min_php = 8.4` para la release de compatibilidad PHP 8.4.
- Anade un gate CI dedicado con scanner de compatibilidad PHP 8.4.
- Ajusta Composer/validadores para ejecutar la suite sobre plataforma PHP 8.4.

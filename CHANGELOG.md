# Changelog

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

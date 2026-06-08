# Changelog

## v1.2 - 2026-06-08

- Skips browser E2E jobs on tag validation runs to keep PHP 8.4 releases focused on scanner, unit, and runtime gates.
- Declara `min_php = 8.4` para la release de compatibilidad PHP 8.4.
- Anade un gate CI dedicado con scanner de compatibilidad PHP 8.4.
- Ajusta Composer/validadores para ejecutar la suite sobre plataforma PHP 8.4.


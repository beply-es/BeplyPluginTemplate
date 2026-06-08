# BeplyPluginTemplate

Plantilla base para arrancar un plugin Beply de FacturaScripts con estructura minima, README normalizado y CI/CD listo para publicar candidatos `dev` y releases `prod`.

## Estado y compatibilidad

| Campo | Valor |
| --- | --- |
| Estado | Plantilla base |
| Tipo | Scaffold reutilizable |
| Nombre de plugin | `BeplyPluginTemplate` |
| Version actual | `1.0` |
| Compatibilidad declarada | `FacturaScripts 2025.71+` |
| PHP minimo declarado | `8.4` |
| Stack objetivo Beply | `FacturaScripts 2025.71 / PHP 8.4` |
| Estado de manifiesto | `Alineado con stack Beply` |
| Rama operativa | `main` |

## Capacidades principales

- Aporta una estructura minima de plugin FacturaScripts lista para renombrar y extender.
- Incluye un `Tests` baseline que clona FacturaScripts, instala dependencias y ejecuta PHPUnit o lint segun el contenido real del plugin.
- Si el plugin llega a declarar `facturascripts/core` en `composer.json`, el workflow omite ese `composer install` local porque el core ya lo aporta el checkout anfitrion.
- Incluye `Release Plugin` con gate sobre `Tests`, candidato `dev` desde la rama operativa y `prod` solo desde tags `v*`.
- Sirve como base para documentar compatibilidad, capacidades y contrato de release de nuevos plugins Beply.

## CI/CD

| Evento | Flujo | Resultado |
| --- | --- | --- |
| `push` a la rama operativa u otra rama | `Tests` | Ejecuta `phpunit` si encuentra tests y siempre hace lint de PHP. |
| `pull_request` | `Tests` | Valida el cambio sin publicar artefactos. |
| `tag vX.Y` | `Tests` + `Release Plugin` | Si `Tests` pasa, genera release de prod y sube el ZIP con `BEPLY_CI_TOKEN`. |
| `workflow_dispatch` | `Release Plugin` | Permite reintentar la publicacion sobre un SHA ya validado. |

Nota: el candidato `dev` usa `BEPLY_DEV_CI_TOKEN`. Si el secreto no existe, la subida `dev` se omite con aviso y no bloquea el workflow.

## Uso recomendado

1. Renombrar la carpeta y el namespace del plugin.
2. Ajustar `facturascripts.ini` sin salir del formato de version `X.Y`.
3. Sustituir el smoke test por tests reales del dominio.
4. Completar `Controller/`, `Model/`, `Table/` y `XMLView/` segun la necesidad del plugin.
5. Revisar si el repo debe publicar desde `main` o declarar `BEPLY_RELEASE_BRANCH`.

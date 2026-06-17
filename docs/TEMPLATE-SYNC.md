# Sincronizacion controlada de plantilla

La plantilla se usa para crear un plugin nuevo. Despues, el plugin es producto
propio y no debe quedar acoplado a la plantilla.

## Que se puede sincronizar

Solo tooling comun y contratos de trabajo:

- workflows de CI/CD;
- bootstrap de runtime de CI;
- validadores de contrato, docs y release;
- scripts de documentacion;
- docs de proceso para Codex, testing, estilo, ROM copy y tools IA;
- `AGENTS.md`;
- boilerplate legal o referencias solo si todavia no existen.

## Que no se sincroniza automaticamente

- codigo del plugin;
- `Init.php`, modelos, controladores, vistas, tablas o assets;
- `README.md`, `CHANGELOG.md` y `facturascripts.ini`;
- `Tools/manifest.json` real del plugin;
- documentacion de usuario real en `docs/user/`;
- `impact-map`, URLs publicadas y matriz real de cobertura UI;
- tests E2E o runtime ya adaptados al plugin.

## Uso

Dry-run:

```bash
node scripts/template/sync-template.mjs --ref v1.4
```

Aplicar:

```bash
node scripts/template/sync-template.mjs --ref v1.4 --apply
```

Usar una copia local de la plantilla:

```bash
node scripts/template/sync-template.mjs --template-root /ruta/BeplyPluginTemplate --apply
```

El script falla si el repo tiene cambios sin commit, salvo que se use
`--allow-dirty`. Despues de aplicar, revisar diff y ejecutar tests.

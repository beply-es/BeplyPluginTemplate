# Sincronizacion controlada de plantilla

La plantilla se usa para crear un plugin nuevo. Despues, el plugin es producto
propio y no debe quedar acoplado a la plantilla.

## Que se puede sincronizar

Solo tooling comun y contratos de trabajo:

- workflow de tests y scripts CI comunes;
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
- tests E2E o runtime ya adaptados al plugin;
- adapters de release/promocion existentes: se crean solo si faltan y nunca se sobrescriben.

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

## Migracion del contrato inmutable

La migracion es explicita por plugin:

1. Sincronizar los validadores y builders comunes.
2. Mantener intactos los adapters actuales durante la revision.
3. Sustituirlos en una PR propia por adapters finos que llamen los workflows
   reutilizables de `BeplyPluginTemplate` fijados a un SHA completo.
4. Ejecutar TDD/CI del plugin antes de crear el primer tag candidato.
5. Validar en DEV los mismos UUID/SHA-256/bytes/tag/source SHA y solo entonces
   habilitar la promocion PROD sin rebuild.

El sync no activa esta migracion por accidente y los plugins no migrados
continuan bajo su contrato previo hasta que su owner publique la PR focal.

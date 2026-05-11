<?php

use FacturaScripts\Core\Base\DataBase;
use FacturaScripts\Core\Base\DataBase\DataBaseWhere;
use FacturaScripts\Core\Cache;
use FacturaScripts\Core\DataSrc\Paises;
use FacturaScripts\Core\DbUpdater;
use FacturaScripts\Core\Internal\Plugin;
use FacturaScripts\Core\Kernel;
use FacturaScripts\Core\Lib\Import\CSVImport;
use FacturaScripts\Core\Model\Almacen;
use FacturaScripts\Core\Model\Divisa;
use FacturaScripts\Core\Model\Empresa;
use FacturaScripts\Core\Model\EstadoDocumento;
use FacturaScripts\Core\Model\FormaPago;
use FacturaScripts\Core\Model\IdentificadorFiscal;
use FacturaScripts\Core\Model\Impuesto;
use FacturaScripts\Core\Model\Pais;
use FacturaScripts\Core\Model\Serie;
use FacturaScripts\Core\Model\User;
use FacturaScripts\Core\Plugins;
use FacturaScripts\Core\Tools;

error_reporting(error_reporting() & ~E_DEPRECATED);

if (!defined('FS_FOLDER')) {
    define('FS_FOLDER', getcwd());
}

$autoload = FS_FOLDER . '/vendor/autoload.php';
if (!file_exists($autoload)) {
    throw new RuntimeException($autoload . ' not found');
}

require_once $autoload;

foreach (glob(FS_FOLDER . '/Plugins/*/vendor/autoload.php') ?: [] as $pluginVendor) {
    require_once $pluginVendor;
}

$config = FS_FOLDER . '/config.php';
if (!file_exists($config)) {
    throw new RuntimeException($config . ' not found');
}

require_once $config;

bootstrapFileSystem();
resetPluginState();

$db = new DataBase();
$db->connect();

Cache::clear();
Kernel::init();
DbUpdater::rebuild();

seedRequestedPlugins();
persistRequestedPlugins();
deployRequestedPlugins();
ensureCoreTables();
seedCoreCatalogData();
seedDefaultSettings();
initializeRequestedPlugins();
seedDefaultSettings();

echo 'Enabled plugins: ' . implode(', ', Plugins::enabled()) . PHP_EOL;

function requestedPluginFolders(): array
{
    $raw = getenv('CI_PLUGIN_FOLDERS') ?: '';
    $folders = array_filter(array_map('trim', explode(',', $raw)));
    $unique = [];

    foreach ($folders as $folder) {
        if ($folder === '' || in_array($folder, $unique, true)) {
            continue;
        }

        if (is_dir(FS_FOLDER . '/Plugins/' . $folder)) {
            $unique[] = $folder;
        }
    }

    return $unique;
}

function bootstrapFileSystem(): void
{
    $myFilesFolder = FS_FOLDER . '/MyFiles';
    $cacheFolder = $myFilesFolder . '/Cache';
    $facturasFolder = $myFilesFolder . '/facturas';

    foreach ([$myFilesFolder, $cacheFolder, $facturasFolder] as $folder) {
        if (!is_dir($folder) && !mkdir($folder, 0777, true) && !is_dir($folder)) {
            throw new RuntimeException('Failed to create runtime folder: ' . $folder);
        }
    }

    $_ENV['myFilesFolder'] = $myFilesFolder;
    $_SERVER['myFilesFolder'] = $myFilesFolder;
    putenv('myFilesFolder=' . $myFilesFolder);
}

function resetPluginState(): void
{
    $pluginStatePath = FS_FOLDER . '/MyFiles/plugins.json';
    if (file_exists($pluginStatePath) && !unlink($pluginStatePath)) {
        throw new RuntimeException('Failed to reset plugin state file');
    }
}

function seedRequestedPlugins(): void
{
    $plugins = [];
    foreach (requestedPluginFolders() as $index => $name) {
        $plugins[] = new Plugin([
            'enabled' => true,
            'folder' => $name,
            'name' => $name,
            'order' => $index + 1,
            'post_disable' => false,
            'post_enable' => false,
        ]);
    }

    $property = new ReflectionProperty(Plugins::class, 'plugins');
    $property->setAccessible(true);
    $property->setValue(null, $plugins);
}


function persistRequestedPlugins(): void
{
    $property = new ReflectionProperty(Plugins::class, 'plugins');
    $property->setAccessible(true);
    $plugins = $property->getValue();

    if (!is_array($plugins)) {
        return;
    }

    $path = FS_FOLDER . '/MyFiles/plugins.json';
    if (false === file_put_contents($path, json_encode($plugins, JSON_PRETTY_PRINT))) {
        throw new RuntimeException('Failed to persist plugin state file');
    }
}

function ensureCoreTables(): void
{
    $tableFiles = glob(FS_FOLDER . '/Core/Table/*.xml') ?: [];
    sort($tableFiles, SORT_STRING);

    $pending = [];
    foreach ($tableFiles as $filePath) {
        $pending[basename($filePath, '.xml')] = $filePath;
    }

    $maxPasses = max(3, count($pending));
    for ($pass = 1; $pass <= $maxPasses && !empty($pending); $pass++) {
        $createdThisPass = 0;
        DbUpdater::rebuild();
        clearDatabaseTableCache();

        foreach ($pending as $tableName => $filePath) {
            $structure = DbUpdater::readTableXml($filePath);
            if (DbUpdater::createOrUpdateTable($tableName, $structure)) {
                unset($pending[$tableName]);
                $createdThisPass++;
            }
        }

        clearDatabaseTableCache();
        if ($createdThisPass === 0) {
            break;
        }
    }

    DbUpdater::rebuild();
    clearDatabaseTableCache();

    if (!empty($pending)) {
        throw new RuntimeException(
            'Failed to bootstrap core tables: ' . implode(', ', array_keys($pending))
            . '. Last error: ' . DbUpdater::getLastError()
        );
    }
}

function clearDatabaseTableCache(): void
{
    $property = new ReflectionProperty(DataBase::class, 'tables');
    $property->setAccessible(true);
    $property->setValue([]);
}

function deployRequestedPlugins(): void
{
    Plugins::deploy(true, true);
}

function initializeRequestedPlugins(): void
{
    foreach (Plugins::enabled() as $pluginName) {
        $className = "FacturaScripts\\Plugins\\{$pluginName}\\Init";
        if (!class_exists($className)) {
            continue;
        }

        $init = new $className();
        $init->update();
        $init->init();
    }
}

function seedCoreCatalogData(): void
{
    $models = [
        new Pais(),
        new Divisa(),
        new FormaPago(),
        new Serie(),
        new Impuesto(),
        new IdentificadorFiscal(),
        new EstadoDocumento(),
    ];

    $db = new DataBase();
    $db->connect();

    foreach ($models as $model) {
        $sql = CSVImport::updateTableSQL($model::tableName());
        if ($sql !== '') {
            $db->exec($sql);
        }
    }
}

function seedDefaultSettings(): void
{
    $countryCode = resolveBootstrapCountryCode();
    Tools::settingsSet('default', 'codpais', $countryCode);

    $filePath = FS_FOLDER . '/Core/Data/Codpais/' . $countryCode . '/default.json';
    if (!file_exists($filePath) && $countryCode !== 'ESP') {
        $filePath = FS_FOLDER . '/Core/Data/Codpais/ESP/default.json';
    }

    if (file_exists($filePath)) {
        $defaultValues = json_decode((string) file_get_contents($filePath), true) ?? [];
        foreach ($defaultValues as $group => $values) {
            foreach ($values as $key => $value) {
                Tools::settingsSet($group, $key, $value);
            }
        }
    }

    ensureRequiredDefaultSettings();
    ensureDefaultCompany();
    ensureDefaultWarehouse();

    $where = [new DataBaseWhere('idempresa', Tools::settings('default', 'idempresa', 1))];
    foreach (Almacen::all($where) as $warehouse) {
        Tools::settingsSet('default', 'codalmacen', $warehouse->codalmacen);
        break;
    }

    ensureDefaultAdminUser();
    ensureAutomationAdminUser();
    Tools::settingsSave();
}

function resolveBootstrapCountryCode(): string
{
    $configuredCountry = trim((string) Tools::settings('default', 'codpais', ''));
    if ($configuredCountry !== '') {
        return $configuredCountry;
    }

    $defaultCountry = Paises::default();
    if (!empty($defaultCountry->codpais)) {
        return (string) $defaultCountry->codpais;
    }

    return 'ESP';
}

function ensureRequiredDefaultSettings(): void
{
    $fallbacks = [
        'codpais' => 'ESP',
        'coddivisa' => 'EUR',
        'idempresa' => 1,
        'codpago' => 'CONT',
        'codserie' => 'A',
        'codserierec' => 'R',
    ];

    foreach ($fallbacks as $key => $value) {
        if (trim((string) Tools::settings('default', $key, '')) === '') {
            Tools::settingsSet('default', $key, $value);
        }
    }
}

function ensureDefaultCompany(): void
{
    $companyId = (int) Tools::settings('default', 'idempresa', 1);
    $company = new Empresa();
    if ($company->load($companyId)) {
        return;
    }

    $company->idempresa = $companyId;
    $company->codpais = Tools::settings('default', 'codpais', 'ESP');
    $company->cifnif = '00000014Z';
    $company->nombre = 'CI bootstrap';
    $company->nombrecorto = 'CI bootstrap';
    $company->tipoidfiscal = Tools::settings('default', 'tipoidfiscal', 'NIF');

    if (!$company->save()) {
        throw new RuntimeException('Failed to create default company');
    }
}

function ensureDefaultWarehouse(): void
{
    $where = [new DataBaseWhere('idempresa', Tools::settings('default', 'idempresa', 1))];
    if (!empty(Almacen::all($where, [], 0, 1))) {
        return;
    }

    $warehouse = new Almacen();
    $warehouse->codalmacen = 'ALG';
    $warehouse->nombre = 'CI Warehouse';
    $warehouse->direccion = 'CI bootstrap';
    $warehouse->ciudad = 'Madrid';
    $warehouse->provincia = 'Madrid';

    if (!$warehouse->save()) {
        throw new RuntimeException('Failed to create default warehouse');
    }
}

function ensureDefaultAdminUser(): void
{
    $userNick = Tools::config('initial_user', 'admin');
    $userPass = Tools::config('initial_pass', 'admin');
    $companyId = (int) Tools::settings('default', 'idempresa', 1);
    $warehouseCode = (string) Tools::settings('default', 'codalmacen', '1');
    $user = new User();

    $requiresSave = !$user->load($userNick);
    if ($requiresSave === false) {
        $requiresSave = !$user->verifyPassword($userPass)
            || !$user->admin
            || !$user->enabled
            || (int) $user->idempresa !== $companyId
            || (string) $user->codalmacen !== $warehouseCode;
    }

    if ($requiresSave === false) {
        return;
    }

    $user->nick = $userNick;
    $user->password = password_hash($userPass, PASSWORD_DEFAULT);
    $user->email = Tools::config('initial_email', 'admin@example.com');
    $user->admin = true;
    $user->enabled = true;
    $user->idempresa = $companyId;
    $user->codalmacen = $warehouseCode;
    $user->langcode = Tools::config('lang');
    $user->homepage = (string) Tools::config('initial_homepage', 'Dashboard');
    $user->level = 99;

    if (!$user->save()) {
        throw new RuntimeException('Failed to create default admin user');
    }
}

function ensureAutomationAdminUser(): void
{
    $companyId = (int) Tools::settings('default', 'idempresa', 1);
    $warehouseCode = (string) Tools::settings('default', 'codalmacen', '1');
    $user = new User();

    if (!$user->load('e2e_admin')) {
        $user->nick = 'e2e_admin';
        $user->email = 'e2e_admin@example.com';
    }

    $requiresSave = !$user->verifyPassword('e2e_admin')
        || !$user->admin
        || !$user->enabled
        || (int) $user->idempresa !== $companyId
        || (string) $user->codalmacen !== $warehouseCode;

    if ($requiresSave === false) {
        return;
    }

    $user->password = password_hash('e2e_admin', PASSWORD_DEFAULT);
    $user->admin = true;
    $user->enabled = true;
    $user->idempresa = $companyId;
    $user->codalmacen = $warehouseCode;
    $user->langcode = Tools::config('lang');
    $user->homepage = (string) Tools::config('initial_homepage', 'Dashboard');
    $user->level = 99;

    if (!$user->save()) {
        throw new RuntimeException('Failed to create automation admin user');
    }
}

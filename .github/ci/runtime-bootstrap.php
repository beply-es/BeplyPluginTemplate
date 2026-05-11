<?php

use FacturaScripts\Core\Base\DataBase;
use FacturaScripts\Core\Cache;
use FacturaScripts\Core\Kernel;
use FacturaScripts\Core\Plugins;

error_reporting(error_reporting() & ~E_DEPRECATED);

define('FS_FOLDER', getcwd());

require_once FS_FOLDER . '/vendor/autoload.php';

foreach (glob(FS_FOLDER . '/Plugins/*/vendor/autoload.php') ?: [] as $pluginVendor) {
    require_once $pluginVendor;
}

$config = FS_FOLDER . '/config.php';
if (file_exists($config)) {
    require_once $config;
}

$myFilesFolder = FS_FOLDER . '/MyFiles';
$_ENV['myFilesFolder'] = $myFilesFolder;
$_SERVER['myFilesFolder'] = $myFilesFolder;
putenv('myFilesFolder=' . $myFilesFolder);

$db = new DataBase();
$db->connect();

Cache::clear();
Kernel::init();
Plugins::init();

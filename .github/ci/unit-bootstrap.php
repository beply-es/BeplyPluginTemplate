<?php

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

\class_exists(\PHPUnit\Framework\TestCase::class);

$autoloaders = spl_autoload_functions() ?: [];
foreach ($autoloaders as $autoloadFn) {
    spl_autoload_unregister($autoloadFn);
}

$pluginFolder = getenv('PLUGIN_FOLDER') ?: '';
try {
    if ($pluginFolder !== '') {
        foreach ([
            FS_FOLDER . '/Plugins/' . $pluginFolder . '/tests/bootstrap.php',
            FS_FOLDER . '/Plugins/' . $pluginFolder . '/Test/bootstrap.php',
        ] as $bootstrapFile) {
            if (file_exists($bootstrapFile)) {
                require_once $bootstrapFile;
                break;
            }
        }
    }
} finally {
    foreach (array_reverse($autoloaders) as $autoloadFn) {
        spl_autoload_register($autoloadFn);
    }
}

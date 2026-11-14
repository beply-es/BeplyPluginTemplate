<?php

declare(strict_types=1);

namespace FacturaScripts\Test\Plugins;

use PHPUnit\Framework\TestCase;
use RuntimeException;

/**
 * Ejecuta de verdad requestedDependencyFolders() de .github/ci/setup-runtime.php (TAREA-647.5):
 * una dependencia declarada que no está clonada o que no está entre CI_PLUGIN_FOLDERS para el
 * arranque, en vez de seguir sin ella. setup-runtime.php tiene efectos al cargarse, así que el test
 * extrae solo las dos funciones y las evalúa con otro nombre y con su propio FS_FOLDER.
 */
final class SetupRuntimeDependenciesTest extends TestCase
{
    private static bool $loaded = false;

    private string $root = '';

    /** @var array<string, string|false> */
    private array $savedEnv = [];

    protected function setUp(): void
    {
        self::loadFunctions();
        $this->root = sys_get_temp_dir() . '/setup-runtime-deps-' . bin2hex(random_bytes(6));
        foreach (['BeplyDemo', 'DepA', 'DepB'] as $folder) {
            mkdir($this->root . '/Plugins/' . $folder, 0700, true);
        }
        $GLOBALS['setupRuntimeTestFsFolder'] = $this->root;
        foreach (['CI_PLUGIN_FOLDERS', 'CI_PLUGIN_DEPENDENCIES'] as $name) {
            $this->savedEnv[$name] = getenv($name);
        }
    }

    protected function tearDown(): void
    {
        foreach ($this->savedEnv as $name => $value) {
            putenv($value === false ? $name : $name . '=' . $value);
        }
        foreach (['BeplyDemo', 'DepA', 'DepB'] as $folder) {
            @rmdir($this->root . '/Plugins/' . $folder);
        }
        @rmdir($this->root . '/Plugins');
        @rmdir($this->root);
    }

    public function testWithoutDependenciesTheListIsEmpty(): void
    {
        $this->env('BeplyDemo', null);
        self::assertSame([], \setupRuntimeTestRequestedDependencyFolders());

        $this->env('BeplyDemo', '');
        self::assertSame([], \setupRuntimeTestRequestedDependencyFolders());
    }

    public function testDeclaredAndCheckedOutDependenciesAreReturnedInOrder(): void
    {
        $this->env('BeplyDemo,DepA,DepB', ' DepA , DepB,DepA ');
        self::assertSame(['DepA', 'DepB'], \setupRuntimeTestRequestedDependencyFolders());
    }

    public function testADependencyThatWasNotCheckedOutStopsTheRuntime(): void
    {
        $this->env('BeplyDemo,DepA,Missing', 'DepA,Missing');
        $this->expectException(RuntimeException::class);
        $this->expectExceptionMessage('Missing');
        \setupRuntimeTestRequestedDependencyFolders();
    }

    public function testADependencyOutsideTheRequestedPluginsStopsTheRuntime(): void
    {
        $this->env('BeplyDemo,DepA', 'DepA,DepB');
        $this->expectException(RuntimeException::class);
        $this->expectExceptionMessage('DepB');
        \setupRuntimeTestRequestedDependencyFolders();
    }

    private function env(string $folders, ?string $dependencies): void
    {
        putenv('CI_PLUGIN_FOLDERS=' . $folders);
        putenv($dependencies === null ? 'CI_PLUGIN_DEPENDENCIES' : 'CI_PLUGIN_DEPENDENCIES=' . $dependencies);
    }

    private static function loadFunctions(): void
    {
        if (self::$loaded) {
            return;
        }

        $source = (string) file_get_contents(dirname(__DIR__) . '/.github/ci/setup-runtime.php');
        $code = "function setupRuntimeTestFsFolder(): string\n{\n    return \$GLOBALS['setupRuntimeTestFsFolder'];\n}\n";
        foreach (['requestedPluginFolders', 'requestedDependencyFolders'] as $name) {
            self::assertSame(1, preg_match('/^function ' . $name . '\(\): array\n\{\n.*?^\}\n/ms', $source, $match), $name);
            $code .= $match[0];
        }
        $code = str_replace(
            ['function requestedPluginFolders(', 'requestedPluginFolders()', 'function requestedDependencyFolders(', 'FS_FOLDER'],
            ['function setupRuntimeTestRequestedPluginFolders(', 'setupRuntimeTestRequestedPluginFolders()', 'function setupRuntimeTestRequestedDependencyFolders(', 'setupRuntimeTestFsFolder()'],
            $code
        );
        // eval solo de dos funciones copiadas del propio setup-runtime.php de este repo (sin datos
        // externos): cargar el fichero entero ejecutaría el arranque completo contra la base.
        eval($code);
        self::$loaded = true;
    }
}

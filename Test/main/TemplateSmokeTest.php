<?php

declare(strict_types=1);

namespace FacturaScripts\Test\Plugins;

use PHPUnit\Framework\TestCase;

final class TemplateSmokeTest extends TestCase
{
    public function testManifestKeepsSingleDecimalVersion(): void
    {
        $manifest = file_get_contents(dirname(__DIR__, 2) . '/facturascripts.ini');

        $this->assertIsString($manifest);
        $this->assertStringContainsString('name = BeplyPluginTemplate', $manifest);
        $this->assertMatchesRegularExpression('/^version\s*=\s*\d+\.\d+$/m', $manifest);
    }

    public function testInitClassExists(): void
    {
        $init = file_get_contents(dirname(__DIR__, 2) . '/Init.php');

        $this->assertIsString($init);
        $this->assertStringContainsString('final class Init extends InitClass', $init);
        $this->assertStringContainsString('public function uninstall(): void', $init);
    }
}

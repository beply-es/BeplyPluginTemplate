<?php

declare(strict_types=1);

namespace FacturaScripts\Test\Plugins;

use PHPUnit\Framework\TestCase;

final class TemplateManifestTest extends TestCase
{
    public function testManifestKeepsSingleDecimalVersionAndRuntimeRequirements(): void
    {
        $manifest = file_get_contents(dirname(__DIR__) . '/facturascripts.ini');

        $this->assertIsString($manifest);
        $this->assertStringContainsString('name = BeplyPluginTemplate', $manifest);
        $this->assertMatchesRegularExpression('/^version\s*=\s*\d+\.\d+$/m', $manifest);
        $this->assertStringContainsString('min_version = 2025.71', $manifest);
        $this->assertStringContainsString('min_php = 8.2', $manifest);
    }
}


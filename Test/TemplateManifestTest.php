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
        $this->assertStringContainsString('min_version = 2026.2', $manifest);
        $this->assertStringContainsString('min_php = 8.4', $manifest);
    }

    public function testInitImplementsFacturaScriptsRuntimeContract(): void
    {
        $init = file_get_contents(dirname(__DIR__) . '/Init.php');

        $this->assertIsString($init);
        $this->assertStringContainsString('public function init(): void', $init);
        $this->assertStringContainsString('public function update(): void', $init);
        $this->assertStringContainsString('public function uninstall(): void', $init);
    }

    public function testTemplateShipsBeplyWorkflowContracts(): void
    {
        $root = dirname(__DIR__);

        foreach ([
            '/.beply/facturascripts-matrix.json',
            '/.beply/template-lock.json',
            '/.beply/template-sync.json',
            '/Tools/manifest.json',
            '/Tools/README.md',
            '/docs/CODEX-WORKFLOW.md',
            '/docs/TESTING.md',
            '/docs/DOCUMENTATION-GOVERNANCE.md',
            '/docs/FACTURASCRIPTS-STYLE-GUIDE.md',
            '/docs/ROM-COPY-CLEANROOM.md',
            '/docs/TEMPLATE-SYNC.md',
            '/docs/AI-TOOLS-MANIFEST.md',
            '/docs/testing/ui-coverage-matrix.json',
            '/docs/docs-sync/impact-map.json',
            '/docs/docs-sync/published-pages.json',
            '/scripts/template/sync-template.mjs',
        ] as $relativePath) {
            $this->assertFileExists($root . $relativePath, $relativePath);
        }
    }
}

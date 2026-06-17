<?php

declare(strict_types=1);

namespace FacturaScripts\Plugins\BeplyPluginTemplate\Lib;

use FacturaScripts\Plugins\BeplyAgents\Lib\Contracts\BeplyAgentToolProviderInterface;

final class BeplyAgentToolProvider implements BeplyAgentToolProviderInterface
{
    public static function pluginName(): string
    {
        return 'BeplyPluginTemplate';
    }

    public static function listAvailableTools(): array
    {
        return TemplateToolsManifest::availableTools();
    }

    public static function listAvailableToolPacks(): array
    {
        return TemplateToolsManifest::availableToolPacks();
    }

    public static function listRuntimeToolDefinitions(): array
    {
        return TemplateToolsManifest::runtimeToolDefinitions();
    }

    /**
     * @param array<string, mixed> $arguments
     * @param array<string, mixed> $context
     * @return array<string, mixed>
     */
    public static function executeRuntimeTool(string $toolName, array $arguments, array $context = []): array
    {
        return TemplateToolExecutor::executeRuntimeTool($toolName, $arguments, $context);
    }
}

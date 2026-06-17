<?php

declare(strict_types=1);

namespace FacturaScripts\Plugins\BeplyPluginTemplate\Lib;

final class TemplateToolExecutor
{
    /**
     * @param array<string, mixed> $arguments
     * @param array<string, mixed> $context
     * @return array<string, mixed>
     */
    public static function executeRuntimeTool(string $toolName, array $arguments, array $context = []): array
    {
        return [
            'success' => false,
            'status' => 'rejected',
            'tool_name' => strtolower(trim($toolName)),
            'error' => 'template-tool-not-implemented',
            'mutations_committed' => false,
            'human_review_required' => true,
        ];
    }
}

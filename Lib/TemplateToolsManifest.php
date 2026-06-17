<?php

declare(strict_types=1);

namespace FacturaScripts\Plugins\BeplyPluginTemplate\Lib;

final class TemplateToolsManifest
{
    /**
     * @return array<string, array<string, mixed>>
     */
    public static function availableTools(): array
    {
        $catalog = [];
        foreach (self::manifestList('tools') as $tool) {
            if (($tool['enabled'] ?? true) === false || empty($tool['id'])) {
                continue;
            }

            $catalog[(string)$tool['id']] = [
                'name' => (string)($tool['name'] ?? $tool['id']),
                'description' => (string)($tool['description'] ?? ''),
                'icon' => (string)($tool['icon'] ?? 'fas fa-plug'),
                'category' => (string)($tool['category'] ?? 'General'),
                'x-beply-manifest' => self::manifestSummary(),
            ];
        }

        return $catalog;
    }

    /**
     * @return array<string, array<string, mixed>>
     */
    public static function availableToolPacks(): array
    {
        $catalog = [];
        foreach (self::manifestList('toolPacks') as $pack) {
            if (($pack['enabled'] ?? true) === false || empty($pack['id'])) {
                continue;
            }

            $catalog[(string)$pack['id']] = [
                'name' => (string)($pack['name'] ?? $pack['id']),
                'description' => (string)($pack['description'] ?? ''),
                'tools' => is_array($pack['tools'] ?? null) ? $pack['tools'] : [],
                'icon' => (string)($pack['icon'] ?? 'fas fa-layer-group'),
                'category' => (string)($pack['category'] ?? 'General'),
                'x-beply-manifest' => self::manifestSummary(),
            ];
        }

        return $catalog;
    }

    /**
     * @return array<string, array<int, array<string, mixed>>>
     */
    public static function runtimeToolDefinitions(): array
    {
        $grouped = [];
        foreach (self::manifestList('runtimeTools') as $definition) {
            if (($definition['enabled'] ?? true) === false || empty($definition['toolType']) || empty($definition['name'])) {
                continue;
            }

            $grouped[(string)$definition['toolType']][] = [
                'type' => 'function',
                'name' => (string)$definition['name'],
                'description' => (string)($definition['description'] ?? ''),
                'parameters' => is_array($definition['parameters'] ?? null)
                    ? $definition['parameters']
                    : ['type' => 'object', 'properties' => new \stdClass(), 'additionalProperties' => false],
                'x-beply-tool-policy' => [
                    'execution_mode' => (string)($definition['executionMode'] ?? 'review_required'),
                    'mutation_risk' => (string)($definition['mutationRisk'] ?? 'none'),
                    'human_review_required' => (bool)($definition['humanReviewRequired'] ?? true),
                    'executor' => (string)($definition['executor'] ?? TemplateToolExecutor::class . '::executeRuntimeTool'),
                ],
            ];
        }

        return $grouped;
    }

    /**
     * @return array<string, mixed>
     */
    private static function manifest(): array
    {
        $path = dirname(__DIR__) . '/Tools/manifest.json';
        $contents = is_file($path) ? file_get_contents($path) : false;
        $data = is_string($contents) ? json_decode($contents, true) : null;

        return is_array($data) ? $data : [];
    }

    /**
     * @return array<int, array<string, mixed>>
     */
    private static function manifestList(string $key): array
    {
        $items = self::manifest()[$key] ?? [];
        return is_array($items) ? array_values(array_filter($items, 'is_array')) : [];
    }

    /**
     * @return array<string, mixed>
     */
    private static function manifestSummary(): array
    {
        $manifest = self::manifest();

        return [
            'schemaVersion' => (string)($manifest['schemaVersion'] ?? ''),
            'manifestVersion' => (string)($manifest['manifestVersion'] ?? ''),
            'plugin' => $manifest['plugin'] ?? ['name' => 'BeplyPluginTemplate'],
            'executionPolicy' => $manifest['executionPolicy'] ?? [],
        ];
    }
}

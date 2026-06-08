<?php

declare(strict_types=1);

if ($argc < 2) {
    fwrite(STDERR, "Usage: php php84-compat-scan.php <plugin-root>\n");
    exit(2);
}

$root = realpath($argv[1]);
if ($root === false || !is_dir($root)) {
    fwrite(STDERR, "Invalid plugin root: {$argv[1]}\n");
    exit(2);
}

$removedFunctions = array_fill_keys([
    'create_function',
    'each',
    'gmstrftime',
    'money_format',
    'mysql_connect',
    'mysql_error',
    'mysql_query',
    'strftime',
    'strptime',
    'utf8_decode',
    'utf8_encode',
], true);
$csvRequiredArgs = [
    'fgetcsv' => 5,
    'fputcsv' => 5,
    'str_getcsv' => 4,
];

$files = [];
$iterator = new RecursiveIteratorIterator(
    new RecursiveDirectoryIterator($root, FilesystemIterator::SKIP_DOTS)
);

foreach ($iterator as $file) {
    if (!$file->isFile() || strtolower($file->getExtension()) !== 'php') {
        continue;
    }

    $path = $file->getPathname();
    $relative = str_replace($root . DIRECTORY_SEPARATOR, '', $path);
    $relative = str_replace(DIRECTORY_SEPARATOR, '/', $relative);

    if (isExcluded($relative)) {
        continue;
    }

    $files[] = [$path, $relative];
}

$issues = [];

foreach ($files as [$path, $relative]) {
    $command = PHP_BINARY . ' -d error_reporting=E_ALL -d display_errors=1 -l ' . escapeshellarg($path) . ' 2>&1';
    exec($command, $output, $exitCode);
    $lintOutput = trim(implode("\n", $output));

    if ($exitCode !== 0) {
        $issues[] = [$relative, 0, 'lint_error', $lintOutput];
        continue;
    }

    if (preg_match('/(^|\n)(PHP )?Deprecated:/i', $lintOutput)) {
        $issues[] = [$relative, 0, 'php84_deprecation', $lintOutput];
    }

    scanTokens($path, $relative, $issues, $removedFunctions, $csvRequiredArgs);
}

if ($issues !== []) {
    foreach ($issues as [$file, $line, $kind, $detail]) {
        $location = $line > 0 ? "{$file}:{$line}" : $file;
        echo "{$location}\t{$kind}\t{$detail}\n";
    }
    exit(1);
}

echo 'PHP 8.4 compatibility scan passed for ' . count($files) . " PHP files.\n";

function isExcluded(string $relative): bool
{
    if (preg_match('#(^|/)(\.git|\.github|node_modules|Test|Tests|tests|docs|coverage-html|playwright-report|test-results)(/|$)#', $relative)) {
        return true;
    }

    return (bool) preg_match('#(^|/)vendor/.*/(\.github|test|tests|Test|Tests|doc|docs)(/|$)#', $relative);
}

function scanTokens(string $path, string $relative, array &$issues, array $removedFunctions, array $csvRequiredArgs): void
{
    $code = file_get_contents($path);
    if ($code === false) {
        $issues[] = [$relative, 0, 'read_error', 'Unable to read file'];
        return;
    }

    $tokens = token_get_all($code);
    $count = count($tokens);

    for ($i = 0; $i < $count; $i++) {
        $token = $tokens[$i];
        if (!is_array($token) || $token[0] !== T_STRING) {
            continue;
        }

        $name = strtolower($token[1]);
        $line = $token[2];
        $previous = previousSignificant($tokens, $i - 1);

        if (is_array($previous) && in_array($previous[0], [T_FUNCTION, T_CLASS, T_INTERFACE, T_TRAIT], true)) {
            continue;
        }

        $next = nextSignificant($tokens, $i + 1);
        if ($next !== '(') {
            continue;
        }

        $openIndex = nextSignificantIndex($tokens, $i + 1);
        if ($openIndex === null) {
            continue;
        }

        if (is_array($previous) && in_array($previous[0], [T_OBJECT_OPERATOR, T_DOUBLE_COLON], true)) {
            if ($name !== 'setcsvcontrol') {
                continue;
            }

            [$argumentCount, $hasEscapeNamed] = countCallArgs($tokens, $openIndex);
            if (!$hasEscapeNamed && $argumentCount < 3) {
                $issues[] = [$relative, $line, 'csv_escape_missing', 'setCsvControl_args_' . $argumentCount];
            }
            continue;
        }

        if (isset($removedFunctions[$name]) || str_starts_with($name, 'mcrypt_') || str_starts_with($name, 'mysql_')) {
            $issues[] = [$relative, $line, 'removed_or_deprecated_api', $name];
            continue;
        }

        if (!isset($csvRequiredArgs[$name])) {
            continue;
        }

        [$argumentCount, $hasEscapeNamed] = countCallArgs($tokens, $openIndex);
        if (!$hasEscapeNamed && $argumentCount < $csvRequiredArgs[$name]) {
            $issues[] = [$relative, $line, 'csv_escape_missing', $name . '_args_' . $argumentCount];
        }
    }
}

function previousSignificant(array $tokens, int $index): mixed
{
    for ($i = $index; $i >= 0; $i--) {
        $token = $tokens[$i];
        if (is_array($token) && in_array($token[0], [T_WHITESPACE, T_COMMENT, T_DOC_COMMENT], true)) {
            continue;
        }
        return $token;
    }
    return null;
}

function nextSignificant(array $tokens, int $index): mixed
{
    $nextIndex = nextSignificantIndex($tokens, $index);
    return $nextIndex === null ? null : $tokens[$nextIndex];
}

function nextSignificantIndex(array $tokens, int $index): ?int
{
    $count = count($tokens);
    for ($i = $index; $i < $count; $i++) {
        $token = $tokens[$i];
        if (is_array($token) && in_array($token[0], [T_WHITESPACE, T_COMMENT, T_DOC_COMMENT], true)) {
            continue;
        }
        return $i;
    }
    return null;
}

function countCallArgs(array $tokens, int $openIndex): array
{
    $depth = 0;
    $commas = 0;
    $hasAny = false;
    $hasEscapeNamed = false;
    $count = count($tokens);

    for ($i = $openIndex; $i < $count; $i++) {
        $token = $tokens[$i];

        if ($token === '(' || $token === '[' || $token === '{') {
            $depth++;
            continue;
        }

        if ($token === ')' || $token === ']' || $token === '}') {
            $depth--;
            if ($depth === 0) {
                return [$hasAny ? $commas + 1 : 0, $hasEscapeNamed];
            }
            continue;
        }

        if ($depth !== 1) {
            continue;
        }

        if (is_array($token) && !in_array($token[0], [T_WHITESPACE, T_COMMENT, T_DOC_COMMENT], true)) {
            $hasAny = true;
            if ($token[0] === T_STRING && strtolower($token[1]) === 'escape') {
                $next = nextSignificant($tokens, $i + 1);
                if ($next === ':') {
                    $hasEscapeNamed = true;
                }
            }
        } elseif (!is_array($token) && !in_array($token, [','], true)) {
            $hasAny = true;
        }

        if ($token === ',') {
            $commas++;
        }
    }

    return [$hasAny ? $commas + 1 : 0, $hasEscapeNamed];
}

# Сборка NowPlayingWidget.exe и готового архива для друзей.
#
#   .\build.ps1                 собрать exe и zip
#   .\build.ps1 -SkipBuild      только пересобрать zip из dist\NowPlayingWidget.exe
#   .\build.ps1 -SkipZip        только собрать exe
#
# Если Python 3.13 установлен в нестандартное место, передайте путь:
#   .\build.ps1 -Python "D:\Python313\python.exe"

#Requires -Version 5.1
param(
    [string]$Python = "",
    [switch]$SkipBuild,
    [switch]$SkipZip
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $Root

function Resolve-Python {
    param([string]$Explicit)
    if ($Explicit) {
        if (-not (Test-Path $Explicit)) {
            throw "Не найден Python: $Explicit"
        }
        return (Resolve-Path $Explicit).Path
    }
    $candidates = @(
        (Join-Path $env:LOCALAPPDATA "Programs\Python\Python313\python.exe"),
        (Join-Path $env:ProgramFiles "Python313\python.exe")
    )
    foreach ($candidate in $candidates) {
        if (Test-Path $candidate) { return $candidate }
    }
    $command = Get-Command python -ErrorAction SilentlyContinue
    if ($command) { return $command.Source }
    throw "Python не найден. Укажите путь через -Python."
}

$pythonExe = Resolve-Python $Python
Write-Host "Python: $pythonExe"

$version = (& $pythonExe -c "import sys; sys.path.insert(0, r'$Root'); from nowplaying import __version__; print(__version__)").Trim()
if (-not $version) { throw "Не удалось прочитать версию из nowplaying\__init__.py" }
Write-Host "Версия: $version"

foreach ($asset in @("assets\icon.ico", "assets\icon.png", "assets\vinyl-record.png")) {
    if (-not (Test-Path $asset)) { throw "Не найден обязательный файл: $asset" }
}

if (-not $SkipBuild) {
    Write-Host "Проверяю PyInstaller…"
    & $pythonExe -c "import PyInstaller" 2>$null
    if ($LASTEXITCODE -ne 0) {
        throw "PyInstaller не установлен. Выполните: & `"$pythonExe`" -m pip install -r requirements-dev.txt"
    }

    Write-Host "Собираю exe (это может занять минуту)…"
    & $pythonExe -m PyInstaller --noconfirm --clean NowPlayingWidget.spec
    if ($LASTEXITCODE -ne 0) { throw "PyInstaller завершился с ошибкой." }
}

$exePath = Join-Path $Root "dist\NowPlayingWidget.exe"
if (-not (Test-Path $exePath)) {
    throw "Не найден $exePath. Сначала выполните сборку без -SkipBuild."
}

$sizeMb = [math]::Round((Get-Item $exePath).Length / 1MB, 1)
Write-Host "Готово: $exePath ($sizeMb МБ)"

if ($SkipZip) {
    Write-Host "Zip пропущен (-SkipZip)."
    exit 0
}

$releaseDir = Join-Path $Root "release"
$stageDir = Join-Path $releaseDir "NowPlayingWidget"
if (Test-Path $stageDir) { Remove-Item $stageDir -Recurse -Force }
New-Item -ItemType Directory -Path $stageDir -Force | Out-Null

Copy-Item $exePath (Join-Path $stageDir "NowPlayingWidget.exe")
Copy-Item (Join-Path $Root "README.md") (Join-Path $stageDir "README.md")

$quickStart = @"
Сейчас играет — виджет для Windows
==================================

1. Распакуйте архив в любую папку (например, на рабочий стол).
2. Запустите NowPlayingWidget.exe.
3. Включите музыку в Spotify, браузере, Яндекс.Музыке или другом плеере.
4. Иконка виджета появится в системном трее рядом с часами.
   Щёлкните по ней или нажмите Ctrl+Alt+Shift+M, чтобы показать облачко.
5. Все настройки — в меню иконки: «Настройки…». JSON трогать не нужно.

Windows может показать предупреждение SmartScreen, потому что файл не подписан.
Нажмите «Подробнее» → «Выполнить в любом случае».

OBS: добавьте источник «Захват окна» (Window Capture) и выберите окно
«Now Playing Widget». Захват экрана (Display Capture) не увидит облачко
во время полноэкранной игры — это нормально.
"@
Set-Content -Path (Join-Path $stageDir "КАК ЗАПУСТИТЬ.txt") -Value $quickStart -Encoding UTF8

$zipPath = Join-Path $releaseDir "NowPlayingWidget-$version-win64.zip"
if (Test-Path $zipPath) { Remove-Item $zipPath -Force }
Compress-Archive -Path (Join-Path $stageDir "*") -DestinationPath $zipPath -CompressionLevel Optimal

Write-Host "Архив: $zipPath"
Write-Host "Папка для проверки: $stageDir"

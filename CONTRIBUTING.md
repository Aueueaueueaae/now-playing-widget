# Участие в разработке

Спасибо за интерес к проекту.

## Требования

- Windows 10/11 x64;
- Python 3.13 x64;
- Git.

## Запуск из исходников

```powershell
git clone https://github.com/Aueueaueueaae/now-playing-widget.git
cd now-playing-widget
python -m pip install -r requirements.txt
pythonw main.py
```

Запускайте через `pythonw.exe`, чтобы не появлялось окно консоли.

## Сборка exe

```powershell
python -m pip install -r requirements-dev.txt
.\build.ps1
```

Готовый архив появится в `release\`.

## Ручные визуальные тесты

В папке `tools\` есть вспомогательные скрипты:

- `settings_dialog_test.py` — скриншоты окна настроек;
- `visual_test.py` — облачко на ярком фоне с обложкой и винилом;
- `game_mode_test.py` — переход в игровой режим;
- `fullscreen_probe.py` — проверка определения полноэкранного окна.

Они не входят в exe и создают файлы в `tools\out\` (папка исключена из Git).

## Стиль кода

- Python 3.13, `from __future__ import annotations`;
- комментарии и пользовательские строки — по-русски;
- не добавляйте сетевые запросы, телеметрию и внешние зависимости без
  обсуждения в issue.

## Pull request

1. Форкните репозиторий и создайте ветку.
2. Убедитесь, что `python -m compileall nowplaying main.py` проходит.
3. Опишите изменение и приложите скриншот, если менялся внешний вид.

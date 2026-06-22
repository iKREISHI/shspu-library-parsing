# SHSPU VKR Downloader

Скрипт скачивает постраничные изображения ВКР из электронной библиотеки SHSPU
и собирает PDF-файлы. На каждую найденную ВКР создается отдельный PDF.

## Установка

```bash
uv sync
uv run playwright install chromium
```

## Запуск

Передавайте ссылку на выдачу в кавычках. Это важно: в ссылках ИРБИС есть символы
`&`, а без кавычек shell обрежет команду.

```bash
uv run python collect_shspu_vkr.py "https://irbis.shspu.ru/cgi-bin/irbis64r_plus/cgiirbis_64_ft.exe?..."
```

Указать папку для сохранения PDF:

```bash
uv run python collect_shspu_vkr.py "https://irbis.shspu.ru/cgi-bin/irbis64r_plus/cgiirbis_64_ft.exe?..." \
  --output-dir output/pdf/my_vkr
```

## Пример

```bash
uv run python collect_shspu_vkr.py "https://irbis.shspu.ru/cgi-bin/irbis64r_plus/cgiirbis_64_ft.exe?LNG=&Z21ID=13151910151016115135330&I21DBN=VKR1_FULLTEXT&P21DBN=VKR1&S21STN=1&S21REF=10&S21FMT=briefHTML_ft&C21COM=S&S21CNR=5&S21P01=0&S21P02=1&S21P03=A=&USES21ALL=1&S21STR=%D0%91%D0%B5%D0%BB%D1%8C%D0%BA%D0%BE%D0%B2%2C%20%D0%94%D0%B5%D0%BD%D0%B8%D1%81%20%D0%9C%D0%B8%D1%85%D0%B0%D0%B9%D0%BB%D0%BE%D0%B2%D0%B8%D1%87" \
  --output-dir output/pdf/belkov
```

## Параметры

```text
url                         Ссылка на выдачу SHSPU. Можно передать позиционно.
--url URL                   То же самое, но именованным параметром.
--output-dir PATH           Папка для отдельных PDF. По умолчанию output/pdf/shspu_vkr.
--images-dir PATH           Папка для скачанных изображений страниц.
                            По умолчанию OUTPUT_DIR/_images.
--combined-output PATH      Дополнительно собрать один общий PDF со всеми ВКР.
--fallback-html PATH        Использовать локально сохраненный HTML выдачи,
                            если сайт не открылся через Playwright.
--no-click                  Не нажимать кнопки просмотра полного текста.
```

## Что создается

По умолчанию результат выглядит так:

```text
output/pdf/shspu_vkr/
  01_mfn_4303_2024vkr_126f.pdf
  02_mfn_4304_2024vkr_127f.pdf
  _images/
    01_mfn_4303_2024vkr_126f.pdf/
      page_0001.jpg
      page_0002.jpg
```

Если скачать прервали, повторный запуск переиспользует уже скачанные изображения.

## Локальный HTML

Файл `search.html` не нужен для обычной работы. Он может пригодиться только как
fallback:

```bash
uv run python collect_shspu_vkr.py "https://irbis.shspu.ru/..." --fallback-html search.html
```

Без `--fallback-html` скрипт использует только сайт и честно сообщает об ошибке,
если ссылка недоступна или передана неправильно.

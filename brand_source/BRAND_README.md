# Иконка интеграции — инструкция

В этом релизе добавлена иконка/логотип зарядного устройства NBPower.

## Как это работает

Home Assistant берёт иконки интеграций из двух мест:

1. **Локальная папка `brand/`** (HA 2026.3 и новее) — иконки уже лежат в
   `custom_components/nbpower_charger/../brand/`... — нет, см. ниже.
2. **Репозиторий [home-assistant/brands](https://github.com/home-assistant/brands)**
   (работает на всех версиях) — нужно отправить PR.

## Вариант 1 — локальные иконки (HA ≥ 2026.3)

Начиная с HA 2026.3, можно положить иконки прямо в интеграцию.
Папка `brand/` в корне репозитория содержит:
- `icon.png` (256×256)
- `icon@2x.png` (512×512)
- `logo.png` (512×182)
- `logo@2x.png` (1024×364)

HA автоматически их подхватит после установки/обновления и перезапуска.
Локальные иконки имеют приоритет над CDN.

> ВАЖНО: на HA 2026.3+ папка `brand/` должна лежать **внутри**
> `custom_components/nbpower_charger/brand/`. Скрипт сборки релиза кладёт её туда.

## Вариант 2 — отправить в home-assistant/brands (для всех версий)

Чтобы иконка работала у всех пользователей (включая HA < 2026.3):

1. Форкни https://github.com/home-assistant/brands
2. Скопируй папку `brands_submission/custom_integrations/nbpower_charger/`
   в `custom_integrations/nbpower_charger/` форка
3. Создай Pull Request

Требования к изображениям (уже соблюдены):
- `icon.png` — 256×256, квадрат, обрезанный по краям, прозрачный фон
- `icon@2x.png` — 512×512
- `logo.png` — длинная сторона ≤ 512
- `logo@2x.png` — длинная сторона ≤ 1024
- PNG с прозрачностью, оптимизированы

После мержа PR иконка появится у всех в течение 1-7 дней (CDN-кэш).

## Исходники

SVG-исходники иконки и логотипа лежат в `brand_source/` —
можешь редактировать их и перегенерировать PNG:

```bash
pip install cairosvg
python3 -c "import cairosvg; cairosvg.svg2png(url='brand_source/icon.svg', write_to='brand/icon.png', output_width=256, output_height=256)"
```

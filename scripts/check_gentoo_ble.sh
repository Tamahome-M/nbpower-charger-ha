#!/bin/bash
# NBPower BLE — проверка окружения на Gentoo Linux
# Запусти: bash check_gentoo_ble.sh

echo "=== Проверка окружения для NBPower BLE на Gentoo ==="
echo ""

OK=0
WARN=0
ERR=0

ok()   { echo "  ✅  $*"; ((OK++)); }
warn() { echo "  ⚠️   $*"; ((WARN++)); }
err()  { echo "  ❌  $*"; ((ERR++)); }

# ── BlueZ ──────────────────────────────────────────────────────────────────────
echo "── BlueZ ───────────────────────────────────────────────"
if command -v bluetoothctl &>/dev/null; then
    VER=$(bluetoothctl --version 2>/dev/null | awk '{print $2}')
    ok "bluetoothctl v${VER:-?}"
    # Нужен BlueZ >= 5.43 для BLE notify
    MAJOR=${VER%%.*}
    if [ -n "$MAJOR" ] && [ "$MAJOR" -ge 5 ]; then
        ok "Версия BlueZ подходит для BLE (>= 5.x)"
    else
        warn "Желательно BlueZ >= 5.43 для надёжной работы BLE notify"
    fi
else
    err "bluetoothctl не найден"
    echo "       → emerge net-wireless/bluez"
    echo "         В /etc/portage/package.use: net-wireless/bluez experimental"
fi

echo ""
echo "── Служба Bluetooth ────────────────────────────────────"
# OpenRC (Gentoo по умолчанию)
if command -v rc-service &>/dev/null; then
    if rc-service bluetooth status 2>/dev/null | grep -q "started"; then
        ok "bluetooth (OpenRC) запущен"
    else
        err "bluetooth (OpenRC) не запущен"
        echo "       → rc-service bluetooth start"
        echo "       → rc-update add bluetooth default"
    fi
elif systemctl is-active --quiet bluetooth 2>/dev/null; then
    ok "bluetooth.service (systemd) запущен"
else
    warn "Не удалось проверить статус службы bluetooth"
    echo "       OpenRC:  rc-service bluetooth start && rc-update add bluetooth default"
fi

echo ""
echo "── HCI адаптер ─────────────────────────────────────────"
if command -v hciconfig &>/dev/null; then
    HCI_OUT=$(hciconfig 2>/dev/null)
    if echo "$HCI_OUT" | grep -q "hci"; then
        ok "HCI адаптер найден:"
        echo "$HCI_OUT" | sed 's/^/         /'
        if echo "$HCI_OUT" | grep -q "UP"; then
            ok "Адаптер включён (UP)"
        else
            warn "Адаптер выключен (DOWN)"
            echo "       → hciconfig hci0 up"
        fi
    else
        err "HCI адаптер не найден (нет Bluetooth оборудования?)"
    fi
else
    # hciconfig убран из новых bluez, используем bluetoothctl
    if command -v bluetoothctl &>/dev/null; then
        BT_LIST=$(echo "list" | bluetoothctl 2>/dev/null | grep "Controller")
        if [ -n "$BT_LIST" ]; then
            ok "Адаптер найден через bluetoothctl:"
            echo "$BT_LIST" | sed 's/^/         /'
        else
            err "Адаптер не найден через bluetoothctl"
        fi
    fi
fi

echo ""
echo "── D-Bus ───────────────────────────────────────────────"
if command -v dbus-daemon &>/dev/null; then
    DBUS_VER=$(dbus-daemon --version 2>/dev/null | head -1 | awk '{print $NF}')
    ok "dbus-daemon ${DBUS_VER}"
else
    err "dbus не найден"
    echo "       → emerge sys-apps/dbus"
fi

# Проверим что D-Bus сессия работает
if [ -n "$DBUS_SESSION_BUS_ADDRESS" ]; then
    ok "DBUS_SESSION_BUS_ADDRESS установлен"
else
    warn "DBUS_SESSION_BUS_ADDRESS не установлен (норма если в tty, не в DE)"
fi

# Системный D-Bus (нужен для bluez)
if pgrep -x dbus-daemon &>/dev/null; then
    ok "dbus-daemon запущен"
else
    err "dbus-daemon не запущен"
    echo "       → rc-service dbus start && rc-update add dbus default"
fi

echo ""
echo "── Python ──────────────────────────────────────────────"
PY=$(python3 --version 2>/dev/null)
if [ -n "$PY" ]; then
    ok "$PY"
    # Проверим версию >= 3.10
    PY_VER=$(python3 -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
    PY_MAJOR=$(echo $PY_VER | cut -d. -f1)
    PY_MINOR=$(echo $PY_VER | cut -d. -f2)
    if [ "$PY_MAJOR" -ge 3 ] && [ "$PY_MINOR" -ge 10 ]; then
        ok "Python >= 3.10 — подходит для bleak"
    else
        warn "Python $PY_VER — желательно >= 3.10 для bleak"
        echo "       → emerge dev-lang/python:3.12"
    fi
else
    err "python3 не найден"
    echo "       → emerge dev-lang/python:3.12"
fi

echo ""
echo "── pip / venv ──────────────────────────────────────────"
if python3 -m pip --version &>/dev/null; then
    ok "pip доступен: $(python3 -m pip --version 2>/dev/null | awk '{print $1,$2}')"
else
    warn "pip недоступен"
    echo "       → emerge dev-python/pip"
    echo "         или: python3 -m ensurepip"
fi

echo ""
echo "── bleak ───────────────────────────────────────────────"
if python3 -c "import bleak; print(bleak.__version__)" 2>/dev/null | grep -q "[0-9]"; then
    BL_VER=$(python3 -c "import bleak; print(bleak.__version__)")
    ok "bleak v${BL_VER} установлен"
else
    err "bleak не установлен"
    echo "       → pip install --user bleak"
    echo "         или в venv: python3 -m venv ble-env && source ble-env/bin/activate && pip install bleak"
fi

echo ""
echo "── Группы пользователя ─────────────────────────────────"
echo "  Текущий пользователь: $(whoami)"
echo "  Группы: $(groups)"
if groups | grep -qE '\b(bluetooth)\b'; then
    ok "Пользователь в группе 'bluetooth'"
else
    err "Пользователь НЕ в группе 'bluetooth'"
    echo "       → usermod -aG bluetooth $(whoami)"
    echo "         Затем перелогиниться или: newgrp bluetooth"
fi

echo ""
echo "── USE-флаги Gentoo ────────────────────────────────────"
if command -v portageq &>/dev/null; then
    BT_USE=$(portageq envvar USE 2>/dev/null | tr ' ' '\n' | grep -i bluetooth)
    if [ -n "$BT_USE" ]; then
        ok "USE флаг 'bluetooth' активен"
    else
        warn "USE флаг 'bluetooth' не найден в USE"
        echo "       → /etc/portage/make.conf: USE=\"... bluetooth ...\""
    fi
fi

echo ""
echo "══════════════════════════════════════════════════════════"
echo "  ✅  OK: $OK   ⚠️  Предупреждений: $WARN   ❌ Ошибок: $ERR"
echo "══════════════════════════════════════════════════════════"

if [ "$ERR" -gt 0 ] || [ "$WARN" -gt 0 ]; then
    echo ""
    echo "📋 Быстрый рецепт установки на Gentoo:"
    echo ""
    echo "  # 1. Установить BlueZ"
    echo "  echo 'net-wireless/bluez experimental' >> /etc/portage/package.use/bluetooth"
    echo "  emerge net-wireless/bluez sys-apps/dbus"
    echo ""
    echo "  # 2. Запустить службы"
    echo "  rc-service dbus start && rc-update add dbus default"
    echo "  rc-service bluetooth start && rc-update add bluetooth default"
    echo ""
    echo "  # 3. Добавить пользователя в группу bluetooth"
    echo "  usermod -aG bluetooth \$USER"
    echo "  newgrp bluetooth   # применить без перелогина"
    echo ""
    echo "  # 4. Включить HCI адаптер"
    echo "  hciconfig hci0 up   # если нужно"
    echo ""
    echo "  # 5. Установить bleak (в virtualenv рекомендуется)"
    echo "  python3 -m venv ~/ble-env"
    echo "  source ~/ble-env/bin/activate"
    echo "  pip install bleak"
    echo ""
    echo "  # 6. Запустить скрипт"
    echo "  python3 nbpower_debug.py --scan"
fi

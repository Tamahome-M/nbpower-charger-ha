#!/usr/bin/env python3
"""
NBPower EV Charger — standalone BLE debug tool.

Run this on any machine with Bluetooth and Python 3.10+ to test
the connection and protocol WITHOUT Home Assistant.

Usage:
    pip install bleak
    python3 nbpower_debug.py --scan           # find nearby chargers
    python3 nbpower_debug.py --mac AA:BB:CC:DD:EE:FF
    python3 nbpower_debug.py --mac ... --start --amps 10
    python3 nbpower_debug.py --mac ... --stop
    python3 nbpower_debug.py --mac ... --raw 31 01  # send raw command bytes
"""
import asyncio
import argparse
import sys

try:
    from bleak import BleakClient, BleakScanner
except ImportError:
    print("ERROR: bleak not installed. Run: pip install bleak")
    sys.exit(1)


# ── Charge state labels ────────────────────────────────────────────────────────
CHARGE_STATES = {
    0: "Кабель не подключён",
    1: "Ожидание (машина не готова)",
    2: "По расписанию...",
    3: "Идёт зарядка ✅",
    4: "Пониженная мощность",
    5: "Ожидание охлаждения",
    255: "Обновление прошивки",
}

CMD_GET_VERSION  = 0x01
CMD_GET_METER    = 0x08
CMD_HEARTBEAT    = 0x31
CMD_START_CHARGE = 0x43
CMD_GET_TIME     = 0x45


class NBPowerDebug:
    def __init__(self, mac: str):
        self.mac = mac
        self.client = None
        self.service_uuid = None
        self.write_char_uuid = None
        self.notify_char_uuid = None
        self.read_char_uuid = None
        self.req_id = 0
        self.pending = {}
        self.device_version = 0
        self.use_polling = False
        self.can_write_no_response = False
        self._write_no_response = False
        self._last_write_time = 0

    async def connect(self):
        print(f"\n🔌 Подключаюсь к {self.mac}...")
        self.client = BleakClient(self.mac, timeout=15.0)
        await self.client.connect()

        print("\n📡 GATT сервисы:")
        # Detect FFE0 (notify mode) vs FFD0 (polling mode) — matches app logic exactly
        is_ffd0_service = False
        is_ffe0_service = False
        candidate_service = None

        for svc in self.client.services:
            uuid_upper = svc.uuid.upper()
            print(f"  Service: {svc.uuid}")
            for char in svc.characteristics:
                props = ",".join(char.properties)
                print(f"    Char:  {char.uuid}  [{props}]")

            # Match FFE0 service (notify mode)
            if "FFE0" in uuid_upper and not candidate_service:
                candidate_service = svc.uuid
                is_ffe0_service = True
                for char in svc.characteristics:
                    if "FFE1" in char.uuid.upper():
                        self.write_char_uuid = char.uuid
                        self.notify_char_uuid = char.uuid  # FFE1 has both write and notify

            # Match FFD0 service (polling mode)
            elif "FFD0" in uuid_upper and not candidate_service:
                candidate_service = svc.uuid
                is_ffd0_service = True
                self.use_polling = True   # ← KEY: FFD0 = polling mode
                for char in svc.characteristics:
                    char_upper = char.uuid.upper()
                    if "FFD1" in char_upper:
                        self.write_char_uuid = char.uuid  # write + read on the same char
                    elif "FFD2" in char_upper:
                        self.notify_char_uuid = char.uuid  # exists but app doesn't use it
                    elif "FFD3" in char_upper:
                        self.read_char_uuid = char.uuid

        if not self.write_char_uuid:
            raise RuntimeError("Не найдена характеристика для записи!")

        self.service_uuid = candidate_service

        # Detect canWriteNoRsp
        for svc in self.client.services:
            if svc.uuid == self.service_uuid:
                for char in svc.characteristics:
                    if char.uuid == self.write_char_uuid:
                        self.can_write_no_response = "write-without-response" in char.properties
                        break

        # Per app logic: writeType = "writeNoResponse" if (noNotify || canWriteNoRsp)
        # noNotify is true for FFD0
        self._write_no_response = self.use_polling or self.can_write_no_response

        mode = "FFD0 (polling)" if is_ffd0_service else ("FFE0 (notify)" if is_ffe0_service else "?")
        print(f"\n✅ Используем режим: {mode}")
        print(f"   Service:        {self.service_uuid}")
        print(f"   Write char:     {self.write_char_uuid}")
        print(f"   Notify char:    {self.notify_char_uuid or '—'}")
        print(f"   Write type:     {'writeNoResponse' if self._write_no_response else 'write+ACK'}")

        # FFE0: subscribe to notify on FFE1
        # FFD0: do NOT subscribe — poll FFD1 instead
        if is_ffe0_service and self.notify_char_uuid:
            try:
                await self.client.start_notify(self.notify_char_uuid, self._on_notify)
                print(f"   Подписка на notify: ОК\n")
            except Exception as e:
                print(f"   ⚠️  Notify не работает: {e}")
                print(f"   Переключаюсь на polling\n")
                self.use_polling = True
        else:
            print(f"   Polling режим (читаем FFD1 после каждого write)\n")

    def _on_notify(self, sender, data: bytearray):
        if len(data) < 2:
            return
        key = (data[0], data[1])
        f = self.pending.get(key)
        if f and not f.done():
            f.set_result(bytes(data[2:]))
        print(f"  ← RECV [{data[0]:02X} {data[1]:02X}] {data[2:].hex()}")

    def _next_id(self) -> int:
        self.req_id = (self.req_id + 1) % 256
        return self.req_id

    async def send(self, cmd: int, params=None, timeout=5.0) -> bytes:
        if params is None:
            params = []
        rid = self._next_id()
        packet = bytes([cmd, rid] + params)
        key = (cmd, rid)

        loop = asyncio.get_event_loop()
        f = loop.create_future()
        self.pending[key] = f

        # Per app logic: 20ms minimum between writes
        import time
        now_ms = time.time() * 1000
        elapsed = now_ms - self._last_write_time
        if elapsed < 20:
            await asyncio.sleep((20 - elapsed) / 1000)
        self._last_write_time = time.time() * 1000

        print(f"  → SEND [{cmd:02X} {rid:02X}] {bytes(params).hex()}  ({'noResp' if self._write_no_response else 'ack'})")
        await self.client.write_gatt_char(
            self.write_char_uuid,
            packet,
            response=not self._write_no_response,
        )

        # Polling mode: read from the SAME characteristic we wrote to (app reads from FFD1)
        if self.use_polling:
            await asyncio.sleep(0.02)   # 20ms delay matching app
            for attempt in range(15):
                try:
                    response = await self.client.read_gatt_char(self.write_char_uuid)
                    if len(response) >= 2 and response[0] == cmd and response[1] == rid:
                        print(f"  ← POLL [{response[0]:02X} {response[1]:02X}] {response[2:].hex()}")
                        if not f.done():
                            f.set_result(bytes(response[2:]))
                        break
                    elif attempt == 0 and len(response) >= 2:
                        # Show what we got even if not matching
                        print(f"  ← (other) [{response[0]:02X} {response[1]:02X}] {response[2:].hex()}")
                except Exception as e:
                    if attempt == 0:
                        print(f"  ⚠️  Polling read error: {e}")
                        break
                await asyncio.sleep(0.05)

        try:
            return await asyncio.wait_for(f, timeout=timeout)
        except asyncio.TimeoutError:
            print(f"  ⚠️  Таймаут ожидания ответа на CMD 0x{cmd:02X}")
            return b""
        finally:
            self.pending.pop(key, None)

    async def get_version(self):
        print("=== CMD 01: Версия прошивки ===")
        d = await self.send(CMD_GET_VERSION)
        if d:
            fw = d[0] if len(d) > 0 else "?"
            devnum = d[1] if len(d) > 1 else "?"
            meters = d[2] if len(d) > 2 else 1
            self.device_version = fw if isinstance(fw, int) else 0
            print(f"  Прошивка: v{fw}")
            print(f"  device_num: {devnum} ({'DC зарядное' if devnum == 30 else 'AC зарядное'})")
            print(f"  Количество метров: {meters}")
            print(f"  Raw: {d.hex()}")
        print()

    async def get_status(self):
        print("=== CMD 31: Статус / Heartbeat ===")
        d = await self.send(CMD_HEARTBEAT, [0x01])
        if d:
            state = d[0]
            print(f"  Состояние: {state} → {CHARGE_STATES.get(state, f'unknown({state})')}")
            if len(d) > 1:
                t1 = "н/д" if d[1] == 255 else f"{d[1]-40}°C"
                print(f"  Темп 1:   {t1}")
            if len(d) > 2:
                t3 = "н/д" if d[2] == 255 else f"{d[2]-40}°C"
                print(f"  Темп 3:   {t3}")
            if len(d) > 3:
                pwm = d[3]
                amps = pwm / 250 * 60
                print(f"  PWM:      {pwm} → {amps:.1f} A (установленный ток)")
            if len(d) > 4:
                t2 = "н/д" if d[4] == 255 else f"{d[4]-40}°C"
                print(f"  Темп 2:   {t2}")
            if len(d) > 8:
                print(f"  CP valid: {'Да' if d[8] == 1 else 'Нет'}")
            print(f"  Raw:      {d.hex()}")
        print()

    async def get_meter(self):
        print("=== CMD 08: Показания электросчётчика ===")
        d = await self.send(CMD_GET_METER)
        if d and len(d) >= 8:
            ver = self.device_version
            if ver > 27:
                v = (d[0] << 8 | d[1]) / 10
                a = (d[2] << 8 | d[3]) / 10
                p_active = d[4] << 8 | d[5]
                kwh = (d[6] << 8 | d[7]) / 100
            else:
                v = (d[1] << 8 | d[2]) / 10 if len(d) > 2 else 0
                a = (d[3] << 8 | d[4]) / 10 if len(d) > 4 else 0
                p_active = 0
                kwh = 0.0
            print(f"  Напряжение:       {v:.1f} В")
            print(f"  Ток:              {a:.1f} А")
            print(f"  Мощность (апп.): {v*a:.0f} Вт")
            if p_active:
                print(f"  Активная мощн.:  {p_active} Вт")
            print(f"  Энергия (сессия): {kwh:.3f} кВт·ч")
            print(f"  Raw:              {d.hex()}")
        elif d:
            print(f"  Raw (короткий): {d.hex()}")
        print()

    async def get_time(self):
        print("=== CMD 45: Время зарядки ===")
        d = await self.send(CMD_GET_TIME)
        if d and len(d) >= 5:
            is_charging = d[0] > 1
            configured = (d[1] << 8 | d[2]) if len(d) > 2 else 0
            elapsed = (d[3] << 8 | d[4]) if len(d) > 4 else 0
            remaining = (d[6] << 8 | d[7]) if len(d) > 7 else 0
            print(f"  Идёт зарядка: {'Да' if is_charging else 'Нет'}")
            if configured == 0xFFFF:
                print(f"  Таймер:       без ограничения")
            else:
                print(f"  Таймер:       {configured} мин")
            print(f"  Прошло:       {elapsed} мин")
            print(f"  Осталось:     {remaining} мин")
            print(f"  Raw:          {d.hex()}")
        print()

    async def get_auth_challenge(self) -> bytes:
        """CMD 66 — Get 5-byte challenge for start charge token computation."""
        print("=== CMD 66: Запрос auth challenge ===")
        d = await self.send(0x42)  # CMD 66 = 0x42
        if d and len(d) >= 5:
            print(f"  Challenge bytes: {d[:5].hex()}")
            return d[:5]
        print(f"  ⚠️  Не получили challenge, raw: {d.hex() if d else 'none'}")
        return None

    @staticmethod
    def compute_start_token(challenge: bytes, minutes_hi: int, minutes_lo: int) -> list[int]:
        """Compute the 6-byte token l[0..5] from auth challenge and duration.

        Reproduces exactly the formula from the app:
            l[0] = (f[0]<<8|f[1]) % (255 & (t+1|e)) & 255
            l[1] = (f[1]<<8|f[2]) % (255 & (t+2|e)) & 255
            l[2] = (f[2]<<8|f[3]) % (255 & (t+3|e)) & 255
            l[3] = (f[3]<<8|f[4]) % (255 & (t+4|e)) & 255
            l[4] = (f[4]<<8|t|e) % 34 & 255
            l[5] = (l[0]+l[1]+l[2]+l[3]+l[4]) % 35 & 255
        where t=minutes_hi, e=minutes_lo, f=challenge bytes.
        Division by zero is handled by falling back to 1.
        """
        f = challenge
        t = minutes_hi
        e = minutes_lo
        token = [0] * 6

        def safe_mod(a, b):
            return a % b if b != 0 else 0

        token[0] = safe_mod((f[0] << 8 | f[1]), 255 & (t + 1 | e)) & 0xFF
        token[1] = safe_mod((f[1] << 8 | f[2]), 255 & (t + 2 | e)) & 0xFF
        token[2] = safe_mod((f[2] << 8 | f[3]), 255 & (t + 3 | e)) & 0xFF
        token[3] = safe_mod((f[3] << 8 | f[4]), 255 & (t + 4 | e)) & 0xFF
        token[4] = ((f[4] << 8 | t | e) % 34) & 0xFF
        token[5] = (sum(token[:5]) % 35) & 0xFF
        return token

    async def verify_pwd_internal(self, pwd: str) -> bool:
        """Internal password verify (CMD 41) used before start/stop."""
        pwd_padded = (pwd[:6] + "000000")[:6]
        pwd_bytes = [ord(c) for c in pwd_padded]
        d = await self.send(0x29, pwd_bytes)
        return bool(d) and d[0] in (1, 255)

    async def start_charging(self, amps: float = 16.0, minutes: int = 0, pwd: str = "000000"):
        """Start charging with password verification + auth challenge."""
        print(f"=== CMD 67: Запуск зарядки ({amps} А, {'без ограничения' if not minutes else str(minutes)+' мин'}) ===")

        # Verify password first (CMD 41), as the app does
        print(f"  Проверка пароля '{pwd}'...")
        if not await self.verify_pwd_internal(pwd):
            print("  ❌ Пароль не принят — старт отменён")
            print()
            return
        print("  ✅ Пароль OK")

        pwm = max(13, round(250 * amps / 60))
        minutes_hi = (minutes >> 8) & 0xFF
        minutes_lo = minutes & 0xFF

        # Get token
        if minutes == 0:
            token = [1, 1, 1, 1, 1, 0]
            print(f"  Используем hardcoded токен: {bytes(token).hex()}")
        else:
            challenge = await self.get_auth_challenge()
            if challenge is None:
                print("  ❌ Не удалось получить challenge — отмена")
                return
            token = self.compute_start_token(challenge, minutes_hi, minutes_lo)
            print(f"  Вычислен токен: {bytes(token).hex()}")

        params = token + [
            minutes_hi, minutes_lo,
            0, 0,
            pwm,
            0, 0
        ]
        d = await self.send(0x43, params)
        if d:
            result = d[0] if d else 255
            mins_ret = (d[1] << 8 | d[2]) if len(d) > 2 else 0
            print(f"  Результат: {result}")
            print(f"  Минут выдано: {mins_ret}")
            if result < 2 and minutes != 0:
                print("  ❌ Зарядка НЕ запущена (ошибка)")
            else:
                print("  ✅ Зарядка запущена!")
            print(f"  Raw: {d.hex()}")
        print()

    async def stop_charging(self, pwd: str = "000000"):
        print("=== CMD 67: Остановка зарядки (minutes=0) ===")
        print(f"  Проверка пароля '{pwd}'...")
        if not await self.verify_pwd_internal(pwd):
            print("  ❌ Пароль не принят — остановка отменена")
            print()
            return
        print("  ✅ Пароль OK")
        params = [1, 1, 1, 1, 1, 0, 0, 0, 0, 0, 0, 0, 0]
        d = await self.send(0x43, params)
        if d:
            print(f"  ✅ Команда остановки отправлена. Raw: {d.hex()}")
        print()

    async def send_raw(self, raw_bytes):
        if not raw_bytes:
            return
        cmd = raw_bytes[0]
        params = raw_bytes[1:] if len(raw_bytes) > 1 else []
        print(f"=== RAW CMD 0x{cmd:02X} params={bytes(params).hex()} ===")
        d = await self.send(cmd, params)
        if d:
            print(f"  Response raw: {d.hex()}")
            print(f"  As ints: {list(d)}")
        print()

    async def test_password(self, pwd: str = "000000"):
        """CMD 41 — Verify the device PIN. Default is '000000'.

        BLE format: writeCommand(41, [6 ASCII password bytes])
        (no extra prefix byte — that's only for net/IMEI mode)

        Response byte[0]:
            1 / undefined / 255 = OK (password accepted)
            2 = locked (5 wrong attempts)
            0 / other = wrong password
        """
        print(f"=== CMD 41: Проверка пароля '{pwd}' ===")
        # setPasswordToCommand pads with '0' char (0x30) to 6 chars, ASCII-encoded
        pwd_padded = (pwd[:6] + "000000")[:6]
        pwd_bytes = [ord(c) for c in pwd_padded]
        params = pwd_bytes  # BLE: just the 6 ASCII bytes, NO leading [1]
        d = await self.send(0x29, params)
        if d is not None:
            result = d[0] if len(d) > 0 else None
            if result in (1, 255, None):
                print(f"  ✅ Пароль ПРИНЯТ (byte[0]={result})")
            elif result == 2:
                print(f"  🔒 Заблокировано (5 неверных попыток подряд)")
            else:
                print(f"  ❌ Пароль НЕ принят (byte[0]={result})")
            print(f"  Отправлено: {bytes(params).hex()} (ASCII '{pwd_padded}')")
            print(f"  Raw ответ:  {d.hex()}")
        print()

    async def get_config(self, pwd: str = "000000"):
        """CMD 47 — Read full charger configuration (requires PIN)."""
        print("=== CMD 47: Конфигурация устройства ===")
        # CMD 47 is protected — verify PIN first
        print(f"  Проверка пароля '{pwd}'...")
        if not await self.verify_pwd_internal(pwd):
            print("  ❌ Пароль не принят — чтение конфига невозможно")
            print()
            return None
        print("  ✅ Пароль OK")
        d = await self.send(0x2F)
        if d and len(d) >= 11:
            run_modes = {0: "Управление из приложения", 1: "Зарядка с вилки (авто)", 2: "Запуск ключом"}
            run_mode = d[4]
            print(f"  Режим работы: {run_mode} → {run_modes.get(run_mode, '?')}")
            print(f"  Авто-возобновление: {'Да' if (d[0]>>3)&1 else 'Нет'}")
            print(f"  Макс. ток: {min(d[10] or 32, 50)} А")
            print(f"  50/60 Гц: {'60' if (d[0]>>7)&1 else '50'} Гц")
            print(f"  Темп. понижения: {d[1]}°C")
            print(f"  Темп. паузы: {d[2]}°C")
            print(f"  Темп. восстановления: {d[3]}°C")
            plug_min = d[5]<<8 | d[6]
            print(f"  Plug-режим: {plug_min} мин, ток {self._pwm2amp(d[7])} А")
            print(f"  Raw: {d.hex()}")
        else:
            print(f"  Raw (короткий): {d.hex() if d else 'нет'}")
        print()
        return d

    @staticmethod
    def _pwm2amp(pwm):
        raw = pwm / 250 * 60
        frac = raw % 1
        frac = 0.5 if 0.3 <= frac <= 0.7 else (1.0 if frac > 0.7 else 0.0)
        return int(raw) + frac

    async def set_run_mode(self, mode: int, pwd: str = "000000"):
        """CMD 48 — Set run mode (0=mobile, 1=plug-start, 2=key)."""
        names = {0: "Управление из приложения", 1: "Зарядка с вилки (авто)", 2: "Запуск ключом"}
        print(f"=== CMD 48: Установка режима {mode} ({names.get(mode, '?')}) ===")
        print(f"  Проверка пароля '{pwd}'...")
        if not await self.verify_pwd_internal(pwd):
            print("  ❌ Пароль не принят — отмена")
            print()
            return
        print("  ✅ Пароль OK")

        # Read current config
        cfg = await self.send(0x2F)
        if not cfg or len(cfg) < 11:
            print("  ❌ Не удалось прочитать текущий конфиг")
            print()
            return
        config = bytearray(cfg)
        config[4] = mode
        if mode == 1:  # plug-start needs valid minutes/amps
            plug_min = config[5]<<8 | config[6]
            if plug_min < 1:
                config[5] = 600 >> 8
                config[6] = 600 & 0xFF
            if config[7] < 25:
                config[7] = round(250 * 6 / 60)
        d = await self.send(0x30, list(config))
        if d:
            if d[0] == 1:
                print(f"  ✅ Режим установлен! Raw: {d.hex()}")
            else:
                print(f"  ❌ Ошибка установки (byte[0]={d[0]}). Raw: {d.hex()}")
        print()

    async def disconnect(self):
        if self.client and self.client.is_connected:
            await self.client.disconnect()
            print("🔌 Отключено")


async def scan():
    print("🔍 Сканирую BLE устройства (10 сек)...\n")
    # return_adv=True возвращает dict {address: (BLEDevice, AdvertisementData)}
    # работает в bleak >= 0.17, совместимо с любыми новыми версиями
    discovered = await BleakScanner.discover(timeout=10.0, return_adv=True)
    if not discovered:
        print("Устройства не найдены.")
        return

    entries = []
    for address, (device, adv) in discovered.items():
        rssi = getattr(adv, "rssi", None) or -999
        name = device.name or getattr(adv, "local_name", None) or "(без имени)"
        entries.append((device, name, rssi))

    entries.sort(key=lambda x: x[2], reverse=True)

    print(f"Найдено {len(entries)} устройств:")
    print(f"{'MAC-адрес':<20} {'Имя':<32} {'RSSI'}")
    print("-" * 67)
    for device, name, rssi in entries:
        rssi_str = f"{rssi} dBm" if rssi != -999 else "?"
        marker = " ← возможно NBPower" if (
            "nbp" in name.lower() or "power" in name.lower() or "charge" in name.lower()
        ) else ""
        print(f"{device.address:<20} {name:<32} {rssi_str}{marker}")


async def main():
    parser = argparse.ArgumentParser(description="NBPower EV Charger BLE debug tool")
    parser.add_argument("--scan", action="store_true", help="Сканировать BLE устройства")
    parser.add_argument("--mac", type=str, help="MAC-адрес зарядного")
    parser.add_argument("--start", action="store_true", help="Запустить зарядку")
    parser.add_argument("--stop", action="store_true", help="Остановить зарядку")
    parser.add_argument("--amps", type=float, default=16.0, help="Максимальный ток (А), default=16")
    parser.add_argument("--minutes", type=int, default=0, help="Длительность (мин), 0=без ограничения")
    parser.add_argument("--raw", nargs="+", type=lambda x: int(x, 16),
                        metavar="HEX", help="Отправить сырую команду (hex байты, напр. --raw 31 01)")
    parser.add_argument("--status-only", action="store_true", help="Только статус (без метра и времени)")
    parser.add_argument("--test-pwd", type=str, metavar="PWD",
                        help="Проверить пароль через CMD 41 (по умолчанию 000000)")
    parser.add_argument("--pwd", type=str, default="000000", metavar="PWD",
                        help="Пароль устройства для старта/остановки (по умолчанию 000000)")
    parser.add_argument("--config", action="store_true",
                        help="Прочитать конфигурацию устройства (CMD 47)")
    parser.add_argument("--set-mode", type=int, choices=[0, 1, 2], metavar="MODE",
                        help="Установить режим: 0=приложение, 1=зарядка с вилки, 2=ключ")

    args = parser.parse_args()

    if args.scan:
        await scan()
        return

    if not args.mac:
        parser.print_help()
        print("\nПример: python3 nbpower_debug.py --mac AA:BB:CC:DD:EE:FF")
        return

    dbg = NBPowerDebug(args.mac)
    try:
        await dbg.connect()

        if args.raw:
            await dbg.send_raw(args.raw)
        elif args.test_pwd is not None:
            await dbg.test_password(args.test_pwd or "000000")
        elif args.config:
            await dbg.get_config(pwd=args.pwd)
        elif args.set_mode is not None:
            await dbg.set_run_mode(args.set_mode, pwd=args.pwd)
            await asyncio.sleep(1)
            await dbg.get_config(pwd=args.pwd)
        elif args.start:
            await dbg.start_charging(amps=args.amps, minutes=args.minutes, pwd=args.pwd)
            await asyncio.sleep(1)
            await dbg.get_status()
        elif args.stop:
            await dbg.stop_charging(pwd=args.pwd)
            await asyncio.sleep(1)
            await dbg.get_status()
        else:
            await dbg.get_version()
            await dbg.get_status()
            if not args.status_only:
                await dbg.get_meter()
                await dbg.get_time()

    except Exception as e:
        print(f"\n❌ Ошибка: {e}")
        import traceback
        traceback.print_exc()
    finally:
        await dbg.disconnect()


if __name__ == "__main__":
    asyncio.run(main())

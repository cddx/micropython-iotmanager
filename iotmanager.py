#!/usr/bin/python
# -*- coding: utf-8 -*-
import esp
import network
import machine
import ntptime
import uasyncio as asyncio
from ucollections import OrderedDict
from esp32 import Partition
from binascii import hexlify
import gc
import json
import time
import socket
import json
import re
import webrepl

try:
    import logging

    log = logging.getLogger(__name__)
    log.setLevel(logging.INFO)
except ImportError:
    print("Logging Module not available")

    class Log:
        def debug(self, *args):
            print(*args)

        def info(self, *args):
            print(*args)

        def error(self, *args):
            print(*args)

        def setLevel(self, level):
            pass

    log = Log()


class Config:
    WIFI_SSID = "01_WIFI_SSID"
    WIFI_PWD = "02_WIFI_PWD"
    WIFI_FALLBACK_SSID = "03_WIFI_FALLBACK_SSID"
    WIFI_FALLBACK_PWD = "04_WIFI_FALLBACK_PWD"
    IPV4_IP = "05_IPV4_IP"
    IPV4_NETMASK = "06_IPV4_NETMASK"
    IPV4_GATEWAY = "07_IPV4_GATEWAY"
    REPL_PWD = "10_REPL_PWD"
    GPIO_STATUS = "11_GPIO_STATUS"
    TZ_OFFSET = "12_TZ_OFFSET"
    OTA_URL = "13_OTA_URL"
    DEBUG = "15_DEBUG"


class Status:
    OFF = 0
    ON = 1
    SLOW = 1000
    FAST = 100


class IotManager:
    def __init__(self, title="IoT Manager", ota_url=None, use_css=True, debug=False):
        if debug:
            log.setLevel(10)

        log.info(f"Starting {title}")
        self.use_css = use_css
        self.title = title

        self.default_config = OrderedDict(
            {
                Config.WIFI_SSID: "",
                Config.WIFI_PWD: "",
                Config.WIFI_FALLBACK_SSID: "",
                Config.WIFI_FALLBACK_PWD: "",
                Config.IPV4_IP: "",
                Config.IPV4_NETMASK: "255.255.255.0",
                Config.IPV4_GATEWAY: "",
                Config.REPL_PWD: "repl",
                Config.GPIO_STATUS: "",
                Config.TZ_OFFSET: "+1",
                Config.DEBUG: "",
            }
        )

        self.data = OrderedDict()
        self.config = OrderedDict()
        self.tasks = []

        # Init config
        self.config_load()
        self.config_add(self.default_config)

        # Debug
        if not debug and self.config.get(Config.DEBUG, ""):
            log.setLevel(logging.DEBUG)

        # Init OTA
        self.ota = False
        if ota_url and self.ota_partiton_available():
            log.debug("Init OTA")

            self.ota_boot_successful()

            self.config_add({Config.OTA_URL: ota_url}, override=True)
            self.ota = True

            cur = Partition(Partition.RUNNING)
            nxt = cur.get_next_update()
            self.data["ota_partitions"] = ", ".join([cur.info()[4], nxt.info()[4]])

        # Connect to WIFI
        ssid = self.config.get(Config.WIFI_SSID, "")
        pwd = self.config.get(Config.WIFI_PWD, "")
        self.wlan_if = self.connect(ssid, pwd)

        # Set NTP time if online
        self.online = self.check_internet()
        if self.online:
            try:
                ntptime.settime()
                TZ = int(self.config.get(Config.TZ_OFFSET, 0))
                tm = time.localtime(time.time() + TZ * 60 * 60)
                log.debug(f"Setting NTP time: {tm}")
                machine.RTC().datetime((tm[0], tm[1], tm[2], tm[6] + 1, tm[3], tm[4], tm[5], 0))
            except:
                pass

        gpio_status = self.config.get(Config.GPIO_STATUS)
        if gpio_status:
            log.debug(f"Setting GPIO {gpio_status} for status led")
            try:
                self.status_led_pin = machine.Pin(int(gpio_status), machine.Pin.OUT)
                asyncio.create_task(self.led())
            except:
                log.error(f"Cannot init LED on {gpio_status}")
                pass

        # Blink faster for AP mode
        if self.wlan_if.ifconfig()[0] == "192.168.4.1":
            self.status_led_duration = Status.FAST
        else:
            self.status_led_duration = Status.SLOW

        # Initialize system stats
        self.update_system_stats()

        webrepl_pwd = self.config.get(Config.REPL_PWD)
        if webrepl_pwd:
            webrepl.start(password=self.config.get(Config.REPL_PWD, "repl"))
            log.info(f"Started WebREPL on port 8266")

    def check_internet(self):
        try:
            socket.getaddrinfo("www.google.com", 443)
            log.info(f"Internet access OK")
            return True
        except OSError as err:
            log.info(f"No internet access. Error:{err}")
            return False

    async def led(self):
        log.debug(f"LED task init")
        while 1:
            if self.status_led_duration == Status.OFF:
                self.status_led_pin.off()
            else:
                self.status_led_pin.on()
                # Also Blink
                if self.status_led_duration > 1:
                    await asyncio.sleep_ms(self.status_led_duration)
                    self.status_led_pin.off()
                    await asyncio.sleep_ms(self.status_led_duration)
            await asyncio.sleep_ms(0)

    def config_load(self):
        try:
            with open("config", "rb") as file:
                loaded_config = json.load(file)
                config = OrderedDict()
                for k in sorted(loaded_config.keys()):
                    config[k] = loaded_config[k]
                self.config = config
                log.debug(f"Running with config: {self.config}")
        except:
            log.error("Config read failed, initializing defaults")
            self.config_persist({})

    def config_persist(self, config={}):
        if config != self.config:
            log.debug(f"Config changed: Persisting: {config}")
            with open("config", "wb") as file:
                json.dump(config, file, separators=(",", ":"))
            self.config_load()
        else:
            log.debug("Config not changed: Not persisting")

    def config_add(self, additonal_config={}, override=False):
        new_config = OrderedDict(self.config)

        if override:
            for k, v in additonal_config.items():
                new_config[k] = v
        else:
            for k, v in additonal_config.items():
                new_config.setdefault(k, v)

        if self.config != new_config:
            log.info(f"Adding custom config {additonal_config}")
            self.config_persist(new_config)

    def connect(self, ssid="", pwd=""):
        log.debug(f"Setting up WIFI {ssid}")

        if not ssid:  # AP Mode if no SSID
            wlan_if = network.WLAN(network.AP_IF)
            log.info(f"Starting in AP Mode: {wlan_if.ifconfig()}")
            wlan_if.active(True)
            start = time.ticks_ms()
            while not wlan_if.isconnected():
                if time.ticks_diff(time.ticks_ms(), start) > 3000:
                    log.error(f"WIFI AP connection timeout")
                    break
            if wlan_if.isconnected():
                log.debug(f"Client connected to AP")
        else:  # Try to connect as client with SSID
            wlan_if = network.WLAN(network.STA_IF)
            if wlan_if.isconnected():
                log.debug(f"WLAN already connected: {wlan_if.ifconfig()}")
                return wlan_if
            wlan_if.active(True)
            wlan_if.config(reconnects=3)
            wlan_if.connect(ssid, pwd)
            start = time.ticks_ms()
            while not wlan_if.isconnected():
                # Check for timeout
                if time.ticks_diff(time.ticks_ms(), start) > 10000:
                    log.error(f"WIFI connection timeout to SSID {ssid}: {wlan_if.status()}")

                    # Do we have Fallback Configured?
                    if ssid == self.config.get(Config.WIFI_SSID) and self.config.get(Config.WIFI_FALLBACK_SSID, ""):
                        ssid = self.config.get(Config.WIFI_FALLBACK_SSID)
                        pwd = self.config.get(Config.WIFI_FALLBACK_PWD)
                        log.info(f"Trying fallback SSID: {ssid}")
                        return self.connect(ssid, pwd)

                    # Else go to AP Mode
                    else:
                        log.info(f"Fallback to AP Mode")
                        return self.connect(ssid="")

        log.info(f"WLAN connected: {wlan_if.ifconfig()}")
        return wlan_if

    def sys_reset(self):
        log.info(f"Rebooting system...")
        if self.config.get(Config.GPIO_STATUS):
            self.status_led_pin.off()
        machine.reset()

    def add_task(self, function):
        if self.wlan_if:
            asyncio.create_task(function)
        else:
            self.tasks.append(function)

    async def _handle(self, reader, writer):
        self.update_system_stats()

        try:
            request_line = await reader.readline()

            if request_line == b"":
                await writer.wait_closed()
                return

            method, path, proto = request_line.decode().split()

            path = path.split("?", 1)
            if len(path) > 1:
                qs = path[1]
            else:
                qs = ""
            path = path[0]

        except Exception as e:
            await self.http_error(writer, "500")
            return

        # Read Headers
        headers = {}
        while True:
            l = await reader.readline()
            if l == b"\r\n":
                break
            k, v = l.split(b":", 1)
            headers[k] = v.strip()

        # log.debug(f"Requested {method} {path} {headers}")

        form_data = {}

        if method == "GET" and path == "/data":
            await self.render_json(writer, self.data)
            return

        if method == "GET" and path == "/config":
            await self.render_json(writer, self.config)
            return

        if path != "/":
            await self.http_error(writer, "404")
            return

        size = int(headers.get(b"Content-Length", 0))
        if method == "POST" and size:
            data = await reader.readexactly(size)
            form_data = self.parse_qs(data.decode())
        else:
            form_data = self.parse_qs(qs) or {}

        log.debug(f"Form Data: {form_data}")

        redirect_timeout = 30
        # Handle Buttons
        if form_data.get("_reset"):
            await self.start_response(
                writer,
                status="303",
                headers=f"Refresh: {redirect_timeout}; url=http://192.168.4.1/",
            )
            await writer.wait_closed()
            self.config_persist({})
            self.sys_reset()
        elif form_data.get("_reboot"):
            await self.start_response(
                writer,
                status="303",
                headers=f"Refresh: {redirect_timeout}; url=http://{self.wlan_if.ifconfig()[0]}/",
            )
            await writer.wait_closed()
            self.sys_reset()
        elif form_data.get("_ota"):
            await self.start_response(writer, status="200")
            result = await self.ota_update(writer, form_data.get("ota_url", self.config.get(Config.OTA_URL)))
            if result:
                writer.write(f'Rebooting. <a href="http://{self.wlan_if.ifconfig()[0]}">Redirecting</a> in {redirect_timeout} seconds')
                writer.write(f'<script>setTimeout(function() {{window.location.replace("http://{self.wlan_if.ifconfig()[0]}")}}, {redirect_timeout*1000});</script>')
                writer.write("</body></html>")
                await writer.drain()
                await writer.wait_closed()
                await asyncio.sleep(3)
                self.ota_boot_next()
                self.sys_reset()
                return
            else:
                await writer.drain()
                await writer.wait_closed()
                log.error("OTA failed")
                return

        # Config was set, persist and reboot
        elif form_data:
            self.config_persist(form_data)
            await self.start_response(
                writer,
                status="303",
                headers=f"Refresh: {redirect_timeout}; url=http://{self.wlan_if.ifconfig()[0]}/",
            )
            await writer.wait_closed()
            self.sys_reset()

        # Render page
        await self.start_response(writer)
        html = self.render(writer, form_data)

        # Chunks Out to avoid buffer overflow for large pages
        chunk_size = 512
        chunks = [html[i : i + chunk_size] for i in range(0, len(html), chunk_size)]
        for chunk in chunks:
            writer.write(chunk)
            await writer.drain()
            gc.collect()

        writer.write("</body></html>")
        await writer.drain()
        await writer.wait_closed()

    def render(self, writer, form_data):
        return self.html_table(self.data) + self.html_form(self.config)

    def html_form(self, data):
        html = '<h3 id="settings">Settings</h3><a href="#data">Data</a>'

        html += '<form class="m-1" method="post" action="/">'

        for key, value in data.items():
            html += '<div class="form-floating mb-3">'
            html += f'<input class="form-control" type="text" id="{key}" name="{key}" value="{value}">'
            html += f'<label for="{key}">{key}:</label>'
            html += "</div>"

        # Buttons
        html += '<input type="submit" class="btn btn-primary btn-sm btn-b m-1" value="Save and restart">'
        html += '<input name="_reboot" class="btn btn-warning btn-sm btn-a btn-sm m-1" type="submit" value="Restart">'
        if self.ota:
            html += '<input name="_ota" class="btn btn-info btn-sm btn-c m-1" type="submit" value="Run OTA">'
        html += '<input name="_reset" class="btn btn-danger btn-sm btn-c m-1" type="submit" value="Factory Reset">'
        html += "</form>"

        return html

    def html_table(self, data):
        html = '<h3 id="data">Data</h3><a href="#settings">Settings</a><table class="table table-striped">'
        for key, value in data.items():
            html += f"<tr><td>{key}</td>"
            if isinstance(value, dict):
                for k, v in value.items():
                    html += f"<td>{v}</td>"
                html += "</tr>"
            elif isinstance(value, list):
                for v in value:
                    html += f"<td>{v}</td>"
                html += "</tr>"
            else:
                html += f"<td>{value}</td></tr>"

        html += "</table>"

        return html

    async def render_json(self, writer, dict):
        content = json.dumps(dict)
        writer.write(f"HTTP/1.0 200 OK\r\nContent-Type: application/json\r\nContent-Length: {len(content)}\r\n\Cache-Control: no-store\r\n\r\n")
        writer.write(content)
        await writer.drain()
        await writer.wait_closed()

    async def start_response(
        self,
        writer,
        content_type="text/html; charset=utf-8",
        status="200",
        headers=None,
        online=False,
    ):
        writer.write(f"HTTP/1.0 {status} OK\r\nContent-Type: {content_type}\r\nCache-Control: no-store\r\n")

        if not headers:
            writer.write("\r\n")
        else:
            writer.write(f"{headers}\r\n\r\n")

        if self.online and self.use_css:
            css = '<link href="https://cdn.jsdelivr.net/npm/bootstrap@5/dist/css/bootstrap.min.css" rel="stylesheet">'
        elif self.use_css:
            css = "<style>"
            # http://mincss.com/download.html
            css += "body,textarea,input,select{background:0;border-radius:0;font:16px sans-serif;margin:0}.addon,.btn-sm,.nav,textarea,input,select{outline:0;font-size:14px}.smooth{transition:all .2s}.btn,.nav a{text-decoration:none}.container{margin:0 20px;width:auto}@media(min-width:1310px){.container{margin:auto;width:1270px}}.btn,h2{font-size:2em}h1{font-size:3em}.btn{background:#999;border-radius:6px;border:0;color:#fff;cursor:pointer;display:inline-block;margin:2px 2px;padding:12px 30px 14px}.btn:hover{background:#888}.btn:active,.btn:focus{background:#777}.btn-a{background:#0ae}.btn-a:hover{background:#09d}.btn-a:active,.btn-a:focus{background:#08b}.btn-b{background:#3c5}.btn-b:hover{background:#2b4}.btn-b:active,.btn-b:focus{background:#2a4}.btn-c{background:#d33}.btn-c:hover{background:#c22}.btn-c:active,.btn-c:focus{background:#b22}.btn-sm{border-radius:4px;padding:10px 14px 11px}label>*{display:inline}form>*{display:block;margin-bottom:10px}textarea,input,select{border:1px solid #ccc;padding:8px}textarea:focus,input:focus,select:focus{border-color:#5ab}textarea,input[type=text]{-webkit-appearance:none;width:13em;outline:0}.addon{box-shadow:0 0 0 1px #ccc;padding:8px 12px}.table th,.table td{padding:.5em;text-align:left}.table tbody>:nth-child(2n-1){background:#ddd}"
            css += "</style>"
        else:
            css = ""

        writer.write(
            f"""
        <!doctype html>
        <html lang="en">
        <head>
            <meta charset="utf-8">
            <meta name="viewport" content="width=device-width, initial-scale=1">
            {css}
            <title>{self.title}</title>
        </head>
        <body class="container">
        """
        )
        await writer.drain()

    async def http_error(self, writer, status):
        await self.start_response(writer, status=status)
        writer.write(status)
        await writer.drain()
        await writer.wait_closed()

    def parse_qs(self, s):
        def unquote_plus(s):
            s = s.replace("+", " ")
            arr = s.split("%")
            arr2 = [chr(int(x[:2], 16)) + x[2:] for x in arr[1:]]
            return arr[0] + "".join(arr2)

        res = {}
        if s:
            pairs = s.split("&")
            for p in pairs:
                vals = [unquote_plus(x) for x in p.split("=", 1)]
                if len(vals) == 1:
                    vals.append(True)
                old = res.get(vals[0])
                if old is not None:
                    if not isinstance(old, list):
                        old = [old]
                        res[vals[0]] = old
                    old.append(vals[1])
                else:
                    res[vals[0]] = vals[1]
        return res

    def update_system_stats(self):
        t = time.localtime()
        self.data["sys_unique_id"] = hexlify(machine.unique_id()).decode("ascii")
        self.data["sys_frequency"] = str(machine.freq())
        self.data["sys_mem_free"] = str(gc.mem_free())
        self.data["sys_flash_size"] = str(esp.flash_size())
        self.data["sys_time"] = f"{t[0]:04}-{t[1]:02}-{t[2]:02}T{t[3]:02}:{t[4]:02}:{t[5]:02}"
        self.data["sys_ifconfig"] = str(self.wlan_if.ifconfig())

    def ota_partiton_available(self):
        try:
            nxt = Partition(Partition.RUNNING).get_next_update()
        except:
            nxt = None

        return bool(nxt)

    def ota_boot_next(self):
        log.info("Booting into next partition")
        cur = Partition(Partition.RUNNING)
        nxt = cur.get_next_update()
        nxt.set_boot()
        machine.reset()

    def ota_boot_successful(self):
        Partition.mark_app_valid_cancel_rollback()

    def copy_partition(self, src, dest):
        log.info(f"Partition copy: {src.info()} --> {dest.info()}")
        sz = src.info()[3]
        if dest.info()[3] != sz:
            raise ValueError(f"Partition sizes don't match: {sz} vs {dest.info()[3]}")
        addr = 0
        blk = bytearray(4096)
        while addr < sz:
            if sz - addr < 4096:
                blk = blk[: sz - addr]
            if addr & 0xFFFF == 0 or len(blk) < 4096:
                log.debug(f"Writing: {len(blk)} Block: {addr >> 12:06x} @ {addr:06x}")
            src.readblocks(addr >> 12, blk)
            dest.writeblocks(addr >> 12, blk)
            addr += len(blk)

    async def ota_update(self, writer, ota_url):
        async def ota_error(err):
            log.error(err)
            writer.write(f"<div>{err}</div>")
            await writer.drain()

        # Parse OTA URL
        splits = re.compile("://|:|/").split(ota_url, 3)

        if len(splits) != 4:
            ota_error("OTA URL should be in format: <proto://host:port/path_to_ota_file>")
            return False

        if splits[0] != "http":
            ota_error("Only HTTP supported for OTA")
            return False

        [proto, host, port, path] = splits

        cur = Partition(Partition.RUNNING)
        nxt = cur.get_next_update()

        if not self.ota_partiton_available():
            ota_error("Firmware has incorrect OTA partitions")
            return False

        log.info(f"Trying to write OTA to partition {nxt.info()[4]}")
        writer.write(f"<div>Trying to write OTA to partition {nxt.info()[4]}</div>")
        await writer.drain()

        try:
            addr = socket.getaddrinfo(host, port, 0, socket.SOCK_STREAM)[0]
            s = socket.socket(addr[0], addr[1], addr[2])
            s.connect(addr[-1])
        except OSError as e:
            ota_error(f"OSError connecting: {e}")
            return False
        except:
            ota_error(f"Unknown error connecting")
            return False

        s.write(f"GET /{path} HTTP/1.1\r\nHost: {host}:{port}\r\nAccept: */*\r\n\r\n")

        response = s.readline()
        log.debug(f"OTA server response: {response.decode().strip()}")
        response = response.split(None, 2)
        status = int(response[1])

        if status < 200 or status >= 300:
            ota_error(f"OTA server responded with invalid status {status}")
            return False

        # Validate fw file len
        headers = {}
        while True:
            header = s.readline()
            if header == b"\r\n":
                break
            header_line = header.decode().strip().split(": ")
            headers[header_line[0]] = header_line[1]
        fw_size = int(headers.get("Content-Length", 0))
        if not fw_size:
            ota_error("Firmware size not detected. Content-Length header missing")
            return False
        if nxt.info()[3] < fw_size:
            ota_error(f"OTA Partition too small for firmware: {fw_size} vs partition {nxt.info()}")
            return False
        else:
            total_blks = fw_size // 4096
            log.info(f"Start writing {fw_size} bytes, {total_blks} blocks @ flash 0x{nxt.info()[2]:06x} size: {nxt.info()[3]}")

        addr = 0
        blk = bytearray(4096)
        while addr < fw_size:
            if fw_size - addr < 4096:
                blk = blk[: fw_size - addr]
                log.debug(f"Not a full block @ {addr}: len {len(blk)}")

            s.readinto(blk)

            if not blk:
                ota_error("OTA server error")
                return False

            # Check file signature of first block
            if addr == 0 and blk[:3] != b"\xe9\x08\x02":
                ota_error(f"Not a valid OTA file signature {blk[:3]}")
                return False

            # Pad Block if < 4096
            if len(blk) < 4096:
                blk = blk + (4096 - len(blk)) * b"\xff"
                log.debug(f"Padding to len {len(blk)}")

            # Show status
            if addr & 0xFFFF == 0 or fw_size - addr < 4096:
                msg = f"Writing block: {addr >> 12}/{total_blks}, offset: {addr+nxt.info()[2]:06x}"
                log.info(msg)
                writer.write(f"<div>{msg}</div>")
                await writer.drain()

            nxt.writeblocks(addr >> 12, blk)
            addr += len(blk)

        msg = f"OTA write complete to partition {cur.info()[4]}"
        log.info(msg)
        writer.write(f"<div>{msg}</div>")
        return True

    def run(self, host="0.0.0.0", port=80):
        log.info(f"Starting IOT webserver")
        # Start all tasks
        server = asyncio.start_server(self._handle, host, port)
        self.add_task(server)
        asyncio.gather(self.tasks)
        loop = asyncio.get_event_loop()
        loop.run_forever()
        loop.close()


if __name__ == "__main__":
    import time

    # Init Manager
    iot1 = IotManager(
        use_css=True,
        title="IoT Demo Controller",
        ota_url="http://10.1.1.10:8080/micropython.bin",
        debug=True,
    )

    # Add a custom config key to manager. This will be persisted.
    iot1.config_add(
        {
            "60_CUSTOM_CONFIG": "Counter",
        }
    )

    # Add Demo Data to Manager
    for i in range(5):
        iot1.data[f"Key {i}"] = f"{i}"

    # Demo Class - Task to run in the background needs to be a non-blocking asyncio co-routine
    class Alive:
        # Method to run must be a async co-routine
        async def run(self):
            i = 0

            # Get a custom config value from manager
            counter_key_name = iot1.config.get("60_CUSTOM_CONFIG")
            while 1:
                print("Increment Counter")
                # Adds dynamic data to the manager for display
                iot1.data[counter_key_name] = f"{i}"
                iot1.data["gmt_time"] = time.gmtime()
                i += 1
                # Ensures that the method yields time to manager and other running tasks
                await asyncio.sleep(3)

    # Add task to manager
    iot1.add_task(Alive().run())

    # Start Manager, code after this line will not be executed anymore
    iot1.run()

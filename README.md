# Micropython ESP32 IoT Manager

The IoT Manager provides a framework with the following features:

## WiFi Auto Config
If no SSID is configured, an AP is automaticaly created to which a client can connect. If an SSID and password is configured, the manager will connect to that SSID on next reboot automatically.

If the primary SSID is not available, a fallback SSID and password can be configured.

For configurations with open access points not requiring a password, a blank password should be used in the config file.

## Config Management
The configuration for the manager is saved to the micropython filesystem with the name 'config'. The config file is saved in JSON format.

In addition, projects using the manager can add and access config keys through the attribut 'IotManager.config' on the class.

## Sensor and App Data
The manager also has an OrderedDict attribute 'IotManager.data'. This will be populated at runtime. Sensor or other data can be added by key. This data will displayed on managers's webpage and can also be accessed via an HTTP GET request to /data for further use by other systems.

## Adding your own code to run
IotManager is based on Micropythons implementation of uasyncio which allows code to run in parallel. Asyncio co-routines can be added as a Task to the manager. After the manager has initialized and is started with the run() method, it will also start the user provided co-routines.

It is important to note that these co-routines should be non-blocking of nature by using the uasyncio.sleep methods on a regular basis.

## OTA
If the running micropython firmware has been built with 2 OTA partitions, the manager also supports downloading an Micropython Application OTA image and deploy it to the secondary OTA partition. After the download was successful, the device will reboot and start with the new application image.

The OTA server is specificied on initialisation of the manager and should follow the following format:
http://<ip or DNS name>:<port>/<path to .bin file>

Please note that HTTPS is not supported and that the .bin file should only be the application image, not a complete firmware file.

## Other Features

### Webpage UI CSS
Once the manager detects internet connectivity, it will use Bootstrap CSS for a nicer UI othwerwise it defaults to integrated basic CSS

## Usage Example:

```python
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
            counter_key_name = iot1.config.get('60_CUSTOM_CONFIG')
            while 1:
                print("Increment Counter")
                # Adds dynamic data to the manager for display
                iot1.data[counter_key_name] = f"{i}"
                iot1.data['gmt_time'] = time.gmtime()
                i += 1
                # Ensures that the method yields time to manager and other running tasks
                await asyncio.sleep(3)

    # Add task to manager
    iot1.add_task(Alive().run())

    # Start Manager, code after this line will not be executed anymore
    iot1.run()
```

# LYWSD02 Sync2

Once installed, you need to add following to HomeAssistant's `configuration.yaml` and restart it:
```yaml
lywsd02:
```

## Setting Time

Now you have have `lywsd.set_time` service that can be used to set time on a LYWSD02 given its BLE MAC address.

Only MAC address parameter is requried, and it will set the time to what is on your HomeAssistant.
Here's how the minimal invocation looks like:
```yaml
service: lywsd02.set_time
data:
  mac: A1:B2:C3:D4:E5:F6
```

Now you can setup an automation to invoke this service as often as you'd like to sync LYWSD02's time.

If you want a lower-lever control - you can tweak the exact time set via additional parameters.
See [./services.yaml](./custom_components/lywsd02/services.yaml) for details.

## Setting Unit

You can also set tempaerature unit (F/C), TZ offset, as well as clock mode (12/24) via optional parameters:
```yaml
service: lywsd02.set_time
data:
  mac: A1:B2:C3:D4:E5:F6
  clock_mode: 24
  tz_offset: 0
  temp_mode: 'C'
```

## Displaying Custom Digits

You can show 4 digits of your choice instead of the current time with the `display` parameter:
```yaml
service: lywsd02.set_time
data:
  mac: A1:B2:C3:D4:E5:F6
  display: "0742"
```

Limitations, as the LYWSD02 can only display a time it computes itself:
- The digits must form a valid time: `HH` between `00` and `23`, `MM` between `00` and `59`.
  Hours above `12` require the clock to be in 24-hour mode.
- The clock keeps running: `07:42` becomes `07:43` one minute later.
- The clock shows the wrong time until the next regular `set_time` call (without `display`).
- Always quote the value: YAML reads an unquoted `0742` as an octal number.

## Timeout

If you get an error establishing connection - could be because it takes longer than expected to get the Bluetooth proxy working. Consider increasing `timeout` from default 10s to a larger value:
```yaml
service: lywsd02.set_time
data:
  mac: A1:B2:C3:D4:E5:F6
  timeout: 60
```

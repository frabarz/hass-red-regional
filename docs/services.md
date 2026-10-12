# Services

Call these from Developer Tools → Actions or your automations.

## `red_regional.refresh`

Force a poll now instead of waiting for the interval. Takes exactly one of:

```yaml
action: red_regional.refresh
data:
  config_entry_id: "01J…"   # or:
  # device_id: "abc123…"
```

## `red_regional.lookup_stop`

Search cached stops by code or name fragment. Falls back to a live check
when the cache has no answer.

```yaml
action: red_regional.lookup_stop
data:
  zone_uuid: "f083f24e-7fee-4fdc-9520-dbbdae877f07"
  query: "tribunales"
  limit: 8
```

Returns `candidates`: `stop_code`, `stop_name`, `latitude`, `longitude`.
Find your zone UUID in the stop device attributes (`zone`) or via the
zone picker during setup.

## `red_regional.get_vehicles`

Live GPS telemetry for one route and direction (`I` ida, `R` retorno;
defaults to `I`).

```yaml
action: red_regional.get_vehicles
data:
  zone_uuid: "f083f24e-7fee-4fdc-9520-dbbdae877f07"
  route: "44B"
  direction: "I"
```

Returns `vehicles`: `plate`, `latitude`, `longitude`, `speed_kmh`, `route`,
`direction`, `last_update`.

Next: [Troubleshooting](troubleshooting.md).

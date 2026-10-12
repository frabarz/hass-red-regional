# Entities

Each stop becomes one device — manufacturer `DTPR / Red Regional`, model the
city name — with stable unique ids (`{zone}_{stop}_…`), so renames never
duplicate entities.

## Next departure — `sensor.<stop>_next_departure`

Timestamp of the soonest predicted arrival (`unknown` off-hours, never an
error state). Attributes:

| Attribute | Content |
|---|---|
| `departures` | Ordered board: `route`, `destination`, `scheduled_at`, `expected_at`, `due_in_min`, `delay_min`, `realtime`, `direction` (`I`/`R`), `vehicle_id`, `route_color`, `cancelled`, `occupancy` |
| `departures_text` | Human summary, e.g. `10L in 14 min, 10N in 9 min` — handy for TTS and Markdown cards |
| `departure_count` | Number of visible departures |
| `stop_code`, `stop_name`, `zone`, `last_update`, `attribution` | Context |

## Service alert — `binary_sensor.<stop>_service_alert`

`on` while operator alerts or crowdsourced reports affect the stop; the
`alerts` attribute lists `title`, `description`, `routes`, and validity
window per alert.

## Departures count — `sensor.<stop>_departures`

Plain integer count of visible departures. Disabled by default; enable it in
the entity settings if you want a graphable number.

## Live buses — `device_tracker.bus_<plate>`

One tracker per bus in service on your watched routes (opt-in during setup
or in options). Map-ready GPS with `route`, `direction`, `speed_kmh`, and
`last_update` attributes. Trackers appear and retire automatically; a plate
serving both directions gets suffixed ids (`…_<plate>_I`, `…_<plate>_R`).

Next: [Dashboards](dashboards.md).

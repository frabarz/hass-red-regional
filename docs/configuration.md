# Configuration

Everything happens in the UI — there is no YAML setup. One config entry
covers one stop; repeat the flow for more stops.

## Adding a stop

1. Settings → Devices & Services → Add Integration → Red Regional.
2. **Zone**: pick your city (e.g. Gran Concepción). The list loads live from
   the backend; pinned cities keep setup working offline.
3. **Stop code**: enter the code painted on the stop sign (e.g. `P45068`,
   `PA151`). It validates live — unknown codes are rejected, while empty
   boards are accepted (the stop may simply be off-hours).
4. **Filters** (all optional, changeable later):

| Option | Meaning | Default |
|---|---|---|
| Only these routes | Comma list, e.g. `44B, 63B` | all routes |
| Only these destinations | Substring match, e.g. `Hualpen` | all |
| Max departures | 1–15 | 5 |
| Look ahead | Drop arrivals later than N minutes (15–360) | 120 |
| Walking time | Hide arrivals sooner than your walk (0–30) | 0 |
| Track live bus positions | Create GPS trackers for buses in service | off |
| Tracked routes | `44B` or `44B:I`, comma-separated (`I` ida, `R` retorno) | — |
| Poll every | Backend poll interval in seconds (30–600) | 60 |

Don't know the code? Run the `red_regional.lookup_stop` action with a name
fragment — see [Services](services.md).

## Changing a stop later

- **Options** (integration card → Configure): filters, tracking, and poll
  interval apply live, no re-setup.
- **Reconfigure** (card → ⋮ → Reconfigure): change the zone or stop code;
  entities follow the new stop.
- **Reauth**: if the backend starts rejecting requests, Home Assistant opens
  a re-authentication flow — confirm to retry.

Next: [Entities](entities.md).

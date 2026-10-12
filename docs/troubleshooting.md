# Troubleshooting

## Sensor reads `unknown`

Normal off-hours: no buses are running (e.g. route 44B runs roughly
06:30–23:00 on weekdays). Entities recover automatically at first service —
no action needed.

## “Invalid stop code”

The code is unknown in that zone. Double-check the sign, or search with the
`red_regional.lookup_stop` action. If a configured stop disappears upstream,
a repair issue appears with a guided fix (reconfigure the entry).

## Backend rejects requests / reauth prompts

The unofficial backend occasionally enforces a newer app version. Confirm the
re-authentication flow; if rejections persist, bump `APP_VERSION` in
`custom_components/red_regional/const.py` (currently `2.5.1`) and reload.

## Repair issues

- **Unknown bus stop** — reconfigure the entry with a valid code.
- **Backend unreachable** — raised after three failed polls in a row;
  confirm to reload and retry. Check your network and the 30 s minimum poll
  interval if it recurs.

## Diagnostics & privacy

Entry diagnostics (Settings → Devices & Services → Red Regional → ⋮ →
Download diagnostics) redact the per-entry phone id. Stop names, positions,
and bus telemetry are public backend data.

## Still stuck?

Open an issue with the diagnostics download attached and note your zone,
stop code, and the time the problem occurred.

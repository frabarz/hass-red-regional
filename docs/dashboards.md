# Dashboards

Entity ids below assume a stop named `Plaza Tribunales de Justicia (P45068)`;
yours follow the same pattern. See [Entities](entities.md) for the full
attribute reference.

## Departure board

```yaml
type: entities
entities:
  - entity: sensor.plaza_tribunales_de_justicia_p45068_next_departure
  - entity: binary_sensor.plaza_tribunales_de_justicia_p45068_service_alert
```

## One-line summary (Markdown)

```yaml
type: markdown
content: >-
  {{ state_attr('sensor.plaza_tribunales_de_justicia_p45068_next_departure',
  'departures_text') }}
```

## TTS announcement

```yaml
action: tts.speak
data:
  message: >-
    Próximo bus:
    {{ state_attr('sensor.plaza_tribunales_de_justicia_p45068_next_departure',
    'departures_text') }}
```

## Live map

```yaml
type: map
entities:
  - entity: device_tracker.bus_abcd12
```

## Delayed/cancelled highlighting (auto-entities)

```yaml
type: custom:auto-entities
card:
  type: entities
filter:
  template: >-
    {{ state_attr('sensor.plaza_tribunales_de_justicia_p45068_next_departure',
    'departures') | selectattr('delay_min') | list | length > 0 }}
```

Next: [Services](services.md).

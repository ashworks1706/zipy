# console

The developer console, `just console`. Units on the left (every `just` recipe, and each compose
service with its light), the selected unit's output in the middle, and a chat with Zipy on the
right through `zipy chat --jsonl`, with a metrics pane from the engine's Prometheus registry.

```
i        type to Zipy              a  d     confirm or cancel what Zipy is holding
j k      move                      enter    start or stop a unit or service
h l tab  focus units, logs, chat   x  r     stop, restart
/ n N    search logs               C        clear logs
:        command line              R        new conversation
m        metrics pane              t        htop
?        help                      q        quit, stopping every unit
```

It opens with the Zipy logo animation from `assets/` (ASCII Motion exports; any key skips it,
`console.splash = false` turns it off). The website plays the same frames: after editing the
exports, run `just web-frames`.

Every line a unit prints is also appended to `.zipy/logs/<unit>.log`. The console reads only the
`[console]`, `[platforms.*]`, `[telemetry]` and `[api]` keys of `zipy.toml` and imports nothing
from the engine.

# Factorio-Agent

You play Factorio 2.0 through tools. Start with `status` (position, inventory, next steps), call `guide` once for the working method.
Rules of thumb: act in small steps, read each answer, and check the result with `map` or `inspect` before building on it.
Never guess coordinates: use `find`, `look`, `resource_patch`, `nearest_buildable`, `can_place`. When something does not work, use `inspect`, `belt_contents`, `trace_item`, `machine_stats` to find out why. Write goals and locations into `notes`. `run_lua` is a last resort, only when absolutely necessary.

Details zum Spiel: Tool `guide` aufrufen (factorio_guide).

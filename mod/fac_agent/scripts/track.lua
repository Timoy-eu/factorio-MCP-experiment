-- track: look at items on belts, follow a single item, sample machines (for throughput and uptime)
local C = require("scripts.common")
local M = {}

local fail, done = C.fail, C.done
local surf, agent, bag = C.surf, C.agent, C.bag
local px, py, dist, r1 = C.px, C.py, C.dist, C.r1

local BELT_TYPES = { ["transport-belt"] = true, ["underground-belt"] = true, ["splitter"] = true }
local BELT_SLOTS = 8 -- items per belt tile when full (4 per lane)
local MAX_TILES = 4000

local function line_items(belt, add)
  local n = 0
  for i = 1, 2 do
    local ok, line = pcall(function() return belt.get_transport_line(i) end)
    if ok and line then
      for _, it in ipairs(line.get_contents()) do
        n = n + it.count
        if add then add(it.name, it.count) end
      end
    end
  end
  return n
end

local function belts_in(area)
  local list = {}
  for _, e in ipairs(surf().find_entities_filtered { area = area, force = agent().force }) do
    if e.valid and BELT_TYPES[e.type] then list[#list + 1] = e end
  end
  return list
end

-- what lies on the belts of an area (without coordinates: 15 tiles around the agent)
function M.belt_contents(x1, y1, x2, y2)
  if x1 == nil or y1 == nil or x2 == nil or y2 == nil then
    local p = agent().position
    x1, y1, x2, y2 = px(p) - 15, py(p) - 15, px(p) + 15, py(p) + 15
  end
  local area = { { math.min(x1, x2), math.min(y1, y2) }, { math.max(x1, x2), math.max(y1, y2) } }
  local belts = belts_in(area)
  if #belts > MAX_TILES then return fail("too_large", #belts .. " belt pieces in that area, use a smaller one") end
  local items, total, empty, tiles = {}, 0, 0, {}
  for _, b in ipairs(belts) do
    local here = {}
    local n = line_items(b, function(name, count)
      items[name] = (items[name] or 0) + count
      here[name] = (here[name] or 0) + count
    end)
    total = total + n
    if n == 0 then empty = empty + 1 elseif #tiles < 40 then
      tiles[#tiles + 1] = { x = r1(px(b.position)), y = r1(py(b.position)), d = C.direction_name(b), n = here }
    end
  end
  local capacity = #belts * BELT_SLOTS
  return done {
    belts = #belts, empty = empty, items = items, total = total, capacity = capacity,
    fill = capacity > 0 and r1(100 * total / capacity) or 0, tiles = tiles,
  }
end

-- put one item on a belt and remember it
function M.trace_start(x, y, item)
  local s, a = surf(), agent()
  local belts = s.find_entities_filtered { position = { x = x, y = y }, radius = 0.7, force = a.force }
  local belt
  for _, e in ipairs(belts) do
    if e.valid and BELT_TYPES[e.type] then belt = e; break end
  end
  if not belt then return fail("no_belt", "no belt of yours at " .. x .. "," .. y, { x = x, y = y }) end
  local inv = bag()
  if inv.get_item_count(item) < 1 then return fail("no_item", "you have no " .. item, { item = item }) end
  local inserted = false
  for i = 1, 2 do
    local ok, res = pcall(function() return belt.get_transport_line(i).insert_at_back { name = item, count = 1 } end)
    if ok and res then inserted = true; break end
  end
  if not inserted then return fail("belt_full", "the belt at " .. x .. "," .. y .. " is full, nothing can be added", { x = x, y = y }) end
  inv.remove { name = item, count = 1 }
  storage.traces = storage.traces or {}
  local id = (storage.trace_id or 0) + 1
  storage.trace_id = id
  local pos = { x = px(belt.position), y = py(belt.position) }
  storage.traces[id] = { item = item, start = pos, last = pos, tick = game.tick, moved_tick = game.tick, path = 0 }
  return done { id = id, item = item, x = r1(pos.x), y = r1(pos.y), tick = game.tick }
end

-- find the tracer: the belt near the last position that holds the item and is farthest from the start
function M.trace_probe(id)
  local t = storage.traces and storage.traces[id]
  if not t then return fail("no_trace", "unknown trace " .. tostring(id)) end
  local s, a = surf(), agent()
  local best, best_d
  for _, e in ipairs(s.find_entities_filtered { position = t.last, radius = 3.5, force = a.force }) do
    if e.valid and BELT_TYPES[e.type] then
      local holds = false
      for i = 1, 2 do
        local ok, line = pcall(function() return e.get_transport_line(i) end)
        if ok and line and line.get_item_count and line.get_item_count(t.item) > 0 then holds = true end
      end
      if holds then
        local d = dist(e.position, t.start)
        if not best or d > best_d then best, best_d = e, d end
      end
    end
  end
  if best then
    local p = { x = px(best.position), y = py(best.position) }
    if p.x ~= t.last.x or p.y ~= t.last.y then
      t.path = t.path + math.abs(p.x - t.last.x) + math.abs(p.y - t.last.y)
      t.last, t.moved_tick = p, game.tick
    end
  end
  t.seen = t.seen or best ~= nil
  return done {
    id = id, found = best ~= nil, x = r1(t.last.x), y = r1(t.last.y), tick = game.tick,
    started = t.tick, idle = game.tick - t.moved_tick, tiles = t.path, item = t.item,
  }
end

-- one snapshot of machines (status and finished products) around a point plus global production of an item
function M.sample(x, y, radius, item)
  local a = agent()
  local origin = (x ~= nil and y ~= nil) and { x = x, y = y } or a.position
  radius = math.min(math.max(radius or 20, 0.5), 80)
  local machines, belts, belt_items = {}, 0, 0
  for _, e in ipairs(surf().find_entities_filtered { position = origin, radius = radius, force = a.force }) do
    if e.valid and e.type ~= "character" then
      if BELT_TYPES[e.type] then
        belts = belts + 1
        belt_items = belt_items + line_items(e)
      elseif e.status ~= nil and #machines < 120 then
        local ok, p = pcall(function() return e.products_finished end)
        machines[#machines + 1] = {
          n = e.name, x = r1(px(e.position)), y = r1(py(e.position)), s = C.STATUS_NAME[e.status],
          p = ok and p or nil,
        }
      end
    end
  end
  local produced
  if item and item ~= "" then
    local ok, stats = pcall(function() return a.force.get_item_production_statistics(surf()) end)
    if ok and stats then produced = (stats.input_counts or {})[item] or 0 end
  end
  return done { tick = game.tick, machines = machines, belts = belts, belt_items = belt_items, produced = produced }
end

return M

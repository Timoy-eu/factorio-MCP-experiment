-- selftest: checks the Factorio API assumptions of this mod inside a free sandbox area.
-- Everything it builds is removed again, the inventory and position are restored.
local C = require("scripts.common")
local Basic = require("scripts.basic")
local Connect = require("scripts.connect")
local Map = require("scripts.map")
local M = {}

local fail, done = C.fail, C.done
local surf, agent, bag = C.surf, C.agent, C.bag
local px, py, r1 = C.px, C.py, C.r1

local SIZE = 14
local GIVE = {
  ["transport-belt"] = 20, ["small-electric-pole"] = 8, ["stone-furnace"] = 3, ["wooden-chest"] = 3,
  ["assembling-machine-1"] = 1, ["inserter"] = 1, ["iron-plate"] = 6, ["offshore-pump"] = 1,
  ["burner-mining-drill"] = 2, coal = 10, rail = 80, ["underground-belt"] = 2,
}

local function good(s) return type(s) == "string" and s:find('"ok":true', 1, true) ~= nil end

local function free_area(s, a, x, y)
  local function free(ox, oy)
    local area = { { ox, oy }, { ox + SIZE, oy + SIZE } }
    if #s.find_entities_filtered { area = area } > 0 then return false end
    return #s.find_tiles_filtered { area = area, name = C.WATER } == 0
  end
  if x ~= nil and y ~= nil then return math.floor(x), math.floor(y), free(math.floor(x), math.floor(y)) end
  local bx, by = math.floor(px(a.position)) + 12, math.floor(py(a.position)) + 12
  for ring = 0, 8 do
    for dx = -ring, ring do
      for dy = -ring, ring do
        if math.max(math.abs(dx), math.abs(dy)) == ring then
          local ox, oy = bx + dx * 8, by + dy * 8
          if free(ox, oy) then return ox, oy, true end
        end
      end
    end
  end
  return bx, by, false
end

function M.run(x, y)
  local s, a = surf(), agent()
  local home = { x = px(a.position), y = py(a.position) }
  local ox, oy, ok_area = free_area(s, a, x, y)
  if not ok_area then
    return fail("no_space", "no free " .. SIZE .. "x" .. SIZE .. " area found, pass x and y of an empty spot")
  end

  -- remember the world so that everything can be undone
  local before_ids = {}
  for _, e in ipairs(s.find_entities_filtered { force = a.force }) do
    if e.valid and e.unit_number then before_ids[e.unit_number] = true end
  end
  local saved = C.counts(bag())
  local inv = bag()
  for name, n in pairs(GIVE) do inv.insert { name = name, count = n } end

  local results = {}
  local function check(name, fn)
    local ok, status, detail = pcall(fn)
    if not ok then
      results[#results + 1] = { n = name, s = "fail", d = "error: " .. tostring(status) }
    else
      results[#results + 1] = { n = name, s = status and (status == true and "ok" or status) or "fail", d = detail }
    end
  end
  local function at(dx, dy) return ox + dx + 0.5, oy + dy + 0.5 end

  check("character_inventory", function()
    local c = bag()
    return c.insert and c.get_item_count and c.remove and "ok", "main inventory works"
  end)

  check("inventory_contents_format", function()
    local cx, cy = at(1, 1)
    local chest = s.create_entity { name = "wooden-chest", position = { x = cx, y = cy }, force = a.force }
    if not chest then return "fail", "could not place a wooden-chest" end
    chest.insert { name = "coal", count = 5 }
    local contents = chest.get_inventory(defines.inventory.chest).get_contents()
    local first = contents[1]
    if first and first.name == "coal" and first.count == 5 then return "ok", "get_contents returns a list of {name,count}" end
    return "fail", "get_contents has another format than {name,count} list: " .. helpers.table_to_json(contents)
  end)

  check("prototype_fields", function()
    local p = prototypes.entity["stone-furnace"]
    local item = p and p.items_to_place_this and p.items_to_place_this[1]
    local w, h = C.entity_size("assembling-machine-1")
    local wire = prototypes.entity["small-electric-pole"]
    local reach
    if wire then pcall(function() reach = wire.get_max_wire_distance() end) end
    local msgs, bad = {}, false
    if not (item and item.name == "stone-furnace") then bad = true; msgs[#msgs + 1] = "items_to_place_this missing" end
    if w ~= 3 or h ~= 3 then bad = true; msgs[#msgs + 1] = "size of assembling-machine-1 is " .. tostring(w) .. "x" .. tostring(h) end
    if not reach then msgs[#msgs + 1] = "get_max_wire_distance unavailable (fallback 7.5 is used)" end
    return (bad and "fail") or (#msgs > 0 and "warn") or "ok", table.concat(msgs, "; ")
  end)

  check("place_and_rotate_belt", function()
    local bx, by = at(1, 3)
    if not good(Basic.build("transport-belt", bx, by, "north")) then return "fail", "build failed" end
    local r = Basic.rotate(bx, by, "east")
    if not good(r) then return "fail", "rotate: " .. tostring(r) end
    local e = C.own_entity_at(bx, by)
    if e and e.direction == defines.direction.east then return "ok", "belt rotated north -> east and read back" end
    return "fail", "direction after rotate is " .. tostring(e and e.direction)
  end)

  check("assembler_recipe_and_rotation", function()
    local ax, ay = at(6, 4)
    if not good(Basic.build("assembling-machine-1", ax + 0.0, ay + 0.0, "north")) then return "fail", "assembler could not be built" end
    local e = C.own_entity_at(ax, ay) or C.own_entity_at(ax + 0.5, ay + 0.5)
    if not e then return "fail", "assembler not found after building" end
    local px_, py_ = px(e.position), py(e.position)
    if not good(Basic.set_recipe(px_, py_, "iron-gear-wheel")) then
      return "warn", "set_recipe failed (recipe may be locked); rotation not tested"
    end
    local r = Basic.rotate(px_, py_, "east")
    if not good(r) then return "fail", "rotate assembler: " .. tostring(r) end
    if r:find('"note"', 1, true) then return "ok", "assembler without fluid recipe has no orientation (handled, recipe kept)" end
    local n = C.own_entity_at(px_, py_)
    local rec = n and n.get_recipe and n.get_recipe()
    if rec and rec.name == "iron-gear-wheel" then return "ok", "assembler recreated, recipe kept" end
    return "fail", "recipe lost after rotation"
  end)

  check("belt_line_and_transport_line", function()
    local x1, y1 = at(0, 8)
    local x2, y2 = at(6, 8)
    local r = Connect.connect("belt", x1, y1, x2, y2, nil, "east")
    if not good(r) then return "fail", "connect belt: " .. tostring(r) end
    if not r:find('"connected":true', 1, true) then return "fail", "connect reports the belt line as not connected (belt_neighbours?)" end
    local first = C.own_entity_at(x1, y1)
    local cur, steps = first, 0
    while cur and cur.belt_neighbours and cur.belt_neighbours.outputs[1] and steps < 10 do
      cur = cur.belt_neighbours.outputs[1]
      steps = steps + 1
    end
    if steps ~= 6 then return "fail", "following belt_neighbours.outputs gave " .. steps .. " steps instead of 6" end
    local line = first.get_transport_line(1)
    local inserted = line.insert_at_back { name = "iron-plate", count = 1 }
    if not inserted or line.get_item_count("iron-plate") < 1 then return "fail", "insert_at_back / get_item_count on a transport line failed" end
    return "ok", "6 belts routed, neighbours and transport line work"
  end)

  check("power_poles", function()
    local x1, y1 = at(0, 12)
    local x2, y2 = at(13, 12)
    local r = Connect.connect("power", x1, y1, x2, y2)
    if not good(r) then return "fail", "connect power: " .. tostring(r) end
    if not r:find('"connected":true', 1, true) then return "fail", "poles are not in one electric network (wire reach too large?)" end
    return "ok", "poles connected into one network"
  end)

  check("machine_status_and_counter", function()
    local fx, fy = at(11, 1)
    local f = s.create_entity { name = "stone-furnace", position = { x = fx + 0.5, y = fy + 0.5 }, force = a.force }
    if not f then return "fail", "furnace not placed" end
    local status_ok = f.status ~= nil
    local counter_ok, counter = pcall(function() return f.products_finished end)
    if status_ok and counter_ok and type(counter) == "number" then return "ok", "status and products_finished readable" end
    return "warn", "status=" .. tostring(f.status) .. ", products_finished=" .. tostring(counter)
  end)

  check("production_statistics", function()
    local ok1, stats = pcall(function() return a.force.get_item_production_statistics(s) end)
    if not ok1 or not stats then return "fail", "get_item_production_statistics failed" end
    if type(stats.input_counts) ~= "table" then return "fail", "input_counts missing" end
    local has_flow = defines.flow_precision_index ~= nil and stats.get_flow_count ~= nil
    return has_flow and "ok" or "warn", has_flow and "totals and per-minute flow available" or "per-minute flow unavailable"
  end)

  check("craft_by_hand", function()
    local before = bag().get_item_count("iron-gear-wheel")
    local r = Basic.craft("iron-gear-wheel", 1)
    if not good(r) then return "fail", "craft: " .. tostring(r) end
    if bag().get_item_count("iron-gear-wheel") ~= before + 1 then return "fail", "gear count did not rise" end
    return "ok", "instant hand crafting works"
  end)

  check("hand_mining", function()
    for _, what in ipairs { "wood", "stone", "coal" } do
      local before = bag().get_item_count(what)
      local r = Basic.gather(what, 1)
      if good(r) and bag().get_item_count(what) > before then return "ok", "mined " .. what .. " with mine_entity" end
    end
    return "skip", "no tree, rock or ore in reach to test mining (try near resources)"
  end)

  check("mining_drill_output", function()
    local r = Basic.build_miner("iron-ore", 1)
    if not good(r) then
      return "skip", "no iron ore reachable or not buildable: " .. tostring(r):sub(1, 120)
    end
    return "ok", "drill placed, output reaches the furnace (checked by build_miner)"
  end)

  check("offshore_pump", function()
    local tiles = s.find_tiles_filtered { position = home, radius = 60, name = C.WATER, limit = 1 }
    if #tiles == 0 then return "skip", "no water within 60 tiles" end
    local p = tiles[1].position
    local r = Basic.build("offshore-pump", px(p), py(p), "auto", 8)
    if good(r) then return "ok", "offshore pump placed on the shore" end
    return "fail", "offshore pump could not be placed: " .. tostring(r):sub(1, 160)
  end)

  check("snapshot", function()
    local r = Map.snapshot(ox, oy, ox + SIZE, oy + SIZE)
    if good(r) and r:find('"entities"', 1, true) then return "ok", "area snapshot works" end
    return "fail", tostring(r):sub(1, 160)
  end)

  check("underground_pair", function()
    local r = require("scripts.underground").build_underground("underground-belt", ox + 1, oy + 11, ox + 5, oy + 11)
    if not good(r) then return "fail", "underground pair failed: " .. tostring(r):sub(1, 200) end
    if not r:find('"paired":true', 1, true) then return "fail", "pair not reported as paired: " .. tostring(r):sub(1, 160) end
    local lone = Basic.build("underground-belt", ox + 1, oy + 13, "east", 0)
    if good(lone) then return "fail", "build placed a single underground belt, it should refuse" end
    return "ok", "pair placed with entrance and exit, pairing checked by the game, single build refused"
  end)

  check("rail_route", function()
    if not defines.rail_direction then return "skip", "this Factorio has no rail API (defines.rail_direction)" end
    local r = Connect.connect("rail", ox + 2, oy + 2, ox + 12, oy + 8, nil, nil, false, true)
    if not good(r) then return "fail", "rail line failed: " .. tostring(r):sub(1, 200) end
    if not r:find('"connected":true', 1, true) then return "fail", "rails placed but not connected: " .. tostring(r):sub(1, 160) end
    local ends = require("scripts.rails").rail_end(ox + 12, oy + 8, 6)
    if not (good(ends) and ends:find('"end_direction"', 1, true)) then return "fail", "rail_end found no open end: " .. tostring(ends):sub(1, 160) end
    local r2 = Connect.connect("rail", ox + 12, oy + 8, ox + 2, oy + 12, nil, nil, false, true)
    if not good(r2) then return "warn", "first line ok, continuing it failed: " .. tostring(r2):sub(1, 160) end
    return "ok", "rail line routed, verified by the game, open end found and continued"
  end)

  check("chat_event", function()
    local ok1 = defines.events and defines.events.on_console_chat ~= nil
    local ok2 = type(game.get_player) == "function"
    if ok1 and ok2 then return "ok", "on_console_chat and get_player exist" end
    return "fail", "chat event or get_player missing"
  end)

  check("save_game", function()
    local ok1, err = pcall(function() game.server_save("fac_agent_selftest") end)
    if ok1 then return "ok", "server_save works (file fac_agent_selftest)" end
    local ok2 = pcall(function() game.auto_save("fac_agent_selftest") end)
    if ok2 then return "ok", "auto_save works" end
    return "warn", "saving failed (needs a multiplayer server): " .. tostring(err):sub(1, 100)
  end)

  -- clean up: remove everything new, restore inventory and position
  for _, e in ipairs(s.find_entities_filtered { force = a.force }) do
    if e.valid and e.unit_number and not before_ids[e.unit_number] and e.type ~= "character" then e.destroy() end
  end
  local inv2 = bag()
  for name, n in pairs(C.counts(inv2)) do inv2.remove { name = name, count = n } end
  for name, n in pairs(saved) do inv2.insert { name = name, count = n } end
  pcall(function() a.teleport(home) end)

  local summary = { ok = 0, fail = 0, skip = 0, warn = 0 }
  for _, r in ipairs(results) do summary[r.s] = (summary[r.s] or 0) + 1 end
  return done { area = { x = ox, y = oy, size = SIZE }, results = results, summary = summary, version = "0.3.1" }
end

return M

-- Tiny fake of the Factorio 2.0 runtime API, just enough to execute mod/fac_agent.
-- It checks the logic of the mod (orientation search, read-back, routing, snapshots, ...).
-- It does NOT prove that the real engine behaves the same way.

mock = {}

local SIZES = {
  ["burner-mining-drill"] = 2, ["stone-furnace"] = 2, ["assembling-machine-1"] = 3,
  ["rock-huge"] = 2, ["rock-big"] = 2, ["character"] = 0.8, ["tree"] = 0.8, ["rocket-silo"] = 9,
}
local NO_DIRECTION = {
  ["stone-furnace"] = true, ["wooden-chest"] = true, ["tree"] = true, ["rock-big"] = true,
  ["rock-huge"] = true, ["pipe"] = true, ["small-electric-pole"] = true, ["rocket-silo"] = true,
}
local FUEL = { coal = true, wood = true }
local SMELT_INPUT = { ["iron-ore"] = true, ["copper-ore"] = true, stone = true }
local WIRE_REACH = 7.5

defines = {
  direction = { north = 0, east = 4, south = 8, west = 12 },
  inventory = { fuel = 1, furnace_source = 2, furnace_result = 3, crafter_input = 5, crafter_output = 6, chest = 7 },
  entity_status = { working = 1, no_fuel = 2, no_power = 3, no_minable_resources = 4 },
}

local world = { entities = {}, water = {}, tiles = {}, spilled = {}, messages = {}, production = {}, next_unit = 0 }
mock.world = world
storage = {}
local forces = {}

----------------------------------------------------------------------------- json
local function is_array(t)
  local n = 0
  for _ in pairs(t) do n = n + 1 end
  if n == 0 then return true end
  for i = 1, n do if t[i] == nil then return false end end
  return true
end

local function encode(v)
  local tv = type(v)
  if tv == "nil" then return "null" end
  if tv == "boolean" then return tostring(v) end
  if tv == "number" then return string.format("%.14g", v) end
  if tv == "string" then
    return '"' .. v:gsub('[%c"\\]', function(c)
      return string.format("\\u%04x", c:byte())
    end) .. '"'
  end
  if is_array(v) then
    local parts = {}
    for i = 1, #v do parts[i] = encode(v[i]) end
    return "[" .. table.concat(parts, ",") .. "]"
  end
  local parts = {}
  for k, val in pairs(v) do parts[#parts + 1] = encode(tostring(k)) .. ":" .. encode(val) end
  return "{" .. table.concat(parts, ",") .. "}"
end
helpers = { table_to_json = encode }

----------------------------------------------------------------------------- inventory
local function new_inventory(max_items)
  local inv = { items = {}, max_items = max_items }
  local function total()
    local n = 0
    for _, c in pairs(inv.items) do n = n + c end
    return n
  end
  function inv.get_contents()
    local out = {}
    for name, count in pairs(inv.items) do
      if count > 0 then out[#out + 1] = { name = name, count = count, quality = "normal" } end
    end
    return out
  end
  function inv.total() return total() end
  function inv.get_item_count(name) return inv.items[name] or 0 end
  function inv.insert(stack)
    local n = stack.count or 1
    if inv.max_items then n = math.max(0, math.min(n, inv.max_items - total())) end
    inv.items[stack.name] = (inv.items[stack.name] or 0) + n
    return n
  end
  function inv.remove(stack)
    local have = inv.items[stack.name] or 0
    local n = math.min(have, stack.count or 1)
    inv.items[stack.name] = have - n
    return n
  end
  return inv
end

----------------------------------------------------------------------------- geometry
local function size_of(name) return SIZES[name] or 1 end

local function box(name, pos)
  local s = size_of(name)
  return pos.x - s / 2, pos.y - s / 2, pos.x + s / 2, pos.y + s / 2
end

local function overlap(a1, b1, a2, b2, c1, d1, c2, d2)
  local eps = 1e-6
  return a1 < c2 - eps and a2 > c1 + eps and b1 < d2 - eps and b2 > d1 + eps
end

local function colliding(e) return e.valid and e.type ~= "resource" and e.type ~= "corpse" end

local function is_water_tile(tx, ty)
  for _, w in ipairs(world.water) do
    if w.x == tx and w.y == ty then return true end
  end
  return false
end

local function water_at(x1, y1, x2, y2)
  for tx = math.floor(x1), math.floor(x2 - 1e-6) do
    for ty = math.floor(y1), math.floor(y2 - 1e-6) do
      if is_water_tile(tx, ty) then return true end
    end
  end
  return false
end

local surface = {}
local status_of
local VEC = { [0] = { 0, -1 }, [4] = { 1, 0 }, [8] = { 0, 1 }, [12] = { -1, 0 } }

function surface.can_place_entity(args)
  local x1, y1, x2, y2 = box(args.name, args.position)
  if args.name == "offshore-pump" then
    -- must sit on land with water directly in front of it
    local v = VEC[args.direction or 0]
    local tx, ty = math.floor(args.position.x), math.floor(args.position.y)
    if is_water_tile(tx, ty) or not is_water_tile(tx + v[1], ty + v[2]) then return false end
  elseif water_at(x1, y1, x2, y2) then
    return false
  end
  for _, e in ipairs(world.entities) do
    if colliding(e) and e.name ~= "character" then
      local a1, b1, a2, b2 = box(e.name, e.position)
      if overlap(x1, y1, x2, y2, a1, b1, a2, b2) then return false end
    end
  end
  return true
end

local DROP = { [0] = { 0, -1.3 }, [4] = { 1.3, 0 }, [8] = { 0, 1.3 }, [12] = { -1.3, 0 } }

local function refresh_drops()
  for _, e in ipairs(world.entities) do
    if e.valid and e.name == "burner-mining-drill" then
      local v = DROP[e.direction]
      e.drop_position = { x = e.position.x + v[1], y = e.position.y + v[2] }
      e.drop_target = nil
      for _, o in ipairs(world.entities) do
        if o.valid and o ~= e and o.type ~= "resource" and o.type ~= "character" then
          local a1, b1, a2, b2 = box(o.name, o.position)
          local p = e.drop_position
          if p.x >= a1 and p.x <= a2 and p.y >= b1 and p.y <= b2 then e.drop_target = o end
        end
      end
    end
  end
end

local function snap(name, x, y)
  if size_of(name) % 2 == 0 and size_of(name) >= 2 then return math.floor(x + 0.5), math.floor(y + 0.5) end
  return math.floor(x) + 0.5, math.floor(y) + 0.5
end

----------------------------------------------------------------------------- entities
local function belt_at(x, y)
  for _, o in ipairs(world.entities) do
    if o.valid and o.type == "transport-belt" and math.floor(o.position.x) == math.floor(x) and math.floor(o.position.y) == math.floor(y) then
      return o
    end
  end
  return nil
end

local function pole_component(start)
  local seen, queue, qi = { [start] = true }, { start }, 1
  while qi <= #queue do
    local cur = queue[qi]
    qi = qi + 1
    for _, o in ipairs(world.entities) do
      if o.valid and o.type == "electric-pole" and not seen[o] then
        local dx, dy = o.position.x - cur.position.x, o.position.y - cur.position.y
        if math.sqrt(dx * dx + dy * dy) <= WIRE_REACH then
          seen[o] = true
          queue[#queue + 1] = o
        end
      end
    end
  end
  return queue
end

local function make_entity(name, etype, pos, dir, force)
  world.next_unit = world.next_unit + 1
  local d = {
    name = name, type = etype, position = { x = pos.x or pos[1], y = pos.y or pos[2] },
    direction = dir or 0, valid = true, force = force or forces.player, unit_number = world.next_unit,
    rotatable = not NO_DIRECTION[name] and name ~= "assembling-machine-1",
    supports_direction = not NO_DIRECTION[name], health = 200,
  }
  if etype == "assembling-machine" then d.direction = 0 end
  local inv_by_index = {}
  if etype == "furnace" or name == "burner-mining-drill" then
    d.fuel = new_inventory()
    inv_by_index[1] = d.fuel
  end
  if etype == "furnace" or etype == "assembling-machine" then d.products_finished = 0 end
  if etype == "furnace" then
    d.source = new_inventory(); d.output = new_inventory()
    inv_by_index[2] = d.source; inv_by_index[3] = d.output
  end
  if etype == "assembling-machine" then
    d.source = new_inventory(); d.output = new_inventory()
    inv_by_index[5] = d.source; inv_by_index[6] = d.output
  end
  if etype == "container" then
    d.chest = new_inventory()
    inv_by_index[7] = d.chest
  end

  if etype == "transport-belt" then
    d.lines = { new_inventory(), new_inventory() }
    for _, line in ipairs(d.lines) do
      function line.insert_at_back(stack)
        if line.total() >= 4 then return false end
        line.insert(stack)
        return true
      end
    end
    function d.get_transport_line(i) return d.lines[i] end
  end

  local e
  e = setmetatable({}, {
    __index = function(_, k)
      if k == "status" then return status_of(d) end
      if k == "belt_neighbours" and d.type == "transport-belt" then
        local v = VEC[d.direction]
        local outs, ins = {}, {}
        local nxt = belt_at(d.position.x + v[1], d.position.y + v[2])
        if nxt then outs[1] = nxt end
        for dir, vec in pairs(VEC) do
          local o = belt_at(d.position.x + vec[1], d.position.y + vec[2])
          if o and o ~= e and VEC[o.direction][1] == -vec[1] and VEC[o.direction][2] == -vec[2] and dir ~= nil then
            ins[#ins + 1] = o
          end
        end
        return { inputs = ins, outputs = outs }
      end
      if k == "electric_network_id" and d.type == "electric-pole" then
        local best = d.unit_number
        for _, o in ipairs(pole_component(e)) do best = math.min(best, o.unit_number) end
        return best
      end
      return d[k]
    end,
    __newindex = function(_, k, v)
      if k == "direction" then
        if d.type == "assembling-machine" then
          if d.recipe ~= "chemical-test" then return end
        elseif not d.rotatable then
          return
        end
      end
      d[k] = v
    end,
  })
  d.self = e
  function d.destroy()
    d.valid = false
    for i, o in ipairs(world.entities) do if o == e then table.remove(world.entities, i); break end end
    refresh_drops()
    return true
  end
  function d.mine(args)
    local inv = args.inventory
    inv.insert { name = d.name, count = 1 }
    for _, held in pairs(inv_by_index) do
      for _, c in pairs(held.get_contents()) do inv.insert { name = c.name, count = c.count } end
    end
    d.destroy()
    return true
  end
  function d.get_fuel_inventory() return d.fuel end
  function d.get_output_inventory() return d.output end
  function d.get_max_inventory_index()
    if next(inv_by_index) then return 7 end
    return 0
  end
  function d.get_inventory(id) return inv_by_index[id] end
  function d.insert(stack)
    if FUEL[stack.name] and d.fuel then return d.fuel.insert(stack) end
    if d.source and (SMELT_INPUT[stack.name] or etype == "assembling-machine") then return d.source.insert(stack) end
    if d.chest then return d.chest.insert(stack) end
    return 0
  end
  function d.get_recipe() return d.recipe and { name = d.recipe } or nil end
  function d.set_recipe(rname) d.recipe = rname; return {} end
  function d.launch_rocket() return d.ready == true end
  return e, d
end

status_of = function(d)
  if d.fuel then
    if d.fuel.get_item_count("coal") + d.fuel.get_item_count("wood") == 0 then return defines.entity_status.no_fuel end
    return defines.entity_status.working
  end
  return nil
end

local function register(name, etype, pos, dir, force)
  local e, d = make_entity(name, etype, pos, dir, force)
  world.entities[#world.entities + 1] = e
  refresh_drops()
  return e, d
end

local TYPES = {
  ["stone-furnace"] = "furnace", ["burner-mining-drill"] = "mining-drill", ["wooden-chest"] = "container",
  ["transport-belt"] = "transport-belt", ["underground-belt"] = "underground-belt", ["pipe"] = "pipe",
  ["small-electric-pole"] = "electric-pole", ["inserter"] = "inserter", ["offshore-pump"] = "offshore-pump",
  ["rocket-silo"] = "rocket-silo",
}
local function entity_type_for(name)
  if TYPES[name] then return TYPES[name] end
  if name:find("assembling-machine", 1, true) then return "assembling-machine" end
  return "simple-entity-with-owner"
end

local function match_name(filter, name)
  if filter == nil then return true end
  if type(filter) == "string" then return filter == name end
  for _, n in ipairs(filter) do if n == name then return true end end
  return false
end

local function force_name(f)
  if f == nil then return nil end
  if type(f) == "string" then return f end
  return f.name
end

function surface.find_entities_filtered(args)
  local out = {}
  for _, e in ipairs(world.entities) do
    local ok = e.valid and match_name(args.name, e.name)
    if ok and args.type and e.type ~= args.type then ok = false end
    if ok and args.force and e.force.name ~= force_name(args.force) then ok = false end
    if ok and args.position and args.radius then
      local dx, dy = e.position.x - (args.position.x or args.position[1]), e.position.y - (args.position.y or args.position[2])
      if math.sqrt(dx * dx + dy * dy) > args.radius then ok = false end
    end
    if ok and args.area then
      local a = args.area
      if e.position.x < a[1][1] or e.position.x > a[2][1] or e.position.y < a[1][2] or e.position.y > a[2][2] then ok = false end
    end
    if ok then out[#out + 1] = e end
  end
  return out
end

function surface.find_tiles_filtered(args)
  local out = {}
  if args.area then
    local a = args.area
    for tx = math.floor(a[1][1]), math.ceil(a[2][1]) - 1 do
      for ty = math.floor(a[1][2]), math.ceil(a[2][2]) - 1 do
        local name = world.tiles[tx .. ":" .. ty] or (is_water_tile(tx, ty) and "water" or "grass-1")
        if match_name(args.name, name) then
          out[#out + 1] = { name = name, position = { x = tx + 0.5, y = ty + 0.5 } }
        end
      end
    end
    return out
  end
  local px, py = args.position.x or args.position[1], args.position.y or args.position[2]
  for _, w in ipairs(world.water) do
    local dx, dy = w.x + 0.5 - px, w.y + 0.5 - py
    if math.sqrt(dx * dx + dy * dy) <= args.radius then
      out[#out + 1] = { name = "water", position = { x = w.x + 0.5, y = w.y + 0.5 } }
      if args.limit and #out >= args.limit then break end
    end
  end
  return out
end

function surface.find_non_colliding_position(name, center, radius, precision, force_to_tile_center)
  local cx, cy = center.x or center[1], center.y or center[2]
  precision = precision or 0.5
  local steps = math.floor(radius / precision)
  local candidates = {}
  for ix = -steps, steps do
    for iy = -steps, steps do
      candidates[#candidates + 1] = { x = cx + ix * precision, y = cy + iy * precision, d = ix * ix + iy * iy }
    end
  end
  table.sort(candidates, function(a, b) return a.d < b.d end)
  for _, c in ipairs(candidates) do
    local x, y = c.x, c.y
    if force_to_tile_center then x, y = snap(name, x, y) end
    if surface.can_place_entity { name = name, position = { x = x, y = y } } then return { x = x, y = y } end
  end
  return nil
end

function surface.spill_item_stack(args) world.spilled[#world.spilled + 1] = args.stack end

function surface.create_entity(args)
  if args.name ~= "character" and not surface.can_place_entity(args) then return nil end
  local pos = args.position
  local etype = args.name == "character" and "character" or entity_type_for(args.name)
  local e, d = register(args.name, etype, pos, args.direction or 0, args.force and forces[force_name(args.force)] or forces.player)
  if args.name == "character" then
    d.inventory = new_inventory()
    d.prototype = { crafting_categories = { crafting = true } }
    d.get_main_inventory = function() return d.inventory end
    d.teleport = function(p)
      d.position = { x = p.x or p[1], y = p.y or p[2] }
      return true
    end
    d.mine_entity = function(target, force)
      local dx, dy = target.position.x - d.position.x, target.position.y - d.position.y
      if math.sqrt(dx * dx + dy * dy) > 2.7 then return false end
      local inv = d.inventory
      if target.type == "resource" then
        inv.insert { name = target.name, count = 1 }
        target.amount = target.amount - 1
        if target.amount <= 0 then target.destroy() end
      elseif target.type == "tree" then
        inv.insert { name = "wood", count = 4 }
        target.destroy()
      elseif target.name:find("^rock") or target.name:find("sand%-rock") then
        inv.insert { name = "stone", count = 10 }
        inv.insert { name = "coal", count = 10 }
        target.destroy()
      else
        return false
      end
      return true
    end
  end
  return e
end

----------------------------------------------------------------------------- forces, recipes
local function recipe(name, category, ingredients, products, enabled)
  local ing = {}
  for _, p in ipairs(ingredients) do ing[#ing + 1] = { type = "item", name = p[1], amount = p[2] } end
  local prod = {}
  for _, p in ipairs(products) do prod[#prod + 1] = { type = "item", name = p[1], amount = p[2] } end
  return { name = name, category = category, ingredients = ing, products = prod, enabled = enabled ~= false, energy = 0.5 }
end

local recipes = {
  ["wooden-chest"] = recipe("wooden-chest", "crafting", { { "wood", 2 } }, { { "wooden-chest", 1 } }),
  ["iron-gear-wheel"] = recipe("iron-gear-wheel", "crafting", { { "iron-plate", 2 } }, { { "iron-gear-wheel", 1 } }),
  ["stone-furnace"] = recipe("stone-furnace", "crafting", { { "stone", 5 } }, { { "stone-furnace", 1 } }),
  ["burner-mining-drill"] = recipe("burner-mining-drill", "crafting",
    { { "iron-gear-wheel", 3 }, { "iron-plate", 3 }, { "stone-furnace", 1 } }, { { "burner-mining-drill", 1 } }),
  ["iron-plate"] = recipe("iron-plate", "smelting", { { "iron-ore", 1 } }, { { "iron-plate", 1 } }),
  ["chemical-test"] = {
    name = "chemical-test", category = "crafting", enabled = true, energy = 1,
    ingredients = { { type = "fluid", name = "water", amount = 10 } }, products = { { type = "item", name = "stone", amount = 1 } },
  },
  ["assembling-machine-1"] = recipe("assembling-machine-1", "crafting", { { "iron-plate", 9 } }, { { "assembling-machine-1", 1 } }, false),
}

local technologies = {
  automation = { name = "automation", enabled = true, researched = false, prerequisites = {},
    research_unit_count = 10, research_unit_ingredients = { { name = "automation-science-pack", amount = 1 } }, saved_progress = 0 },
  logistics = { name = "logistics", enabled = true, researched = false, prerequisites = {},
    research_unit_count = 20, research_unit_ingredients = { { name = "automation-science-pack", amount = 1 } }, saved_progress = 0.5 },
  ["electronics"] = { name = "electronics", enabled = true, researched = false, prerequisites = { { researched = false } },
    research_unit_count = 30, research_unit_ingredients = { { name = "automation-science-pack", amount = 1 } }, saved_progress = 0 },
}

forces.player = { name = "player", recipes = recipes, technologies = technologies, current_research = nil, research_progress = 0 }
forces.enemy = { name = "enemy", recipes = {}, technologies = {} }
forces.neutral = { name = "neutral", recipes = {}, technologies = {} }
function forces.player.add_research(name)
  local t = technologies[name]
  if not t then return false end
  for _, pre in ipairs(t.prerequisites) do if not pre.researched then return false end end
  forces.player.current_research = t
  return true
end
function forces.player.get_item_production_statistics(_surface)
  return { input_counts = world.production }
end

game = {
  tick = 0, surfaces = { nauvis = surface }, forces = forces, speed = 1,
  get_player = function(i) return { name = (game.players and game.players[i]) or '?' } end,
  server_save = function(name) world.saved = name end,
  print = function(message, color) world.messages[#world.messages + 1] = message end,
}

prototypes = { entity = {} }
for _, n in ipairs { "stone-furnace", "burner-mining-drill", "wooden-chest", "transport-belt", "underground-belt", "inserter",
  "assembling-machine-1", "pipe", "small-electric-pole", "offshore-pump", "rocket-silo" } do
  prototypes.entity[n] = {
    supports_direction = not NO_DIRECTION[n],
    items_to_place_this = { { name = n, count = 1 } },
    tile_width = SIZES[n] or 1, tile_height = SIZES[n] or 1,
  }
end
prototypes.entity["small-electric-pole"].get_max_wire_distance = function() return WIRE_REACH end

----------------------------------------------------------------------------- remote / script
local interfaces = {}
remote = {
  add_interface = function(name, funcs) interfaces[name] = funcs end,
  call = function(name, fn, ...)
    local iface = interfaces[name]
    if not iface then error("Unknown interface: " .. name) end
    if not iface[fn] then error("Interface " .. name .. " has no function " .. fn) end
    return iface[fn](...)
  end,
}
script = {
  on_init = function(f) mock.on_init = f end,
  on_event = function(id, f) mock.events = mock.events or {}; mock.events[id] = f end,
}
defines.events = { on_console_chat = 1 }
function mock.chat(player, text)
  game.players = game.players or {}
  game.get_player = function(i) return { name = (game.players[i] or "?") } end
  game.players[1] = player
  mock.events[1]({ player_index = 1, message = text })
end

local printed = {}
rcon = { print = function(s) printed[#printed + 1] = tostring(s) end }
function mock.take_output()
  local s = table.concat(printed)
  printed = {}
  return s
end

----------------------------------------------------------------------------- scenario helpers
function mock.reset()
  for i = #world.entities, 1, -1 do world.entities[i] = nil end
  world.water = {}
  world.tiles = {}
  world.spilled = {}
  world.messages = {}
  world.production = {}
  storage.agent = nil
  forces.player.current_research = nil
  forces.player.research_progress = 0
  game.speed = 1
  printed = {}
end

function mock.add_resource(name, x, y, amount)
  local e = register(name, "resource", { x = x + 0.5, y = y + 0.5 }, 0, forces.neutral)
  e.amount = amount or 100
  return e
end

function mock.add_patch(name, x1, y1, x2, y2, amount)
  for x = x1, x2 do for y = y1, y2 do mock.add_resource(name, x, y, amount) end end
end

function mock.add_tree(x, y) return register("tree", "tree", { x = x, y = y }, 0, forces.neutral) end
function mock.add_rock(x, y) return register("rock-big", "simple-entity", { x = x, y = y }, 0, forces.neutral) end
function mock.add_water(x, y) world.water[#world.water + 1] = { x = x, y = y } end
function mock.set_tile(x, y, name) world.tiles[x .. ":" .. y] = name end

function mock.add_entity(name, x, y, dir)
  return register(name, entity_type_for(name), { x = x, y = y }, dir or 0, forces.player)
end

function mock.add_enemy(x, y)
  return register("small-biter", "unit", { x = x, y = y }, 0, forces.enemy)
end

function mock.give(name, count)
  local a = storage.agent
  if not (a and a.valid) then
    a = surface.create_entity { name = "character", position = { x = 0, y = 0 }, force = "player" }
    storage.agent = a
  end
  a.get_main_inventory().insert { name = name, count = count }
end

function mock.inventory_count(name)
  local a = storage.agent
  return a.get_main_inventory().get_item_count(name)
end

function mock.entity_count(name)
  local n = 0
  for _, e in ipairs(world.entities) do if e.valid and e.name == name then n = n + 1 end end
  return n
end

function mock.first(name)
  for _, e in ipairs(world.entities) do
    if e.valid and e.name == name then return e end
  end
  return nil
end

function mock.status_of(e) return status_of(e) end


-- move every item on every belt one tile along its direction (one "step" = 8 ticks)
function mock.advance(ticks)
  local steps = math.max(1, math.floor((ticks or 8) / 8))
  for _ = 1, steps do
    local moves = {}
    for _, e in ipairs(world.entities) do
      if e.valid and e.type == "transport-belt" then
        local nb = e.belt_neighbours.outputs[1]
        if nb then
          for i = 1, 2 do
            for _, it in ipairs(e.get_transport_line(i).get_contents()) do
              moves[#moves + 1] = { from = e, to = nb, line = i, name = it.name, count = it.count }
            end
          end
        end
      end
    end
    for _, m in ipairs(moves) do
      if m.to.get_transport_line(m.line).insert_at_back { name = m.name, count = m.count } then
        m.from.get_transport_line(m.line).remove { name = m.name, count = m.count }
      end
    end
  end
  game.tick = game.tick + (ticks or 8)
end

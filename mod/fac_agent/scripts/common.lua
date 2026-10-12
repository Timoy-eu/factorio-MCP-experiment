-- Shared helpers for the fac_agent modules.
local C = {}

C.DIRS = {
  north = defines.direction.north, east = defines.direction.east,
  south = defines.direction.south, west = defines.direction.west,
}
C.DIR_NAME = {}
for name, value in pairs(C.DIRS) do C.DIR_NAME[value] = name end
C.VEC = { north = { 0, -1 }, east = { 1, 0 }, south = { 0, 1 }, west = { -1, 0 } }
C.ORDER = { "north", "east", "south", "west" }

C.STATUS_NAME = {}
for name, value in pairs(defines.entity_status or {}) do C.STATUS_NAME[value] = name end
C.INV_NAME = {}
for name, value in pairs(defines.inventory or {}) do C.INV_NAME[value] = C.INV_NAME[value] or name end

C.MINE_REACH = 2.5
C.BUILD_STANDOFF = 3
C.ROCKS = { "rock-huge", "rock-big", "sand-rock-big" }
C.WATER = { "water", "deepwater", "water-green", "deepwater-green", "water-shallow", "water-mud" }

-- item that can be mined by hand -> list of entity filters to look for (first hit wins)
C.SOURCES = {
  ["wood"] = { { type = "tree" } },
  ["stone"] = { { name = "stone" }, { name = C.ROCKS } },
  ["coal"] = { { name = "coal" }, { name = C.ROCKS } },
  ["iron-ore"] = { { name = "iron-ore" } },
  ["copper-ore"] = { { name = "copper-ore" } },
  ["uranium-ore"] = { { name = "uranium-ore" } },
}

function C.json(t) return helpers.table_to_json(t) end

function C.fail(code, message, extra)
  local t = extra or {}
  t.ok = false
  t.code = code
  t.message = message
  return C.json(t)
end

function C.done(t)
  t = t or {}
  t.ok = true
  return C.json(t)
end

function C.surf() return game.surfaces["nauvis"] end

function C.agent()
  local a = storage.agent
  if a and a.valid then return a end
  local s = C.surf()
  local function make()
    local pos = s.find_non_colliding_position("character", { 0, 0 }, 30, 0.5) or { 0, 0 }
    return s.create_entity { name = "character", position = pos, force = "player" }
  end
  a = make()
  if not a then
    -- without players the start area may not be generated yet
    pcall(function()
      s.request_to_generate_chunks({ 0, 0 }, 3)
      s.force_generate_chunk_requests()
    end)
    a = make()
  end
  if not a then error("cannot create the agent character at the map origin (start area not generated?)") end
  storage.agent = a
  return a
end

function C.bag() return C.agent().get_main_inventory() end

function C.counts(inventory)
  local t = {}
  for _, c in pairs(inventory.get_contents()) do t[c.name] = (t[c.name] or 0) + c.count end
  return t
end

function C.px(pos) return pos.x or pos[1] end
function C.py(pos) return pos.y or pos[2] end
function C.dist(a, b)
  local dx, dy = C.px(a) - C.px(b), C.py(a) - C.py(b)
  return math.sqrt(dx * dx + dy * dy)
end
function C.r1(n) return math.floor(n * 10 + 0.5) / 10 end
function C.pt(pos) return { x = C.r1(C.px(pos)), y = C.r1(C.py(pos)) } end

function C.copy(t)
  local c = {}
  for k, v in pairs(t) do c[k] = v end
  return c
end

function C.nearest(filter, origin, radii)
  for _, r in ipairs(radii or { 40, 120, 250 }) do
    local f = C.copy(filter)
    f.position = origin
    f.radius = r
    local best, bestd
    for _, e in pairs(C.surf().find_entities_filtered(f)) do
      if e.valid then
        local d = C.dist(origin, e.position)
        if not bestd or d < bestd then best, bestd = e, d end
      end
    end
    if best then return best, bestd end
  end
  return nil
end

-- teleport the agent next to a target (never onto it)
function C.move_near(target, reach)
  local a = C.agent()
  if C.dist(a.position, target) <= (reach or C.MINE_REACH) then return true end
  local spot = C.surf().find_non_colliding_position("character", target, 3, 0.5)
  if not spot then return false end
  return a.teleport(spot)
end

-- stand a few tiles away from a build site so the character never blocks the footprint
function C.stand_off(target)
  local a = C.agent()
  local s = C.surf()
  local d0 = C.dist(a.position, target)
  if d0 >= C.BUILD_STANDOFF and d0 <= 10 then return true end
  for _, d in ipairs(C.ORDER) do
    local v = C.VEC[d]
    local want = { x = C.px(target) + v[1] * C.BUILD_STANDOFF, y = C.py(target) + v[2] * C.BUILD_STANDOFF }
    local spot = s.find_non_colliding_position("character", want, 1.5, 0.5)
    if spot and C.dist(spot, target) >= C.BUILD_STANDOFF - 0.5 then return a.teleport(spot) end
  end
  return false
end

function C.item_for(entity_name)
  local proto = prototypes.entity[entity_name]
  if not proto then return nil end
  local items = proto.items_to_place_this
  if items and items[1] then
    local first = items[1]
    if type(first) == "string" then return first end
    return first.name
  end
  return entity_name
end

-- tile footprint (width, height) of an entity prototype
function C.entity_size(name)
  local proto = prototypes.entity[name]
  if proto then
    local w, h = proto.tile_width, proto.tile_height
    if w and h then return w, h end
    local box = proto.collision_box
    if box then
      local lt, rb = box.left_top or box[1], box.right_bottom or box[2]
      return math.max(1, math.ceil(C.px(rb) - C.px(lt))), math.max(1, math.ceil(C.py(rb) - C.py(lt)))
    end
  end
  return 1, 1
end

-- snap a free coordinate to a valid centre for a w x h footprint
function C.snap_dims(w, h, x, y)
  local function a(v, s)
    if s % 2 == 1 then return math.floor(v) + 0.5 end
    return math.floor(v + 0.5)
  end
  return a(x, w), a(y, h)
end

function C.snap_center(name, x, y)
  local w, h = C.entity_size(name)
  return C.snap_dims(w, h, x, y)
end

function C.own_entity_at(x, y)
  local a = C.agent()
  local area = { { x - 0.5, y - 0.5 }, { x + 0.5, y + 0.5 } }
  local best, bestd
  for _, e in pairs(C.surf().find_entities_filtered { area = area, force = a.force }) do
    if e.valid and e.type ~= "character" then
      local d = C.dist({ x = x, y = y }, e.position)
      if not bestd or d < bestd then best, bestd = e, d end
    end
  end
  return best
end

function C.blockers_at(pos)
  local list = {}
  local area = { { C.px(pos) - 1.5, C.py(pos) - 1.5 }, { C.px(pos) + 1.5, C.py(pos) + 1.5 } }
  for _, e in pairs(C.surf().find_entities_filtered { area = area }) do
    if e.valid and e.type ~= "character" and e.type ~= "resource" and e.type ~= "corpse" then
      list[#list + 1] = e.name
    end
  end
  return list
end

function C.direction_name(e)
  return C.DIR_NAME[e.direction] or tostring(e.direction)
end

function C.try_place(name, pos, dir_name)
  local a = C.agent()
  local d = C.DIRS[dir_name or "north"]
  if not C.surf().can_place_entity { name = name, position = pos, direction = d, force = a.force } then return nil end
  return C.surf().create_entity { name = name, position = pos, direction = d, force = a.force, raise_built = true }
end

function C.has_inventory_api(e)
  local ok, n = pcall(function() return e.get_max_inventory_index() end)
  return ok and n ~= nil and n > 0
end

-- all inventories of an entity as {inventory_name = {item = count}}
function C.entity_inventories(e)
  local out = {}
  local ok, n = pcall(function() return e.get_max_inventory_index() end)
  if not ok or not n then return out end
  for i = 1, n do
    local inv = e.get_inventory(i)
    if inv then
      local c = C.counts(inv)
      if next(c) then out[C.INV_NAME[i] or tostring(i)] = c end
    end
  end
  return out
end

return C

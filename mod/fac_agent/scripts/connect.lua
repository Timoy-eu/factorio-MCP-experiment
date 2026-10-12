-- connect: belts and pipes along a routed path, power poles along a straight line
local C = require("scripts.common")
local M = {}

local fail, done = C.fail, C.done
local surf, agent, bag = C.surf, C.agent, C.bag
local px, py, dist, r1 = C.px, C.py, C.dist, C.r1
local DIRS, VEC = C.DIRS, C.VEC

local DEFAULT_ENTITY = { belt = "transport-belt", pipe = "pipe", power = "small-electric-pole" }
local STEPS = { { 1, 0, "east" }, { -1, 0, "west" }, { 0, 1, "south" }, { 0, -1, "north" } }
local NODE_LIMIT = 8000
local MARGIN = 12

----------------------------------------------------------------------------- binary heap
local function heap_push(h, item)
  h[#h + 1] = item
  local i = #h
  while i > 1 do
    local p = math.floor(i / 2)
    if h[p].f <= h[i].f then break end
    h[p], h[i] = h[i], h[p]
    i = p
  end
end

local function heap_pop(h)
  local top = h[1]
  local last = h[#h]
  h[#h] = nil
  local n = #h
  if n > 0 then
    h[1] = last
    local i = 1
    while true do
      local l, r, m = i * 2, i * 2 + 1, i
      if l <= n and h[l].f < h[m].f then m = l end
      if r <= n and h[r].f < h[m].f then m = r end
      if m == i then break end
      h[m], h[i] = h[i], h[m]
      i = m
    end
  end
  return top
end

----------------------------------------------------------------------------- A* over tiles
-- tile state: 1 = free, 2 = already holds this entity, 0 = blocked
local function route(entity, sx, sy, ex, ey, allow_reuse)
  local s, a = surf(), agent()
  local minx, maxx = math.min(sx, ex) - MARGIN, math.max(sx, ex) + MARGIN
  local miny, maxy = math.min(sy, ey) - MARGIN, math.max(sy, ey) + MARGIN
  local cache = {}
  local function state(tx, ty)
    local key = tx .. ":" .. ty
    local v = cache[key]
    if v == nil then
      local pos = { x = tx + 0.5, y = ty + 0.5 }
      if s.can_place_entity { name = entity, position = pos, force = a.force } then
        v = 1
      elseif #s.find_entities_filtered { name = entity, position = pos, radius = 0.4, force = a.force } > 0 then
        v = 2
      else
        v = 0
      end
      cache[key] = v
    end
    return v
  end
  local function usable(tx, ty)
    local v = state(tx, ty)
    return v == 1 or (v == 2 and allow_reuse)
  end
  if not usable(sx, sy) then return nil, "start" end
  if not usable(ex, ey) then return nil, "end" end

  local open, g, came, dir_of, closed = {}, {}, {}, {}, {}
  local skey = sx .. ":" .. sy
  g[skey] = 0
  heap_push(open, { f = math.abs(sx - ex) + math.abs(sy - ey), x = sx, y = sy })
  local expanded = 0
  while #open > 0 do
    local cur = heap_pop(open)
    local ckey = cur.x .. ":" .. cur.y
    if not closed[ckey] then
      closed[ckey] = true
      if cur.x == ex and cur.y == ey then
        local path, k = {}, ckey
        while k do
          local tx, ty = k:match("^(-?%d+):(-?%d+)$")
          table.insert(path, 1, { x = tonumber(tx), y = tonumber(ty), reused = state(tonumber(tx), tonumber(ty)) == 2 })
          k = came[k]
        end
        return path
      end
      expanded = expanded + 1
      if expanded > NODE_LIMIT then return nil, "limit" end
      for _, st in ipairs(STEPS) do
        local nx, ny = cur.x + st[1], cur.y + st[2]
        if nx >= minx and nx <= maxx and ny >= miny and ny <= maxy and usable(nx, ny) then
          local nkey = nx .. ":" .. ny
          local turn = (dir_of[ckey] and dir_of[ckey] ~= st[3]) and 0.05 or 0
          local cost = g[ckey] + 1 + turn
          if not g[nkey] or cost < g[nkey] then
            g[nkey] = cost
            came[nkey] = ckey
            dir_of[nkey] = st[3]
            heap_push(open, { f = cost + math.abs(nx - ex) + math.abs(ny - ey), x = nx, y = ny })
          end
        end
      end
    end
  end
  return nil, "no_path"
end

local function route_error(where)
  if where == "start" or where == "end" then
    return fail("blocked_endpoint", "the " .. where .. " tile is blocked, pick a free tile next to it", { where = where })
  elseif where == "limit" then
    return fail("no_path", "path search gave up (too far or too many obstacles)")
  end
  return fail("no_path", "no free route between the two points")
end

local function dir_between(a, b)
  if b.x > a.x then return "east" end
  if b.x < a.x then return "west" end
  if b.y > a.y then return "south" end
  return "north"
end

local function rollback(placed)
  local inventory = bag()
  for _, e in ipairs(placed) do
    if e.valid then e.mine { inventory = inventory } end
  end
end

----------------------------------------------------------------------------- belts and pipes

local function connect_path(kind, entity, x1, y1, x2, y2, end_direction, dry_run)
  local item = C.item_for(entity)
  if not item then return fail("unknown_entity", "unknown entity '" .. entity .. "'", { entity = entity }) end
  local sx, sy = math.floor(x1), math.floor(y1)
  local ex, ey = math.floor(x2), math.floor(y2)
  local path, why = route(entity, sx, sy, ex, ey, kind == "pipe")
  if not path then return route_error(why) end
  local needed = 0
  for _, t in ipairs(path) do
    if not t.reused then needed = needed + 1 end
  end
  local inventory = bag()
  local have = inventory.get_item_count(item)
  if dry_run then
    return done { entity = entity, item = item, needed = needed, have = have, length = #path, enough = have >= needed }
  end
  if have < needed then
    return fail("missing", "missing " .. (needed - have) .. " " .. item, { item = item, count = needed - have, needed = needed, have = have })
  end

  C.stand_off({ x = sx + 0.5, y = sy + 0.5 })
  local placed, first, last = {}, nil, nil
  for i, t in ipairs(path) do
    if not t.reused then
      local dname = "north"
      if kind == "belt" then
        if i < #path then
          dname = dir_between(t, path[i + 1])
        else
          dname = end_direction or (i > 1 and dir_between(path[i - 1], t)) or "north"
        end
      end
      if inventory.remove { name = item, count = 1 } ~= 1 then
        rollback(placed)
        return fail("missing", "ran out of " .. item, { item = item })
      end
      local e = C.try_place(entity, { x = t.x + 0.5, y = t.y + 0.5 }, dname)
      if not e then
        inventory.insert { name = item, count = 1 }
        rollback(placed)
        return fail("blocked", "path became blocked at " .. t.x .. "," .. t.y .. "; everything placed was picked up again", { x = t.x, y = t.y })
      end
      placed[#placed + 1] = e
      if kind == "belt" and C.direction_name(e) ~= dname then
        pcall(function() e.direction = DIRS[dname] end)
      end
    end
  end
  first, last = placed[1], placed[#placed]

  local connected = true
  if kind == "belt" and first and last and #placed == #path then
    connected = false
    local cur = first
    for _ = 1, #path + 1 do
      if not cur or not cur.valid then break end
      if cur == last then connected = true; break end
      local nb = cur.belt_neighbours
      cur = nb and nb.outputs and nb.outputs[1] or nil
    end
  end
  return done {
    kind = kind, entity = entity, placed = #placed, length = #path, connected = connected,
    from = { x = path[1].x + 0.5, y = path[1].y + 0.5 }, to = { x = path[#path].x + 0.5, y = path[#path].y + 0.5 },
  }
end

----------------------------------------------------------------------------- power poles

local function wire_reach(entity)
  local proto = prototypes.entity[entity]
  if proto then
    local ok, v = pcall(function() return proto.get_max_wire_distance() end)
    if ok and v then return v end
    if proto.max_wire_distance then return proto.max_wire_distance end
  end
  return 7.5
end

local function connect_power(entity, x1, y1, x2, y2, dry_run)
  local item = C.item_for(entity)
  if not item then return fail("unknown_entity", "unknown entity '" .. entity .. "'", { entity = entity }) end
  local s, a = surf(), agent()
  local reach = wire_reach(entity)
  local step = math.max(1, math.floor(reach))
  local total = dist({ x = x1, y = y1 }, { x = x2, y = y2 })
  local n = math.max(1, math.ceil(total / step))
  local spots = {}
  for i = 0, n do
    local fx = x1 + (x2 - x1) * i / n
    local fy = y1 + (y2 - y1) * i / n
    local cx, cy = C.snap_center(entity, fx, fy)
    spots[#spots + 1] = { x = cx, y = cy }
  end
  local needed = 0
  local plan = {}
  for _, p in ipairs(spots) do
    local existing = s.find_entities_filtered { name = entity, position = p, radius = 0.4, force = a.force }
    if #existing > 0 then
      plan[#plan + 1] = { pos = p, existing = existing[1] }
    else
      plan[#plan + 1] = { pos = p }
      needed = needed + 1
    end
  end
  local inventory = bag()
  local have = inventory.get_item_count(item)
  if dry_run then
    return done { entity = entity, item = item, needed = needed, have = have, length = #spots, enough = have >= needed, reach = reach }
  end
  if have < needed then
    return fail("missing", "missing " .. (needed - have) .. " " .. item, { item = item, count = needed - have, needed = needed, have = have })
  end

  local placed, poles = {}, {}
  for i, p in ipairs(plan) do
    if p.existing then
      poles[#poles + 1] = p.existing
    else
      local pos = p.pos
      if not s.can_place_entity { name = entity, position = pos, force = a.force } then
        -- nudge to a nearby free tile but stay within wire reach of the previous pole
        local alt = s.find_non_colliding_position(entity, pos, 2, 1, true)
        if alt and (#poles == 0 or dist(alt, poles[#poles].position) <= reach) then pos = alt else pos = nil end
      end
      if not pos or inventory.remove { name = item, count = 1 } ~= 1 then
        rollback(placed)
        return fail("blocked", "no free tile for a pole near " .. p.pos.x .. "," .. p.pos.y .. "; everything placed was picked up again", { x = p.pos.x, y = p.pos.y })
      end
      C.stand_off(pos)
      local e = C.try_place(entity, pos, "north")
      if not e then
        inventory.insert { name = item, count = 1 }
        rollback(placed)
        return fail("blocked", "pole placement failed near " .. p.pos.x .. "," .. p.pos.y, { x = p.pos.x, y = p.pos.y })
      end
      placed[#placed + 1] = e
      poles[#poles + 1] = e
    end
  end
  local connected = true
  local id = poles[1] and poles[1].electric_network_id
  for _, e in ipairs(poles) do
    if e.electric_network_id ~= id then connected = false end
  end
  return done {
    kind = "power", entity = entity, placed = #placed, length = #poles, connected = connected, reach = reach,
    from = { x = poles[1].position.x, y = poles[1].position.y },
    to = { x = poles[#poles].position.x, y = poles[#poles].position.y },
  }
end

function M.connect(kind, x1, y1, x2, y2, entity, end_direction, dry_run)
  if not DEFAULT_ENTITY[kind] then
    return fail("bad_kind", "kind must be belt, pipe or power", { kind = kind })
  end
  entity = (entity and entity ~= "") and entity or DEFAULT_ENTITY[kind]
  if end_direction ~= nil and end_direction ~= "" and not DIRS[end_direction] then
    return fail("bad_direction", "end_direction must be north, east, south or west", { direction = end_direction })
  end
  if end_direction == "" then end_direction = nil end
  if kind == "power" then return connect_power(entity, x1, y1, x2, y2, dry_run) end
  return connect_path(kind, entity, x1, y1, x2, y2, end_direction, dry_run)
end

return M

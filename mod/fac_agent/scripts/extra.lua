-- Inspection, placement helpers and misc tools (FLE parity set)
local C = require("scripts.common")
local Basic = require("scripts.basic")
local M = {}

local fail, done = C.fail, C.done
local surf, agent, bag, counts = C.surf, C.agent, C.bag, C.counts
local px, py, dist, r1, pt = C.px, C.py, C.dist, C.r1, C.pt
local DIRS, VEC = C.DIRS, C.VEC
local direction_name, own_entity_at = C.direction_name, C.own_entity_at

local BELT_TYPES = { ["transport-belt"] = true, ["underground-belt"] = true, ["splitter"] = true, ["loader"] = true, ["loader-1x1"] = true }

local function any_entity_at(x, y)
  local area = { { x - 0.5, y - 0.5 }, { x + 0.5, y + 0.5 } }
  local best, bestd
  for _, e in pairs(surf().find_entities_filtered { area = area }) do
    if e.valid and e.type ~= "character" then
      local d = dist({ x = x, y = y }, e.position)
      if not bestd or d < bestd then best, bestd = e, d end
    end
  end
  return best
end

local function pos_of(e) return { x = r1(px(e.position)), y = r1(py(e.position)) } end

----------------------------------------------------------------------------- can_place, nearest_buildable

function M.can_place(entity, x, y, direction)
  local a = agent()
  if not prototypes.entity[entity] then return fail("unknown_entity", "unknown entity '" .. entity .. "'", { entity = entity }) end
  local dname = (direction and direction ~= "" and direction ~= "auto") and direction or "north"
  if not DIRS[dname] then return fail("bad_direction", "direction must be north, east, south, west or auto") end
  local pos = { x = x, y = y }
  if surf().can_place_entity { name = entity, position = pos, direction = DIRS[dname], force = a.force } then
    return done { can_place = true, entity = entity, x = x, y = y, direction = dname }
  end
  local suggestion = surf().find_non_colliding_position(entity, pos, 10, 1, true)
  return done {
    can_place = false, entity = entity, x = x, y = y,
    blocked_by = C.blockers_at(pos), suggestion = suggestion and pt(suggestion) or nil,
  }
end

-- find the nearest free w x h area; with `resource` at least half of the tiles must hold that ore
function M.nearest_buildable(entity, width, height, x, y, resource, radius)
  local a = agent()
  local s = surf()
  local origin = (x ~= nil and y ~= nil) and { x = x, y = y } or a.position
  if entity and not prototypes.entity[entity] then return fail("unknown_entity", "unknown entity '" .. entity .. "'", { entity = entity }) end
  local ew, eh = 1, 1
  if entity then ew, eh = C.entity_size(entity) end
  local w, h = width or ew, height or eh
  radius = math.min(radius or 30, 60)
  local need_cover = resource and math.ceil(w * h / 2) or 0

  local function tiles_free(cx, cy)
    for i = 0, w - 1 do
      for j = 0, h - 1 do
        local pos = { x = cx - w / 2 + i + 0.5, y = cy - h / 2 + j + 0.5 }
        if not s.can_place_entity { name = "wooden-chest", position = pos, force = a.force } then return false end
      end
    end
    return true
  end

  local checked = 0
  local function search()
    for r = 0, radius do
      for dx = -r, r do
        for dy = -r, r do
          if math.max(math.abs(dx), math.abs(dy)) == r then
            checked = checked + 1
            if checked > 3000 then return nil end
            local cx, cy = C.snap_dims(w, h, px(origin) + dx, py(origin) + dy)
            local covered = 0
            if resource then
              covered = #s.find_entities_filtered { name = resource, area = { { cx - w / 2, cy - h / 2 }, { cx + w / 2, cy + h / 2 } } }
            end
            if covered >= need_cover then
              local ok = true
              if entity and w == ew and h == eh then
                ok = s.can_place_entity { name = entity, position = { x = cx, y = cy }, force = a.force }
              else
                ok = tiles_free(cx, cy)
              end
              if ok then return { x = cx, y = cy, covered = covered } end
            end
          end
        end
      end
    end
    return nil
  end

  local found = search()
  if not found then
    return fail("no_site", "no free " .. w .. "x" .. h .. " area within " .. radius .. " tiles" .. (resource and (" on " .. resource) or ""), { width = w, height = h })
  end
  return done {
    x = found.x, y = found.y, width = w, height = h, covered = resource and found.covered or nil,
    left_top = { x = found.x - w / 2, y = found.y - h / 2 }, right_bottom = { x = found.x + w / 2, y = found.y + h / 2 },
    d = r1(dist(origin, found)),
  }
end

-- place an entity adjacent to an existing one (direction = side of the reference), optional gap
function M.build_next_to(entity, rx, ry, side, spacing, facing)
  local ref = own_entity_at(rx, ry)
  if not ref then return fail("no_entity", "no entity of yours at " .. rx .. "," .. ry) end
  if not VEC[side] then return fail("bad_direction", "side must be north, east, south or west", { direction = side }) end
  if not prototypes.entity[entity] then return fail("unknown_entity", "unknown entity '" .. entity .. "'", { entity = entity }) end
  spacing = spacing or 0
  local rw, rh = C.entity_size(ref.name)
  local nw, nh = C.entity_size(entity)
  local v = VEC[side]
  local x = px(ref.position) + v[1] * ((rw + nw) / 2 + spacing)
  local y = py(ref.position) + v[2] * ((rh + nh) / 2 + spacing)
  x, y = C.snap_center(entity, x, y)
  return Basic.build(entity, x, y, facing or "auto", 0)
end

----------------------------------------------------------------------------- entity manipulation

function M.pickup(x, y)
  local e = own_entity_at(x, y)
  if not e then return fail("no_entity", "no entity of yours at " .. x .. "," .. y) end
  local name = e.name
  local inventory = bag()
  local before = counts(inventory)
  if not e.mine { inventory = inventory } then
    return fail("pickup_failed", "could not pick up " .. name, { entity = name })
  end
  local got = {}
  for item, n in pairs(counts(inventory)) do
    local delta = n - (before[item] or 0)
    if delta > 0 then got[item] = delta end
  end
  return done { entity = name, x = x, y = y, got = got }
end

function M.shift_entity(x, y, nx, ny)
  local a = agent()
  local e = own_entity_at(x, y)
  if not e then return fail("no_entity", "no entity of yours at " .. x .. "," .. y) end
  local name = e.name
  local dname = e.supports_direction ~= false and direction_name(e) or "north"
  local recipe = e.get_recipe and e.get_recipe() or nil
  local old = { x = px(e.position), y = py(e.position) }
  local item = C.item_for(name)
  local inventory = bag()
  local before = counts(inventory)
  if not e.mine { inventory = inventory } then
    return fail("pickup_failed", "could not pick up " .. name, { entity = name })
  end
  local target = { x = nx, y = ny }
  local placed = C.try_place(name, target, dname)
  if placed then
    if recipe and placed.set_recipe then placed.set_recipe(recipe.name) end
    inventory.remove { name = item, count = 1 }
    return done { entity = name, x = r1(px(placed.position)), y = r1(py(placed.position)), direction = direction_name(placed) }
  end
  -- target blocked: put the entity back where it was
  local restored = C.try_place(name, old, dname)
  if restored then
    if recipe and restored.set_recipe then restored.set_recipe(recipe.name) end
    inventory.remove { name = item, count = 1 }
  end
  return fail("blocked", "cannot place " .. name .. " at " .. nx .. "," .. ny .. (restored and "; it stayed where it was" or ""), {
    entity = name, blocked_by = C.blockers_at(target), restored = restored and true or false,
  })
end

function M.extract(x, y, item, count)
  local e = own_entity_at(x, y)
  if not e then return fail("no_entity", "no entity of yours at " .. x .. "," .. y) end
  local inventory = bag()
  local remaining = (count and count > 0) and math.floor(count) or math.huge
  local taken = 0
  local ok, n = pcall(function() return e.get_max_inventory_index() end)
  if ok and n then
    for i = 1, n do
      local inv = e.get_inventory(i)
      if inv and remaining > 0 then
        local have = inv.get_item_count(item)
        if have > 0 then
          local want = math.min(have, remaining)
          local moved = inventory.insert { name = item, count = want }
          if moved > 0 then
            inv.remove { name = item, count = moved }
            taken = taken + moved
            remaining = remaining - moved
          end
        end
      end
    end
  end
  if taken == 0 then return fail("nothing_to_extract", e.name .. " holds no " .. item, { entity = e.name, item = item }) end
  return done { entity = e.name, item = item, extracted = taken, have = inventory.get_item_count(item) }
end

function M.inventory(x, y)
  if x == nil or y == nil then
    return done { owner = "you", items = counts(bag()) }
  end
  local e = own_entity_at(x, y)
  if not e then return fail("no_entity", "no entity of yours at " .. x .. "," .. y) end
  return done { owner = e.name, x = r1(px(e.position)), y = r1(py(e.position)), inventories = C.entity_inventories(e) }
end

function M.get_entity(x, y)
  local e = any_entity_at(x, y)
  if not e then return fail("no_entity", "nothing at " .. x .. "," .. y) end
  local out = {
    name = e.name, type = e.type, x = r1(px(e.position)), y = r1(py(e.position)),
    direction = (e.supports_direction and direction_name(e)) or nil,
    status = C.STATUS_NAME[e.status], health = e.health and r1(e.health) or nil,
    amount = e.amount,
  }
  if e.get_recipe then
    local r = e.get_recipe()
    if r then out.recipe = r.name end
  end
  local inventories = C.entity_inventories(e)
  if next(inventories) then out.inventories = inventories end
  local ok, n = pcall(function() return #e.fluidbox end)
  if ok and n and n > 0 then
    local fluids = {}
    for i = 1, n do
      local f = e.fluidbox[i]
      if f then fluids[#fluids + 1] = { name = f.name, amount = r1(f.amount) } end
    end
    if #fluids > 0 then out.fluids = fluids end
  end
  local drop = e.drop_target
  if drop and drop.valid then out.drops_into = { name = drop.name, x = r1(px(drop.position)), y = r1(py(drop.position)) } end
  if e.electric_network_id then out.electric_network = e.electric_network_id end
  if BELT_TYPES[e.type] and e.belt_neighbours then
    local outs = {}
    for _, o in pairs(e.belt_neighbours.outputs or {}) do outs[#outs + 1] = pos_of(o) end
    out.belt_outputs = outs
  end
  return done(out)
end

----------------------------------------------------------------------------- get_entities with groups

local function belt_groups(list)
  local by_id = {}
  for _, e in ipairs(list) do by_id[e.unit_number] = e end
  local seen, groups = {}, {}
  for _, e in ipairs(list) do
    if not seen[e.unit_number] then
      seen[e.unit_number] = true
      local queue, qi, members = { e }, 1, {}
      while qi <= #queue do
        local cur = queue[qi]
        qi = qi + 1
        members[#members + 1] = cur
        local nb = cur.belt_neighbours
        for _, kind in ipairs { "inputs", "outputs" } do
          for _, n in pairs((nb and nb[kind]) or {}) do
            if n.valid and by_id[n.unit_number] and not seen[n.unit_number] then
              seen[n.unit_number] = true
              queue[#queue + 1] = n
            end
          end
        end
      end
      local starts, ends = {}, {}
      for _, m in ipairs(members) do
        local nb = m.belt_neighbours
        local info = { x = r1(px(m.position)), y = r1(py(m.position)), dir = m.supports_direction and direction_name(m) or nil }
        if nb and #(nb.inputs or {}) == 0 and #starts < 3 then starts[#starts + 1] = info end
        if nb and #(nb.outputs or {}) == 0 and #ends < 3 then ends[#ends + 1] = info end
      end
      groups[#groups + 1] = { n = #members, starts = starts, ends = ends }
    end
  end
  return groups
end

local function pipe_groups(list)
  local at = {}
  for _, e in ipairs(list) do at[math.floor(px(e.position)) .. ":" .. math.floor(py(e.position))] = e end
  local seen, groups = {}, {}
  for key, e in pairs(at) do
    if not seen[key] then
      seen[key] = true
      local queue, qi, n = { key }, 1, 0
      local minx, miny, maxx, maxy = math.huge, math.huge, -math.huge, -math.huge
      while qi <= #queue do
        local k = queue[qi]
        qi = qi + 1
        local cur = at[k]
        n = n + 1
        local cx, cy = math.floor(px(cur.position)), math.floor(py(cur.position))
        minx, miny, maxx, maxy = math.min(minx, cx), math.min(miny, cy), math.max(maxx, cx), math.max(maxy, cy)
        for _, d in ipairs { { 1, 0 }, { -1, 0 }, { 0, 1 }, { 0, -1 } } do
          local nk = (cx + d[1]) .. ":" .. (cy + d[2])
          if at[nk] and not seen[nk] then
            seen[nk] = true
            queue[#queue + 1] = nk
          end
        end
      end
      groups[#groups + 1] = { n = n, from = { x = minx, y = miny }, to = { x = maxx, y = maxy } }
    end
  end
  return groups
end

local function pole_groups(list)
  local by_net = {}
  for _, e in ipairs(list) do
    local id = e.electric_network_id
    if id then
      local g = by_net[id]
      if not g then
        g = { id = id, n = 0, minx = math.huge, miny = math.huge, maxx = -math.huge, maxy = -math.huge }
        by_net[id] = g
      end
      g.n = g.n + 1
      g.minx, g.miny = math.min(g.minx, px(e.position)), math.min(g.miny, py(e.position))
      g.maxx, g.maxy = math.max(g.maxx, px(e.position)), math.max(g.maxy, py(e.position))
    end
  end
  local groups = {}
  for _, g in pairs(by_net) do
    groups[#groups + 1] = { id = g.id, n = g.n, from = { x = r1(g.minx), y = r1(g.miny) }, to = { x = r1(g.maxx), y = r1(g.maxy) } }
  end
  return groups
end

function M.get_entities(names, x, y, radius, limit)
  local a = agent()
  local origin = (x ~= nil and y ~= nil) and { x = x, y = y } or a.position
  radius = math.min(math.max(radius or 25, 1), 80)
  limit = math.min(limit or 60, 200)
  local filter = { position = origin, radius = radius, force = a.force }
  if type(names) == "table" and #names > 0 then filter.name = names end
  local list = {}
  for _, e in pairs(surf().find_entities_filtered(filter)) do
    if e.valid and e.type ~= "character" then list[#list + 1] = e end
  end
  table.sort(list, function(l, r) return dist(origin, l.position) < dist(origin, r.position) end)

  local entities, belts, pipes, poles = {}, {}, {}, {}
  for _, e in ipairs(list) do
    if #entities < limit then
      entities[#entities + 1] = {
        name = e.name, x = r1(px(e.position)), y = r1(py(e.position)),
        dir = e.supports_direction and direction_name(e) or nil, status = C.STATUS_NAME[e.status],
      }
    end
    if BELT_TYPES[e.type] then belts[#belts + 1] = e end
    if e.type == "pipe" then pipes[#pipes + 1] = e end
    if e.type == "electric-pole" then poles[#poles + 1] = e end
  end
  return done {
    total = #list, entities = entities,
    groups = { belts = belt_groups(belts), pipes = pipe_groups(pipes), poles = pole_groups(poles) },
  }
end

----------------------------------------------------------------------------- resource patch

function M.resource_patch(resource, x, y)
  local a = agent()
  local origin = (x ~= nil and y ~= nil) and { x = x, y = y } or a.position
  local start = C.nearest({ name = resource }, origin)
  if not start then return fail("not_found", "no " .. resource .. " within 250 tiles", { resource = resource }) end
  local tiles = surf().find_entities_filtered { name = resource, position = start.position, radius = 80 }
  local at = {}
  for _, e in ipairs(tiles) do at[math.floor(px(e.position)) .. ":" .. math.floor(py(e.position))] = e end
  local sx, sy = math.floor(px(start.position)), math.floor(py(start.position))
  local queue, qi = { { sx, sy } }, 1
  local seen = { [sx .. ":" .. sy] = true }
  local count, amount = 0, 0
  local minx, miny, maxx, maxy = math.huge, math.huge, -math.huge, -math.huge
  while qi <= #queue and count < 6000 do
    local cx, cy = queue[qi][1], queue[qi][2]
    qi = qi + 1
    local e = at[cx .. ":" .. cy]
    count = count + 1
    amount = amount + (e.amount or 0)
    minx, miny, maxx, maxy = math.min(minx, cx), math.min(miny, cy), math.max(maxx, cx), math.max(maxy, cy)
    for dx = -1, 1 do
      for dy = -1, 1 do
        local key = (cx + dx) .. ":" .. (cy + dy)
        if (dx ~= 0 or dy ~= 0) and at[key] and not seen[key] then
          seen[key] = true
          queue[#queue + 1] = { cx + dx, cy + dy }
        end
      end
    end
  end
  return done {
    resource = resource, tiles = count, amount = amount,
    left_top = { x = minx, y = miny }, right_bottom = { x = maxx + 1, y = maxy + 1 },
    center = { x = r1((minx + maxx + 1) / 2), y = r1((miny + maxy + 1) / 2) },
    d = r1(dist(origin, start.position)),
  }
end

----------------------------------------------------------------------------- misc

function M.move_to(x, y)
  local a = agent()
  local target = { x = x, y = y }
  local spot = surf().find_non_colliding_position("character", target, 5, 0.5)
  if not spot then return fail("unreachable", "no free ground near " .. x .. "," .. y) end
  local from = { x = px(a.position), y = py(a.position) }
  a.teleport(spot)
  return done { x = r1(px(a.position)), y = r1(py(a.position)), moved = r1(dist(from, a.position)) }
end

function M.say(message)
  message = tostring(message or "")
  if #message > 400 then message = message:sub(1, 400) end
  game.print("[Bot] " .. message, { r = 0.45, g = 0.85, b = 1 })
  return done { said = message }
end

-- chat lines typed by players, collected by control.lua (storage.inbox)
function M.read_chat(keep)
  local inbox = storage.inbox or {}
  local out = {}
  for _, m in ipairs(inbox) do
    if not m.read then
      out[#out + 1] = { player = m.player, text = m.text, tick = m.tick }
      if not keep then m.read = true end
    end
  end
  return done { messages = out }
end

function M.on_chat(event)
  local name = "?"
  local ok, player = pcall(function() return game.get_player(event.player_index) end)
  if ok and player then name = player.name end
  storage.inbox = storage.inbox or {}
  local inbox = storage.inbox
  inbox[#inbox + 1] = { player = name, text = event.message, tick = game.tick }
  while #inbox > 50 do table.remove(inbox, 1) end
end

function M.set_speed(speed)
  speed = math.max(0.1, math.min(speed or 1, 20))
  game.speed = speed
  return done { speed = speed }
end

function M.score()
  local a = agent()
  local force = a.force
  local produced = {}
  local ok, stats = pcall(function() return force.get_item_production_statistics(surf()) end)
  if ok and stats then
    for name, n in pairs(stats.input_counts or {}) do produced[name] = n end
  end
  local per_minute
  if ok and stats and defines.flow_precision_index then
    per_minute = {}
    for name, _ in pairs(produced) do
      local okf, rate = pcall(function()
        return stats.get_flow_count { name = name, category = "input", precision_index = defines.flow_precision_index.one_minute, count = true }
      end)
      if okf and rate and rate > 0 then per_minute[name] = r1(rate) end
    end
  end
  local researched = 0
  for _, tech in pairs(force.technologies) do
    if tech.researched then researched = researched + 1 end
  end
  local top = {}
  for name, n in pairs(produced) do top[#top + 1] = { name = name, n = n } end
  table.sort(top, function(l, r) return l.n > r.n end)
  local shown, total = {}, 0
  for i, t in ipairs(top) do
    total = total + t.n
    if i <= 15 then shown[t.name] = t.n end
  end
  return done { tick = game.tick, produced = shown, produced_total = total, per_minute = per_minute, researched = researched }
end

function M.launch_rocket(x, y)
  local a = agent()
  local origin = (x ~= nil and y ~= nil) and { x = x, y = y } or a.position
  local silo = C.nearest({ name = "rocket-silo", force = a.force }, origin)
  if not silo then return fail("not_found", "no rocket silo found") end
  if not silo.launch_rocket() then
    return fail("not_ready", "the rocket is not ready to launch yet", { x = r1(px(silo.position)), y = r1(py(silo.position)) })
  end
  return done { launched = true, x = r1(px(silo.position)), y = r1(py(silo.position)) }
end

function M.research_info(name)
  local force = agent().force
  local tech
  if name and name ~= "" then tech = force.technologies[name] else tech = force.current_research end
  if not tech then
    if name and name ~= "" then return fail("unknown_tech", "unknown technology " .. name) end
    return fail("no_research", "nothing is being researched")
  end
  local current = force.current_research
  local progress = 0
  if current and current.name == tech.name then
    progress = force.research_progress or 0
  elseif tech.saved_progress then
    progress = tech.saved_progress
  end
  local units = tech.research_unit_count or 0
  local remaining_units = math.ceil(units * (1 - progress))
  local packs = {}
  for _, ing in pairs(tech.research_unit_ingredients or {}) do
    packs[#packs + 1] = { name = ing.name, amount = ing.amount * remaining_units }
  end
  return done {
    name = tech.name, researched = tech.researched and true or false, progress = r1(progress * 100),
    units_total = units, units_left = remaining_units, packs_needed = packs,
  }
end

----------------------------------------------------------------------------- diagnose and save

local OK_STATUS = { working = true, normal = true, waiting_for_source_items = true, waiting_for_space_in_destination = true,
  waiting_for_more_items = true, preparing_rocket_for_launch = true, waiting_to_launch_rocket = true }

-- overview of all own buildings: counts per name and everything that is not running
function M.diagnose(x, y, radius)
  local a = agent()
  local filter = { force = a.force }
  if x ~= nil and y ~= nil then
    filter.position = { x = x, y = y }
    filter.radius = math.min(radius or 60, 200)
  end
  local counts, problems, total = {}, {}, 0
  for _, e in ipairs(surf().find_entities_filtered(filter)) do
    if e.valid and e.type ~= "character" and e.type ~= "resource" then
      total = total + 1
      counts[e.name] = (counts[e.name] or 0) + 1
      local st = C.STATUS_NAME[e.status]
      if st and not OK_STATUS[st] then
        local list = problems[st]
        if not list then
          list = { n = 0, at = {} }
          problems[st] = list
        end
        list.n = list.n + 1
        if #list.at < 8 then list.at[#list.at + 1] = { name = e.name, x = r1(px(e.position)), y = r1(py(e.position)) } end
      end
    end
  end
  return done { total = total, counts = counts, problems = problems }
end

-- write a save file (checkpoint) so the human can load it later
function M.save_game(name)
  name = (name and name ~= "") and name or ("fac_agent_" .. game.tick)
  local ok = pcall(function() game.server_save(name) end)
  if not ok then ok = pcall(function() game.auto_save(name) end) end
  if not ok then return fail("save_failed", "the game refused to save (needs a server or multiplayer host)") end
  return done { saved = name, tick = game.tick }
end

return M

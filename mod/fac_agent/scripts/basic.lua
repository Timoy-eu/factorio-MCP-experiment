-- Core tools: look, gather, craft, build, rotate, fuel, ... (all return JSON strings)
local C = require("scripts.common")
local M = {}

local json, fail, done = C.json, C.fail, C.done
local surf, agent, bag, counts = C.surf, C.agent, C.bag, C.counts
local px, py, dist, r1, pt = C.px, C.py, C.dist, C.r1, C.pt
local DIRS, ORDER, VEC = C.DIRS, C.ORDER, C.VEC
local STATUS_NAME, ROCKS, WATER, SOURCES = C.STATUS_NAME, C.ROCKS, C.WATER, C.SOURCES
local nearest, move_near, stand_off = C.nearest, C.move_near, C.stand_off
local direction_name, own_entity_at, item_for = C.direction_name, C.own_entity_at, C.item_for

----------------------------------------------------------------------------- read tools

function M.status()
  local a = agent()
  local placed = {}
  for _, e in pairs(surf().find_entities_filtered { force = a.force, position = a.position, radius = 60 }) do
    if e.valid and e.type ~= "character" then
      local entry = placed[e.name]
      if not entry then
        entry = { n = 0, status = {} }
        placed[e.name] = entry
      end
      entry.n = entry.n + 1
      local sname = STATUS_NAME[e.status]
      if sname then entry.status[sname] = (entry.status[sname] or 0) + 1 end
    end
  end
  local research = a.force.current_research
  return done {
    tick = game.tick,
    position = pt(a.position),
    health = a.health and r1(a.health) or nil,
    inventory = counts(bag()),
    placed = placed,
    research = research and research.name or nil,
  }
end

function M.look(radius)
  local a = agent()
  radius = math.min(math.max(radius or 25, 5), 60)
  local origin = a.position
  local s = surf()
  local resources = {}
  for _, e in pairs(s.find_entities_filtered { type = "resource", position = origin, radius = radius }) do
    local r = resources[e.name]
    local d = dist(origin, e.position)
    if not r then
      r = { tiles = 0, amount = 0, x = r1(px(e.position)), y = r1(py(e.position)), d = r1(d), best = d }
      resources[e.name] = r
    end
    r.tiles = r.tiles + 1
    r.amount = r.amount + (e.amount or 0)
    if d < r.best then
      r.best = d; r.x = r1(px(e.position)); r.y = r1(py(e.position)); r.d = r1(d)
    end
  end
  for _, r in pairs(resources) do r.best = nil end

  local function nearest_info(filter)
    local e, d = nearest(filter, origin, { radius })
    if not e then return nil end
    return { x = r1(px(e.position)), y = r1(py(e.position)), d = r1(d) }
  end
  local tree_count = #s.find_entities_filtered { type = "tree", position = origin, radius = radius }
  local water
  local tiles = s.find_tiles_filtered { name = WATER, position = origin, radius = radius, limit = 1 }
  if tiles and tiles[1] then
    water = { x = r1(px(tiles[1].position)), y = r1(py(tiles[1].position)), d = r1(dist(origin, tiles[1].position)) }
  end

  local entities = {}
  for _, e in pairs(s.find_entities_filtered { force = a.force, position = origin, radius = radius }) do
    if e.valid and e.type ~= "character" and #entities < 30 then
      entities[#entities + 1] = {
        name = e.name, x = r1(px(e.position)), y = r1(py(e.position)),
        dir = e.supports_direction and direction_name(e) or nil,
        status = STATUS_NAME[e.status],
      }
    end
  end
  local enemies = #s.find_entities_filtered { force = "enemy", position = origin, radius = radius }
  return done {
    position = pt(origin), radius = radius, resources = resources,
    trees = { count = tree_count, nearest = nearest_info { type = "tree" } },
    rock = nearest_info { name = ROCKS },
    water = water, entities = entities, enemies = enemies,
  }
end

function M.find(kind)
  local a = agent()
  local origin = a.position
  local filters = SOURCES[kind]
  if kind == "tree" then filters = SOURCES["wood"] end
  if kind == "rock" then filters = { { name = ROCKS } } end
  if kind == "water" then
    for _, r in ipairs { 40, 120, 250 } do
      local tiles = surf().find_tiles_filtered { name = WATER, position = origin, radius = r, limit = 1 }
      if tiles and tiles[1] then
        return done { kind = kind, x = r1(px(tiles[1].position)), y = r1(py(tiles[1].position)), d = r1(dist(origin, tiles[1].position)) }
      end
    end
    return fail("not_found", "no water within 250 tiles", { kind = kind })
  end
  if not filters then
    filters = { { name = kind, force = a.force }, { name = kind } }
  end
  for _, f in ipairs(filters) do
    local e, d = nearest(f, origin)
    if e then return done { kind = kind, x = r1(px(e.position)), y = r1(py(e.position)), d = r1(d), name = e.name } end
  end
  return fail("not_found", "nothing called '" .. kind .. "' within 250 tiles", { kind = kind })
end

function M.recipe(item)
  local a = agent()
  local recipe = a.force.recipes[item]
  if not recipe then return fail("no_recipe", "no recipe produces '" .. item .. "'", { item = item }) end
  local ingredients = {}
  for _, ing in ipairs(recipe.ingredients) do ingredients[#ingredients + 1] = { name = ing.name, amount = ing.amount, type = ing.type } end
  local products = {}
  for _, p in ipairs(recipe.products) do products[#products + 1] = { name = p.name, amount = p.amount or p.amount_min or 1 } end
  local by_hand = a.prototype.crafting_categories[recipe.category] == true
  return done {
    item = item, category = recipe.category, enabled = recipe.enabled, by_hand = by_hand,
    ingredients = ingredients, products = products, energy = recipe.energy,
  }
end

----------------------------------------------------------------------------- gather and craft

-- origin_x/origin_y/radius are optional: harvest around a position instead of around the agent
function M.gather(item, count, origin_x, origin_y, radius)
  count = math.max(1, math.floor(count or 10))
  local sources = SOURCES[item]
  if not sources then
    return fail("not_gatherable", item .. " cannot be mined by hand (use wood, stone, coal, iron-ore, copper-ore)", { item = item })
  end
  local a = agent()
  local inventory = bag()
  local start = inventory.get_item_count(item)
  local target = start + count
  local steps = 0
  local reason
  local fixed = (origin_x ~= nil and origin_y ~= nil) and { x = origin_x, y = origin_y } or nil
  local radii = fixed and { math.min(radius or 10, 60) } or nil
  while inventory.get_item_count(item) < target and steps < 400 do
    local e
    for _, f in ipairs(sources) do
      e = nearest(f, fixed or a.position, radii)
      if e then break end
    end
    if not e then reason = "nothing_found"; break end
    if not move_near(e.position, C.MINE_REACH) then reason = "unreachable"; break end
    if not a.mine_entity(e, true) then reason = "mine_failed"; break end
    steps = steps + 1
  end
  local got = inventory.get_item_count(item) - start
  if got >= count then
    return done { item = item, got = got, have = inventory.get_item_count(item) }
  elseif got > 0 then
    return done { item = item, got = got, have = inventory.get_item_count(item), partial = true, reason = reason or "step_limit" }
  end
  return fail(reason or "nothing_found", "could not gather any " .. item, { item = item })
end

local function product_amount(recipe, name)
  local total = 0
  for _, p in ipairs(recipe.products) do
    if p.name == name then total = total + (p.amount or p.amount_min or 1) end
  end
  return total
end

-- returns true, or false + {code, item, count, message}
local function craft_recursive(a, name, count, made, depth)
  local recipe = a.force.recipes[name]
  if not recipe then return false, { code = "no_recipe", item = name, message = "no recipe for " .. name } end
  if not recipe.enabled then return false, { code = "locked", item = name, message = name .. " is not researched yet" } end
  if not a.prototype.crafting_categories[recipe.category] then
    return false, { code = "not_by_hand", item = name, category = recipe.category, message = name .. " needs a machine (" .. recipe.category .. ")" }
  end
  local inventory = a.get_main_inventory()
  local per = product_amount(recipe, name)
  if per < 1 then return false, { code = "no_recipe", item = name, message = "recipe does not produce " .. name } end
  local crafts = math.ceil(count / per)
  for _, ing in ipairs(recipe.ingredients) do
    if ing.type ~= "item" then
      return false, { code = "fluid", item = name, message = name .. " needs fluids and cannot be hand crafted" }
    end
    local need = ing.amount * crafts
    local have = inventory.get_item_count(ing.name)
    if have < need then
      local sub = a.force.recipes[ing.name]
      local by_hand = sub and sub.enabled and a.prototype.crafting_categories[sub.category]
      if by_hand and depth < 8 then
        local ok, err = craft_recursive(a, ing.name, need - have, made, depth + 1)
        if not ok then return false, err end
      else
        return false, { code = "missing", item = ing.name, count = need - have, message = "missing " .. (need - have) .. " " .. ing.name }
      end
    end
  end
  for _, ing in ipairs(recipe.ingredients) do
    inventory.remove { name = ing.name, count = ing.amount * crafts }
  end
  for _, p in ipairs(recipe.products) do
    local n = (p.amount or p.amount_min or 1) * crafts
    local inserted = inventory.insert { name = p.name, count = n }
    if inserted < n then
      surf().spill_item_stack { position = a.position, stack = { name = p.name, count = n - inserted } }
    end
  end
  made[name] = (made[name] or 0) + crafts * per
  return true
end

function M.craft(item, count)
  count = math.max(1, math.floor(count or 1))
  local a = agent()
  local made = {}
  local ok, err = craft_recursive(a, item, count, made, 0)
  if not ok then
    err.crafted = made
    return fail(err.code, err.message, err)
  end
  return done { item = item, have = a.get_main_inventory().get_item_count(item), crafted = made }
end

----------------------------------------------------------------------------- build tools

-- candidate positions for a placement: exact spot first, then alternatives
local function candidate_positions(entity, wanted, flex)
  local positions = { wanted }
  if flex <= 0 then return positions end
  if entity == "offshore-pump" then
    -- pumps only fit on the shore: scan tiles around the wanted point by distance
    local cands = {}
    local reach = math.max(flex, 8)
    for dx = -reach, reach do
      for dy = -reach, reach do
        local x, y = C.snap_center(entity, px(wanted) + dx, py(wanted) + dy)
        cands[#cands + 1] = { x = x, y = y, d = dx * dx + dy * dy }
      end
    end
    table.sort(cands, function(l, r) return l.d < r.d end)
    for i, c in ipairs(cands) do
      if i > 1 then positions[#positions + 1] = { x = c.x, y = c.y } end
      if #positions >= 400 then break end
    end
    return positions
  end
  local alt = surf().find_non_colliding_position(entity, wanted, flex, 1, true)
  if alt and (px(alt) ~= px(wanted) or py(alt) ~= py(wanted)) then positions[#positions + 1] = alt end
  return positions
end

-- ug_type: only for blueprint placement of one underground piece ("input" or "output")
function M.build(entity, x, y, direction, flex, ug_type)
  local a = agent()
  local item = item_for(entity)
  if not item then return fail("unknown_entity", "unknown entity '" .. entity .. "'", { entity = entity }) end
  if ug_type == nil and require("scripts.underground").is_underground(entity) then
    return fail("use_build_underground", entity .. " is always a pair (entrance and exit); a single piece never works", { entity = entity })
  end
  local inventory = a.get_main_inventory()
  if inventory.get_item_count(item) < 1 then
    return fail("no_item", "you have no " .. item, { item = item })
  end
  local proto = prototypes.entity[entity]
  local supports = proto == nil or proto.supports_direction ~= false
  local dirs
  local auto = (direction == nil or direction == "" or direction == "auto")
  if not supports then
    dirs = { "north" }
  elseif auto then
    dirs = ORDER
  elseif DIRS[direction] then
    dirs = { direction }
  else
    return fail("bad_direction", "direction must be north, east, south, west or auto", { direction = direction })
  end

  local wanted = { x = x, y = y }
  local positions = candidate_positions(entity, wanted, flex or 0)

  stand_off(wanted)
  for _, pos in ipairs(positions) do
    for _, dname in ipairs(dirs) do
      if inventory.remove { name = item, count = 1 } == 1 then
        local e = C.try_place(entity, pos, dname, ug_type)
        if e then
          local actual = direction_name(e)
          local warning
          if supports and not auto and not ug_type and actual ~= direction and e.type ~= "assembling-machine" then
            pcall(function() e.direction = DIRS[direction] end)
            actual = direction_name(e)
            if actual ~= direction then warning = "requested " .. direction .. " but entity faces " .. actual end
          end
          return done {
            entity = entity, x = r1(px(e.position)), y = r1(py(e.position)),
            direction = supports and actual or nil,
            moved = (px(e.position) ~= x or py(e.position) ~= y) or nil,
            warning = warning,
          }
        end
        inventory.insert { name = item, count = 1 }
      end
    end
  end
  local suggestion = surf().find_non_colliding_position(entity, wanted, 10, 1, true)
  return fail("blocked", "cannot place " .. entity .. " at " .. x .. "," .. y, {
    entity = entity, blocked_by = C.blockers_at(wanted),
    suggestion = suggestion and pt(suggestion) or nil,
  })
end

local function recreate_assembler(e, target)
  local saved = {
    name = e.name, position = e.position, force = e.force, health = e.health,
    recipe = e.get_recipe and e.get_recipe() or nil,
  }
  local recipe_name = saved.recipe and saved.recipe.name or nil
  local kept = {}
  local input_id = defines.inventory.crafter_input or defines.inventory.assembling_machine_input
  for _, inventory in ipairs { e.get_inventory(input_id), e.get_output_inventory() } do
    if inventory then
      for _, c in pairs(inventory.get_contents()) do kept[#kept + 1] = { name = c.name, count = c.count } end
    end
  end
  e.destroy()
  local n = surf().create_entity { name = saved.name, position = saved.position, direction = target, force = saved.force, raise_built = true }
  if not n then return nil end
  if saved.health then n.health = saved.health end
  if recipe_name then
    n.set_recipe(recipe_name)
    if n.direction ~= target then n.direction = target end
  end
  for _, stack in ipairs(kept) do n.insert(stack) end
  return n
end

local function recipe_has_fluid(recipe)
  if not recipe then return false end
  for _, list in ipairs { recipe.ingredients or {}, recipe.products or {} } do
    for _, p in pairs(list) do
      if p.type == "fluid" then return true end
    end
  end
  return false
end

function M.rotate(x, y, direction)
  if not DIRS[direction] then
    return fail("bad_direction", "direction must be north, east, south or west", { direction = direction })
  end
  local e = own_entity_at(x, y)
  if not e then return fail("no_entity", "no entity of yours at " .. x .. "," .. y) end
  if e.type == "underground-belt" then
    return fail("rotate_underground", "rotating an underground belt turns the entrance into an exit and breaks the pair", { entity = e.name })
  end
  local target = DIRS[direction]
  if e.direction ~= target then
    if e.type == "assembling-machine" then
      -- Factorio 2.0: assemblers only have an orientation for recipes with fluids
      pcall(function() e.direction = target end)
      if e.direction ~= target then
        local recipe = e.get_recipe and e.get_recipe() or nil
        if not recipe_has_fluid(recipe) then
          return done {
            entity = e.name, x = r1(px(e.position)), y = r1(py(e.position)), direction = direction_name(e),
            note = e.name .. " has no orientation without a fluid recipe, nothing to rotate",
          }
        end
        e = recreate_assembler(e, target)
        if not e then return fail("rotate_failed", "could not recreate assembler after rotation") end
      end
    elseif e.supports_direction == false then
      return fail("not_rotatable", e.name .. " has no direction", { entity = e.name })
    else
      pcall(function() e.direction = target end)
    end
  end
  local actual = direction_name(e)
  if actual ~= direction then
    return fail("rotate_failed", e.name .. " still faces " .. actual, { entity = e.name, direction = actual })
  end
  return done { entity = e.name, x = r1(px(e.position)), y = r1(py(e.position)), direction = actual }
end

function M.set_recipe(x, y, recipe)
  local a = agent()
  local e = own_entity_at(x, y)
  if not e then return fail("no_entity", "no entity of yours at " .. x .. "," .. y) end
  if e.type ~= "assembling-machine" then return fail("no_recipe_slot", e.name .. " has no recipe") end
  local r = a.force.recipes[recipe]
  if not r then return fail("no_recipe", "unknown recipe " .. recipe) end
  if not r.enabled then return fail("locked", recipe .. " is not researched yet") end
  local before = e.direction
  e.set_recipe(recipe)
  if e.direction ~= before then e.direction = before end
  return done { entity = e.name, recipe = recipe, direction = direction_name(e) }
end

-- Burner drill on ore dropping straight into a furnace. The orientation is searched here,
-- the model never has to pick a direction.
function M.build_miner(ore, tries)
  local a = agent()
  local inventory = a.get_main_inventory()
  if inventory.get_item_count("burner-mining-drill") < 1 then return fail("no_item", "you have no burner-mining-drill", { item = "burner-mining-drill" }) end
  if inventory.get_item_count("stone-furnace") < 1 then return fail("no_item", "you have no stone-furnace", { item = "stone-furnace" }) end
  local s = surf()
  local tiles = s.find_entities_filtered { name = ore, position = a.position, radius = 60 }
  if #tiles == 0 then return fail("no_ore", "no " .. ore .. " within 60 tiles, use find " .. ore, { ore = ore }) end
  table.sort(tiles, function(l, r) return dist(a.position, l.position) < dist(a.position, r.position) end)

  local seen, attempts = {}, 0
  tries = tries or 40
  for _, tile in ipairs(tiles) do
    if attempts >= tries then break end
    local cx, cy = math.floor(px(tile.position)) + 1, math.floor(py(tile.position)) + 1
    local key = cx .. ":" .. cy
    if not seen[key] then
      seen[key] = true
      local under = #s.find_entities_filtered { name = ore, area = { { cx - 1, cy - 1 }, { cx + 1, cy + 1 } } }
      if under >= 3 then
        attempts = attempts + 1
        stand_off({ x = cx, y = cy })
        for _, dname in ipairs(ORDER) do
          local v = VEC[dname]
          local fpos = { x = cx + 2 * v[1], y = cy + 2 * v[2] }
          local d = DIRS[dname]
          if s.can_place_entity { name = "burner-mining-drill", position = { x = cx, y = cy }, direction = d, force = a.force }
              and s.can_place_entity { name = "stone-furnace", position = fpos, force = a.force } then
            inventory.remove { name = "burner-mining-drill", count = 1 }
            inventory.remove { name = "stone-furnace", count = 1 }
            local drill = s.create_entity { name = "burner-mining-drill", position = { x = cx, y = cy }, direction = d, force = a.force, raise_built = true }
            local furnace = drill and s.create_entity { name = "stone-furnace", position = fpos, force = a.force, raise_built = true }
            if drill and furnace and drill.drop_target == furnace then
              local fueled = 0
              for _, target in ipairs { drill, furnace } do
                if inventory.get_item_count("coal") > 0 then
                  local put = target.insert { name = "coal", count = math.min(5, inventory.get_item_count("coal")) }
                  inventory.remove { name = "coal", count = put }
                  fueled = fueled + put
                end
              end
              return done {
                ore = ore, drill = { x = cx, y = cy, direction = direction_name(drill) },
                furnace = { x = fpos.x, y = fpos.y }, coal_inserted = fueled, tried = attempts,
              }
            end
            -- wrong layout: take both back and try the next orientation
            if drill and drill.valid then drill.mine { inventory = inventory } end
            if furnace and furnace.valid then furnace.mine { inventory = inventory } end
          end
        end
      end
    end
  end
  return fail("no_site", "no free spot found where a drill can feed a furnace on " .. ore, { ore = ore, tried = attempts })
end

----------------------------------------------------------------------------- logistics tools

local function has_fuel_slot(e)
  local ok, inv = pcall(function() return e.get_fuel_inventory() end)
  return ok and inv ~= nil
end

function M.fuel(x, y, item, per)
  local a = agent()
  local inventory = a.get_main_inventory()
  item = item or "coal"
  per = per or 5
  local targets = {}
  if x ~= nil and y ~= nil then
    local e = own_entity_at(x, y)
    if not e then return fail("no_entity", "no entity of yours at " .. x .. "," .. y) end
    targets[1] = e
  else
    for _, e in pairs(surf().find_entities_filtered { force = a.force, position = a.position, radius = 30 }) do
      if e.valid and e.type ~= "character" and has_fuel_slot(e) then targets[#targets + 1] = e end
    end
  end
  local fueled, total = {}, 0
  for _, e in ipairs(targets) do
    local have = inventory.get_item_count(item)
    if have < 1 then break end
    local put = e.insert { name = item, count = math.min(per, have) }
    if put > 0 then
      inventory.remove { name = item, count = put }
      total = total + put
      if #fueled < 20 then fueled[#fueled + 1] = { name = e.name, x = r1(px(e.position)), y = r1(py(e.position)), put = put } end
    end
  end
  if total == 0 then
    if inventory.get_item_count(item) < 1 then return fail("no_item", "you have no " .. item, { item = item }) end
    return fail("nothing_to_fuel", "no entity accepted " .. item)
  end
  return done { item = item, total = total, fueled = fueled, left = inventory.get_item_count(item) }
end

function M.collect(radius)
  local a = agent()
  local inventory = a.get_main_inventory()
  radius = math.min(radius or 30, 60)
  local totals = {}
  for _, e in pairs(surf().find_entities_filtered { force = a.force, position = a.position, radius = radius }) do
    if e.valid and e.type ~= "character" then
      local ok, out = pcall(function() return e.get_output_inventory() end)
      if ok and out then
        for _, c in pairs(out.get_contents()) do
          local moved = inventory.insert { name = c.name, count = c.count }
          if moved > 0 then
            out.remove { name = c.name, count = moved }
            totals[c.name] = (totals[c.name] or 0) + moved
          end
        end
      end
    end
  end
  return done { collected = totals, inventory = counts(inventory) }
end

function M.insert(x, y, item, count)
  local a = agent()
  local inventory = a.get_main_inventory()
  local e = own_entity_at(x, y)
  if not e then return fail("no_entity", "no entity of yours at " .. x .. "," .. y) end
  local have = inventory.get_item_count(item)
  if have < 1 then return fail("no_item", "you have no " .. item, { item = item }) end
  local want = math.min(math.max(1, math.floor(count or have)), have)
  local put = e.insert { name = item, count = want }
  if put < 1 then return fail("rejected", e.name .. " does not accept " .. item, { entity = e.name, item = item }) end
  inventory.remove { name = item, count = put }
  return done { entity = e.name, item = item, inserted = put, left = inventory.get_item_count(item) }
end

function M.research(name)
  local a = agent()
  local force = a.force
  if name and name ~= "" then
    local tech = force.technologies[name]
    if not tech then return fail("unknown_tech", "unknown technology " .. name) end
    if tech.researched then return fail("already_done", name .. " is already researched") end
    if not force.add_research(name) then return fail("cannot_queue", name .. " cannot be queued (missing prerequisites?)") end
    return done { queued = name }
  end
  local available = {}
  for tname, tech in pairs(force.technologies) do
    if tech.enabled and not tech.researched and #available < 15 then
      local ready = true
      for _, pre in pairs(tech.prerequisites) do
        if not pre.researched then ready = false; break end
      end
      if ready then available[#available + 1] = tname end
    end
  end
  table.sort(available)
  local current = force.current_research
  return done {
    current = current and current.name or nil,
    progress = current and r1((force.research_progress or 0) * 100) or nil,
    available = available,
  }
end

return M

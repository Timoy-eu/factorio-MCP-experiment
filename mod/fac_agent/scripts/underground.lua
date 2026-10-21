-- build_underground: an underground belt is always a PAIR (input = entrance, output = exit, same direction, in a line,
-- at most max_underground_distance tiles apart). create_entity without `type` makes an input, so a lone "build"
-- never yields a working pair. This places both pieces with the right types, checks the pairing the game reports and
-- undoes everything on failure.
local C = require("scripts.common")
local M = {}

local fail, done = C.fail, C.done
local agent, bag = C.agent, C.bag
local DIRS = C.DIRS

function M.is_underground(name)
  local proto = prototypes.entity[name]
  return proto ~= nil and proto.type == "underground-belt"
end

local function tile_center(v) return math.floor(v) + 0.5 end

local function rollback(placed, inventory, item)
  for _, e in ipairs(placed) do
    if e.valid then e.destroy() end
  end
  if #placed > 0 then inventory.insert { name = item, count = #placed } end
end

-- entrance at (x1, y1), exit at (x2, y2): same row or column; the direction is entrance -> exit
function M.build_underground(entity, x1, y1, x2, y2)
  entity = (entity ~= nil and entity ~= "") and entity or "underground-belt"
  if not M.is_underground(entity) then
    return fail("unknown_entity", "'" .. tostring(entity) .. "' is not an underground belt (use underground-belt, fast-underground-belt or express-underground-belt)", { entity = entity })
  end
  local ax, ay, bx, by = tile_center(x1), tile_center(y1), tile_center(x2), tile_center(y2)
  local dx, dy = bx - ax, by - ay
  if (dx ~= 0 and dy ~= 0) or (dx == 0 and dy == 0) then
    return fail("not_in_line", "entrance (" .. ax .. "," .. ay .. ") and exit (" .. bx .. "," .. by .. ") must be in the same row or column and different tiles",
      { x1 = ax, y1 = ay, x2 = bx, y2 = by })
  end
  local distance = math.abs(dx) + math.abs(dy)
  local max = prototypes.entity[entity].max_underground_distance or 5
  if distance > max then
    return fail("too_far", entity .. " reaches at most " .. max .. " tiles from entrance to exit (" .. (max - 1) .. " tiles in between), you asked for " .. distance,
      { distance = distance, max = max })
  end
  local dname = dx > 0 and "east" or dx < 0 and "west" or dy > 0 and "south" or "north"

  local item = C.item_for(entity)
  local inventory = bag()
  local have = inventory.get_item_count(item)
  if have < 2 then
    return fail("missing", "an underground pair needs 2 " .. item .. ", you have " .. have, { item = item, count = 2 - have, needed = 2, have = have })
  end

  local a, s = agent(), C.surf()
  local function place(x, y, kind)
    local pos = { x = x, y = y }
    if not s.can_place_entity { name = entity, position = pos, direction = DIRS[dname], force = a.force } then return nil end
    return s.create_entity { name = entity, position = pos, direction = DIRS[dname], force = a.force, type = kind, raise_built = true }
  end

  C.stand_off({ x = ax, y = ay })
  if inventory.remove { name = item, count = 2 } ~= 2 then
    return fail("missing", "could not take 2 " .. item .. " from the inventory", { item = item })
  end
  local placed = {}
  local entrance = place(ax, ay, "input")
  if not entrance then
    inventory.insert { name = item, count = 2 }
    return fail("blocked", "the entrance spot (" .. ax .. "," .. ay .. ") is not free", { x = ax, y = ay, side = "entrance" })
  end
  placed[1] = entrance
  local exit = place(bx, by, "output")
  if not exit then
    rollback(placed, inventory, item)
    inventory.insert { name = item, count = 1 }
    return fail("blocked", "the exit spot (" .. bx .. "," .. by .. ") is not free; the entrance was picked up again", { x = bx, y = by, side = "exit" })
  end
  placed[2] = exit

  local partner = entrance.neighbours
  local paired = partner ~= nil and partner.valid and partner.unit_number == exit.unit_number
    and entrance.belt_to_ground_type == "input" and exit.belt_to_ground_type == "output"
  if not paired then
    rollback(placed, inventory, item)
    return fail("not_paired", "the two pieces did not pair up (something else underground in between, or wrong direction); both were picked up again",
      { x1 = ax, y1 = ay, x2 = bx, y2 = by })
  end
  return done {
    entity = entity, direction = dname, distance = distance, paired = true,
    entrance = { x = ax, y = ay }, exit = { x = bx, y = by },
  }
end

return M

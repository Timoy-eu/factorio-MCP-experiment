-- trains: stations, trains and schedules on straight rails.
-- Facts learned in a real Factorio 2.0.77 (see docs/PLAN_RAILS.md):
--  * a train stop stands on the RIGHT side of the travel direction (east: south of the rail, facing east) and is only
--    valid when stop.connected_rail is not nil, so the spot is found by trying and checking that;
--  * coupled rolling stock sits 7 tiles apart (centre to centre) on the same straight line;
--  * a schedule with ONE station never leaves it, a lap needs two.
local C = require("scripts.common")
local M = {}

local fail, done = C.fail, C.done
local agent, bag, surf = C.agent, C.bag, C.surf
local DIRS, VEC = C.DIRS, C.VEC

local RIGHT = { east = "south", south = "west", west = "north", north = "east" }
local STRAIGHT_DIRS = { north = { [0] = true, [8] = true }, south = { [0] = true, [8] = true },
                        east = { [4] = true, [12] = true }, west = { [4] = true, [12] = true } }
local ORIENTATION = { north = 0, east = 0.25, south = 0.5, west = 0.75 }
local STOCK_PITCH = 7
local MAX_STOCK = 12
local ROLLING = { "locomotive", "cargo-wagon", "fluid-wagon", "artillery-wagon" }

local STATE_NAME = {}
for name, value in pairs(defines.train_state or {}) do STATE_NAME[value] = name end

local function r1(n) return math.floor(n * 10 + 0.5) / 10 end

-- the pieces of this module that need no game: tested with lupa
M.geometry = {
  RIGHT = RIGHT, STOCK_PITCH = STOCK_PITCH,
  -- centre of the n-th piece of rolling stock (0 = front) behind (x, y) for a train travelling in `travel`
  stock_position = function(x, y, travel, index)
    local v = VEC[travel]
    return x - v[1] * STOCK_PITCH * index, y - v[2] * STOCK_PITCH * index
  end,
  -- canonical spot of a train stop for a straight rail at (x, y)
  stop_position = function(x, y, travel)
    local v = VEC[RIGHT[travel]]
    return x + v[1] * 2, y + v[2] * 2
  end,
}

-- nearest straight rail within `radius` whose direction fits the axis of `travel` (nil = any axis)
local function straight_rail_near(x, y, travel, radius)
  local best, bestd
  for _, e in ipairs(surf().find_entities_filtered { area = { { x - radius, y - radius }, { x + radius, y + radius } }, name = "straight-rail", force = agent().force }) do
    if e.valid and (travel == nil or STRAIGHT_DIRS[travel][e.direction]) then
      local d = (e.position.x - x) ^ 2 + (e.position.y - y) ^ 2
      if not bestd or d < bestd then best, bestd = e, d end
    end
  end
  return best
end

local function axis_travels(rail)
  if rail.direction == 0 or rail.direction == 8 then return { "south", "north" } end
  return { "east", "west" }
end

local function valid_travel(t)
  return t ~= nil and DIRS[t] ~= nil
end

----------------------------------------------------------------------------- station

function M.build_station(name, x, y, travel)
  name = (name ~= nil and name ~= "") and name or "Station"
  local s, a = surf(), agent()
  local inventory = bag()
  if inventory.get_item_count("train-stop") < 1 then
    return fail("no_item", "you have no train-stop", { item = "train-stop" })
  end
  local auto = travel == nil or travel == "" or travel == "auto"
  if not auto and not valid_travel(travel) then
    return fail("bad_direction", "travel must be north, east, south, west or auto", { direction = travel })
  end
  local rail = straight_rail_near(x, y, auto and nil or travel, 3)
  if not rail then
    return fail("no_rail", "no straight rail near " .. x .. "," .. y .. (auto and "" or " that runs " .. travel) .. "; a train stop needs a straight piece, not a curve",
      { x = x, y = y })
  end
  local candidates = auto and axis_travels(rail) or { travel }
  C.stand_off({ x = rail.position.x, y = rail.position.y })
  for _, t in ipairs(candidates) do
    local sx, sy = M.geometry.stop_position(rail.position.x, rail.position.y, t)
    local along = VEC[t]
    local spots = { { sx, sy }, { sx - along[1], sy - along[2] }, { sx + along[1], sy + along[2] } }
    for _, pos in ipairs(spots) do
      if s.can_place_entity { name = "train-stop", position = pos, direction = DIRS[t], force = a.force } then
        local stop = s.create_entity { name = "train-stop", position = pos, direction = DIRS[t], force = a.force, raise_built = true }
        if stop then
          if stop.connected_rail then
            if inventory.remove { name = "train-stop", count = 1 } ~= 1 then
              stop.destroy()
              return fail("no_item", "you have no train-stop", { item = "train-stop" })
            end
            stop.backer_name = name
            return done {
              name = name, x = r1(stop.position.x), y = r1(stop.position.y), direction = t,
              rail = { x = rail.position.x, y = rail.position.y },
              note = "trains travelling " .. t .. " stop here",
            }
          end
          stop.destroy()
        end
      end
    end
  end
  return fail("no_site", "no spot for a train stop beside the rail at " .. rail.position.x .. "," .. rail.position.y .. " (blocked, or the rail is not straight on both sides)",
    { x = rail.position.x, y = rail.position.y })
end

----------------------------------------------------------------------------- train

local function rollback(entities)
  for _, e in ipairs(entities) do
    if e.valid then e.destroy() end
  end
end

-- front of the train at (x, y), travelling `travel`, locomotives first then wagons
function M.build_train(x, y, travel, locomotives, wagons, wagon, fuel_item, fuel_count)
  if not valid_travel(travel) then
    return fail("bad_direction", "travel must be north, east, south or west", { direction = travel })
  end
  locomotives = math.floor(locomotives or 1)
  wagons = math.floor(wagons or 0)
  wagon = (wagon ~= nil and wagon ~= "") and wagon or "cargo-wagon"
  if wagon ~= "cargo-wagon" and wagon ~= "fluid-wagon" then
    return fail("unknown_entity", "wagon must be cargo-wagon or fluid-wagon", { entity = wagon })
  end
  if locomotives < 1 or locomotives + wagons > MAX_STOCK then
    return fail("bad_count", "a train needs 1 to " .. MAX_STOCK .. " cars in total, with at least one locomotive", { count = locomotives + wagons })
  end
  local s, a = surf(), agent()
  local inventory = bag()
  local need = { locomotive = locomotives, [wagon] = wagons }
  for item, n in pairs(need) do
    local have = inventory.get_item_count(item)
    if n > 0 and have < n then
      return fail("missing", "you need " .. n .. " " .. item .. ", you have " .. have, { item = item, count = n - have, needed = n, have = have })
    end
  end

  local rail = straight_rail_near(x, y, travel, 3)
  if not rail then
    return fail("no_rail", "no straight rail near " .. x .. "," .. y .. " that runs " .. travel .. "; the train needs " .. ((locomotives + wagons) * STOCK_PITCH) .. " tiles of straight track",
      { x = x, y = y })
  end
  -- stay on the axis of the rail: snap the cross coordinate, keep the along coordinate
  local fx, fy = x, y
  if travel == "east" or travel == "west" then fy = rail.position.y else fx = rail.position.x end
  C.stand_off({ x = fx, y = fy })

  local made = {}
  local order = {}
  for i = 1, locomotives do order[#order + 1] = "locomotive" end
  for i = 1, wagons do order[#order + 1] = wagon end
  for index, name in ipairs(order) do
    local px, py = M.geometry.stock_position(fx, fy, travel, index - 1)
    local pos = { x = px, y = py }
    if not s.can_place_entity { name = name, position = pos, direction = DIRS[travel], force = a.force } then
      rollback(made)
      return fail("blocked", name .. " " .. index .. " of " .. #order .. " does not fit at " .. r1(px) .. "," .. r1(py) .. " (straight track too short, or something in the way); nothing was placed",
        { x = r1(px), y = r1(py), index = index })
    end
    local e = s.create_entity { name = name, position = pos, direction = DIRS[travel], orientation = ORIENTATION[travel], force = a.force, raise_built = true }
    if not e then
      rollback(made)
      return fail("blocked", name .. " " .. index .. " could not be placed at " .. r1(px) .. "," .. r1(py) .. "; nothing was placed", { x = r1(px), y = r1(py), index = index })
    end
    made[#made + 1] = e
  end

  local train = made[1].train
  if not train or #train.carriages ~= #made then
    rollback(made)
    return fail("not_coupled", "the cars did not form one train on the rails (are they on one straight line?); nothing was placed", { count = #made })
  end
  for item, n in pairs(need) do
    if n > 0 then inventory.remove { name = item, count = n } end
  end

  -- fuel for every locomotive, taken from the inventory
  fuel_item = (fuel_item ~= nil and fuel_item ~= "") and fuel_item or "coal"
  local want = math.floor(fuel_count or 20)
  local fueled = 0
  for _, e in ipairs(made) do
    if e.type == "locomotive" and want > 0 then
      local give = math.min(want, inventory.get_item_count(fuel_item))
      if give > 0 then
        local inserted = e.get_fuel_inventory().insert { name = fuel_item, count = give }
        if inserted > 0 then inventory.remove { name = fuel_item, count = inserted } end
        fueled = fueled + inserted
      end
    end
  end
  return done {
    train_id = train.id, cars = #made, locomotives = locomotives, wagons = wagons, direction = travel,
    x = r1(made[1].position.x), y = r1(made[1].position.y), fuel_item = fuel_item, fuel = fueled,
    warning = fueled == 0 and ("no " .. fuel_item .. " in your inventory, the train has no fuel") or nil,
  }
end

----------------------------------------------------------------------------- schedule and status

local function stock_near(x, y, radius)
  local best, bestd
  for _, e in ipairs(surf().find_entities_filtered { area = { { x - radius, y - radius }, { x + radius, y + radius } }, type = ROLLING }) do
    if e.valid then
      local d = (e.position.x - x) ^ 2 + (e.position.y - y) ^ 2
      if not bestd or d < bestd then best, bestd = e, d end
    end
  end
  return best
end

local function fuel_of(train)
  local total, locos = 0, 0
  for _, e in ipairs(train.carriages) do
    if e.type == "locomotive" then
      locos = locos + 1
      for _, c in ipairs(e.get_fuel_inventory().get_contents()) do total = total + c.count end
    end
  end
  return total, locos
end

local function names_of(text)
  local list = {}
  for part in tostring(text):gmatch("[^;]+") do
    local trimmed = part:gsub("^%s+", ""):gsub("%s+$", "")
    if trimmed ~= "" then list[#list + 1] = trimmed end
  end
  return list
end

-- stations: "A; B" (names of train stops), wait: seconds at every stop
function M.train_schedule(x, y, stations, wait)
  local stock = stock_near(x, y, 5)
  if not stock then return fail("no_train", "no locomotive or wagon near " .. x .. "," .. y, { x = x, y = y }) end
  local train = stock.train
  local list = names_of(stations or "")
  if #list == 0 then return fail("no_station", "give at least one station name, e.g. stations=\"Mine; Smelter\"") end
  local known = {}
  for _, e in ipairs(surf().find_entities_filtered { type = "train-stop", force = agent().force }) do
    if e.valid then known[e.backer_name] = true end
  end
  for _, n in ipairs(list) do
    if not known[n] then
      local names = {}
      for k in pairs(known) do names[#names + 1] = k end
      table.sort(names)
      return fail("no_station", "no train stop named '" .. n .. "'" .. (#names > 0 and ("; existing: " .. table.concat(names, ", ")) or "; build one with build_station"), { name = n })
    end
  end
  local ticks = math.max(1, math.floor((wait or 5) * 60))
  local records = {}
  for _, n in ipairs(list) do
    records[#records + 1] = { station = n, wait_conditions = { { type = "time", ticks = ticks, compare_type = "and" } } }
  end
  train.schedule = { current = 1, records = records }
  train.manual_mode = false
  local fuel, locos = fuel_of(train)
  local state = STATE_NAME[train.state] or tostring(train.state)
  local notes = {}
  if #list == 1 then notes[#notes + 1] = "with one station the train drives there and stays; use two stations for a lap" end
  if fuel == 0 then notes[#notes + 1] = "no fuel in the locomotive" end
  if state == "no_path" then notes[#notes + 1] = "no path to the first station: the rails are not connected" end
  return done {
    train_id = train.id, stations = list, wait = ticks / 60, state = state, locomotives = locos, fuel = fuel,
    note = #notes > 0 and table.concat(notes, "; ") or nil,
  }
end

function M.train_status(x, y)
  local stock = stock_near(x, y, 5)
  if not stock then return fail("no_train", "no locomotive or wagon near " .. x .. "," .. y, { x = x, y = y }) end
  local train = stock.train
  local fuel, locos = fuel_of(train)
  local schedule = {}
  for _, rec in ipairs((train.schedule and train.schedule.records) or {}) do
    schedule[#schedule + 1] = rec.station or (rec.rail and "rail") or "?"
  end
  local front = train.carriages[1]
  local speed = train.speed or 0
  return done {
    train_id = train.id, state = STATE_NAME[train.state] or tostring(train.state), manual = train.manual_mode,
    speed_kmh = math.floor(math.abs(speed) * 60 * 3.6 + 0.5), cars = #train.carriages, locomotives = locos, fuel = fuel,
    station = train.station and train.station.backer_name or nil, schedule = schedule,
    x = r1(front.position.x), y = r1(front.position.y),
    driver = (function() for _, e in ipairs(train.carriages) do if e.get_driver and e.get_driver() then return true end end return false end)(),
  }
end

return M

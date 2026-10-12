-- snapshot: compact description of a rectangle of the world for the ASCII map and the renderer
local C = require("scripts.common")
local M = {}

local fail, done = C.fail, C.done
local surf, agent = C.surf, C.agent
local px, py, r1 = C.px, C.py, C.r1

local MAX_SIDE = 160
local MAX_ENTITIES = 6000
local ALPHABET = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
local SKIP_TYPES = { tree = true, resource = true, character = true, corpse = true, ["item-entity"] = true, ["entity-ghost"] = true }

-- x1,y1,x2,y2 are tile coordinates; with all four nil the area is centred on the agent
function M.snapshot(x1, y1, x2, y2, radius)
  local a = agent()
  local s = surf()
  if x1 == nil or y1 == nil or x2 == nil or y2 == nil then
    local half = math.min(math.max(math.floor(radius or 32), 4), math.floor(MAX_SIDE / 2))
    local cx, cy = math.floor(px(a.position)), math.floor(py(a.position))
    x1, y1, x2, y2 = cx - half, cy - half, cx + half, cy + half
  end
  x1, x2 = math.floor(math.min(x1, x2)), math.ceil(math.max(x1, x2))
  y1, y2 = math.floor(math.min(y1, y2)), math.ceil(math.max(y1, y2))
  if x2 == x1 then x2 = x1 + 1 end
  if y2 == y1 then y2 = y1 + 1 end
  local w, h = x2 - x1, y2 - y1
  if w > MAX_SIDE or h > MAX_SIDE then
    return fail("too_large", "area is " .. w .. "x" .. h .. " tiles, the maximum is " .. MAX_SIDE .. "x" .. MAX_SIDE, { width = w, height = h })
  end
  local area = { { x1, y1 }, { x2, y2 } }

  -- terrain as one character per tile plus a palette
  local palette, char_of, count = {}, {}, 0
  local grid = {}
  for _, t in ipairs(s.find_tiles_filtered { area = area }) do
    local ch = char_of[t.name]
    if not ch then
      count = count + 1
      ch = count <= #ALPHABET and ALPHABET:sub(count, count) or "?"
      char_of[t.name] = ch
      palette[ch] = t.name
    end
    local tx, ty = math.floor(px(t.position)) - x1, math.floor(py(t.position)) - y1
    if tx >= 0 and tx < w and ty >= 0 and ty < h then
      grid[ty * w + tx] = ch
    end
  end
  local rows = {}
  for ty = 0, h - 1 do
    local row = {}
    for tx = 0, w - 1 do row[#row + 1] = grid[ty * w + tx] or " " end
    rows[#rows + 1] = table.concat(row)
  end

  -- resources: name -> flat list x, y, amount (tile coordinates)
  local resources = {}
  for _, e in ipairs(s.find_entities_filtered { area = area, type = "resource" }) do
    local list = resources[e.name]
    if not list then
      list = {}
      resources[e.name] = list
    end
    list[#list + 1] = math.floor(px(e.position))
    list[#list + 1] = math.floor(py(e.position))
    list[#list + 1] = e.amount or 0
  end

  local trees = {}
  for _, e in ipairs(s.find_entities_filtered { area = area, type = "tree" }) do
    trees[#trees + 1] = r1(px(e.position))
    trees[#trees + 1] = r1(py(e.position))
  end

  local entities, truncated = {}, false
  local sizes = {}
  for _, e in ipairs(s.find_entities_filtered { area = area }) do
    if e.valid and not SKIP_TYPES[e.type] then
      if #entities >= MAX_ENTITIES then truncated = true; break end
      local size = sizes[e.name]
      if not size then
        local ew, eh = C.entity_size(e.name)
        size = { ew, eh }
        sizes[e.name] = size
      end
      local ew, eh = size[1], size[2]
      local dname = e.supports_direction and C.direction_name(e) or nil
      if (dname == "east" or dname == "west") and ew ~= eh then ew, eh = eh, ew end
      local item = {
        n = e.name, t = e.type, x = r1(px(e.position)), y = r1(py(e.position)), w = ew, h = eh,
        d = dname, s = C.STATUS_NAME[e.status],
      }
      local fname = e.force and e.force.name
      item.f = (fname == "player" and "p") or (fname == "enemy" and "e") or "n"
      if e.get_recipe then
        local ok, rec = pcall(function() return e.get_recipe() end)
        if ok and rec then item.r = rec.name end
      end
      if e.type == "underground-belt" then
        local ok, kind = pcall(function() return e.belt_to_ground_type end)
        if ok and kind then item.u = kind end
      end
      entities[#entities + 1] = item
    end
  end

  return done {
    tick = game.tick,
    area = { x1 = x1, y1 = y1, x2 = x2, y2 = y2 },
    palette = palette, rows = rows, resources = resources, trees = trees,
    entities = entities, truncated = truncated or nil,
    agent = { x = r1(px(a.position)), y = r1(py(a.position)) },
  }
end

return M

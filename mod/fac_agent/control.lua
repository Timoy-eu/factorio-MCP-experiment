-- fac_agent: high level action API for LLM agents, called over RCON as
--   /silent-command rcon.print(remote.call("fac_agent", "<function>", args...))
-- Every function returns a JSON string: {"ok":true,...} or {"ok":false,"code":...,"message":...}.
-- Target: Factorio 2.0 (storage, helpers.table_to_json, 16 direction values).
-- Movement and mining are intentionally "cheaty" (teleport, instant mining) to keep the
-- tool surface small. Placement and rotation are always verified by reading them back.

local C = require("scripts.common")
local Basic = require("scripts.basic")
local Extra = require("scripts.extra")
local Connect = require("scripts.connect")
local Rails = require("scripts.rails")
local Underground = require("scripts.underground")
local Map = require("scripts.map")
local Track = require("scripts.track")
local Selftest = require("scripts.selftest")

local function safe(fn)
  return function(...)
    local ok, result = pcall(fn, ...)
    if ok then return result end
    return C.fail("lua_error", tostring(result))
  end
end

local api = {
  -- core
  status = Basic.status, look = Basic.look, find = Basic.find, recipe = Basic.recipe,
  gather = Basic.gather, craft = Basic.craft,
  build = Basic.build, rotate = Basic.rotate, set_recipe = Basic.set_recipe, build_miner = Basic.build_miner,
  fuel = Basic.fuel, collect = Basic.collect, insert = Basic.insert, research = Basic.research,
  -- inspection and placement helpers
  can_place = Extra.can_place, nearest_buildable = Extra.nearest_buildable, build_next_to = Extra.build_next_to,
  pickup = Extra.pickup, shift_entity = Extra.shift_entity, extract = Extra.extract,
  inventory = Extra.inventory, get_entity = Extra.get_entity, get_entities = Extra.get_entities,
  resource_patch = Extra.resource_patch, move_to = Extra.move_to, say = Extra.say,
  set_speed = Extra.set_speed, score = Extra.score, launch_rocket = Extra.launch_rocket,
  research_info = Extra.research_info, diagnose = Extra.diagnose, read_chat = Extra.read_chat, save_game = Extra.save_game,
  -- connections and world snapshot
  connect = Connect.connect, rail_end = Rails.rail_end, build_underground = Underground.build_underground, snapshot = Map.snapshot,
  selftest = Selftest.run,
  -- item tracking
  belt_contents = Track.belt_contents, trace_start = Track.trace_start, trace_probe = Track.trace_probe, sample = Track.sample,
}

local wrapped = {}
for name, fn in pairs(api) do wrapped[name] = safe(fn) end
wrapped.version = function() return "0.3.2" end

remote.add_interface("fac_agent", wrapped)

script.on_init(function() storage.agent = nil; storage.inbox = {} end)
if defines.events and defines.events.on_console_chat then
  script.on_event(defines.events.on_console_chat, function(event) pcall(Extra.on_chat, event) end)
end

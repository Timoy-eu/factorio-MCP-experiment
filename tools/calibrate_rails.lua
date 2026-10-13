local s=game.surfaces[1]
local types={"straight-rail","half-diagonal-rail","curved-rail-a","curved-rail-b"}
local cx,cy=4001,4001
local table_out={}
local seen={}
local function rel(a,b) return {math.floor(a.x-b.x+0.5), math.floor(a.y-b.y+0.5)} end
local ncreate=0
for _,st in ipairs{"@SEED@"} do
  for sd=0,15 do
    local seed=s.create_entity{name=st, position={cx,cy}, direction=sd, force="player"}
    if seed then
      local key=st.."|"..seed.direction
      if not seen[key] then
        seen[key]=true
        local origin=seed.position
        local entry={}
        for ri,rd in ipairs{defines.rail_direction.front, defines.rail_direction.back} do
          local e=seed.get_rail_end(rd)
          local loc=e.location
          local list={}
          local found={}
          for _,t in ipairs(types) do
            for d=0,15 do
              for dx=-7,7,2 do for dy=-7,7,2 do
                local pos={loc.position.x+dx-0, loc.position.y+dy-0}
                if s.can_place_entity{name=t, position=pos, direction=d, force="player"} then
                  local c=s.create_entity{name=t, position=pos, direction=d, force="player"}
                  ncreate=ncreate+1
                  if c then
                    for _,cdn in ipairs{"left","straight","right"} do
                      local ee=seed.get_rail_end(rd)
                      if ee.move_forward(defines.rail_connection_direction[cdn]) and ee.rail and ee.rail.valid and ee.rail.unit_number==c.unit_number then
                        local k=cdn.."|"..c.name.."|"..c.direction.."|"..c.position.x.."|"..c.position.y
                        if not found[k] then
                          found[k]=true
                          local r=rel(c.position,origin)
                          local nl=ee.location
                          local nr=rel(nl.position,origin)
                          list[#list+1]={cdn,c.name,c.direction,r[1],r[2],nl.direction,nr[1],nr[2]}
                        end
                      end
                    end
                    c.destroy()
                  end
                end
              end end
            end
          end
          entry[ri==1 and "front" or "back"]={end_dir=loc.direction, end_rel=rel(loc.position,origin), next=list}
        end
        table_out[key]=entry
      end
      seed.destroy()
    end
  end
end
rcon.print(helpers.table_to_json({created=ncreate, table=table_out}))

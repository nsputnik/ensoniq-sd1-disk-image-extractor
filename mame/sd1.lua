-- Driver for MAME's sd132: runs a step list, reads the VFD as text, taps MIDI OUT,
-- and publishes live status to mame/live/status.json for the monitor page (monitor/).
-- Steps come from the file named in env SD1_STEPS, one per line:
--   press <btn>[ <btn>...]  tap button(s) (names or numbers, see BTN)
--   hold <btn> / release <btn>
--   wait <seconds>          emulated seconds
--   until <text> [timeout]  wait until the display contains text
--   untilnot <text> [timeout]  wait until the display no longer contains text
--   status <word> [timeout] wait until the sequencer status (lower-left: STOP, PLAY, SNGS...) is word
--   seek <btn> <max> <text> press btn (one at a time) until the display contains text
--   ifpress <text> | <btn>...  press button(s) only if the display contains text (!text: doesn't)
--   setnum <btn> <value>    select a soft-button field and step it with up/down to value
--                           (reads the field's current number off the display)
--   setword <btn> <word>    select a soft-button field and press down until it reads word
--                           (track MIDI status: down steps MIDI -> LOCAL -> BOTH, so presses vary)
--   grabtracks <first>      record track names + has-data dots from a Tracks page (1 or 7)
--   grabinfo                read the time signature (Locate page, end of the top row) and/or
--                           BARS= (Edit Seq INFO page) for the current item's conversion
--   expect <text>           stop the run if the display doesn't contain text
--   slider <0-1023>         set the data entry slider
--   midistop [timeout]      during a capture: wait for MIDI Start then Stop (FA ... FC) from the
--                           sequencer -- exact, unlike the display, for sequences shorter than a press
--   playlength [timeout]    during a capture, with LOOP on: after Play, press Stop once the SD-1
--                           has sent the clocks for the sequence's length (grabinfo bars x meter)
--   capture <file>          log every MIDI OUT byte as "<emulated-seconds> <byte>"
--   endcapture              close it; a *.cap is converted to *.mid + *.json (tools/cap2mid.py)
--   item <label>            start a named unit of work (shown on the monitor)
--   done [result]           finish the current item
--   note <text>             set the phase line on the monitor
--   dump [tag]              print the display
--   save <name> / load <name>  MAME state slot
--   reinsert                eject and reinsert the floppy, so the OS sees a disk change after a
--                           state load (a state remembers the directory of the disk it was saved with)
--   exit
local BTN = {
  cart=52, sounds=53, presets=54, seqbank=51,
  b0=55, b1=56, b2=57, b3=46, b4=47, b5=48, b6=49, b7=35, b8=34, b9=25,
  replace=29, tracks16=30, tracks712=31, selectvoice=5, copy=9, write=3, compare=8,
  patchselect=26, midi=27, effects=28, keyzone=39, transpose=40, release=41,
  volume=36, pan=37, timbre=38,
  rec=19, stop=22, play=23, click=32, seqcontrol=18, locate=33,
  song=60, seq=59, track=61, master=20, storage=21, midicontrol=24,
  wave=4, modmixer=6, programcontrol=2, peffects=7, pitch=11, pitchmod=13,
  filters=15, output=17, lfo=10, env1=12, env2=14, env3=16,
  -- soft buttons: lower row L/M/R, upper row L/M/R
  sl1=50, sl2=44, sl3=45, su1=58, su2=42, su3=43,
  up=62, down=63,
}
local root = os.getenv("SD1_ROOT") or "."
-- the VFD font ROM, extracted from esq2x40_vfx.zip by tools/setup.py
local f = assert(io.open(root .. "/mame/esqvfd_font_vfx.bin", "rb"), "run tools/setup.py first (VFD font missing)")
local font = f:read("a"); f:close()
local SEG = {}
-- Font covers 0x20-0x7F; several glyphs share segments (S/5, O/0, lowercase=uppercase).
-- Assign first-wins in priority order: space, A-Z and punctuation 0x41-0x5F, then 0x21-0x40.
local order = {0}
for c = 0x21, 0x3F do order[#order+1] = c end   -- 0x41-0x5F
for c = 0x01, 0x20 do order[#order+1] = c end   -- 0x21-0x40
for _, c in ipairs(order) do
  local v = font:byte(c*2+1) * 256 + font:byte(c*2+2)
  if SEG[v] == nil then SEG[v] = string.char(c + 32) end
end
local function display()
  local out = manager.machine.output
  local rows = {}
  for r = 0, 1 do
    local s = {}
    for c = 0, 39 do
      local v = math.floor(out:get_value("vfd" .. (r*40 + c))) & 0x7fff
      s[#s+1] = SEG[v] or (v == 0 and " " or "?")
    end
    rows[#rows+1] = table.concat(s)
  end
  return rows
end

-- ---------------------------------------------------------------- live status
local LIVE = root .. "/mame/live"
os.execute('mkdir -p "' .. LIVE .. '"')
local ST = {
  steps_file = os.getenv("SD1_STEPS"), step = 0, steps = 0, cmd = "", phase = "starting",
  item = nil, items = {}, log = {}, capture = nil, tracks = {},
}
local MID = { bytes = 0, clocks = 0, notes = 0, transport = "idle", running = 0, data = {},
              t0 = nil, recent = {}, roll = {}, chans = {} }
local NOTE = {"C","C#","D","D#","E","F","F#","G","G#","A","A#","B"}

local function jstr(s)
  s = tostring(s):gsub('[%c"\\]', function(c)
    if c == '"' then return '\\"' elseif c == "\\" then return "\\\\" end
    return string.format("\\u%04x", c:byte())
  end)
  return '"' .. s .. '"'
end
local function json(v)
  local t = type(v)
  if t == "nil" then return "null"
  elseif t == "boolean" or t == "number" then return tostring(v)
  elseif t == "string" then return jstr(v) end
  if #v > 0 or next(v) == nil then
    local p = {}; for i = 1, #v do p[i] = json(v[i]) end
    return "[" .. table.concat(p, ",") .. "]"
  end
  local p = {}
  for k, x in pairs(v) do p[#p+1] = jstr(k) .. ":" .. json(x) end
  return "{" .. table.concat(p, ",") .. "}"
end
local function emutime() return manager.machine.time:as_double() end
local function log(msg)
  local line = string.format("[%8.2f] %s", emutime(), msg)
  print(line)
  table.insert(ST.log, line); if #ST.log > 200 then table.remove(ST.log, 1) end
end
local last_write = -1
local function publish(force)
  local now = os.clock()
  if not force and now - last_write < 0.15 then return end
  last_write = now
  local chans = {}
  for ch, n in pairs(MID.chans) do chans[#chans+1] = {ch = ch, notes = n} end
  table.sort(chans, function(a, b) return a.ch < b.ch end)
  local doc = {
    updated = os.time(), emu = emutime(), pid = ST.pid,
    display = display(), steps_file = ST.steps_file, step = ST.step, steps = ST.steps,
    cmd = ST.cmd, phase = ST.phase, item = ST.item, items = ST.items, log = ST.log,
    capture = ST.capture, tracks = ST.tracks,
    midi = { bytes = MID.bytes, clocks = MID.clocks, notes = MID.notes, transport = MID.transport,
             bpm = MID.bpm, recent = MID.recent, roll = MID.roll, chans = chans },
  }
  local tmp = LIVE .. "/status.json.tmp"
  local fh = io.open(tmp, "w"); fh:write(json(doc)); fh:close()
  os.rename(tmp, LIVE .. "/status.json")
end

-- Live MIDI decoding for the monitor only; the .cap file is the record of truth.
local function midi_event(t, ev)
  local s = ev[1] & 0xf0
  local ch = (ev[1] & 0x0f) + 1
  local txt
  if s == 0x90 and ev[3] > 0 then
    MID.notes = MID.notes + 1
    MID.chans[ch] = (MID.chans[ch] or 0) + 1
    local n = ev[2]
    txt = string.format("ch%-2d NOTE ON  %-3s%d vel %d", ch, NOTE[n % 12 + 1], n // 12 - 1, ev[3])
    MID.roll[#MID.roll+1] = { t = t - (MID.t0 or t), ch = ch, n = n, v = ev[3] }
    if #MID.roll > 600 then table.remove(MID.roll, 1) end
  elseif s == 0x80 or s == 0x90 then return
  elseif s == 0xb0 then txt = string.format("ch%-2d CC %d = %d", ch, ev[2], ev[3])
  elseif s == 0xc0 then txt = string.format("ch%-2d PROGRAM %d", ch, ev[2] + 1)
  elseif s == 0xe0 then txt = string.format("ch%-2d PITCH BEND %d", ch, (ev[3] << 7 | ev[2]) - 8192)
  elseif s == 0xd0 then txt = string.format("ch%-2d PRESSURE %d", ch, ev[2])
  else txt = string.format("%02X", ev[1]) end
  table.insert(MID.recent, string.format("%8.3f %s", t - (MID.t0 or t), txt))
  if #MID.recent > 40 then table.remove(MID.recent, 1) end
end
local LEN = { [0x80]=3, [0x90]=3, [0xa0]=3, [0xb0]=3, [0xc0]=2, [0xd0]=2, [0xe0]=3 }
local last_clock
local function midi_byte(t, b)
  MID.bytes = MID.bytes + 1
  if b >= 0xf8 then
    if b == 0xf8 then
      MID.clocks = MID.clocks + 1
      if last_clock and t > last_clock then MID.bpm = 60 / ((t - last_clock) * 24) end
      last_clock = t
    elseif b == 0xfa then MID.transport = "start"; MID.t0 = t; MID.clocks = 0
    elseif b == 0xfb then MID.transport = "continue"
    elseif b == 0xfc then MID.transport = "stop" end
    return
  end
  if b >= 0x80 then
    if b >= 0xf0 then MID.running = 0; MID.data = {}; return end
    MID.running = b; MID.data = {}
    return
  end
  if MID.running == 0 then return end
  MID.data[#MID.data+1] = b
  if #MID.data + 1 == LEN[MID.running & 0xf0] then
    midi_event(t, { MID.running, MID.data[1], MID.data[2] })
    MID.data = {}
  end
end

local function dump(tag)
  local d = display()
  print(string.format("[%7.2fs] %s", manager.machine.time.seconds, tag or ""))
  print("  |" .. d[1] .. "|"); print("  |" .. d[2] .. "|")
end
local function field(n)
  local port = manager.machine.ioport.ports[n < 32 and ":panel:buttons_0" or ":panel:buttons_32"]
  return port:field(1 << (n % 32))
end
local function btn(name) return BTN[name] or tonumber(name) end
local POS = { su1 = {1, 1}, su2 = {1, 2}, su3 = {1, 3}, sl1 = {2, 1}, sl2 = {2, 2}, sl3 = {2, 3} }
local function fieldnum(b)
  local p = POS[b]; local row = display()[p[1]]
  local nums = {}
  -- values start at column 10 (after the page label / status word). S and 5, O and 0
  -- share a VFD glyph and decode as letters, so map them back inside number fields.
  for tok in row:sub(9):gmatch("%S+") do
    if tok:match("^[%dSO]+$") then nums[#nums+1] = tonumber((tok:gsub("S", "5"):gsub("O", "0"))) end
  end
  return nums[p[2]]
end
local function fieldword(b)
  local p = POS[b]; local toks = {}
  for tok in display()[p[1]]:sub(9):gmatch("%S+") do toks[#toks+1] = tok end
  return toks[p[2]]
end
local function shows(text) local d = display(); return (d[1] .. d[2]):find(text, 1, true) ~= nil end

PRESS = tonumber(os.getenv("SD1_PRESS") or "0.05")
local steps = {}
for line in io.lines(os.getenv("SD1_STEPS")) do
  line = line:gsub("#.*", ""):match("^%s*(.-)%s*$")
  if line ~= "" then steps[#steps+1] = line end
end
ST.steps = #steps
do -- our own pid, so the monitor can show/kill exactly this process
  local p = io.popen("echo $PPID"); ST.pid = tonumber(p:read("l")); p:close()
end

-- Waits use emu.wait (scheduler timers). The sd132 driver has no screen, so frame
-- callbacks only arrive about once per emulated second -- far too coarse for button taps.
local function wait(sec)
  while sec > 0 do
    local d = math.min(sec, 0.25); emu.wait(d); sec = sec - d; publish()
  end
end
local function fail(msg)
  log("FAILED: " .. msg); ST.phase = "failed: " .. msg
  if ST.item then ST.items[#ST.items].result = "failed"; ST.item = nil end
  publish(true); manager.machine:exit()
end

local co = coroutine.create(function()
  for i, s in ipairs(steps) do
    ST.step, ST.cmd = i, s; publish()
    local cmd, rest = s:match("^(%S+)%s*(.*)$")
    if cmd == "press" then
      for b in rest:gmatch("%S+") do
        local fl = field(btn(b)); fl:set_value(1); wait(PRESS); fl:clear_value(); wait(0.5)
      end
    elseif cmd == "hold" then field(btn(rest)):set_value(1); wait(0.1)
    elseif cmd == "release" then field(btn(rest)):clear_value(); wait(0.1)
    elseif cmd == "wait" then wait(tonumber(rest))
    elseif cmd == "until" or cmd == "untilnot" then
      local text, to = rest:match("^(.-)%s+(%d+)$"); text = text or rest; to = tonumber(to) or 60
      local t0 = manager.machine.time.seconds
      local want = cmd == "until"
      while shows(text) ~= want and manager.machine.time.seconds - t0 <= to do wait(0.1) end
      dump(cmd .. " '" .. text .. "'")
      if shows(text) ~= want then return fail(cmd .. " '" .. text .. "' timed out") end
    elseif cmd == "status" then
      local word, to = rest:match("^(%S+)%s*(%d*)$"); to = tonumber(to) or 600
      local t0 = manager.machine.time.seconds
      local function cur() return display()[2]:sub(1, 4):match("^(%S+)") or "" end
      while cur() ~= word and manager.machine.time.seconds - t0 <= to do wait(0.1) end
      dump("status " .. word)
      if cur() ~= word then return fail("status " .. word .. " timed out (is " .. cur() .. ")") end
    elseif cmd == "midistop" then
      local to = tonumber(rest) or 1800
      local t0 = manager.machine.time.seconds
      while MID.t0 == nil and manager.machine.time.seconds - t0 <= 10 do wait(0.05) end
      if MID.t0 == nil then return fail("midistop: no MIDI Start within 10s") end
      while MID.transport ~= "stop" and manager.machine.time.seconds - t0 <= to do wait(0.1) end
      dump("midistop")
      if MID.transport ~= "stop" then return fail("midistop: no MIDI Stop within " .. to .. "s") end
    elseif cmd == "playlength" then
      -- LOOP=OFF is not a reliable end: the SD-1 stopped one 16-bar factory sequence after 4 bars.
      -- So play looped and stop by counting the sequencer's own clocks (24 per quarter note).
      if not (ST.bars and ST.meter) then return fail("playlength: bars/meter not read (grabinfo)") end
      local n, d = ST.meter:match("(%d+)/(%d+)")
      local target = ST.bars * tonumber(n) * 96 // tonumber(d)
      local to = tonumber(rest) or 1800
      local t0 = manager.machine.time.seconds
      while MID.t0 == nil and manager.machine.time.seconds - t0 <= 10 do wait(0.02) end
      if MID.t0 == nil then return fail("playlength: no MIDI Start within 10s") end
      -- Wait for one clock past the end (the loop restart, tick = length): notes in the last
      -- 3 ticks come after the final clock, and stopping on it cut them. cap2mid trims the restart.
      while MID.clocks <= target and MID.transport ~= "stop" and manager.machine.time.seconds - t0 <= to do
        emu.wait(0.002)
      end
      if MID.transport == "stop" then
        log(string.format("playlength: SD-1 stopped itself after %d of %d clocks", MID.clocks, target))
      elseif MID.clocks < target then return fail("playlength: timed out")
      else
        local fl = field(btn("stop")); fl:set_value(1); wait(PRESS); fl:clear_value()
        local t1 = manager.machine.time.seconds
        while MID.transport ~= "stop" and manager.machine.time.seconds - t1 <= 5 do wait(0.05) end
        log(string.format("playlength: %d clocks (%d bars of %s), stopped", target, ST.bars, ST.meter))
      end
      dump("playlength")
    elseif cmd == "seek" then
      local b, mx, text = rest:match("^(%S+)%s+(%d+)%s+(.+)$")
      local fl, found = field(btn(b)), false
      for _ = 0, tonumber(mx) do
        if shows(text) then found = true; break end
        fl:set_value(1); wait(PRESS); fl:clear_value(); wait(0.6)
      end
      dump((found and "seek ok '" or "SEEK FAILED '") .. text .. "'")
      if not found then return fail("seek '" .. text .. "'") end
    elseif cmd == "ifpress" then
      local text, btns = rest:match("^(.-)%s*|%s*(.+)$")
      local want = true
      if text:sub(1, 1) == "!" then text, want = text:sub(2), false end
      if shows(text) == want then
        log("saw '" .. text .. "' -> press " .. btns)
        for b in btns:gmatch("%S+") do
          local fl = field(btn(b)); fl:set_value(1); wait(PRESS); fl:clear_value(); wait(0.5)
        end
      end
    elseif cmd == "setnum" then
      local b, target = rest:match("^(%S+)%s+(%d+)$"); target = tonumber(target)
      local fl = field(btn(b)); fl:set_value(1); wait(PRESS); fl:clear_value(); wait(0.4)
      local tries = 0
      while fieldnum(b) ~= target and tries < 40 do
        local cur = fieldnum(b)
        if not cur then return fail("setnum " .. b .. ": no number on display") end
        local f2 = field(btn(cur < target and "up" or "down"))
        f2:set_value(1); wait(PRESS); f2:clear_value(); wait(0.3); tries = tries + 1
      end
      if fieldnum(b) ~= target then dump("setnum"); return fail("setnum " .. b .. " " .. target) end
    elseif cmd == "setword" then
      local b, want = rest:match("^(%S+)%s+(%S+)$")
      local fl = field(btn(b)); fl:set_value(1); wait(PRESS); fl:clear_value(); wait(0.4)
      local tries = 0
      while fieldword(b) ~= want and tries < 6 do
        local f2 = field(btn("down")); f2:set_value(1); wait(PRESS); f2:clear_value(); wait(0.3)
        tries = tries + 1
      end
      if fieldword(b) ~= want then dump("setword"); return fail("setword " .. b .. " " .. want) end
    elseif cmd == "grabtracks" then
      local first = tonumber(rest); local d = display()
      for r = 1, 2 do
        for i = 0, 2 do
          local col = 5 + 12 * i
          local k = first + (r - 1) * 3 + i
          ST.tracks[k] = { name = d[r]:sub(col + 1, col + 11):match("^%s*(.-)%s*$"),
                           data = d[r]:sub(col, col) == "." }
        end
      end
    elseif cmd == "grabinfo" then
      local d = display()
      local function num(x) return x and (x:gsub("S", "5"):gsub("O", "0")) end
      local n, dd = d[1]:sub(33):match("([%dSO]+)/([%dSO]+)")
      if n then ST.meter = num(n) .. "/" .. num(dd) end
      local bars = num((d[1] .. d[2]):match("BARS=([%dSO]+)"))
      if bars then ST.bars = tonumber(bars) end
      log("info: meter " .. tostring(ST.meter) .. ", bars " .. tostring(ST.bars))
    elseif cmd == "expect" then
      if not shows(rest) then dump("expect"); return fail("expected '" .. rest .. "'") end
    elseif cmd == "slider" then
      manager.machine.ioport.ports[":panel:analog_data_entry"]:field(0x3ff):set_value(tonumber(rest)); wait(0.4)
    elseif cmd == "capture" then
      -- MIDI OUT = 68681 DUART channel A; its TX holding register (reg 3) sits at
      -- 0x280007 (registers on odd bytes, umask16 0x00ff). Timestamps are emulated time,
      -- so the log is exact regardless of emulation speed.
      os.execute('mkdir -p "' .. rest:match("^(.*)/[^/]+$") .. '"')
      CAP = io.open(rest, "w")
      local d = display()
      -- set tempo, if the page shows it (5/S and 0/O share a glyph, as in setnum)
      CAPTEMPO = (d[1] .. d[2]):match("TEMPO=([%dSO]+)")
      if CAPTEMPO then CAPTEMPO = CAPTEMPO:gsub("S", "5"):gsub("O", "0") end
      MID.bytes, MID.clocks, MID.notes, MID.transport, MID.t0 = 0, 0, 0, "armed", nil
      MID.recent, MID.roll, MID.chans, MID.bpm, last_clock = {}, {}, {}, nil, nil
      ST.capture = rest
      local space = manager.machine.devices[":maincpu"].spaces["program"]
      TAP = space:install_write_tap(0x280006, 0x280007, "midiout", function(offset, data, mask)
        if offset == 0x280006 and (mask & 0xff) ~= 0 then
          local t = manager.machine.time:as_double()
          CAP:write(string.format("%.6f %d\n", t, data & 0xff))
          midi_byte(t, data & 0xff)
        end
      end)
      log("capture -> " .. rest)
    elseif cmd == "endcapture" then
      if TAP then TAP:remove(); TAP = nil end
      if CAP then CAP:close(); CAP = nil end
      log(string.format("capture closed: %d bytes, %d notes, %d clocks", MID.bytes, MID.notes, MID.clocks))
      local capfile = ST.capture; ST.capture = nil
      if capfile and capfile:match("%.cap$") then
        -- layout (tools/layout.py): <dir>/cap/<name>.cap -> <dir>/<name>.mid + <dir>/json/<name>.json
        local dir, name = capfile:match("^(.*)/cap/([^/]+)%.cap$")
        if not dir then dir, name = capfile:match("^(.*)/([^/]+)%.cap$") end
        local mid, jsonf = dir .. "/" .. name .. ".mid", dir .. "/json/" .. name .. ".json"
        os.execute('mkdir -p "' .. dir .. '/json"')
        local names = {}
        for k = 1, 12 do
          local t = ST.tracks[k]
          names[k] = t and ((t.data and "*" or "") .. t.name):gsub('[|"$`\\]', "") or ""
        end
        local cmd = string.format('python3 -I "%s/tools/cap2mid.py" "%s" "%s" --name "%s"%s "--tracks=%s" > "%s"',
          root, capfile, mid, (ST.item or name):gsub('"', ""),
          (CAPTEMPO and (" --tempo " .. CAPTEMPO) or "") ..
          (ST.meter and (" --timesig " .. ST.meter) or "") .. (ST.bars and (" --bars " .. ST.bars) or ""),
          table.concat(names, "|"), jsonf)
        local okc = os.execute(cmd)
        local fh = io.open(jsonf); local info = fh and fh:read("a") or ""; if fh then fh:close() end
        log("converted -> " .. mid .. " " .. info:gsub("%s+$", ""))
        if ST.item then ST.items[#ST.items].result = okc and "ok" or "empty" end
      end
    elseif cmd == "item" then
      ST.tracks, ST.meter, ST.bars = {}, nil, nil
      ST.item = rest; ST.items[#ST.items+1] = { name = rest, result = "running" }; log("== " .. rest)
    elseif cmd == "done" then
      if ST.item then ST.items[#ST.items].result = rest ~= "" and rest or "ok" end
      ST.item = nil
    elseif cmd == "note" then ST.phase = rest; log(rest)
    elseif cmd == "dump" then dump(rest)
    elseif cmd == "save" then manager.machine:save(rest); wait(0.1)
    elseif cmd == "load" then manager.machine:load(rest); wait(0.1)
    elseif cmd == "reinsert" then
      for tag, img in pairs(manager.machine.images) do
        local fn = img.filename
        if fn and fn ~= "" then
          img:unload(); wait(1); img:load(fn); log("reinserted " .. tag .. ": " .. fn)
        end
      end
      wait(1)
    elseif cmd == "exit" then ST.phase = "finished"; publish(true); manager.machine:exit(); return
    end
  end
  ST.phase = "finished"; publish(true)
end)
local ok, err = coroutine.resume(co)
if not ok then print("LUA ERROR: " .. err); ST.phase = "lua error: " .. err; publish(true); manager.machine:exit() end

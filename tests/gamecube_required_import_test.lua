-- Structural required-import validation must accept equivalent GameCube CISO
-- containers without weakening ordinary MD5-only imports.
-- Self-contained: `luajit tests/gamecube_required_import_test.lua`.
package.path = "./?.lua;./?/init.lua;" .. package.path
if not _G.love then _G.love = require("tests.love_stub") end

local S = require("tests.harness").suite("gamecube required import")
local check, eq = S.check, S.eq
local RequiredImports = require("src.mods.RequiredImports")

local function be32(n)
  return string.char(math.floor(n / 16777216) % 256,
    math.floor(n / 65536) % 256, math.floor(n / 256) % 256, n % 256)
end
local function le32(n)
  return string.char(n % 256, math.floor(n / 256) % 256,
    math.floor(n / 65536) % 256, math.floor(n / 16777216) % 256)
end
local function put(s, offset, bytes)
  return s:sub(1, offset) .. bytes .. s:sub(offset + #bytes + 1)
end

local logicalSize = 0x40000
local blockSize = 0x8000
local logical = string.rep("\0", logicalSize)
logical = put(logical, 0, "GC6E01")
logical = put(logical, 7, string.char(0))
logical = put(logical, 0x1C, be32(0xC2339F3D))
local fstOffset, fstSize = 0x500, 0x30
logical = put(logical, 0x424, be32(fstOffset))
logical = put(logical, 0x428, be32(fstSize))
local fst = be32(0x01000000) .. be32(0) .. be32(2)
  .. be32(0) .. be32(0x9000) .. be32(4) .. "file\0"
logical = put(logical, fstOffset, fst .. string.rep("\0", fstSize - #fst))
logical = put(logical, 0x9000, "TEST")

-- Only the first two logical blocks are stored; the rest are scrubbed zeroes.
local cisoHeader = "CISO" .. le32(blockSize) .. string.char(1, 1)
  .. string.rep("\0", 0x8000 - 10)
local ciso = cisoHeader .. logical:sub(1, blockSize)
  .. logical:sub(blockSize + 1, blockSize * 2)
local path = "mods/cbe/baseroms/disc.iso"
local files = { [path] = ciso }
local fs = {}
function fs.getInfo(name)
  local data = files[name]
  return data and { size = #data, modtime = 1, type = "file" } or nil
end
function fs.newFile(name)
  local data = files[name]
  if not data then return nil, "missing" end
  local file = { pos = 0 }
  function file:open() return true end
  function file:seek(pos) self.pos = pos; return pos end
  function file:read(n)
    local out = data:sub(self.pos + 1, self.pos + n)
    self.pos = self.pos + #out
    return out
  end
  function file:close() end
  return file
end
function fs.remove() return true end

local manifest = {
  path = "mods/cbe",
  required_imports = { {
    -- Keep the existing raw vocabulary so the same mod manifest still loads on
    -- older engines. The extra gamecube_* fields opt into structural identity
    -- on engines that support it.
    id = "disc", file = "disc.iso", format = "raw",
    max_size = logicalSize,
    gamecube_disc_ids = { "GC6E01" }, gamecube_revisions = { 0 },
    gamecube_logical_size = logicalSize,
    -- Deliberately does not match the physical CISO: logical disc structure is
    -- the compatibility contract for an opted-in GameCube required import.
    md5 = { "00000000000000000000000000000000" },
  } },
}

local ok, detail = RequiredImports.acceptStoredDigest(manifest, "disc",
  "ffffffffffffffffffffffffffffffff", fs)
check(ok == true, "valid sparse CISO is accepted despite physical MD5 mismatch")
eq(detail, "gamecube:GC6E01:0:ciso", "structural result identifies disc/container")

local valid, storedDetail = RequiredImports.validateStored(
  manifest, manifest.required_imports[1], fs)
check(valid == true, "installed CISO remains valid on a later launcher inspection")
eq(storedDetail, detail, "stored validation uses the same structural identity")

-- The same arbitrary digest must not turn a different disc into a valid import.
files[path] = put(ciso, 0x8000, "BAD001")
local bad, why = RequiredImports.acceptStoredDigest(manifest, "disc",
  "ffffffffffffffffffffffffffffffff", fs)
check(not bad, "wrong GameCube disc id is rejected")
check(tostring(why):find("disc id", 1, true) ~= nil,
  "wrong-disc rejection explains the structural mismatch")

S.finish()

-- Structural validation for user-supplied GameCube required imports.
--
-- A GameCube disc can be stored as a full/trimmed raw ISO or as Dolphin's
-- sparse CISO container without changing the logical disc contents. Required
-- imports that opt into format="gamecube" are therefore identified by the
-- disc header + FST contract declared by the mod rather than by one physical
-- container MD5. This module only reads a few KiB of header plus the FST; it
-- never materializes an optical image into one Lua string.

local GameCube = {}

local CISO_HEADER = 0x8000
local GC_MAGIC = 0xC2339F3D
local DEFAULT_LOGICAL_SIZE = 1459978240

local function be32(s, p)
  local a,b,c,d = s:byte(p + 1, p + 4)
  if not d then return nil end
  return ((a * 256 + b) * 256 + c) * 256 + d
end

local function le32(s, p)
  local a,b,c,d = s:byte(p + 1, p + 4)
  if not d then return nil end
  return a + b * 256 + c * 65536 + d * 16777216
end

local function accepted(list, value)
  if type(list) ~= "table" or #list == 0 then return true end
  for _, candidate in ipairs(list) do
    if candidate == value or tostring(candidate) == tostring(value) then return true end
  end
  return false
end

local function openFile(fs, path)
  if not (fs and type(fs.newFile) == "function") then
    return nil, "streaming file access is unavailable"
  end
  local file, makeErr = fs.newFile(path)
  if not file then return nil, makeErr or "could not open GameCube import" end
  local ok, openErr = file:open("r")
  if not ok then return nil, openErr or "could not open GameCube import" end
  return file
end

local function fileReadAt(file, offset, count)
  if count <= 0 then return "" end
  local okSeek, seekErr = pcall(file.seek, file, offset)
  if not okSeek or seekErr == false then return nil, "could not seek GameCube import" end
  local okRead, data, readErr = pcall(file.read, file, count)
  if not okRead then return nil, tostring(data) end
  if type(data) ~= "string" then return nil, readErr or "could not read GameCube import" end
  return data
end

local function rawReader(file, physicalSize, logicalSize)
  return function(offset, count)
    if offset < 0 or count < 0 or offset + count > logicalSize then
      return nil, "logical GameCube read is out of range"
    end
    if offset >= physicalSize then return string.rep("\0", count) end
    local available = math.min(count, physicalSize - offset)
    local data, err = fileReadAt(file, offset, available)
    if not data then return nil, err end
    if #data ~= available then return nil, "truncated raw GameCube image" end
    if available < count then data = data .. string.rep("\0", count - available) end
    return data
  end, "raw"
end

local function cisoReader(file, physicalSize, logicalSize, header)
  if #header < CISO_HEADER then return nil, nil, "truncated CISO header" end
  local blockSize = le32(header, 4)
  if not blockSize or blockSize < 0x8000 or blockSize > 0x8000000
      or blockSize % 0x8000 ~= 0 then
    return nil, nil, "invalid CISO block size"
  end
  local blockCount = math.floor((logicalSize + blockSize - 1) / blockSize)
  if blockCount > CISO_HEADER - 8 then return nil, nil, "CISO block map is too small" end

  local locations = {}
  local stored = 0
  for index = 0, blockCount - 1 do
    local present = (header:byte(9 + index) or 0) ~= 0
    if present then
      locations[index] = CISO_HEADER + stored * blockSize
      stored = stored + 1
    end
  end
  if not locations[0] then return nil, nil, "CISO is missing logical block zero" end
  local minimumPhysical = CISO_HEADER + stored * blockSize
  if physicalSize < minimumPhysical then return nil, nil, "truncated CISO payload" end

  local function readLogical(offset, count)
    if offset < 0 or count < 0 or offset + count > logicalSize then
      return nil, "logical GameCube read is out of range"
    end
    local out = {}
    local remaining = count
    local cursor = offset
    while remaining > 0 do
      local block = math.floor(cursor / blockSize)
      local inBlock = cursor % blockSize
      local take = math.min(remaining, blockSize - inBlock)
      local physical = locations[block]
      if physical then
        local data, err = fileReadAt(file, physical + inBlock, take)
        if not data then return nil, err end
        if #data ~= take then return nil, "truncated CISO block" end
        out[#out + 1] = data
      else
        out[#out + 1] = string.rep("\0", take)
      end
      cursor = cursor + take
      remaining = remaining - take
    end
    return table.concat(out)
  end
  return readLogical, "ciso"
end

local function validateFst(readLogical, logicalSize, fstOff, fstSize, container)
  if not fstOff or not fstSize or fstOff < 0x440 or fstSize < 12
      or fstOff + fstSize > logicalSize then
    return nil, "invalid GameCube FST range"
  end
  local root, err = readLogical(fstOff, 12)
  if not root then return nil, err end
  local rootType = be32(root, 0)
  local entries = be32(root, 8)
  if not rootType or rootType < 0x01000000 or not entries or entries < 1
      or entries > 200000 or entries * 12 > fstSize then
    return nil, "invalid GameCube FST root"
  end
  local tableBytes = entries * 12
  local tableData, tableErr = readLogical(fstOff, tableBytes)
  if not tableData then return nil, tableErr end
  for index = 0, entries - 1 do
    local base = index * 12
    local typeName = be32(tableData, base)
    local a = be32(tableData, base + 4)
    local b = be32(tableData, base + 8)
    if not typeName or not a or not b then return nil, "truncated GameCube FST entry" end
    local isDir = typeName >= 0x01000000
    if isDir then
      if index > 0 and (b <= index or b > entries) then
        return nil, "invalid GameCube FST directory extent"
      end
    elseif a > logicalSize or b > logicalSize or a + b > logicalSize then
      return nil, "GameCube FST file extent is out of range"
    end
  end
  return { entries = entries, container = container }
end

function GameCube.validate(fs, path, spec)
  spec = spec or {}
  local info = fs and fs.getInfo and fs.getInfo(path, "file") or nil
  if not info or type(info.size) ~= "number" or info.size <= 0 then
    return nil, "GameCube import is missing"
  end
  local logicalSize = tonumber(spec.gamecube_logical_size) or DEFAULT_LOGICAL_SIZE
  if logicalSize < 0x440 then return nil, "invalid declared GameCube logical size" end
  if info.size > logicalSize then return nil, "GameCube container is larger than the declared disc" end

  local file, openErr = openFile(fs, path)
  if not file then return nil, openErr end
  local function close() pcall(file.close, file) end
  local ok, result, detail = xpcall(function()
    local prefix, err = fileReadAt(file, 0, math.min(CISO_HEADER, info.size))
    if not prefix then return nil, err end
    local readLogical, container, readerErr
    if prefix:sub(1, 4) == "CISO" then
      readLogical, container, readerErr = cisoReader(file, info.size, logicalSize, prefix)
      if not readLogical then return nil, readerErr end
    else
      readLogical, container = rawReader(file, info.size, logicalSize)
    end

    local boot, bootErr = readLogical(0, 0x42C)
    if not boot then return nil, bootErr end
    local discId = boot:sub(1, 6)
    local revision = boot:byte(8) or 0
    if not accepted(spec.gamecube_disc_ids, discId) then
      return nil, "unexpected GameCube disc id " .. tostring(discId)
    end
    if not accepted(spec.gamecube_revisions, revision) then
      return nil, "unexpected GameCube disc revision " .. tostring(revision)
    end
    if be32(boot, 0x1C) ~= GC_MAGIC then return nil, "GameCube disc magic was not found" end
    local fstOff, fstSize = be32(boot, 0x424), be32(boot, 0x428)
    local fst, fstErr = validateFst(readLogical, logicalSize, fstOff, fstSize, container)
    if not fst then return nil, fstErr end
    fst.discId = discId
    fst.revision = revision
    fst.logicalSize = logicalSize
    fst.physicalSize = info.size
    fst.token = ("gamecube:%s:%d:%s"):format(discId, revision, container)
    return fst
  end, function(err) return tostring(err) end)
  close()
  if not ok then return nil, result end
  if not result then return nil, detail end
  return true, result.token, result
end

return GameCube

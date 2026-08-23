#!/usr/bin/env python3
from pathlib import Path

def read(path):
    return Path(path).read_text(encoding="utf-8")

def write(path, text):
    Path(path).write_text(text, encoding="utf-8")

def replace_once(text, old, new, label):
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected exactly one match, found {count}")
    return text.replace(old, new, 1)

# Lua launcher
p = "src/import/RomImporter.lua"
s = read(p)

old = '''local function requiredImportNotice(self, modId, importId, text)
  self.requiredImportNotice = {
    modId = modId,
    importId = importId,
    text = tostring(text),
  }
end

function RomImporter:_importRequiredData(modId, importId, data)
'''
new = '''local function requiredImportNotice(self, modId, importId, text)
  self.requiredImportNotice = {
    modId = modId,
    importId = importId,
    text = tostring(text),
  }
end

local PICK_COMPLETE_FILENAME = "pick_complete.flag"

-- A current mobile bridge can write a raw required import straight into its
-- engine-owned baseroms destination. The completion marker contains:
--   relative destination path
--   MD5 calculated while the native bridge copied
--   byte count
-- Older bridges still stage picked_required_import.bin, so both paths remain.
local function directRequiredImportTarget(self, marker)
  marker = trim(marker)
  if marker == "" then return nil end
  local path, digest = marker:match("^([^\\r\\n]+)[\\r\\n]+([%x]+)")
  path = path or marker:match("^([^\\r\\n]+)")
  if not path then return nil end
  digest = digest and digest:lower() or nil

  if not self.mods and self._refreshMods then pcall(self._refreshMods, self) end
  local RequiredImports = require("src.mods.RequiredImports")

  local function checkRow(row)
    local manifest = row and row.manifest
    if not manifest then return nil end
    for _, spec in ipairs(RequiredImports.specs(manifest)) do
      if RequiredImports.path(manifest, spec) == path then
        return manifest, spec, row.id or manifest.id
      end
    end
    return nil
  end

  -- Fast path while the same launcher instance that opened the picker lives.
  if self.pickerPendingModId and self.pickerPendingImportId then
    for _, row in ipairs(self.mods or {}) do
      if row.id == self.pickerPendingModId then
        local manifest, spec, modId = checkRow(row)
        if manifest and spec.id == self.pickerPendingImportId then
          return path, digest, manifest, spec, modId
        end
      end
    end
  end

  -- Android may recreate the activity while DocumentsUI is open. The marker's
  -- private destination is enough to recover the request without pending IDs.
  for _, row in ipairs(self.mods or {}) do
    local manifest, spec, modId = checkRow(row)
    if manifest then return path, digest, manifest, spec, modId end
  end
  return path, digest
end

local function finishDirectRequiredImport(self, marker)
  local path, digest, manifest, spec, modId = directRequiredImportTarget(self, marker)
  if not (path and manifest and spec) then
    self.modNotice = { ok = false,
      text = "A completed dependency file did not match an installed mod request." }
    return nil
  end

  local RequiredImports = require("src.mods.RequiredImports")
  local ok, detail
  if digest and #digest == 32 then
    -- No second large-file pass: Android/iOS calculated this digest while copying.
    ok, detail = RequiredImports.acceptStoredDigest(
      manifest, spec.id, digest, love.filesystem)
  else
    -- Compatibility with an early bridge that only wrote a destination marker.
    ok, detail = RequiredImports.validateStored(manifest, spec, love.filesystem)
  end

  if not ok then
    -- Never leave a rejected direct copy in baseroms, where the next launcher
    -- refresh would rediscover and hash it again.
    love.filesystem.remove(path)
    if RequiredImports.receiptPath then
      love.filesystem.remove(RequiredImports.receiptPath(manifest, spec))
    end
    requiredImportNotice(self, modId or manifest.id, spec.id, detail)
    self.modNotice = nil
    return nil
  end

  self.requiredImportNotice = nil
  self.modNotice = { ok = true, text = "Imported " .. tostring(spec.id)
    .. " for " .. tostring(manifest.name or manifest.id) .. "." }
  self:_refreshMods()
  return true
end

function RomImporter:_importRequiredData(modId, importId, data)
'''
s = replace_once(s, old, new, "RomImporter direct helper")

old = '''    if pickError:find("picked_required_import", 1, true)
        or pickError:find("picked_stadium", 1, true)
        or (legacyRequiredPick and pickError:find("picked_rom", 1, true)) then
'''
new = '''    if pickError:find("picked_required_import", 1, true)
        or pickError:find("picked_stadium", 1, true)
        or pickError:find("/baseroms/", 1, true)
        or pickError:find("\\\\baseroms\\\\", 1, true)
        or (legacyRequiredPick and pickError:find("picked_rom", 1, true)) then
'''
s = replace_once(s, old, new, "RomImporter direct error classification")

old = '''    return
  end
  local requiredName = findPendingRequiredImport(self)
'''
new = '''    return
  end

  -- New mobile bridge: the native picker streamed a raw dependency directly
  -- into mods/<id>/baseroms while hashing it. Validate/publish that one copy.
  local completedRequired = love.filesystem.getInfo(PICK_COMPLETE_FILENAME, "file")
    and love.filesystem.read(PICK_COMPLETE_FILENAME)
  if completedRequired then
    love.filesystem.remove(PICK_COMPLETE_FILENAME)
    self.pickPending = nil
    finishDirectRequiredImport(self, completedRequired)
    self.pickerPendingKind = nil
    self.pickerPendingModId = nil
    self.pickerPendingImportId = nil
    self.requiredImportLegacyRomPick = nil
    return
  end

  local requiredName = findPendingRequiredImport(self)
'''
s = replace_once(s, old, new, "RomImporter focus completion")

old = '''  -- The Swift bridge reports a failed pick copy through pick_error.txt;
  -- surface it on whichever tab the player is looking at rather than
  -- letting the pick silently do nothing.
  local pickError = love.filesystem.read("pick_error.txt")
  if pickError then
    love.filesystem.remove("pick_error.txt")
    self.pickPending = nil
    self.modNotice = { ok = false, text = pickError }
    self.notice = { version = self.chooseVersion or "red",
                    status = "File import failed:", detail = pickError }
    return
  end
  local found = love.filesystem.getInfo("export_done.flag", "file") ~= nil
'''
new = '''  -- Old iOS builds report through pick_error.txt; current mobile bridges use
  -- pick_error.flag so focus() can classify the failed destination.
  local pickError = love.filesystem.read("pick_error.txt")
  if pickError then
    love.filesystem.remove("pick_error.txt")
    self.pickPending = nil
    self.modNotice = { ok = false, text = pickError }
    self.notice = { version = self.chooseVersion or "red",
                    status = "File import failed:", detail = pickError }
    return
  end
  local found = love.filesystem.getInfo("export_done.flag", "file") ~= nil
    or love.filesystem.getInfo("pick_error.flag", "file") ~= nil
    or love.filesystem.getInfo(PICK_COMPLETE_FILENAME, "file") ~= nil
'''
s = replace_once(s, old, new, "RomImporter polling markers")

old = '''    self.pickerPendingKind = "required_import"
    self.pickerPendingModId = modId
    self.pickerPendingImportId = importId
    self.requiredImportLegacyRomPick = legacyAndroidPicker or nil
    if not pickFile(legacyAndroidPicker and "rom" or "required_import") then
'''
new = '''    self.pickerPendingKind = "required_import"
    self.pickerPendingModId = modId
    self.pickerPendingImportId = importId
    self.requiredImportLegacyRomPick = legacyAndroidPicker or nil
    -- Raw imports can be copied directly into their private final destination
    -- by current Android/iOS bridges. N64 keeps staging because the launcher
    -- must canonicalize byte order/header variants before it is stored.
    local directDestination = (not legacyAndroidPicker and spec.format ~= "n64")
      and require("src.mods.RequiredImports").path(manifest, spec) or nil
    if not pickFile(legacyAndroidPicker and "rom" or "required_import",
        directDestination) then
'''
s = replace_once(s, old, new, "RomImporter picker destination")
write(p, s)

# Android wrapper
p = "mobile/android/love/src/jni/love/src/modules/system/System.h"
s = read(p)
s = replace_once(
    s,
    'virtual bool pickFile(const char *kind = nullptr) const;',
    'virtual bool pickFile(const char *kind = nullptr, const char *destination = nullptr) const;',
    "System.h signature")
write(p, s)

p = "mobile/android/love/src/jni/love/src/modules/system/wrap_System.cpp"
s = read(p)
old = '''int w_pickFile(lua_State *L)
{
\tconst char *kind = luaL_optstring(L, 1, nullptr);
\tluax_pushboolean(L, instance()->pickFile(kind));
\treturn 1;
}
'''
new = '''int w_pickFile(lua_State *L)
{
\tconst char *kind = luaL_optstring(L, 1, nullptr);
\tconst char *destination = luaL_optstring(L, 2, nullptr);
\tluax_pushboolean(L, instance()->pickFile(kind, destination));
\treturn 1;
}
'''
s = replace_once(s, old, new, "wrap_System pickFile")
write(p, s)

p = "mobile/android/love/src/jni/love/src/modules/system/System.cpp"
s = read(p)
s = replace_once(
    s,
    'bool System::pickFile(const char *kind) const\\n{',
    'bool System::pickFile(const char *kind, const char *destination) const\\n{',
    "System.cpp signature")
s = replace_once(
    s,
    '''\t\telse if (strcmp(kind, "required_import") == 0)
\t\t\tdest = "picked_required_import.bin";
''',
    '''\t\telse if (strcmp(kind, "required_import") == 0)
\t\t\tdest = (destination != nullptr && destination[0] != '\\\\0')
\t\t\t\t? destination : "picked_required_import.bin";
''',
    "System.cpp required destination")
write(p, s)

# Android Java
p = "mobile/android/love/src/main/java/org/love2d/android/GameActivity.java"
s = read(p)
s = replace_once(s, 'import java.util.Map;\\n',
                 'import java.util.Map;\\nimport java.security.MessageDigest;\\n',
                 "GameActivity MessageDigest import")
s = replace_once(
    s,
    '''    private static final String PICK_ERROR_FILENAME = "pick_error.flag";
''',
    '''    private static final String PICK_ERROR_FILENAME = "pick_error.flag";
    // Direct required-import copies publish this only after the final file has
    // been atomically renamed into mods/<id>/baseroms/. Body: path, MD5, size.
    private static final String PICK_COMPLETE_FILENAME = "pick_complete.flag";
''',
    "GameActivity completion constant")

old = '''        // Reject path separators so a hostile JNI caller cannot escape the
        // save identity directory.
        if (destFilename.indexOf('/') >= 0 || destFilename.indexOf('\\\\\\\\') >= 0) {
            Log.d("GameActivity", "refusing unsafe picker dest: " + destFilename);
            return false;
        }

        self.pendingPickFilename = destFilename;
'''
new = '''        // Current required-import callers may name a PRIVATE path beneath the
        // mounted save root (mods/<id>/baseroms/<file>) so optical-disc-sized
        // sources do not need a second picked_required_import.bin copy. Keep
        // the same sandbox boundary by canonicalizing and refusing escapes.
        File pickRoot = self.saveIdentityDir();
        try {
            File rootCanonical = pickRoot.getCanonicalFile();
            File destCanonical = new File(rootCanonical, destFilename).getCanonicalFile();
            String rootPrefix = rootCanonical.getPath() + File.separator;
            if (destCanonical.equals(rootCanonical)
                    || !destCanonical.getPath().startsWith(rootPrefix)) {
                Log.d("GameActivity", "refusing unsafe picker dest: " + destFilename);
                return false;
            }
        } catch (IOException e) {
            Log.d("GameActivity", "could not validate picker dest: " + e.getMessage());
            return false;
        }

        self.pendingPickFilename = destFilename.replace('\\\\\\\\', '/');
'''
s = replace_once(s, old, new, "GameActivity safe nested destination")

old = '''        String destName = pendingPickFilename != null
            ? pendingPickFilename : PICKED_ROM_FILENAME;
        File destFile = new File(destDir, destName);

        // ACTION_OPEN_DOCUMENT is meant to land in the system documents UI, but
'''
new = '''        final String destName = pendingPickFilename != null
            ? pendingPickFilename : PICKED_ROM_FILENAME;
        final File destFile;
        try {
            File rootCanonical = destDir.getCanonicalFile();
            destFile = new File(rootCanonical, destName).getCanonicalFile();
            String rootPrefix = rootCanonical.getPath() + File.separator;
            if (destFile.equals(rootCanonical)
                    || !destFile.getPath().startsWith(rootPrefix)) {
                Log.d("GameActivity", "refusing unsafe result dest: " + destName);
                writeSaveDirFlag(PICK_ERROR_FILENAME, destName);
                return;
            }
        } catch (IOException e) {
            Log.d("GameActivity", "could not validate result dest: " + e.getMessage());
            writeSaveDirFlag(PICK_ERROR_FILENAME, destName);
            return;
        }

        // ACTION_OPEN_DOCUMENT is meant to land in the system documents UI, but
'''
s = replace_once(s, old, new, "GameActivity result destination")

old = '''        if (!copyAssetFile(source, destFile.getPath())) {
            Log.d("GameActivity", "could not copy picked file to " + destFile);
            // A truncated pick would only fail verification later, so drop it
            // and report instead.
            destFile.delete();
            writeSaveDirFlag(PICK_ERROR_FILENAME, destName);
        }
    }

    /**
     * Copies a given file from the assets folder to the destination.
'''
new = '''        final InputStream pickedSource = source;
        final File pickedRoot = destDir;
        final boolean directRequired = destName.indexOf('/') >= 0
            || destName.indexOf('\\\\\\\\') >= 0;

        if (directRequired) {
            // Hundreds of MiB must never be copied in onActivityResult's UI
            // thread. One worker streams directly to the private final path,
            // hashes the same bytes, then publishes a tiny completion marker.
            new Thread(new Runnable() {
                @Override public void run() {
                    PickCopyResult result = copyPickedFile(pickedSource, destFile);
                    if (!result.ok) {
                        destFile.delete();
                        writeFlagFile(pickedRoot, PICK_ERROR_FILENAME, destName);
                        return;
                    }
                    String marker = destName + "\\\\n" + result.md5 + "\\\\n"
                        + Long.toString(result.bytes) + "\\\\n";
                    writeFlagFile(pickedRoot, PICK_COMPLETE_FILENAME, marker);
                }
            }, "gen1recomp-required-import").start();
            return;
        }

        if (!copyAssetFile(pickedSource, destFile.getPath())) {
            Log.d("GameActivity", "could not copy picked file to " + destFile);
            // A truncated pick would only fail verification later, so drop it
            // and report instead.
            destFile.delete();
            writeSaveDirFlag(PICK_ERROR_FILENAME, destName);
        }
    }

    private static final class PickCopyResult {
        boolean ok;
        long bytes;
        String md5 = "";
    }

    private static String hex(byte[] bytes) {
        StringBuilder out = new StringBuilder(bytes.length * 2);
        for (byte b : bytes) out.append(String.format(Locale.US, "%02x", b & 0xff));
        return out.toString();
    }

    private static void writeFlagFile(File dir, String name, String body) {
        try {
            if (!dir.isDirectory() && !dir.mkdirs()) return;
            FileOutputStream out = new FileOutputStream(new File(dir, name), false);
            out.write(body.getBytes("UTF-8"));
            out.close();
        } catch (Exception e) {
            Log.d("GameActivity", "could not write " + name + ": " + e.getMessage());
        }
    }

    private static PickCopyResult copyPickedFile(InputStream source, File destination) {
        PickCopyResult result = new PickCopyResult();
        File parent = destination.getParentFile();
        File partial = new File(destination.getPath() + ".part");
        InputStream in = null;
        OutputStream out = null;
        try {
            if (parent != null && !parent.isDirectory() && !parent.mkdirs()) {
                return result;
            }
            if (partial.exists()) partial.delete();
            MessageDigest md5 = MessageDigest.getInstance("MD5");
            in = new BufferedInputStream(source, 1024 * 1024);
            out = new BufferedOutputStream(new FileOutputStream(partial, false),
                1024 * 1024);
            byte[] buf = new byte[1024 * 1024];
            int n;
            long total = 0;
            while ((n = in.read(buf)) != -1) {
                if (n == 0) continue;
                out.write(buf, 0, n);
                md5.update(buf, 0, n);
                total += n;
            }
            out.flush();
            out.close(); out = null;
            in.close(); in = null;
            if (destination.exists() && !destination.delete()) return result;
            if (!partial.renameTo(destination)) return result;
            result.ok = true;
            result.bytes = total;
            result.md5 = hex(md5.digest());
            Log.d("GameActivity", "Direct required import copied " + total
                + " bytes to " + destination);
            return result;
        } catch (Exception e) {
            Log.d("GameActivity", "direct required import failed: " + e.getMessage());
            return result;
        } finally {
            try { if (in != null) in.close(); } catch (IOException ignored) {}
            try { if (out != null) out.close(); } catch (IOException ignored) {}
            if (!result.ok && partial.exists()) partial.delete();
        }
    }

    /**
     * Copies a given file from the assets folder to the destination.
'''
s = replace_once(s, old, new, "GameActivity direct copy")

old = '''        try {
            byte[] buf = new byte[1024];
            chunk_read = source.read(buf);
            do {
                destination.write(buf, 0, chunk_read);
                bytes_written += chunk_read;
                chunk_read = source.read(buf);
            } while (chunk_read != -1);
        } catch (IOException e) {
'''
new = '''        try {
            byte[] buf = new byte[1024 * 1024];
            while ((chunk_read = source.read(buf)) != -1) {
                if (chunk_read == 0) continue;
                destination.write(buf, 0, chunk_read);
                bytes_written += chunk_read;
            }
        } catch (IOException e) {
'''
s = replace_once(s, old, new, "GameActivity legacy copy buffer")

old = '''    private void writeSaveDirFlag(String name, String body) {
        try {
            FileOutputStream fos = new FileOutputStream(new File(saveIdentityDir(), name), false);
            fos.write(body.getBytes());
            fos.close();
        } catch (IOException e) {
            Log.d("GameActivity", "could not write " + name + ": " + e.getMessage());
        }
    }
'''
new = '''    private void writeSaveDirFlag(String name, String body) {
        writeFlagFile(saveIdentityDir(), name, body);
    }
'''
s = replace_once(s, old, new, "GameActivity flag helper")
write(p, s)

# iOS bridge
p = "mobile/ios/native/GRPickerBridge.swift"
s = read(p)
s = replace_once(s, 'import UniformTypeIdentifiers\\n',
                 'import UniformTypeIdentifiers\\nimport CryptoKit\\n',
                 "iOS CryptoKit import")

old = '''    @objc(presentPickerWithKind:saveDir:)
    public static func presentPicker(kind: UnsafePointer<CChar>?,
                                     saveDir: UnsafePointer<CChar>?) -> Bool {
        let kindStr = kind.map { String(cString: $0) } ?? "rom"
        guard let dir = resolvedSaveDir(saveDir) else { return false }

        let destName: String
'''
new = '''    @objc(presentPickerWithKind:saveDir:)
    public static func presentPicker(kind: UnsafePointer<CChar>?,
                                     saveDir: UnsafePointer<CChar>?) -> Bool {
        return presentPicker(kind: kind, saveDir: saveDir, destination: nil)
    }

    @objc(presentPickerWithKind:saveDir:destination:)
    public static func presentPicker(kind: UnsafePointer<CChar>?,
                                     saveDir: UnsafePointer<CChar>?,
                                     destination: UnsafePointer<CChar>?) -> Bool {
        let kindStr = kind.map { String(cString: $0) } ?? "rom"
        guard let dir = resolvedSaveDir(saveDir) else { return false }

        let requestedDestination = destination.map { String(cString: $0) }
        let destName: String
'''
s = replace_once(s, old, new, "iOS picker signature")

s = replace_once(
    s,
    '''        case "required_import":
            destName = "picked_required_import.bin"
''',
    '''        case "required_import":
            if let requestedDestination,
               safeDestination(in: dir, relative: requestedDestination) != nil {
                destName = requestedDestination
            } else {
                destName = "picked_required_import.bin"
            }
''',
    "iOS required destination")

old = '''        let picker = UIDocumentPickerViewController(forOpeningContentTypes: types,
                                                    asCopy: true)
        picker.allowsMultipleSelection = false
        let delegate = PickerDelegate { urls in
            guard let src = urls.first else { return }
            copyItem(at: src, into: dir, named: destName)
        }
'''
new = '''        let directRequired = kindStr == "required_import"
            && destName != "picked_required_import.bin"
        let picker = UIDocumentPickerViewController(forOpeningContentTypes: types,
                                                    asCopy: !directRequired)
        picker.allowsMultipleSelection = false
        let delegate = PickerDelegate { urls in
            guard let src = urls.first else { return }
            if directRequired {
                copyRequiredItemAsync(at: src, into: dir, relative: destName)
            } else {
                copyItem(at: src, into: dir, named: destName)
            }
        }
'''
s = replace_once(s, old, new, "iOS direct picker mode")

old = '''    private static func copyItem(at src: URL, into dir: URL, named name: String) {
'''
new = '''    private static func safeDestination(in root: URL, relative: String) -> URL? {
        guard !relative.isEmpty, !relative.hasPrefix("/") else { return nil }
        let rootPath = root.standardizedFileURL.path
        let candidate = root.appendingPathComponent(relative).standardizedFileURL
        let prefix = rootPath.hasSuffix("/") ? rootPath : rootPath + "/"
        guard candidate.path.hasPrefix(prefix) else { return nil }
        return candidate
    }

    private static func writeFlag(in dir: URL, name: String, body: String) {
        try? body.data(using: .utf8)?.write(to: dir.appendingPathComponent(name),
                                           options: .atomic)
    }

    private static func copyRequiredItemAsync(at src: URL, into dir: URL,
                                              relative: String) {
        DispatchQueue.global(qos: .userInitiated).async {
            let scoped = src.startAccessingSecurityScopedResource()
            defer { if scoped { src.stopAccessingSecurityScopedResource() } }
            guard let dest = safeDestination(in: dir, relative: relative) else {
                writeFlag(in: dir, name: "pick_error.flag", body: relative)
                return
            }
            let fm = FileManager.default
            ensureDirectory(dest.deletingLastPathComponent())
            let partial = URL(fileURLWithPath: dest.path + ".part")
            try? fm.removeItem(at: partial)
            fm.createFile(atPath: partial.path, contents: nil)

            var hasher = Insecure.MD5()
            var total: UInt64 = 0
            do {
                let input = try FileHandle(forReadingFrom: src)
                let output = try FileHandle(forWritingTo: partial)
                defer {
                    try? input.close()
                    try? output.close()
                }
                while true {
                    let data = input.readData(ofLength: 1024 * 1024)
                    if data.isEmpty { break }
                    hasher.update(data: data)
                    output.write(data)
                    total += UInt64(data.count)
                }
                output.synchronizeFile()
                try? fm.removeItem(at: dest)
                try fm.moveItem(at: partial, to: dest)
                let digest = hasher.finalize().map { String(format: "%02x", $0) }.joined()
                let marker = relative + "\\\\n" + digest + "\\\\n" + String(total) + "\\\\n"
                writeFlag(in: dir, name: "pick_complete.flag", body: marker)
                NSLog("GRPickerBridge: direct required import delivered %llu bytes",
                      total)
            } catch {
                try? fm.removeItem(at: partial)
                try? fm.removeItem(at: dest)
                NSLog("GRPickerBridge: direct required import failed: \\\\(error)")
                writeFlag(in: dir, name: "pick_error.flag", body: relative)
            }
        }
    }

    private static func copyItem(at src: URL, into dir: URL, named name: String) {
'''
s = replace_once(s, old, new, "iOS direct copy helper")
s = s.replace('dir.appendingPathComponent("pick_error.txt")',
              'dir.appendingPathComponent("pick_error.flag")')
write(p, s)

# iOS LÖVE patch
p = "mobile/ios/patch_love_src.py"
s = read(p)
old = '''int w_pickFile(lua_State *L)
{
\tconst char *kind = luaL_optstring(L, 1, "rom");
\treturn gr_callBridge(L, "GRPickerBridge", "presentPickerWithKind:saveDir:", kind);
}
'''
new = '''int w_pickFile(lua_State *L)
{
\tconst char *kind = luaL_optstring(L, 1, "rom");
\tconst char *destination = luaL_optstring(L, 2, nullptr);
\tClass cls = objc_getClass("GRPickerBridge");
\tif (cls == nullptr)
\t{
\t\tlua_pushboolean(L, 0);
\t\treturn 1;
\t}
\ttypedef signed char (*GRPick)(Class, SEL, const char *, const char *,
\t                              const char *);
\tsigned char ok = ((GRPick)objc_msgSend)(
\t\tcls, sel_registerName("presentPickerWithKind:saveDir:destination:"),
\t\tkind, gr_saveDirectory(), destination);
\tlua_pushboolean(L, ok != 0);
\treturn 1;
}
'''
s = replace_once(s, old, new, "iOS patch w_pickFile")
write(p, s)

# Tests
p = "tests/rom_importer_android_mod_pick_test.lua"
s = read(p)
old = '''local pickCalls = {}
love.system.getOS = function() return "Android" end
love.system.pickFile = function(kind)
  pickCalls[#pickCalls + 1] = kind or "rom"
  return true
end
'''
new = '''local pickCalls, pickDestinations = {}, {}
love.system.getOS = function() return "Android" end
love.system.pickFile = function(kind, destination)
  pickCalls[#pickCalls + 1] = kind or "rom"
  pickDestinations[#pickCalls] = destination
  return true
end
'''
s = replace_once(s, old, new, "test picker args")

s = s.replace(
    'manifest = { id = "needs_source", name = "Needs Source",\\n    required_imports',
    'manifest = { id = "needs_source", name = "Needs Source", path = "mods/needs_source",\\n    required_imports')

old = '''eq(pickCalls[1], "required_import",
  "required file asks for the dedicated picker kind")
eq(ri.pickerPendingModId, "needs_source", "pending mod is remembered")
'''
new = '''eq(pickCalls[1], "required_import",
  "required file asks for the dedicated picker kind")
eq(pickDestinations[1], "mods/needs_source/baseroms/source.bin",
  "raw required file is offered a direct private baseroms destination")
eq(ri.pickerPendingModId, "needs_source", "pending mod is remembered")
'''
s = replace_once(s, old, new, "test direct destination assertion")

insert_after = '''check(love.filesystem.getInfo("picked_required_import.bin") == nil,
  "focus removes the staged required-file pick")
'''
addition = '''

-- Current mobile bridges copy a raw required import directly into its private
-- baseroms path and publish path+MD5 in pick_complete.flag. Focus validates the
-- already-copied bytes without a staged-file round trip.
local directPath = "mods/needs_source/baseroms/source.bin"
love.filesystem.createDirectory("mods/needs_source/baseroms")
love.filesystem.write(directPath, "source bytes")
love.filesystem.write("pick_complete.flag",
  directPath .. "\\\\nfe1eb7483479c3a4e44fd41ce6f6d6ad\\\\n12\\\\n")
ri.mods[1].manifest.required_imports[1].md5 = {
  "fe1eb7483479c3a4e44fd41ce6f6d6ad"
}
ri._importRequiredSource = RomImporter._importRequiredSource
ri:focus(true)
check(ri.modNotice ~= nil and ri.modNotice.ok == true,
  "focus accepts a direct native required-import completion")
check(love.filesystem.getInfo(directPath, "file") ~= nil,
  "direct required import stays in its final baseroms path")
check(love.filesystem.getInfo("pick_complete.flag") == nil,
  "direct completion marker is consumed")
'''
if insert_after not in s:
    raise SystemExit("test staged required insertion anchor missing")
s = s.replace(insert_after, insert_after + addition, 1)

old = '''ri:chooseRequiredImport("needs_source", "source")
eq(pickCalls[1], "rom", "legacy Android bridge falls back to its ROM SAF picker")
'''
new = '''ri:chooseRequiredImport("needs_source", "source")
eq(pickCalls[1], "rom", "legacy Android bridge falls back to its ROM SAF picker")
check(pickDestinations[1] == nil,
  "legacy ROM fallback does not receive a nested dependency destination")
'''
s = replace_once(s, old, new, "test legacy destination")

old = '''love.filesystem.remove("picked_required_import.bin")
love.filesystem.remove("picked_rom.gb")

S.finish()
'''
new = '''love.filesystem.remove("picked_required_import.bin")
love.filesystem.remove("picked_rom.gb")
love.filesystem.remove("pick_complete.flag")
love.filesystem.remove("pick_error.flag")
love.filesystem.remove("mods/needs_source/baseroms/source.bin")

S.finish()
'''
s = replace_once(s, old, new, "test cleanup")
write(p, s)

# Docs
p = "docs/modding.md"
s = read(p)
old = '''Android uses the Storage Access Framework, and iOS uses
the Files document picker; both stage the choice as `picked_required_import.bin`
before validation. Xbox/UWP uses its native picker and hands the launcher a
temporary path. Switch/NX has no host picker, so the player copies a file to
'''
new = '''Android uses the Storage Access Framework, and iOS uses
the Files document picker. For raw required imports, current mobile builds
stream the selection directly into that mod's private `baseroms/` destination,
hashing it during the same copy and publishing it only after completion; this
avoids a second optical-disc-sized staging copy. Older mobile bridges still
fall back to `picked_required_import.bin` and remain compatible. Xbox/UWP uses
its native picker and hands the launcher a temporary path. Switch/NX has no
host picker, so the player copies a file to
'''
s = replace_once(s, old, new, "docs platform import")
write(p, s)

print("mobile required-import direct streaming patch applied")

#!/usr/bin/env python3
from pathlib import Path
# Normalize over-escaped literals introduced while staging the patch and make
# the Java destination replacement resilient to backslash escaping.
p = Path('tools/apply_mobile_required_import_patch.py')
s = p.read_text(encoding='utf-8')
replacements = {
    r"'bool System::pickFile(const char *kind) const\\n{'": r"'bool System::pickFile(const char *kind) const\n{'",
    r"'bool System::pickFile(const char *kind, const char *destination) const\\n{'": r"'bool System::pickFile(const char *kind, const char *destination) const\n{'",
    r"'import java.util.Map;\\n'": r"'import java.util.Map;\n'",
    r"'import java.util.Map;\\nimport java.security.MessageDigest;\\n'": r"'import java.util.Map;\nimport java.security.MessageDigest;\n'",
    r"'import UniformTypeIdentifiers\\n'": r"'import UniformTypeIdentifiers\n'",
    r"'import UniformTypeIdentifiers\\nimport CryptoKit\\n'": r"'import UniformTypeIdentifiers\nimport CryptoKit\n'",
    r"name = \"Needs Source\",\\n    required_imports": r"name = \"Needs Source\",\n    required_imports",
    r"path = \"mods/needs_source\",\\n    required_imports": r"path = \"mods/needs_source\",\n    required_imports",
}
for old, new in replacements.items():
    if old in s:
        s = s.replace(old, new)

needle = 's = replace_once(s, old, new, "GameActivity safe nested destination")'
replacement = '''start = s.find("        // Reject path separators so a hostile JNI caller cannot escape the")
if start < 0:
    raise SystemExit("GameActivity safe nested destination: start anchor missing")
end_marker = "        self.pendingPickFilename = destFilename;\\n"
end = s.find(end_marker, start)
if end < 0:
    raise SystemExit("GameActivity safe nested destination: end anchor missing")
end += len(end_marker)
s = s[:start] + new + s[end:]'''
if needle not in s:
    raise SystemExit('patch helper: Java safe-destination call missing')
s = s.replace(needle, replacement, 1)

p.write_text(s, encoding='utf-8')
print('fixed patch-script escapes/anchors')

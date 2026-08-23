#!/usr/bin/env python3
from pathlib import Path
# Normalize over-escaped newline literals introduced while staging the patch.
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
p.write_text(s, encoding='utf-8')
print('fixed patch-script newline escapes')

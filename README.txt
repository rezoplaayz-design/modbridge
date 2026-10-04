MODBRIDGE WORKING PROTOTYPE v0.8
================================

HOW TO RUN ON WINDOWS
1. Extract this ZIP.
2. Double-click run.bat.
3. Your browser opens http://127.0.0.1:8765/
4. Click Get Started and upload a Java .jar.

No npm/pip packages are required. The backend uses Python's standard library.

WHAT ACTUALLY WORKS
- Real .jar upload to a local backend.
- ZIP/JAR safety checks (file count, expanded size, unsafe paths).
- Fabric / Forge / NeoForge / Quilt metadata detection.
- Minecraft version / namespace detection when present in mod metadata.
- Real scanning of Java mod resources: item/block textures, recipes, language files, sounds, models, classes, mixin configs and code-pattern hints.
- Real compatibility report based on what was found.
- Real Bedrock Resource Pack + Behavior Pack generation for the supported subset.
- Copies item/block textures.
- Generates basic Bedrock item definitions from Java item textures.
- Converts Java en_us/en_gb JSON language files to Bedrock .lang files.
- Converts common shaped and shapeless crafting recipes.
- Copies OGG sound assets.
- Generates linked Bedrock manifests and UUIDs.
- Validates generated JSON, manifests and item texture references.
- Builds actual .mcpack files and a downloadable .mcaddon package.
- Downloadable editable source ZIP and JSON conversion report.
- Limited real repair path: rebuilds pack metadata/texture indexes and repackages the add-on when the Content Log points to those categories.

IMPORTANT LIMITATION
A Java mod and a Bedrock add-on use different APIs and engines. Mixins, custom Java rendering, arbitrary Java gameplay code, networking, Forge/Fabric APIs, custom GUIs and many entity systems cannot be converted perfectly by a generic automatic tool. This prototype never pretends those features were converted; it puts them in the report as warnings/skipped/manual work.

SECURITY
Uploaded JAR code is not executed. The app reads the JAR as a ZIP archive and parses selected resources/metadata.

For public hosting, put this behind a production reverse proxy/container, add authentication/rate limits, isolated job storage, malware scanning and stricter resource limits.

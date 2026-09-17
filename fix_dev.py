import re

with open('scripts/dev.mjs', 'r') as f:
    content = f.read()

# Remove GEV config block
content = re.sub(r"const GEV = {[\s\S]*?};\n", "", content)

# Remove GEV from servers array
content = content.replace("const servers = [BRAIN, UI, GEV];", "const servers = [BRAIN, UI];")

# Remove GEV from cleanLeftovers
content = content.replace("for (const port of [BRAIN.port, UI.port, GEV.port]) {", "for (const port of [BRAIN.port, UI.port]) {")

# Remove GEV from waitForReady
content = content.replace("const [brainUp, uiUp, gevUp] = await Promise.all([", "const [brainUp, uiUp] = await Promise.all([")
content = content.replace("portOpen(GEV.port),", "")
content = content.replace("if (brainUp && uiUp && gevUp && !shuttingDown) {", "if (brainUp && uiUp && !shuttingDown) {")
content = content.replace("console.log(`${GREEN}   → GEV:     http://localhost:${GEV.port}${RESET}`);\n", "")
content = content.replace("if (!gevUp) waiting.push(`${GEV.color}${GEV.short}${RESET} on :${GEV.port}`);\n", "")

with open('scripts/dev.mjs', 'w') as f:
    f.write(content)

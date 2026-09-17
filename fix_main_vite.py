import re

with open('vite.config.js', 'r') as f:
    content = f.read()

# Add imports
content = content.replace("import react from '@vitejs/plugin-react'", 
"import react from '@vitejs/plugin-react'\nimport { getGevPlugins } from './vite.gev.config.js'\nimport { resolve } from 'path'")

# Change export default defineConfig({ to function format
content = content.replace("export default defineConfig({", 
"export default defineConfig(({ mode }) => {\n  const gevConfig = getGevPlugins(mode);\n  return {")

content = content.replace("plugins: [react()],", "plugins: [react(), ...gevConfig.plugins],")

# Add input for rollupOptions
content = content.replace("output: {", """input: {
          main: resolve(__dirname, 'index.html'),
          gev: resolve(__dirname, 'src/gev/index.html')
        },
        output: {""")

# Change warning limit
content = content.replace("chunkSizeWarningLimit: 1200,", "chunkSizeWarningLimit: 1500,")

# Add server and define
content = content.replace("  },\n})", "  },\n  server: gevConfig.server,\n  define: gevConfig.define\n})")

with open('vite.config.js', 'w') as f:
    f.write(content)

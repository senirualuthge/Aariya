import re

with open('gods-eye-view/vite.config.js', 'r') as f:
    content = f.read()

# Revert my bad sed commands
content = content.replace("export function getGevPlugins(mode) { // getGevPlugins", "export default defineConfig(({ mode }) => {")
content = content.replace("return [\n    plugins:", "return {\n    plugins:")

# Now we actually want to extract just the plugins and define getGevPlugins
content = content.replace("export default defineConfig(({ mode }) => {", "export function getGevPlugins(mode) {")

content = content.replace("""    plugins: [
      cesium(),
      openSkyProxy(),
      celestrakProxy(),
      tomtomProxy(),
      firmsProxy(),
      rocketLaunchesProxy(),
      terrainHeightsProxy(),
      adsbdbProxy(),
      overpassProxy(),
      militaryInstallationsProxy(),
      regionalBriefProxy(),
      weatherEffectsProxy(),
      cctvProxy(),
      radioBrowserProxy(),
      gbfsProxy(),
      adsbLolProxy(),
      aisLiveProxy(),
      trackBackfillProxies(),
      openAiRealtimeProxy(),
      googlePlacesContextProxy(),
    ],""", """    plugins: [
      cesium(),
      openSkyProxy(),
      celestrakProxy(),
      tomtomProxy(),
      firmsProxy(),
      rocketLaunchesProxy(),
      terrainHeightsProxy(),
      adsbdbProxy(),
      overpassProxy(),
      militaryInstallationsProxy(),
      regionalBriefProxy(),
      weatherEffectsProxy(),
      cctvProxy(),
      radioBrowserProxy(),
      gbfsProxy(),
      adsbLolProxy(),
      aisLiveProxy(),
      trackBackfillProxies(),
      openAiRealtimeProxy(),
      googlePlacesContextProxy(),
    ]
  };
}
""")

# We need to remove the trailing config
content = re.sub(r'    server: {.*}\);\n?', '', content, flags=re.DOTALL)

with open('vite.gev.config.js', 'w') as f:
    f.write(content)


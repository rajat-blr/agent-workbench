const path = require('node:path')

module.exports = {
  packagerConfig: {
    asar: true,
    executableName: 'Agent Workbench',
    extraResource: [
      path.resolve(__dirname, '../backend/dist/agent-workbench-backend'),
    ],
    appBundleId: 'com.rajatvarma.agentworkbench',
    appCategoryType: 'public.app-category.developer-tools',
    extendInfo: {
      CFBundleDisplayName: 'Agent Workbench',
    },
    name: 'Agent Workbench',
  },
  rebuildConfig: {},
  makers: [
    {
      name: '@electron-forge/maker-zip',
      platforms: ['darwin'],
    },
    {
      name: '@electron-forge/maker-dmg',
      config: {},
      platforms: ['darwin'],
    },
  ],
}

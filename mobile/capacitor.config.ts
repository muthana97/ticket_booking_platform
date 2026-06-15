import type { CapacitorConfig } from '@capacitor/cli';

/* Capacitor configuration for the Tazkirati iOS + Android apps.
 *
 * webDir points at the sibling /frontend directory so any change to the web
 * SPA flows into the next `npx cap sync` without duplication.
 *
 * The web app detects Capacitor at runtime (window.Capacitor.isNativePlatform)
 * and switches the API base URL via TAZ_API_NATIVE_DEFAULT defined in
 * index.html — make sure that points at your deployed backend before building
 * for the stores. */
const config: CapacitorConfig = {
  appId: 'app.tazkirati',
  appName: 'Tazkirati',
  webDir: '../frontend',

  // Lock the webview to the bundled assets. Setting `server.url` would point
  // the webview at a live URL instead, which we explicitly do NOT want — the
  // whole reason for bundling is to render reliably offline / on cold-start.
  server: {
    androidScheme: 'https',
  },

  ios: {
    // Adjust the safe-area insets so the navy topbar tucks under the status
    // bar correctly on notched devices.
    contentInset: 'always',
  },

  android: {
    // Disallow http subresources — every backend call should be https in
    // production. The dev backend (http://localhost) is still reachable
    // because Android's `https` scheme remap routes localhost correctly.
    allowMixedContent: false,
  },

  plugins: {
    SplashScreen: {
      launchShowDuration: 1500,
      backgroundColor: '#0F2A47',
      showSpinner: false,
      androidScaleType: 'CENTER_CROP',
    },
    StatusBar: {
      style: 'DARK',
      backgroundColor: '#0F2A47',
    },
    Keyboard: {
      resize: 'body',
      resizeOnFullScreen: true,
    },
  },
};

export default config;
